"""Regression tests for strict Ansible action argument validation."""

from __future__ import annotations

from typing import Any

import pytest
from test_policy_action import _action, _load_action

from cgiswitch.model.config import DeviceConfig
from cgiswitch.model.port import PortConfig
from cgiswitch.model.vlan import VlanConfig


def _assert_rejected_without_switch(
    monkeypatch: pytest.MonkeyPatch,
    args: dict[str, Any],
    check_mode: bool = False,
) -> None:
    module = _load_action()
    calls: list[str] = []

    class UnexpectedSwitch:
        def __init__(self, **kwargs: object) -> None:
            calls.append("construct")

        def open(self) -> None:
            calls.append("open")

    monkeypatch.setattr("cgiswitch.switch.JTComSwitch", UnexpectedSwitch)

    result = _action(module, args, check_mode=check_mode).run()

    assert result["failed"] is True
    assert result["changed"] is False
    assert calls == []


@pytest.mark.parametrize(
    "args",
    [
        {"vlans": None},
        {"vlans": []},
        {"vlans": "10"},
        {"ports": None},
        {"ports": []},
        {"ports": "1"},
        {"vlans": {10: None}},
        {"vlans": {10: []}},
        {"vlans": {10: "entry"}},
        {"ports": {1: None}},
        {"ports": {1: []}},
        {"ports": {1: "entry"}},
        {"ports": {1: {"flow_controll": True}}},
        {"vlans": {10: {"unknown": True}}},
        {"vlans": {10: {1: True}}},
        {"vlans": {10: {1: True, "oops": False}}},
    ],
)
@pytest.mark.parametrize("check_mode", [False, True])
def test_invalid_maps_entries_and_nested_keys_fail_before_switch(
    monkeypatch: pytest.MonkeyPatch,
    args: dict[str, Any],
    check_mode: bool,
) -> None:
    _assert_rejected_without_switch(monkeypatch, args, check_mode)


@pytest.mark.parametrize(
    "args",
    [
        {"vlans": {True: {}}},
        {"vlans": {1.5: {}}},
        {"vlans": {"1.5": {}}},
        {"vlans": {"\u0661": {}}},
        {"vlans": {0: {}}},
        {"vlans": {4095: {}}},
        {"ports": {True: {}}},
        {"ports": {1.5: {}}},
        {"ports": {"1.5": {}}},
        {"ports": {"\u0661": {}}},
        {"ports": {0: {}}},
        {"vlans": {"01": {}, 1: {}}},
        {"ports": {"01": {}, 1: {}}},
    ],
)
@pytest.mark.parametrize("check_mode", [False, True])
def test_invalid_ids_and_duplicate_normalized_keys_fail_before_switch(
    monkeypatch: pytest.MonkeyPatch,
    args: dict[str, Any],
    check_mode: bool,
) -> None:
    _assert_rejected_without_switch(monkeypatch, args, check_mode)


@pytest.mark.parametrize(
    "args",
    [
        {"vlans": {10: {"tagged_ports": 1}}},
        {"vlans": {10: {"tagged_ports": "1"}}},
        {"vlans": {10: {"tagged_ports": [1, True]}}},
        {"vlans": {10: {"tagged_ports": [1.0]}}},
        {"vlans": {10: {"tagged_ports": ["1"]}}},
        {"vlans": {10: {"tagged_ports": [0]}}},
        {"vlans": {10: {"name": 10}}},
        {"vlans": {10: {"state": True}}},
        {"ports": {1: {"admin_up": 1}}},
        {"ports": {1: {"flow_control": "false"}}},
        {"ports": {1: {"access_vlan": True}}},
        {"ports": {1: {"access_vlan": 1.0}}},
        {"ports": {1: {"access_vlan": "10"}}},
        {"ports": {1: {"access_vlan": 0}}},
        {"ports": {1: {"access_vlan": 4095}}},
        {"ports": {1: {"trunk_set_vlans": [10, False]}}},
        {"ports": {1: {"trunk_set_vlans": [10.0]}}},
        {"ports": {1: {"trunk_set_vlans": ["10"]}}},
        {"ports": {1: {"trunk_set_vlans": [0]}}},
        {"ports": {1: {"trunk_set_vlans": [4095]}}},
        {"ports": {1: {"speed": 1000}}},
        {"ports": {1: {"speed": "invalid"}}},
        {"ports": {1: {"access_vlan": 10, "trunk_set_vlans": [20]}}},
        {"vlans": {10: {"tagged_add": [1], "tagged_set": [2]}}},
    ],
)
@pytest.mark.parametrize("check_mode", [False, True])
def test_invalid_nested_values_fail_before_switch(
    monkeypatch: pytest.MonkeyPatch,
    args: dict[str, Any],
    check_mode: bool,
) -> None:
    _assert_rejected_without_switch(monkeypatch, args, check_mode)


@pytest.mark.parametrize(
    "args",
    [
        {"unexpected": True},
        {"verify_tls": 1},
        {"backup_before_change": "yes"},
        {"allow_port_mode_change": None},
        {"safety_port_id": None},
        {"safety_port_id": True},
        {"safety_port_id": 6.0},
        {"safety_port_id": "6"},
        {"safety_port_id": 0},
        {"safety_port_id": -1},
        {"host": ""},
        {"username": 1},
        {"password": None},
    ],
)
@pytest.mark.parametrize("check_mode", [False, True])
def test_invalid_top_level_arguments_fail_before_switch(
    monkeypatch: pytest.MonkeyPatch,
    args: dict[str, Any],
    check_mode: bool,
) -> None:
    _assert_rejected_without_switch(monkeypatch, args, check_mode)


def test_optional_null_values_are_forwarded_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_action()
    seen: list[DeviceConfig] = []

    class FakeSwitch:
        def __init__(self, **kwargs: object) -> None:
            pass

        def open(self) -> None:
            pass

        def close(self) -> None:
            pass

        def apply(self, desired: DeviceConfig, *, check_mode: bool) -> dict[str, object]:
            seen.append(desired)
            return {"changed": False, "diff": {}}

    monkeypatch.setattr("cgiswitch.switch.JTComSwitch", FakeSwitch)
    result = _action(
        module,
        {
            "vlans": {"10": {"name": None, "tagged_ports": None, "state": "present"}},
            "ports": {
                "1": {
                    "admin_up": None,
                    "speed": None,
                    "flow_control": None,
                    "access_vlan": None,
                    "native_vlan": None,
                    "trunk_set_vlans": None,
                }
            },
        },
    ).run()

    assert result["changed"] is False
    assert seen == [
        DeviceConfig(
            vlans={10: VlanConfig(10, name=None, tagged_ports=None)},
            ports={
                1: PortConfig(
                    1,
                    admin_up=None,
                    speed_duplex=None,
                    flow_control=None,
                    access_vlan=None,
                    native_vlan=None,
                    trunk_set_vlans=None,
                )
            },
        )
    ]


@pytest.mark.parametrize("vlan_key", [10, "10", 4094])
@pytest.mark.parametrize("port_key", [1, "1", 9999])
@pytest.mark.parametrize("check_mode", [False, True])
def test_valid_config_forwards_desired_and_check_mode(
    monkeypatch: pytest.MonkeyPatch,
    vlan_key: int | str,
    port_key: int | str,
    check_mode: bool,
) -> None:
    module = _load_action()
    seen: list[tuple[DeviceConfig, bool]] = []

    class FakeSwitch:
        def __init__(self, **kwargs: object) -> None:
            pass

        def open(self) -> None:
            pass

        def close(self) -> None:
            pass

        def apply(self, desired: DeviceConfig, *, check_mode: bool) -> dict[str, object]:
            seen.append((desired, check_mode))
            return {"changed": False, "diff": {}}

    monkeypatch.setattr("cgiswitch.switch.JTComSwitch", FakeSwitch)
    result = _action(
        module,
        {
            "vlans": {vlan_key: {"name": "users", "tagged_ports": [2]}},
            "ports": {
                port_key: {"admin_up": True, "speed": "1G/Full", "access_vlan": int(vlan_key)}
            },
        },
        check_mode=check_mode,
    ).run()

    assert result["changed"] is False
    assert seen == [
        (
            DeviceConfig(
                vlans={int(vlan_key): VlanConfig(
                    int(vlan_key),
                    name="users",
                    tagged_ports=[2],
                )},
                ports={
                    int(port_key): PortConfig(
                        int(port_key), admin_up=True,
                        speed_duplex="1000M/Full", access_vlan=int(vlan_key)
                    )
                },
            ),
            check_mode,
        )
    ]
