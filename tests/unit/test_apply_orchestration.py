"""Regression coverage for apply orchestration and failure boundaries."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from cgiswitch import ApplyPolicy, JTComApplyError, JTComPolicyError, JTComSwitch
from cgiswitch.client.errors import JTComVerificationError
from cgiswitch.model.config import DeviceConfig
from cgiswitch.model.port import PortConfig, PortSettings
from cgiswitch.model.vlan import VlanConfig, VlanEntry
from cgiswitch.utils.device_diff import build_device_plan
from cgiswitch.utils.operations import compile_apply_operations
from cgiswitch.utils.vlan_membership import plan_vlan_membership_changes


def _state() -> tuple[dict[int, VlanEntry], list[PortSettings]]:
    return (
        {
            1: VlanEntry(1, "default", untagged_ports=["Port 1"]),
            10: VlanEntry(10, "old", tagged_ports=["Port 1"]),
            20: VlanEntry(20, "delete"),
        },
        [PortSettings(1, "Port 1", True, "Auto", False)],
    )


def _switch(monkeypatch: pytest.MonkeyPatch, *, policy: ApplyPolicy | None = None) -> JTComSwitch:
    switch = JTComSwitch("192.0.2.1", "admin", "secret", policy=policy)
    switch._session = MagicMock()
    monkeypatch.setattr(switch, "_save_backup", MagicMock(return_value="/tmp/backup.cfg"))
    return switch


def test_noop_and_check_mode_do_not_backup_or_write(monkeypatch: pytest.MonkeyPatch) -> None:
    current, ports = _state()
    switch = _switch(monkeypatch, policy=ApplyPolicy(backup_before_change=True))
    monkeypatch.setattr(switch, "_read_current_state", lambda _: (current, ports))

    noop = switch.apply(DeviceConfig())
    preview = switch.apply(DeviceConfig(), check_mode=True)

    assert noop["changed"] is False
    assert preview["changed"] is False
    assert noop["applied"] == preview["applied"] == []
    switch._save_backup.assert_not_called()
    switch._session.post.assert_not_called()


def test_check_mode_returns_plan_without_backup_or_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    current, ports = _state()
    switch = _switch(monkeypatch, policy=ApplyPolicy(safety_port_id=1))
    monkeypatch.setattr(switch, "_read_current_state", lambda _: (current, ports))
    result = switch.apply(DeviceConfig(vlans={30: VlanConfig(30, "new")}), check_mode=True)

    assert result["changed"] is True
    assert result["blocked"] is False
    assert result["backup_file"] == ""
    assert result["applied"] == []
    switch._save_backup.assert_not_called()
    switch._session.post.assert_not_called()


def test_compile_operations_are_deterministic_and_grouped() -> None:
    current, ports = _state()
    desired = DeviceConfig(
        vlans={
            30: VlanConfig(30, "create"),
            10: VlanConfig(10, "renamed", tagged_ports=[]),
            20: VlanConfig(20, state="absent"),
        },
        ports={1: PortConfig(1, speed_duplex="100M/Full")},
    )
    current_cfg = DeviceConfig.from_current(current, ports)
    plan = build_device_plan(current_cfg, desired)
    membership = plan_vlan_membership_changes(
        {1: {"untagged_vlan": 1, "tagged_vlans": {10}}}, desired.vlans.values(),
    )
    operations = compile_apply_operations(plan, desired, ports, membership)

    assert [(operation.kind, operation.key) for operation in operations] == [
        ("vlan_create", "vlan:30"),
        ("vlan_rename", "vlan:10"),
        ("vlan_membership", "vlan_membership:port:1"),
        ("port_update", "port:1"),
        ("vlan_delete", "vlan:20"),
    ]


def test_real_apply_posts_operations_in_deterministic_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current, ports = _state()
    post = (
        {
            1: VlanEntry(1, "default", untagged_ports=["Port 1"]),
            10: VlanEntry(10, "renamed"),
            30: VlanEntry(30, "create"),
        },
        [PortSettings(1, "Port 1", True, "100M/Full", False)],
    )
    switch = _switch(
        monkeypatch,
        policy=ApplyPolicy(backup_before_change=False, allow_port_mode_change=True),
    )
    monkeypatch.setattr(
        switch, "_read_current_state", MagicMock(side_effect=[(current, ports), post])
    )
    desired = DeviceConfig(
        vlans={
            30: VlanConfig(30, "create"),
            10: VlanConfig(10, "renamed", tagged_ports=[]),
            20: VlanConfig(20, state="absent"),
        },
        ports={1: PortConfig(1, speed_duplex="100M/Full")},
    )

    result = switch.apply(desired)

    posted = [call.args[0] for call in switch._session.post.call_args_list]
    assert posted == [
        "/staticvlan.cgi",
        "/staticvlan.cgi",
        "/vlanport.cgi",
        "/port.cgi",
        "/staticvlan.cgi",
    ]
    assert [item["kind"] for item in result["completed_operations"]] == [
        "vlan_create", "vlan_rename", "vlan_membership", "port_update", "vlan_delete",
    ]


def test_policy_preflight_blocks_before_backup_or_write(monkeypatch: pytest.MonkeyPatch) -> None:
    current, ports = _state()
    switch = _switch(monkeypatch, policy=ApplyPolicy(safety_port_id=1))
    monkeypatch.setattr(switch, "_read_current_state", lambda _: (current, ports))
    desired = DeviceConfig(ports={1: PortConfig(1, admin_up=False)})

    preview = switch.apply(desired, check_mode=True)
    assert preview["blocked"] is True
    assert preview["violations"]
    with pytest.raises(JTComPolicyError) as error:
        switch.apply(desired)
    assert error.value.violations == preview["violations"]
    switch._save_backup.assert_not_called()
    switch._session.post.assert_not_called()


def test_partial_write_preserves_original_error_and_completed_operations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current, ports = _state()
    switch = _switch(
        monkeypatch,
        policy=ApplyPolicy(backup_before_change=True, allow_port_mode_change=True),
    )
    post = ({**current, 30: VlanEntry(30, "create")}, ports)
    monkeypatch.setattr(
        switch, "_read_current_state", MagicMock(side_effect=[(current, ports), post, post])
    )
    switch._session.post.side_effect = [None, RuntimeError("membership rejected")]

    desired = DeviceConfig(
        vlans={30: VlanConfig(30, "create"), 10: VlanConfig(10, "old", tagged_ports=[])},
    )
    with pytest.raises(JTComApplyError) as error:
        switch.apply(desired)

    failure = error.value
    assert isinstance(failure.original_exception, RuntimeError)
    assert failure.__cause__ is failure.original_exception
    assert failure.backup_file == "/tmp/backup.cfg"
    assert failure.write_attempted is True
    assert failure.completed_operations == [{
        "key": "vlan:30", "kind": "vlan_create", "endpoint": "/staticvlan.cgi",
    }]
    assert failure.failed_operation["key"] == "vlan_membership:port:1"


def test_verification_failure_is_wrapped_with_readback(monkeypatch: pytest.MonkeyPatch) -> None:
    current, ports = _state()
    switch = _switch(monkeypatch, policy=ApplyPolicy(backup_before_change=False))
    monkeypatch.setattr(
        switch,
        "_read_current_state",
        MagicMock(side_effect=[(current, ports), (current, ports), (current, ports)]),
    )
    monkeypatch.setattr(
        switch,
        "_verify_vlan_membership",
        MagicMock(side_effect=JTComVerificationError({"total_changes": 1})),
    )
    with pytest.raises(JTComApplyError) as error:
        switch.apply(DeviceConfig(vlans={30: VlanConfig(30, "new")}))

    assert isinstance(error.value.original_exception, JTComVerificationError)
    assert error.value.failed_operation["kind"] == "verification"
    assert error.value.readback is not None


def test_success_reports_operations_and_uses_one_verification_readback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current, ports = _state()
    post = ({**current, 30: VlanEntry(30, "new")}, ports)
    switch = _switch(monkeypatch, policy=ApplyPolicy(backup_before_change=False))
    readback = MagicMock(side_effect=[(current, ports), post])
    monkeypatch.setattr(switch, "_read_current_state", readback)

    result = switch.apply(DeviceConfig(vlans={30: VlanConfig(30, "new")}))

    assert result["changed"] is True
    assert result["backup_file"] == ""
    assert result["applied"] == ["vlan:30"]
    assert result["completed_operations"] == result["operations"]
    assert readback.call_count == 2
    assert switch._session.post.call_count == 1


def test_backup_failure_has_no_completed_operations_or_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current, ports = _state()
    switch = _switch(monkeypatch)
    backup_error = OSError("backup unavailable")
    switch._save_backup.side_effect = backup_error
    monkeypatch.setattr(switch, "_read_current_state", lambda _: (current, ports))

    with pytest.raises(JTComApplyError) as error:
        switch.apply(DeviceConfig(vlans={30: VlanConfig(30, "new")}))

    assert error.value.original_exception is backup_error
    assert error.value.failed_operation["key"] == "backup"
    assert error.value.completed_operations == []
    assert error.value.write_attempted is False
    switch._session.post.assert_not_called()


def test_first_write_failure_is_reported_without_completed_operations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current, ports = _state()
    switch = _switch(monkeypatch, policy=ApplyPolicy(backup_before_change=False))
    write_error = RuntimeError("first write rejected")
    switch._session.post.side_effect = write_error
    monkeypatch.setattr(
        switch, "_read_current_state", MagicMock(side_effect=[(current, ports), (current, ports)])
    )

    with pytest.raises(JTComApplyError) as error:
        switch.apply(DeviceConfig(vlans={30: VlanConfig(30, "new")}))

    assert error.value.original_exception is write_error
    assert error.value.completed_operations == []
    assert error.value.failed_operation["key"] == "vlan:30"
    assert error.value.write_attempted is True


def test_late_payload_preflight_failure_happens_before_backup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current, ports = _state()
    switch = _switch(monkeypatch)
    monkeypatch.setattr(switch, "_read_current_state", lambda _: (current, ports))
    preflight_error = ValueError("payload cannot be represented")

    def fail_compile(*args: object, **kwargs: object) -> object:
        raise preflight_error

    monkeypatch.setattr("cgiswitch.switch.compile_apply_operations", fail_compile)

    with pytest.raises(ValueError, match="payload cannot") as error:
        switch.apply(DeviceConfig(vlans={30: VlanConfig(30, "new")}))

    assert error.value is preflight_error
    switch._save_backup.assert_not_called()
    switch._session.post.assert_not_called()


def test_readback_failure_preserves_verification_error_and_does_not_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current, ports = _state()
    switch = _switch(monkeypatch, policy=ApplyPolicy(backup_before_change=False))
    verify_error = TimeoutError("verification readback failed")
    recovery_error = ConnectionError("recovery readback failed")
    monkeypatch.setattr(
        switch,
        "_read_current_state",
        MagicMock(side_effect=[(current, ports), verify_error, recovery_error]),
    )

    with pytest.raises(JTComApplyError) as error:
        switch.apply(DeviceConfig(vlans={30: VlanConfig(30, "new")}))

    assert error.value.original_exception is verify_error
    assert error.value.readback is None
    assert error.value.readback_error is recovery_error
    assert error.value.failed_operation["kind"] == "verification"
    assert switch._session.post.call_count == 1
