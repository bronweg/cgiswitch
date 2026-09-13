"""Exercise every write position through the complete apply orchestrator."""

from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from cgiswitch import ApplyPolicy, JTComApplyError, JTComSwitch
from cgiswitch.model.config import DeviceConfig
from cgiswitch.model.port import PortConfig, PortSettings
from cgiswitch.model.vlan import VlanConfig, VlanEntry


@pytest.mark.parametrize("failed_index", [None, *range(10)])
def test_full_operation_order_and_failure_at_each_position(
    monkeypatch: pytest.MonkeyPatch,
    failed_index: int | None,
) -> None:
    events: list[object] = []
    current = {
        500: VlanEntry(500, "delete"),
        50: VlanEntry(50, "delete"),
        30: VlanEntry(30, "old"),
        3: VlanEntry(3, "old"),
        4: VlanEntry(4, "tagged", tagged_ports=["Port 10", "Port 2"]),
        1: VlanEntry(1, "default", untagged_ports=["Port 10", "Port 2"]),
    }
    ports = [PortSettings(pid, f"Port {pid}", True, "Auto", False) for pid in [10, 2]]
    desired = DeviceConfig(
        vlans={
            500: VlanConfig(500, state="absent"),
            100: VlanConfig(100, "create100"),
            30: VlanConfig(30, "rename30"),
            50: VlanConfig(50, state="absent"),
            4: VlanConfig(4, tagged_remove=[10, 2]),
            3: VlanConfig(3, "rename3"),
            2: VlanConfig(2, "create2"),
        },
        ports={10: PortConfig(10, flow_control=True), 2: PortConfig(2, flow_control=True)},
    )
    post = {
        1: current[1],
        4: VlanEntry(4, "tagged"),
        2: VlanEntry(2, "create2"),
        100: VlanEntry(100, "create100"),
        3: VlanEntry(3, "rename3"),
        30: VlanEntry(30, "rename30"),
    }
    post_ports = [PortSettings(pid, f"Port {pid}", True, "Auto", True) for pid in [10, 2]]
    states = iter(
        [(current, ports), (post, post_ports) if failed_index is None else (current, ports)]
    )

    def read(_session: object) -> tuple[dict[int, VlanEntry], list[PortSettings]]:
        events.append("read")
        return next(states)

    def backup(*_args: object) -> str:
        events.append("backup")
        return "/tmp/saved.cfg"

    failure = TimeoutError("write outcome unknown")
    posted: list[tuple[str, object]] = []

    def write(endpoint: str, *, data: object) -> None:
        events.append("write")
        posted.append((endpoint, deepcopy(data)))
        if len(posted) - 1 == failed_index:
            raise failure

    switch = JTComSwitch(
        "192.0.2.1",
        "admin",
        "secret",
        policy=ApplyPolicy(
            allow_port_mode_change=True,
        ),
    )
    switch._session = MagicMock()
    switch._session.post.side_effect = write
    monkeypatch.setattr(switch, "_read_current_state", read)
    monkeypatch.setattr(switch, "_save_backup", backup)
    expected_keys = [
        "vlan:2",
        "vlan:100",
        "vlan:3",
        "vlan:30",
        "vlan_membership:port:2",
        "vlan_membership:port:10",
        "port:2",
        "port:10",
        "vlan:500",
        "vlan:50",
    ]
    if failed_index is None:
        result = switch.apply(desired)
        assert result["applied"] == expected_keys
        assert result["completed_operations"] == result["operations"]
        assert result["backup_file"] == "/tmp/saved.cfg"
    else:
        with pytest.raises(JTComApplyError) as captured:
            switch.apply(desired)
        error = captured.value
        assert error.original_exception is error.__cause__ is failure
        assert error.applied == expected_keys[:failed_index]
        assert [op["key"] for op in error.completed_operations] == expected_keys[:failed_index]
        assert error.failed_operation["key"] == expected_keys[failed_index]
        assert error.backup_file == "/tmp/saved.cfg"
        assert error.readback is not None
        assert error.readback_error is None
        assert error.as_result()["changed"] is True
    count = 10 if failed_index is None else failed_index + 1
    assert events == ["read", "backup", *(["write"] * count), "read"]
    expected_payloads: list[tuple[str, object]] = [
        ("/staticvlan.cgi", {"vlanid": "2", "vlanname": "create2", "cmd": "add"}),
        ("/staticvlan.cgi", {"vlanid": "100", "vlanname": "create100", "cmd": "add"}),
        ("/staticvlan.cgi", {"vlanid": "3", "vlanname": "rename3", "cmd": "add"}),
        ("/staticvlan.cgi", {"vlanid": "30", "vlanname": "rename30", "cmd": "add"}),
        *[
            (
                "/vlanport.cgi",
                {
                    "PortId": str(pid - 1),
                    "VlanType": "0",
                    "AccessVlan": "1",
                    "NativeVlan": "1",
                    "PermitVlan": "",
                },
            )
            for pid in [2, 10]
        ],
        *[
            ("/port.cgi", {"portid": str(pid - 1), "state": "1", "speed_duplex": "0", "flow": "1"})
            for pid in [2, 10]
        ],
        ("/staticvlan.cgi", [("del", "500"), ("cmd", "del")]),
        ("/staticvlan.cgi", [("del", "50"), ("cmd", "del")]),
    ]
    assert posted == expected_payloads[:count]
