"""Regression tests for fail-closed configuration preflight (F01/F03/F07)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cgiswitch import ApplyPolicy, JTComSwitch
from cgiswitch.client.errors import JTComStateError
from cgiswitch.model.config import DeviceConfig
from cgiswitch.model.port import PortConfig, PortSettings
from cgiswitch.model.vlan import VlanConfig, VlanEntry


@pytest.mark.parametrize("check_mode", [False, True])
@pytest.mark.parametrize("port_ids", [[9], [10, 9], [1, 9]])
def test_unknown_desired_ports_fail_before_backup_and_write(
    monkeypatch: pytest.MonkeyPatch,
    check_mode: bool,
    port_ids: list[int],
) -> None:
    switch = JTComSwitch("192.0.2.1", "admin", "secret")
    session = MagicMock()
    switch._session = session
    backup = MagicMock()
    monkeypatch.setattr(switch, "_save_backup", backup)
    monkeypatch.setattr(
        switch,
        "_read_current_state",
        lambda _: (
            {},
            [
                PortSettings(1, "Port 1", True, "Auto", False),
                PortSettings(2, "Port 2", True, "Auto", False),
            ],
        ),
    )
    with pytest.raises(ValueError, match="unknown ports") as exc:
        switch.apply(
            DeviceConfig(
                ports={pid: PortConfig(pid, admin_up=False) for pid in port_ids},
                vlans={20: VlanConfig(20, name="new")},
            ),
            check_mode=check_mode,
        )
    assert "known ports: [1, 2]" in str(exc.value)
    assert str(sorted(set(port_ids) - {1, 2})) in str(exc.value)
    backup.assert_not_called()
    session.post.assert_not_called()
    session.download_config_backup.assert_not_called()


@pytest.mark.parametrize("check_mode", [False, True])
@pytest.mark.parametrize("field", ["admin_up", "flow_control", "speed_duplex"])
def test_unknown_preserved_field_blocks_whole_plan(
    monkeypatch: pytest.MonkeyPatch,
    check_mode: bool,
    field: str,
) -> None:
    current = PortSettings(3, "Port 3", True, "Auto", False)
    setattr(current, field, None)
    desired = PortConfig(3, speed_duplex="100M/Full")
    if field == "speed_duplex":
        desired = PortConfig(3, flow_control=True)
    switch = JTComSwitch("192.0.2.1", "admin", "secret")
    session = MagicMock()
    switch._session = session
    backup = MagicMock()
    monkeypatch.setattr(switch, "_save_backup", backup)
    monkeypatch.setattr(switch, "_read_current_state", lambda _: ({}, [current]))
    with pytest.raises(ValueError, match=field):
        switch.apply(
            DeviceConfig(
                vlans={20: VlanConfig(20, name="new")},
                ports={3: desired},
            ),
            check_mode=check_mode,
        )
    backup.assert_not_called()
    session.post.assert_not_called()
    session.download_config_backup.assert_not_called()


@pytest.mark.parametrize("check_mode", [False, True])
def test_explicit_fields_resolve_unknown_current_values(
    monkeypatch: pytest.MonkeyPatch,
    check_mode: bool,
) -> None:
    switch = JTComSwitch(
        "192.0.2.1", "admin", "secret", policy=ApplyPolicy(backup_before_change=False)
    )
    session = MagicMock()
    switch._session = session
    current = PortSettings(3, "Port 3", None, None, None)
    post = PortSettings(3, "Port 3", True, "100M/Full", False)
    monkeypatch.setattr(
        switch,
        "_read_current_state",
        MagicMock(
            side_effect=[({}, [current]), ({}, [post])],
        ),
    )
    result = switch.apply(
        DeviceConfig(
            ports={
                3: PortConfig(
                    3,
                    admin_up=True,
                    speed_duplex="100M/Full",
                    flow_control=False,
                )
            }
        ),
        check_mode=check_mode,
    )
    assert result["changed"] is True
    assert session.post.call_count == (0 if check_mode else 1)
    if not check_mode:
        assert session.post.call_args.kwargs["data"] == {
            "portid": "2",
            "state": "1",
            "speed_duplex": "4",
            "flow": "0",
        }
    session.download_config_backup.assert_not_called()


@pytest.mark.parametrize(
    "mode,access,native,permit,field",
    [
        ("Access", "20", "--", "--", "access_vlan"),
        ("Trunk", "--", "20", "20", "native_vlan"),
        ("Trunk", "--", "1", "1,20", "permit_vlans"),
    ],
)
@pytest.mark.parametrize("check_mode", [False, True])
def test_readback_referencing_missing_vlan_fails_before_mutation(
    mode: str,
    access: str,
    native: str,
    permit: str,
    field: str,
    check_mode: bool,
) -> None:
    switch = JTComSwitch("192.0.2.1", "admin", "secret")
    session = MagicMock()
    switch._session = session
    session.get.side_effect = [
        '<form id="vlanDel"><table><tr><td></td><td>1</td>'
        "<td>1</td><td>default</td></tr></table></form>",
        "<table><tr><th>Port</th><th>VLAN Type</th><th>Access VLAN</th>"
        "<th>Native VLAN</th><th>Permit VLAN</th></tr>"
        f"<tr><td>Port 3</td><td>{mode}</td><td>{access}</td>"
        f"<td>{native}</td><td>{permit}</td></tr></table>",
    ]
    with pytest.raises(JTComStateError, match="20") as exc:
        switch.apply(DeviceConfig(), check_mode=check_mode)
    assert field in str(exc.value)
    assert "Port 3" in str(exc.value)
    session.post.assert_not_called()
    session.download_config_backup.assert_not_called()


def test_known_preserved_fields_are_not_replaced(monkeypatch: pytest.MonkeyPatch) -> None:
    switch = JTComSwitch(
        "192.0.2.1", "admin", "secret", policy=ApplyPolicy(backup_before_change=False)
    )
    session = MagicMock()
    switch._session = session
    vlans = {1: VlanEntry(1, "default", untagged_ports=["Port 3"])}
    monkeypatch.setattr(
        switch,
        "_read_current_state",
        MagicMock(
            side_effect=[
                (vlans, [PortSettings(3, "Port 3", False, "Auto", True)]),
                (vlans, [PortSettings(3, "Port 3", False, "100M/Full", True)]),
            ]
        ),
    )
    switch.apply(DeviceConfig(ports={3: PortConfig(3, speed_duplex="100M/Full")}))
    assert session.post.call_args.kwargs["data"] == {
        "portid": "2",
        "state": "0",
        "speed_duplex": "4",
        "flow": "1",
    }


@pytest.mark.parametrize("check_mode", [False, True])
@pytest.mark.parametrize(
    "field",
    [
        "tagged_ports",
        "untagged_ports",
        "tagged_add",
        "tagged_remove",
        "tagged_set",
        "untagged_add",
        "untagged_remove",
        "untagged_set",
    ],
)
def test_unknown_vlan_membership_ports_are_validated(
    monkeypatch: pytest.MonkeyPatch,
    check_mode: bool,
    field: str,
) -> None:
    switch = JTComSwitch("192.0.2.1", "admin", "secret")
    session = MagicMock()
    switch._session = session
    monkeypatch.setattr(
        switch,
        "_read_current_state",
        lambda _: (
            {},
            [
                PortSettings(1, "Port 1", True, "Auto", False),
            ],
        ),
    )
    vlan = VlanConfig(20, **{field: [9, 1]})
    with pytest.raises(ValueError, match=r"unknown ports: \[9\]"):
        switch.apply(DeviceConfig(vlans={20: vlan}), check_mode=check_mode)
    session.post.assert_not_called()
    session.download_config_backup.assert_not_called()


def test_mismatched_desired_port_key_fails_before_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    switch = JTComSwitch("192.0.2.1", "admin", "secret")
    session = MagicMock()
    switch._session = session
    monkeypatch.setattr(
        switch,
        "_read_current_state",
        lambda _: (
            {},
            [
                PortSettings(1, "Port 1", True, "Auto", False),
            ],
        ),
    )
    with pytest.raises(ValueError, match="mismatched port_id"):
        switch.apply(DeviceConfig(ports={1: PortConfig(9, admin_up=False)}))
    session.post.assert_not_called()
    session.download_config_backup.assert_not_called()


@pytest.mark.parametrize("check_mode", [False, True])
def test_mismatched_desired_vlan_key_fails_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
    check_mode: bool,
) -> None:
    switch = JTComSwitch("192.0.2.1", "admin", "secret")
    session = MagicMock()
    switch._session = session
    planner = MagicMock()
    monkeypatch.setattr("cgiswitch.switch.build_device_plan", planner)
    backup = MagicMock()
    monkeypatch.setattr(switch, "_save_backup", backup)
    monkeypatch.setattr(
        switch,
        "_read_current_state",
        lambda _: ({}, [PortSettings(1, "Port 1", True, "Auto", False)]),
    )

    with pytest.raises(ValueError, match="mismatched vlan_id"):
        switch.apply(
            DeviceConfig(vlans={20: VlanConfig(30, name="wrong-key")}),
            check_mode=check_mode,
        )

    planner.assert_not_called()
    backup.assert_not_called()
    session.post.assert_not_called()
    session.download_config_backup.assert_not_called()


@pytest.mark.parametrize("field", ["access", "native", "permit", "mode", "id"])
@pytest.mark.parametrize("check_mode", [False, True])
def test_malformed_vlan_page_blocks_apply_without_backup(field: str, check_mode: bool) -> None:
    from cgiswitch.client.errors import JTComParseError

    fixtures = Path(__file__).parent.parent / "fixtures"
    static = fixtures / ("malformed_vlan_id.html" if field == "id" else "vlan_static.html")
    port = fixtures / ("vlan_port_based.html" if field == "id" else f"malformed_vlan_{field}.html")
    switch = JTComSwitch("192.0.2.1", "admin", "secret")
    session = MagicMock()
    switch._session = session
    session.get.side_effect = [static.read_text(), port.read_text()]
    with pytest.raises(JTComParseError):
        switch.apply(DeviceConfig(vlans={20: VlanConfig(20, name="new")}), check_mode=check_mode)
    session.post.assert_not_called()
    session.download_config_backup.assert_not_called()


@pytest.mark.parametrize("vlan_ports", [[1], [1, 2, 3, 4, 5, 6, 9]])
def test_mismatched_current_port_inventories_fail(vlan_ports: list[int]) -> None:
    fixtures = Path(__file__).parent.parent / "fixtures"
    rows = "".join(
        f"<tr><td>Port {pid}</td><td>Access</td><td>1</td><td>--</td><td>--</td></tr>"
        for pid in vlan_ports
    )
    port_vlan = "<table><tr><th>Port</th><th>VLAN Type</th><th>Access VLAN</th>"
    port_vlan += "<th>Native VLAN</th><th>Permit VLAN</th></tr>" + rows + "</table>"
    switch = JTComSwitch("192.0.2.1", "admin", "secret")
    session = MagicMock()
    switch._session = session
    session.get.side_effect = [
        (fixtures / "vlan_static.html").read_text(),
        port_vlan,
        (fixtures / "port_settings.html").read_text(),
    ]
    with pytest.raises(JTComStateError, match="port inventory"):
        switch.apply(DeviceConfig(), check_mode=True)
    session.post.assert_not_called()
    session.download_config_backup.assert_not_called()


def test_consistent_current_fixture_pages_can_be_read_without_writes() -> None:
    fixtures = Path(__file__).parent.parent / "fixtures"
    switch = JTComSwitch("192.0.2.1", "admin", "secret")
    session = MagicMock()
    switch._session = session
    session.get.side_effect = [
        (fixtures / filename).read_text()
        for filename in (
            "vlan_static.html",
            "vlan_port_based.html",
            "port_settings.html",
        )
    ]
    assert switch.apply(DeviceConfig(), check_mode=True)["changed"] is False
    session.post.assert_not_called()
    session.download_config_backup.assert_not_called()


def test_trunk_readback_missing_native_in_permit_fails_with_port_context() -> None:
    fixtures = Path(__file__).parent.parent / "fixtures"
    switch = JTComSwitch("192.0.2.1", "admin", "secret")
    session = MagicMock()
    switch._session = session
    session.get.side_effect = [
        (fixtures / "vlan_static.html").read_text(),
        "<table><tr><th>Port</th><th>VLAN Type</th><th>Access VLAN</th>"
        "<th>Native VLAN</th><th>Permit VLAN</th></tr><tr><td>Port 3</td>"
        "<td>Trunk</td><td>--</td><td>1</td><td>10</td></tr></table>",
    ]
    with pytest.raises(JTComStateError, match="Port 3.*permit_vlans.*10.*native VLAN 1"):
        switch.read_vlans()
    session.post.assert_not_called()
