"""Unit tests for the device-level diff / plan engine."""

from __future__ import annotations

from typing import Literal

import pytest

from cgiswitch.model.config import DeviceConfig
from cgiswitch.model.port import PortConfig
from cgiswitch.model.vlan import VlanConfig
from cgiswitch.utils.device_diff import build_device_plan

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cfg(
    vlans: dict[int, VlanConfig] | None = None,
    ports: dict[int, PortConfig] | None = None,
) -> DeviceConfig:
    return DeviceConfig(vlans=vlans or {}, ports=ports or {})


def _vlan(
    vid: int,
    name: str = "v",
    tagged: list[int] | None = None,
    untagged: list[int] | None = None,
    state: Literal["present", "absent"] = "present",
) -> VlanConfig:
    return VlanConfig(
        vlan_id=vid,
        name=name,
        tagged_ports=tagged or [],
        untagged_ports=untagged or [],
        state=state,
    )


def _port(
    pid: int,
    admin_up: bool | None = None,
    speed: str | None = None,
    flow: bool | None = None,
) -> PortConfig:
    return PortConfig(
        port_id=pid,
        admin_up=admin_up,
        speed_duplex=speed,
        flow_control=flow,
    )


# ---------------------------------------------------------------------------
# No-change cases
# ---------------------------------------------------------------------------


def test_no_changes_empty_configs() -> None:
    plan = build_device_plan(_cfg(), _cfg())
    assert plan.changes == []
    assert plan.summary == {"vlan_create": 0, "vlan_update": 0,
                            "port_update": 0, "vlan_delete": 0}


def test_no_changes_identical_vlan() -> None:
    cfg = _cfg(vlans={10: _vlan(10, "data", untagged=[1, 2])})
    plan = build_device_plan(cfg, cfg)
    assert plan.changes == []


def test_no_changes_identical_port() -> None:
    cfg = _cfg(ports={1: _port(1, admin_up=True, speed="Auto", flow=True)})
    plan = build_device_plan(cfg, cfg)
    assert plan.changes == []


def test_unlisted_vlan_not_touched() -> None:
    """VLANs absent from desired are never deleted or modified."""
    cur = _cfg(vlans={10: _vlan(10), 20: _vlan(20)})
    des = _cfg()  # empty desired — no changes
    plan = build_device_plan(cur, des)
    assert plan.changes == []


# ---------------------------------------------------------------------------
# VLAN creates
# ---------------------------------------------------------------------------


def test_vlan_create_new_vlan() -> None:
    cur = _cfg()
    des = _cfg(vlans={20: _vlan(20, "new")})
    plan = build_device_plan(cur, des)
    assert len(plan.changes) == 1
    ch = plan.changes[0]
    assert ch.kind == "vlan_create"
    assert ch.key == "vlan:20"
    assert ch.details["vlan_id"] == 20


def test_vlan_create_sorted_ascending() -> None:
    cur = _cfg()
    des = _cfg(vlans={30: _vlan(30), 10: _vlan(10), 20: _vlan(20)})
    plan = build_device_plan(cur, des)
    kinds = [c.kind for c in plan.changes]
    assert kinds == ["vlan_create", "vlan_create", "vlan_create"]
    vids = [c.details["vlan_id"] for c in plan.changes]
    assert vids == [10, 20, 30]


# ---------------------------------------------------------------------------
# VLAN updates
# ---------------------------------------------------------------------------


def test_vlan_update_name_change() -> None:
    cur = _cfg(vlans={10: _vlan(10, "old")})
    des = _cfg(vlans={10: _vlan(10, "new")})
    plan = build_device_plan(cur, des)
    assert len(plan.changes) == 1
    ch = plan.changes[0]
    assert ch.kind == "vlan_update"
    assert ch.details["name"] == {"from": "old", "to": "new"}


def test_vlan_update_membership_change() -> None:
    cur = _cfg(vlans={10: _vlan(10, untagged=[1])})
    des = _cfg(vlans={10: _vlan(10, untagged=[1, 2])})
    plan = build_device_plan(cur, des)
    assert len(plan.changes) == 1
    assert plan.changes[0].kind == "vlan_update"


def test_vlan_update_preserves_none_membership_when_side_omitted() -> None:
    cur = _cfg(
        vlans={
            10: VlanConfig(
                vlan_id=10,
                name="data",
                tagged_ports=None,
                untagged_ports=[],
            )
        }
    )
    des = _cfg(vlans={10: VlanConfig(vlan_id=10)})
    plan = build_device_plan(cur, des)
    assert plan.changes == []


def test_vlan_update_remove_only_membership_diff_shows_resulting_membership() -> None:
    cur = _cfg(vlans={10: VlanConfig(vlan_id=10, tagged_ports=[10, 20, 30])})
    des = _cfg(vlans={10: VlanConfig(vlan_id=10, tagged_remove=[20])})
    plan = build_device_plan(cur, des)
    assert len(plan.changes) == 1
    assert plan.changes[0].details["tagged_ports"] == {
        "from": [10, 20, 30],
        "to": [10, 30],
    }
    assert "meta" not in plan.changes[0].details["tagged_ports"]


def test_vlan_update_add_remove_membership_diff_shows_resulting_membership() -> None:
    cur = _cfg(vlans={10: VlanConfig(vlan_id=10, tagged_ports=[10, 20])})
    des = _cfg(vlans={10: VlanConfig(vlan_id=10, tagged_add=[30], tagged_remove=[10])})
    plan = build_device_plan(cur, des)
    assert len(plan.changes) == 1
    assert plan.changes[0].details["tagged_ports"] == {
        "from": [10, 20],
        "to": [20, 30],
    }
    assert "meta" not in plan.changes[0].details["tagged_ports"]


def test_vlan_update_unknown_baseline_add_remove_has_structured_meta() -> None:
    cur = _cfg(
        vlans={10: VlanConfig(vlan_id=10, tagged_ports=None, untagged_ports=[])}
    )
    des = _cfg(vlans={10: VlanConfig(vlan_id=10, tagged_add=[3], tagged_remove=[1])})
    plan = build_device_plan(cur, des)
    assert len(plan.changes) == 1
    tagged_diff = plan.changes[0].details["tagged_ports"]
    assert tagged_diff["from"] is None
    assert tagged_diff["to"] is None
    assert "unknown current membership" in tagged_diff["note"]
    assert tagged_diff["meta"] == {
        "unknown_membership": True,
        "reason": "unknown_current_baseline_with_add_remove",
    }


def test_new_vlan_create_unknown_membership_is_internal_invariant_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cgiswitch.utils import device_diff as dd

    monkeypatch.setattr(
        dd,
        "apply_vlan_membership_config",
        lambda _tagged, _untagged, _cfg: (None, set()),
    )
    cur = _cfg()
    des = _cfg(vlans={20: VlanConfig(vlan_id=20)})
    with pytest.raises(AssertionError, match="Internal invariant violated"):
        build_device_plan(cur, des)


# ---------------------------------------------------------------------------
# VLAN deletes
# ---------------------------------------------------------------------------


def test_vlan_delete_when_state_absent() -> None:
    cur = _cfg(vlans={1: _vlan(1), 10: _vlan(10), 20: _vlan(20)})
    des = _cfg(vlans={10: _vlan(10, state="absent"), 20: _vlan(20, state="absent")})
    plan = build_device_plan(cur, des)
    delete_kinds = [c for c in plan.changes if c.kind == "vlan_delete"]
    vids = [c.details["vlan_id"] for c in delete_kinds]
    assert sorted(vids) == [10, 20]
    # Deletes must be in descending VID order
    assert vids == [20, 10]


def test_vlan_1_never_deleted() -> None:
    cur = _cfg(vlans={1: _vlan(1), 5: _vlan(5)})
    des = _cfg(vlans={1: _vlan(1, state="absent"), 5: _vlan(5, state="absent")})
    plan = build_device_plan(cur, des)
    deleted_vids = [c.details["vlan_id"] for c in plan.changes if c.kind == "vlan_delete"]
    assert 1 not in deleted_vids
    assert 5 in deleted_vids


# ---------------------------------------------------------------------------
# Port updates
# ---------------------------------------------------------------------------


def test_port_update_admin_up_change() -> None:
    cur = _cfg(ports={2: _port(2, admin_up=True, speed="Auto", flow=True)})
    des = _cfg(ports={2: _port(2, admin_up=False)})
    plan = build_device_plan(cur, des)
    assert len(plan.changes) == 1
    ch = plan.changes[0]
    assert ch.kind == "port_update"
    assert ch.key == "port:2"
    assert ch.details["admin_up"] == {"from": True, "to": False}


def test_port_update_speed_duplex_change() -> None:
    cur = _cfg(ports={1: _port(1, admin_up=True, speed="Auto", flow=True)})
    des = _cfg(ports={1: _port(1, speed="1000M/Full")})
    plan = build_device_plan(cur, des)
    assert plan.changes[0].details["speed_duplex"] == {"from": "Auto", "to": "1000M/Full"}


def test_port_update_flow_control_change() -> None:
    cur = _cfg(ports={3: _port(3, admin_up=True, speed="Auto", flow=True)})
    des = _cfg(ports={3: _port(3, flow=False)})
    plan = build_device_plan(cur, des)
    assert plan.changes[0].details["flow_control"] == {"from": True, "to": False}


def test_port_update_none_field_not_diffed() -> None:
    """None in desired means 'don't care' — no change planned."""
    cur = _cfg(ports={1: _port(1, admin_up=True, speed="Auto", flow=True)})
    des = _cfg(ports={1: _port(1)})  # all fields None
    plan = build_device_plan(cur, des)
    assert plan.changes == []


def test_port_unknown_to_current_skipped() -> None:
    """Desired port not in current → silently ignored."""
    cur = _cfg()
    des = _cfg(ports={99: _port(99, admin_up=True)})
    plan = build_device_plan(cur, des)
    assert plan.changes == []


def test_port_admin_up_false_disables() -> None:
    """admin_up=False on a port entry produces a port_update to disable it."""
    cur = _cfg(ports={3: _port(3, admin_up=True, speed="Auto", flow=True)})
    des = _cfg(ports={3: _port(3, admin_up=False)})
    plan = build_device_plan(cur, des)
    assert len(plan.changes) == 1
    ch = plan.changes[0]
    assert ch.kind == "port_update"
    assert ch.details["admin_up"] == {"from": True, "to": False}


# ---------------------------------------------------------------------------
# Safety-port planning
# ---------------------------------------------------------------------------


def test_safety_port_disable_remains_in_plan() -> None:
    cur = _cfg(ports={6: _port(6, admin_up=True, speed="Auto", flow=True)})
    des = _cfg(ports={6: _port(6, admin_up=False)})
    plan = build_device_plan(cur, des)
    assert len(plan.changes) == 1
    assert plan.changes[0].details["admin_up"] == {"from": True, "to": False}


def test_safety_port_allows_enable() -> None:
    cur = _cfg(ports={6: _port(6, admin_up=False, speed="Auto", flow=True)})
    des = _cfg(ports={6: _port(6, admin_up=True)})
    plan = build_device_plan(cur, des)
    assert len(plan.changes) == 1
    assert plan.changes[0].details["admin_up"] == {"from": False, "to": True}


def test_safety_port_allows_speed_change() -> None:
    cur = _cfg(ports={6: _port(6, admin_up=True, speed="Auto", flow=True)})
    des = _cfg(ports={6: _port(6, speed="1000M/Full")})
    plan = build_device_plan(cur, des)
    assert len(plan.changes) == 1
    assert "speed_duplex" in plan.changes[0].details


# ---------------------------------------------------------------------------
# Change ordering
# ---------------------------------------------------------------------------


def test_change_ordering() -> None:
    """Creates → updates → port_updates → deletes."""
    cur = _cfg(
        vlans={
            1: _vlan(1),
            10: _vlan(10, "old"),
            50: _vlan(50),
        },
        ports={2: _port(2, admin_up=True, speed="Auto", flow=True)},
    )
    des = _cfg(
        vlans={
            10: _vlan(10, "new"),          # update
            50: _vlan(50, state="absent"),  # delete
            99: _vlan(99, "fresh"),         # create
        },
        ports={2: _port(2, admin_up=False)},  # port update
    )
    plan = build_device_plan(cur, des)
    kinds = [c.kind for c in plan.changes]
    # expected order: create(99), update(10), port_update(2), delete(50)
    assert kinds.index("vlan_create") < kinds.index("vlan_update")
    assert kinds.index("vlan_update") < kinds.index("port_update")
    assert kinds.index("port_update") < kinds.index("vlan_delete")


# ---------------------------------------------------------------------------
# Summary counts
# ---------------------------------------------------------------------------


def test_summary_counts() -> None:
    cur = _cfg(
        vlans={10: _vlan(10), 20: _vlan(20)},
        ports={1: _port(1, admin_up=True, speed="Auto", flow=True)},
    )
    des = _cfg(
        vlans={
            10: _vlan(10, state="absent"),  # delete 10
            20: _vlan(20, state="absent"),  # delete 20
            30: _vlan(30),                  # create 30
        },
        ports={1: _port(1, admin_up=False)},
    )
    plan = build_device_plan(cur, des)
    assert plan.summary["vlan_create"] == 1
    assert plan.summary["vlan_update"] == 0
    assert plan.summary["port_update"] == 1
    assert plan.summary["vlan_delete"] == 2
