"""Verify the effective canonical target using the post-write snapshot."""

from unittest.mock import MagicMock

import pytest

from cgiswitch import ApplyPolicy, JTComApplyError, JTComSwitch
from cgiswitch.client.errors import JTComVerificationError
from cgiswitch.model.config import DeviceConfig
from cgiswitch.model.port import PortSettings
from cgiswitch.model.vlan import VlanConfig, VlanEntry


@pytest.mark.parametrize("rename", [False, True])
def test_fallback_resolved_noop_is_not_replayed_during_verification(
    monkeypatch: pytest.MonkeyPatch,
    rename: bool,
) -> None:
    switch = JTComSwitch("192.0.2.1", "admin", "secret")
    switch._session = MagicMock()
    backup = MagicMock(return_value="/tmp/backup.cfg")
    monkeypatch.setattr(switch, "_save_backup", backup)
    ports = [PortSettings(1, "Port 1", True, "Auto", False)]
    current = {1: VlanEntry(1, "default", untagged_ports=["Port 1"]), 20: VlanEntry(20, "old")}
    post = {1: current[1], 20: VlanEntry(20, "new" if rename else "old")}
    reader = MagicMock(side_effect=[(current, ports), (post, ports)])
    monkeypatch.setattr(switch, "_read_current_state", reader)
    desired = DeviceConfig(vlans={1: VlanConfig(1, untagged_remove=[1])})
    if rename:
        desired.vlans[20] = VlanConfig(20, name="new")
    result = switch.apply(desired)
    assert result["changed"] is rename
    assert result["applied"] == (["vlan:20"] if rename else [])
    assert reader.call_count == (2 if rename else 1)
    assert backup.call_count == int(rename)
    assert switch._session.post.call_count == int(rename)


def test_membership_verification_failure_preserves_confirmed_write_and_diff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    switch = JTComSwitch(
        "192.0.2.1",
        "admin",
        "secret",
        policy=ApplyPolicy(
            allow_port_mode_change=True,
            backup_before_change=False,
        ),
    )
    switch._session = MagicMock()
    ports = [PortSettings(1, "Port 1", True, "Auto", False)]
    current = {1: VlanEntry(1, "default", untagged_ports=["Port 1"]), 20: VlanEntry(20, "existing")}
    reader = MagicMock(side_effect=[(current, ports)] * 3)
    monkeypatch.setattr(switch, "_read_current_state", reader)
    with pytest.raises(JTComApplyError) as captured:
        switch.apply(DeviceConfig(vlans={20: VlanConfig(20, tagged_add=[1])}))
    failure = captured.value
    assert isinstance(failure.original_exception, JTComVerificationError)
    assert failure.__cause__ is failure.original_exception
    assert failure.applied == ["vlan_membership:port:1"]
    assert failure.failed_operation == {"key": "verify", "kind": "verification"}
    assert failure.as_result()["remaining_diff"]["total_changes"] == 1
    assert failure.readback is not None
    assert reader.call_count == 3
    switch._session.post.assert_called_once()


@pytest.mark.parametrize("check_mode", [False, True])
def test_late_membership_compile_failure_precedes_backup_and_all_writes(
    monkeypatch: pytest.MonkeyPatch,
    check_mode: bool,
) -> None:
    from cgiswitch.utils.vlan_membership import VlanMembershipPlan, make_port_state

    switch = JTComSwitch("192.0.2.1", "admin", "secret")
    switch._session = MagicMock()
    backup = MagicMock()
    monkeypatch.setattr(switch, "_save_backup", backup)
    ports = [PortSettings(pid, f"Port {pid}", True, "Auto", False) for pid in [2, 10]]
    current = {1: VlanEntry(1, "default", untagged_ports=["Port 2", "Port 10"])}
    monkeypatch.setattr(switch, "_read_current_state", lambda _: (current, ports))
    # Exercise the real compiler defensively, even if a future planner misses a violation.
    membership = VlanMembershipPlan(
        current_per_port={pid: make_port_state(untagged_vlan=1) for pid in [2, 10]},
        desired_per_port={
            2: make_port_state(untagged_vlan=1, tagged_vlans={20}),
            10: make_port_state(tagged_vlans={20}),
        },
        changed_ports=[2, 10],
        changed_vlans=[20],
    )
    monkeypatch.setattr(switch, "_plan_vlan_membership", lambda *_args, **_kwargs: membership)
    with pytest.raises(ValueError, match="Port 10 canonical state cannot be compiled"):
        switch.apply(DeviceConfig(vlans={20: VlanConfig(20, "new")}), check_mode=check_mode)
    backup.assert_not_called()
    switch._session.post.assert_not_called()
    switch._session.download_config_backup.assert_not_called()


def test_verification_does_not_skip_a_missing_requested_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cgiswitch.model.port import PortConfig

    switch = JTComSwitch(
        "192.0.2.1",
        "admin",
        "secret",
        policy=ApplyPolicy(
            backup_before_change=False,
        ),
    )
    switch._session = MagicMock()
    before = (
        {1: VlanEntry(1, "default", untagged_ports=["Port 1"])},
        [PortSettings(1, "Port 1", True, "Auto", False)],
    )
    after = ({1: VlanEntry(1, "default")}, [])
    monkeypatch.setattr(
        switch, "_read_current_state", MagicMock(side_effect=[before, after, after])
    )
    with pytest.raises(JTComApplyError) as captured:
        switch.apply(DeviceConfig(ports={1: PortConfig(1, flow_control=True)}))
    error = captured.value
    assert isinstance(error.original_exception, JTComVerificationError)
    assert error.applied == ["port:1"]
    assert error.as_result()["remaining_diff"]["changes"] == [
        {"kind": "port_missing", "key": "port:1", "details": {"port_id": 1}},
    ]
    switch._session.post.assert_called_once()
