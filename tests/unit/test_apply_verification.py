"""Verify the effective canonical target using the post-write snapshot."""

from unittest.mock import MagicMock

import pytest

from cgiswitch import ApplyPolicy, JTComApplyError, JTComSwitch
from cgiswitch.client.errors import JTComVerificationError
from cgiswitch.model.config import DeviceConfig
from cgiswitch.model.port import PortSettings
from cgiswitch.model.vlan import VlanConfig, VlanEntry


@pytest.mark.parametrize("check_mode", [False, True])
@pytest.mark.parametrize("rename", [False, True])
def test_fallback_resolved_noop_is_not_replayed_during_verification(
    monkeypatch: pytest.MonkeyPatch,
    rename: bool,
    check_mode: bool,
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
    result = switch.apply(desired, check_mode=check_mode)
    assert result["diff"]["total_changes"] == int(rename)
    assert [c["key"] for c in result["diff"]["changes"]] == (["vlan:20"] if rename else [])
    assert sum(result["diff"]["summary"].values()) == int(rename)
    assert result["diff"]["vlan_membership"]["before"] == result["diff"]["vlan_membership"]["after"]
    assert result["changed"] is rename
    writes = rename and not check_mode
    assert result["applied"] == (["vlan:20"] if writes else [])
    assert reader.call_count == (2 if writes else 1)
    assert backup.call_count == int(writes)
    assert switch._session.post.call_count == int(writes)


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
    converged = {1: current[1], 20: VlanEntry(20, "existing", tagged_ports=["Port 1"])}
    reader = MagicMock(side_effect=[(current, ports), (current, ports), (converged, ports)])
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
    assert failure.readback["vlans"][20]["tagged_ports"] == []
    assert reader.call_count == 2
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


def test_failed_verification_read_uses_recovery_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    switch = JTComSwitch(
        "192.0.2.1",
        "admin",
        "secret",
        policy=ApplyPolicy(
            backup_before_change=False,
        ),
    )
    switch._session = MagicMock()
    current = {1: VlanEntry(1, "default")}
    recovered = {**current, 20: VlanEntry(20, "new")}
    read_error = TimeoutError("verification read failed")
    reader = MagicMock(side_effect=[(current, []), read_error, (recovered, [])])
    monkeypatch.setattr(switch, "_read_current_state", reader)
    with pytest.raises(JTComApplyError) as captured:
        switch.apply(DeviceConfig(vlans={20: VlanConfig(20, "new")}))
    error = captured.value
    assert error.original_exception is error.__cause__ is read_error
    assert error.readback is not None
    assert error.readback["vlans"][20]["name"] == "new"
    assert error.readback_error is None
    assert reader.call_count == 3
    switch._session.post.assert_called_once()


def test_scalar_mismatch_keeps_the_snapshot_that_produced_remaining_diff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    switch = JTComSwitch(
        "192.0.2.1",
        "admin",
        "secret",
        policy=ApplyPolicy(
            backup_before_change=False,
        ),
    )
    switch._session = MagicMock()
    current = {20: VlanEntry(20, "old")}
    later = {20: VlanEntry(20, "new")}
    reader = MagicMock(side_effect=[(current, []), (current, []), (later, [])])
    monkeypatch.setattr(switch, "_read_current_state", reader)
    with pytest.raises(JTComApplyError) as captured:
        switch.apply(DeviceConfig(vlans={20: VlanConfig(20, "new")}))
    error = captured.value
    assert error.readback is not None
    assert error.readback["vlans"][20]["name"] == "old"
    assert error.as_result()["remaining_diff"]["changes"][0]["details"]["name"] == {
        "from": "old",
        "to": "new",
    }
    assert reader.call_count == 2


def test_effective_diff_includes_implicit_fallback_destination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    switch = JTComSwitch(
        "192.0.2.1",
        "admin",
        "secret",
        policy=ApplyPolicy(
            allow_untagged_move=True,
        ),
    )
    switch._session = MagicMock()
    current = {1: VlanEntry(1, "default"), 20: VlanEntry(20, "users", untagged_ports=["Port 1"])}
    ports = [PortSettings(1, "Port 1", True, "Auto", False)]
    monkeypatch.setattr(switch, "_read_current_state", lambda _: (current, ports))
    desired = DeviceConfig(vlans={20: VlanConfig(20, untagged_remove=[1])})
    result = switch.apply(desired, check_mode=True)
    assert result["changed"] is True
    assert result["diff"]["total_changes"] == 2
    assert [(c["key"], c["details"]["untagged_ports"]) for c in result["diff"]["changes"]] == [
        ("vlan:1", {"from": [], "to": [1]}),
        ("vlan:20", {"from": [1], "to": []}),
    ]
    assert desired.vlans[20].untagged_remove == [1]
    assert current[20].untagged_ports == ["Port 1"]
    switch._session.post.assert_not_called()
