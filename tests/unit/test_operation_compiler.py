"""Tests for pure apply operation compilation."""

from __future__ import annotations

import pytest

from cgiswitch.client.vlan_ops import (
    build_vlan_create_payload,
    build_vlan_delete_payload,
    build_vlan_port_payload,
    vlan_create,
    vlan_delete,
    vlan_set_port,
)
from cgiswitch.model.config import DeviceConfig
from cgiswitch.model.port import PortConfig, PortSettings
from cgiswitch.model.vlan import VlanConfig
from cgiswitch.utils.device_diff import Change, DevicePlan
from cgiswitch.utils.operations import compile_apply_operations
from cgiswitch.utils.vlan_membership import (
    VlanMembershipPlan,
    make_port_state,
)


def _membership(*ports: int) -> VlanMembershipPlan:
    current = {port: make_port_state() for port in ports}
    desired = {port: make_port_state() for port in ports}
    return VlanMembershipPlan(current, desired, [], [], [], [])


def _port_settings(*ports: int) -> list[PortSettings]:
    return [PortSettings(port, f"Port {port}", True, "Auto", False) for port in ports]


def test_compile_operations_has_deterministic_dependency_order() -> None:
    desired = DeviceConfig(
        vlans={
            30: VlanConfig(30, "thirty"),
            10: VlanConfig(10, "ten"),
            20: VlanConfig(20, "twenty"),
        },
        ports={2: PortConfig(2, admin_up=False), 1: PortConfig(1, flow_control=True)},
    )
    plan = DevicePlan([
        Change("vlan_delete", "vlan:40", {"vlan_id": 40}),
        Change("port_update", "port:2", {"port_id": 2}),
        Change("vlan_update", "vlan:30", {"vlan_id": 30, "name": {"to": "thirty"}}),
        Change("vlan_create", "vlan:20", {"vlan_id": 20}),
        Change("vlan_create", "vlan:10", {"vlan_id": 10}),
        Change("vlan_delete", "vlan:50", {"vlan_id": 50}),
        Change("port_update", "port:1", {"port_id": 1}),
    ])
    membership = VlanMembershipPlan(
        {1: make_port_state(), 2: make_port_state()},
        {2: make_port_state(untagged_vlan=20), 1: make_port_state(untagged_vlan=10)},
        [2, 1], [10, 20], [], [],
    )

    operations = compile_apply_operations(plan, desired, _port_settings(1, 2), membership)

    assert [operation.key for operation in operations] == [
        "vlan:10", "vlan:20", "vlan:30", "vlan_membership:port:1",
        "vlan_membership:port:2", "port:1", "port:2", "vlan:50", "vlan:40",
    ]
    assert [operation.kind for operation in operations] == [
        "vlan_create", "vlan_create", "vlan_rename", "vlan_membership",
        "vlan_membership", "port_update", "port_update", "vlan_delete", "vlan_delete",
    ]


def test_compile_operations_fails_before_transport_for_uncompileable_membership() -> None:
    plan = DevicePlan([])
    membership = VlanMembershipPlan(
        {1: make_port_state()},
        {1: {"untagged_vlan": None, "tagged_vlans": {20}}},
        [1], [20], [], [],
    )

    with pytest.raises(ValueError, match="Port 1 canonical state"):
        compile_apply_operations(plan, DeviceConfig(), _port_settings(1), membership)


def test_payload_builders_match_low_level_transport_helpers() -> None:
    class Session:
        def __init__(self) -> None:
            self.posts: list[tuple[str, object]] = []

        def post(self, endpoint: str, *, data: object) -> None:
            self.posts.append((endpoint, data))

    session = Session()
    vlan_create(session, 20, "users")
    vlan_delete(session, [30, 20])
    vlan_set_port(session, [2], "trunk", None, 10, [10, 20])
    assert session.posts == [
        ("/staticvlan.cgi", build_vlan_create_payload(20, "users")),
        ("/staticvlan.cgi", build_vlan_delete_payload([30, 20])),
        ("/vlanport.cgi", build_vlan_port_payload([2], "trunk", None, 10, [10, 20])),
    ]
