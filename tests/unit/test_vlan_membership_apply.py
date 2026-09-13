"""Unit tests for the pure VLAN membership apply engine."""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
from unittest.mock import MagicMock

import pytest

from cgiswitch.client.errors import JTComVerificationError
from cgiswitch.model.config import DeviceConfig
from cgiswitch.model.options import ApplyPolicy, JTComConnectionOptions
from cgiswitch.model.port import PortSettings
from cgiswitch.model.vlan import VlanConfig, VlanEntry, VlanPortConfig
from cgiswitch.switch import JTComSwitch
from cgiswitch.utils.vlan_membership import (
    PortMembershipMap,
    VlanMembershipPlan,
    build_current_per_port_from_jtcom_readback,
    build_current_per_port_from_vlans,
    canonical_to_jtcom_port_vlan_state,
    make_port_state,
    plan_vlan_membership_changes,
    port_name_to_id,
)


def assert_common_warning_fields(
    warning: dict[str, object],
    *,
    type_: str,
    entity: str,
) -> None:
    assert warning["type"] == type_
    assert warning["entity"] == entity
    assert isinstance(warning["message"], str)
    assert warning["message"]
    assert "hint" in warning


def test_port_name_to_id_parses_canonical_1_based_ids() -> None:
    assert port_name_to_id("Port 1") == 1
    assert port_name_to_id("Port 5") == 5


def test_port_name_to_id_rejects_malformed_input() -> None:
    with pytest.raises(ValueError, match="Invalid JTCom port name"):
        port_name_to_id("Gi1/0/1")


def test_tagged_add_merges() -> None:
    current = {5: make_port_state(tagged_vlans={10, 30})}
    plan = plan_vlan_membership_changes(current, [VlanConfig(vlan_id=20, tagged_add=[5])])
    assert plan.desired_per_port[5]["tagged_vlans"] == {10, 20, 30}


def test_tagged_remove_subtracts() -> None:
    current = {5: make_port_state(tagged_vlans={10, 20, 30})}
    plan = plan_vlan_membership_changes(current, [VlanConfig(vlan_id=20, tagged_remove=[5])])
    assert plan.desired_per_port[5]["tagged_vlans"] == {10, 30}


def test_tagged_set_replaces_vlan_dimension_only() -> None:
    current = {
        5: make_port_state(tagged_vlans={10, 20, 30}),
        6: make_port_state(tagged_vlans={40}),
    }
    plan = plan_vlan_membership_changes(
        current,
        [VlanConfig(vlan_id=40, tagged_set=[5])],
    )
    assert plan.desired_per_port[5]["tagged_vlans"] == {10, 20, 30, 40}
    assert plan.desired_per_port[6]["tagged_vlans"] == set()


def test_untagged_add_assigns_native_vlan() -> None:
    current = {3: make_port_state(untagged_vlan=10)}
    plan = plan_vlan_membership_changes(
        current,
        [VlanConfig(vlan_id=20, untagged_add=[3])],
        allow_untagged_move=True,
    )
    assert plan.desired_per_port[3]["untagged_vlan"] == 20


def test_untagged_remove_clears_native_if_matching() -> None:
    current = {3: make_port_state(untagged_vlan=20)}
    plan = plan_vlan_membership_changes(
        current,
        [VlanConfig(vlan_id=20, untagged_remove=[3])],
    )
    assert_common_warning_fields(plan.warnings[0], type_="mode_none_mapped_to_vlan1", entity="port")
    assert plan.desired_per_port[3]["untagged_vlan"] == 1
    assert plan.warnings[0]["type"] == "mode_none_mapped_to_vlan1"


def test_tagged_untagged_same_vlan_is_auto_normalized() -> None:
    current = {3: make_port_state(tagged_vlans={20})}
    plan = plan_vlan_membership_changes(
        current,
        [VlanConfig(vlan_id=20, untagged_add=[3])],
        allow_port_mode_change=True,
    )
    assert plan.desired_per_port[3]["untagged_vlan"] == 20
    assert plan.desired_per_port[3]["tagged_vlans"] == set()


def test_tagged_only_changed_state_is_an_unsupported_violation() -> None:
    current = {3: make_port_state()}
    plan = plan_vlan_membership_changes(
        current,
        [VlanConfig(vlan_id=30, tagged_add=[3])],
        allow_port_mode_change=True,
    )
    assert plan.changed_ports == [3]
    assert [violation["type"] for violation in plan.violations] == [
        "unsupported_vlan_port_mode",
    ]
    assert plan.violations[0]["desired_mode"] == "trunk"


def test_access_to_trunk_is_a_violation_by_default() -> None:
    current = {3: make_port_state(untagged_vlan=20)}
    plan = plan_vlan_membership_changes(current, [VlanConfig(vlan_id=30, tagged_add=[3])])
    assert_common_warning_fields(
        plan.violations[0],
        type_="port_mode_change",
        entity="port",
    )
    assert plan.violations[0]["port_id"] == 3
    assert plan.violations[0]["vlan_id"] is None
    assert plan.violations[0]["current_mode"] == "access"
    assert plan.violations[0]["desired_mode"] == "trunk"
    assert "allow_port_mode_change=true" in plan.violations[0]["hint"]


def test_trunk_to_access_is_a_violation_by_default() -> None:
    current = {5: make_port_state(untagged_vlan=10, tagged_vlans={20, 30})}
    desired = [
        VlanConfig(vlan_id=20, tagged_remove=[5]),
        VlanConfig(vlan_id=30, tagged_remove=[5]),
    ]
    plan = plan_vlan_membership_changes(current, desired)
    assert plan.violations[0]["port_id"] == 5
    assert plan.violations[0]["current_mode"] == "trunk"
    assert plan.violations[0]["desired_mode"] == "access"


def test_access_to_trunk_allowed_with_flag() -> None:
    current = {3: make_port_state(untagged_vlan=20)}
    plan = plan_vlan_membership_changes(
        current,
        [VlanConfig(vlan_id=30, tagged_add=[3])],
        allow_port_mode_change=True,
    )
    assert plan.desired_per_port[3]["untagged_vlan"] == 20
    assert plan.desired_per_port[3]["tagged_vlans"] == {30}
    assert plan.warnings[0]["desired_mode"] == "trunk"


def test_mode_change_is_a_violation_without_override() -> None:
    current = {3: make_port_state(untagged_vlan=20)}
    plan = plan_vlan_membership_changes(
        current,
        [VlanConfig(vlan_id=30, tagged_add=[3])],
    )
    assert_common_warning_fields(plan.violations[0], type_="port_mode_change", entity="port")
    assert plan.violations[0]["port_id"] == 3
    assert "allow_port_mode_change=true" in plan.violations[0]["hint"]


def test_policy_violations_are_aggregated_and_overrides_are_independent() -> None:
    current = {3: make_port_state(untagged_vlan=20)}
    configs = [
        VlanConfig(vlan_id=30, untagged_add=[3]),
        VlanConfig(vlan_id=40, tagged_add=[3]),
    ]

    plan = plan_vlan_membership_changes(current, configs)
    assert [item["type"] for item in plan.violations] == [
        "untagged_move",
        "port_mode_change",
    ]

    mode_allowed = plan_vlan_membership_changes(
        current,
        configs,
        allow_port_mode_change=True,
    )
    assert [item["type"] for item in mode_allowed.violations] == ["untagged_move"]
    assert [item["type"] for item in mode_allowed.warnings] == ["port_mode_change"]

    move_allowed = plan_vlan_membership_changes(
        current,
        configs,
        allow_untagged_move=True,
    )
    assert [item["type"] for item in move_allowed.violations] == ["port_mode_change"]
    assert [item["type"] for item in move_allowed.warnings] == ["untagged_move"]


def test_omitted_legacy_fields_are_noop_not_empty_replacement() -> None:
    current = {5: make_port_state(untagged_vlan=10, tagged_vlans={20, 30})}
    plan = plan_vlan_membership_changes(current, [VlanConfig(vlan_id=20)])
    assert plan.changed_ports == []
    assert plan.desired_per_port[5]["untagged_vlan"] == 10
    assert plan.desired_per_port[5]["tagged_vlans"] == {20, 30}


def test_canonical_compilation_produces_full_final_permit_list_not_delta() -> None:
    backend = canonical_to_jtcom_port_vlan_state(
        make_port_state(untagged_vlan=10, tagged_vlans={20, 30})
    )
    assert backend["mode"] == "trunk"
    assert backend["native_vlan"] == 10
    assert backend["permit_vlans"] == [10, 20, 30]


def test_driver_apply_compiles_canonical_state_at_final_boundary() -> None:
    switch = JTComSwitch("192.0.2.1", "admin", "admin")
    session = MagicMock()
    plan = VlanMembershipPlan(
        current_per_port={4: make_port_state(), 5: make_port_state(tagged_vlans={20})},
        desired_per_port={
            4: make_port_state(),
            5: make_port_state(untagged_vlan=10, tagged_vlans={20, 30}),
        },
        changed_ports=[5],
        changed_vlans=[10, 30],
        warnings=[],
    )

    switch._apply_vlan_membership_plan(session, plan)

    session.post.assert_called_once()
    endpoint = session.post.call_args.args[0]
    payload = session.post.call_args.kwargs["data"]
    assert endpoint == "/vlanport.cgi"
    assert payload["PortId"] == "4"
    assert payload["VlanType"] == "1"
    assert payload["NativeVlan"] == "10"
    assert payload["PermitVlan"] == "10_20_30"


def test_driver_apply_uses_shared_canonical_to_jtcom_compiler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    switch = JTComSwitch("192.0.2.1", "admin", "admin")
    session = MagicMock()
    seen: list[dict[str, object]] = []

    def fake_compile(state: dict[str, object]) -> dict[str, object]:
        seen.append(state)
        return {
            "mode": "trunk",
            "access_vlan": None,
            "native_vlan": 1,
            "permit_vlans": [1, 61],
        }

    monkeypatch.setattr(
        "cgiswitch.utils.operations.canonical_to_jtcom_port_vlan_state", fake_compile,
    )
    plan = VlanMembershipPlan(
        current_per_port={1: make_port_state(untagged_vlan=1)},
        desired_per_port={1: make_port_state(untagged_vlan=1, tagged_vlans={61})},
        changed_ports=[1],
        changed_vlans=[61],
        warnings=[],
    )

    switch._apply_vlan_membership_plan(session, plan)

    assert seen == [make_port_state(untagged_vlan=1, tagged_vlans={61})]
    payload = session.post.call_args.kwargs["data"]
    assert payload["NativeVlan"] == "1"
    assert payload["PermitVlan"] == "1_61"


def test_apply_boundary_rejects_tagged_only_canonical_state_clearly() -> None:
    switch = JTComSwitch("192.0.2.1", "admin", "admin")

    with pytest.raises(
        ValueError,
        match="Port 5 canonical state cannot be compiled to JTCom backend",
    ):
        switch._apply_vlan_membership_plan(
            MagicMock(),
            VlanMembershipPlan(
                current_per_port={5: make_port_state()},
                desired_per_port={5: make_port_state(tagged_vlans={61})},
                changed_ports=[5],
                changed_vlans=[61],
                warnings=[],
            ),
        )


def test_apply_boundary_rejects_empty_canonical_state_clearly() -> None:
    switch = JTComSwitch("192.0.2.1", "admin", "admin")

    with pytest.raises(
        ValueError,
        match="Port 5 canonical state cannot be compiled to JTCom backend",
    ):
        switch._apply_vlan_membership_plan(
            MagicMock(),
            VlanMembershipPlan(
                current_per_port={5: make_port_state(untagged_vlan=10)},
                desired_per_port={5: make_port_state()},
                changed_ports=[5],
                changed_vlans=[10],
                warnings=[],
            ),
        )


def test_apply_boundary_does_not_mutate_canonical_plan_state() -> None:
    switch = JTComSwitch("192.0.2.1", "admin", "admin")
    session = MagicMock()
    desired_state = make_port_state(untagged_vlan=1, tagged_vlans={61})
    plan = VlanMembershipPlan(
        current_per_port={1: make_port_state(untagged_vlan=1)},
        desired_per_port={1: desired_state},
        changed_ports=[1],
        changed_vlans=[61],
        warnings=[],
    )
    before = make_port_state(untagged_vlan=1, tagged_vlans={61})

    switch._apply_vlan_membership_plan(session, plan)

    assert plan.desired_per_port[1] == before
    assert desired_state == before


def test_real_world_trunk_playbook_scenario_stays_canonical_until_apply() -> None:
    current = {
        port_id: make_port_state(untagged_vlan=1)
        for port_id in [1, 2, 3, 4, 5]
    }
    plan = plan_vlan_membership_changes(
        current,
        [VlanConfig(vlan_id=61, tagged_add=[1, 2, 3, 4, 5])],
        allow_port_mode_change=True,
    )

    for port_id in [1, 2, 3, 4, 5]:
        assert plan.desired_per_port[port_id] == make_port_state(
            untagged_vlan=1,
            tagged_vlans={61},
        )
        assert canonical_to_jtcom_port_vlan_state(plan.desired_per_port[port_id]) == {
            "mode": "trunk",
            "access_vlan": None,
            "native_vlan": 1,
            "permit_vlans": [1, 61],
        }


def test_fetch_vlan_state_materializes_canonical_membership_from_jtcom_readback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    switch = JTComSwitch("192.0.2.1", "admin", "admin")
    session = MagicMock()

    monkeypatch.setattr(
        "cgiswitch.switch.parse_static_vlans",
        lambda _html: [
            VlanEntry(vlan_id=1, name="default"),
            VlanEntry(vlan_id=61, name="admin"),
        ],
    )
    monkeypatch.setattr(
        "cgiswitch.switch.parse_port_vlan_settings",
        lambda _html: [
            VlanPortConfig(
                port_name="Port 1",
                vlan_type="Trunk",
                native_vlan=1,
                permit_vlans=[1, 61],
            )
        ],
    )
    session.get.side_effect = ["static_html", "port_html"]

    vlan_map = switch._fetch_vlan_state(session)

    assert vlan_map[1].untagged_ports == ["Port 1"]
    assert vlan_map[1].tagged_ports == []
    assert vlan_map[61].untagged_ports == []
    assert vlan_map[61].tagged_ports == ["Port 1"]


def test_build_current_rejects_port_untagged_in_multiple_vlans() -> None:
    current_vlans = {
        10: VlanEntry(vlan_id=10, name="v10", untagged_ports=["Port 1"]),
        20: VlanEntry(vlan_id=20, name="v20", untagged_ports=["Port 1"]),
    }
    with pytest.raises(ValueError, match="Impossible VLAN state"):
        build_current_per_port_from_vlans(current_vlans, known_ports=[1])


def test_build_current_from_jtcom_readback_normalizes_native_out_of_tagged_set() -> None:
    current = build_current_per_port_from_jtcom_readback(
        [
            VlanPortConfig(
                port_name="Port 1",
                vlan_type="Trunk",
                native_vlan=1,
                permit_vlans=[1, 61],
            )
        ],
        known_ports=[1],
    )
    assert current[1] == make_port_state(untagged_vlan=1, tagged_vlans={61})


def test_check_mode_warns_instead_of_failing_on_desired_mode_none() -> None:
    current = {3: make_port_state(untagged_vlan=20)}
    plan = plan_vlan_membership_changes(
        current,
        [VlanConfig(vlan_id=20, untagged_remove=[3])],
    )
    assert_common_warning_fields(plan.warnings[0], type_="mode_none_mapped_to_vlan1", entity="port")
    assert plan.desired_per_port[3] == make_port_state(untagged_vlan=1)
    assert plan.desired_per_port[3]["untagged_vlan"] == 1
    assert plan.warnings[0]["type"] == "mode_none_mapped_to_vlan1"
    assert plan.warnings[0]["port_id"] == 3
    assert plan.warnings[0]["vlan_id"] == 1
    assert plan.warnings[0]["mapped_vlan"] == 1


def test_apply_mode_maps_desired_mode_none_to_vlan1() -> None:
    current = {3: make_port_state(untagged_vlan=20)}
    plan = plan_vlan_membership_changes(
        current,
        [VlanConfig(vlan_id=20, untagged_remove=[3])],
    )
    assert plan.desired_per_port[3] == make_port_state(untagged_vlan=1)
    assert canonical_to_jtcom_port_vlan_state(plan.desired_per_port[3]) == {
        "mode": "access",
        "access_vlan": 1,
        "native_vlan": None,
        "permit_vlans": [],
    }
    assert plan.warnings[0]["type"] == "mode_none_mapped_to_vlan1"


def test_apply_mode_none_maps_to_vlan1_before_apply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    switch = JTComSwitch("192.0.2.1", "admin", "admin")
    session = MagicMock()
    switch._session = session
    current_vlans = {
        20: VlanEntry(vlan_id=20, name="v20", untagged_ports=["Port 4"]),
    }
    current_ports = [
        PortSettings(port_id=4, name="Port 4", admin_up=True),
    ]
    monkeypatch.setattr(
        switch,
        "_read_current_state",
        lambda _session: (current_vlans, current_ports),
    )

    result = switch.apply(
        DeviceConfig(vlans={20: VlanConfig(vlan_id=20, untagged_remove=[4])}),
        check_mode=True,
    )

    assert result["diff"]["vlan_membership"]["after"][4] == {
        "untagged_vlan": 1,
        "tagged_vlans": [],
    }
    assert result["warnings"][0]["type"] == "mode_none_mapped_to_vlan1"
    session.download_config_backup.assert_not_called()


def test_untagged_move_is_a_violation_by_default() -> None:
    current = {3: make_port_state(untagged_vlan=20)}
    plan = plan_vlan_membership_changes(current, [VlanConfig(vlan_id=30, untagged_add=[3])])
    assert_common_warning_fields(
        plan.violations[0],
        type_="untagged_move",
        entity="port",
    )
    assert plan.violations[0]["type"] == "untagged_move"
    assert plan.violations[0]["vlan_id"] is None
    assert plan.violations[0]["current_untagged_vlan"] == 20
    assert plan.violations[0]["desired_untagged_vlan"] == 30


def test_untagged_move_is_a_violation_without_override() -> None:
    current = {3: make_port_state(untagged_vlan=20)}
    plan = plan_vlan_membership_changes(
        current,
        [VlanConfig(vlan_id=30, untagged_add=[3])],
    )
    assert_common_warning_fields(plan.violations[0], type_="untagged_move", entity="port")
    assert plan.violations[0]["type"] == "untagged_move"
    assert plan.desired_per_port[3]["untagged_vlan"] == 30


def test_untagged_move_allowed_with_flag() -> None:
    current = {3: make_port_state(untagged_vlan=20)}
    plan = plan_vlan_membership_changes(
        current,
        [VlanConfig(vlan_id=30, untagged_add=[3])],
        allow_untagged_move=True,
    )
    assert plan.desired_per_port[3]["untagged_vlan"] == 30
    assert plan.warnings[0]["type"] == "untagged_move"


def test_native_vlan_move_on_trunk_fails_by_default() -> None:
    current = {5: make_port_state(untagged_vlan=10, tagged_vlans={20})}
    plan = plan_vlan_membership_changes(current, [VlanConfig(vlan_id=30, untagged_add=[5])])
    assert plan.violations[0]["type"] == "untagged_move"


def test_delete_vlan_in_use_is_a_violation_by_default() -> None:
    current = {3: make_port_state(untagged_vlan=20)}
    plan = plan_vlan_membership_changes(current, [VlanConfig(vlan_id=20, state="absent")])
    assert_common_warning_fields(
        plan.violations[0],
        type_="vlan_delete_in_use",
        entity="vlan",
    )
    assert plan.violations[0]["type"] == "vlan_delete_in_use"
    assert plan.violations[0]["port_id"] is None
    assert plan.violations[0]["vlan_id"] == 20
    assert plan.violations[0]["affected_ports_untagged"] == [3]


def test_delete_vlan_in_use_is_a_violation_without_override() -> None:
    current = {3: make_port_state(untagged_vlan=20)}
    plan = plan_vlan_membership_changes(
        current,
        [VlanConfig(vlan_id=20, state="absent")],
    )
    assert_common_warning_fields(plan.violations[0], type_="vlan_delete_in_use", entity="vlan")
    assert plan.violations[0]["type"] == "vlan_delete_in_use"
    assert plan.changed_ports == []


def test_allow_vlan_delete_in_use_detaches_and_falls_back_to_vlan1() -> None:
    current = {
        3: make_port_state(untagged_vlan=20),
        5: make_port_state(untagged_vlan=10, tagged_vlans={20, 30}),
    }
    plan = plan_vlan_membership_changes(
        current,
        [VlanConfig(vlan_id=20, state="absent")],
        allow_vlan_delete_in_use=True,
    )
    assert_common_warning_fields(plan.warnings[0], type_="vlan_delete_in_use", entity="vlan")
    assert_common_warning_fields(plan.warnings[1], type_="mode_none_mapped_to_vlan1", entity="port")
    assert plan.desired_per_port[3]["untagged_vlan"] == 1
    assert plan.desired_per_port[5]["untagged_vlan"] == 10
    assert plan.desired_per_port[5]["tagged_vlans"] == {30}
    assert [warning["type"] for warning in plan.warnings][:2] == [
        "vlan_delete_in_use",
        "mode_none_mapped_to_vlan1",
    ]


def test_delete_unused_vlan_is_allowed_without_warning() -> None:
    current = {3: make_port_state(untagged_vlan=10)}
    plan = plan_vlan_membership_changes(current, [VlanConfig(vlan_id=20, state="absent")])
    assert plan.warnings == []
    assert plan.changed_ports == []


def test_allow_vlan_delete_in_use_preserves_tagged_set_style_result() -> None:
    current = {
        5: make_port_state(untagged_vlan=10, tagged_vlans={20, 30}),
        6: make_port_state(untagged_vlan=10, tagged_vlans={20}),
    }
    plan = plan_vlan_membership_changes(
        current,
        [
            VlanConfig(vlan_id=20, state="absent"),
            VlanConfig(vlan_id=30, tagged_set=[5]),
        ],
        allow_vlan_delete_in_use=True,
    )
    assert plan.desired_per_port[5]["untagged_vlan"] == 10
    assert plan.desired_per_port[5]["tagged_vlans"] == {30}
    assert plan.desired_per_port[6]["untagged_vlan"] == 10
    assert plan.desired_per_port[6]["tagged_vlans"] == set()
    assert plan.changed_ports == [5, 6]
    assert [warning["type"] for warning in plan.warnings] == [
        "vlan_delete_in_use",
    ]
    assert [violation["type"] for violation in plan.violations] == ["port_mode_change"]


def test_allow_vlan_delete_in_use_preserves_untagged_set_style_result() -> None:
    current = {5: make_port_state(untagged_vlan=20)}
    plan = plan_vlan_membership_changes(
        current,
        [
            VlanConfig(vlan_id=20, state="absent"),
            VlanConfig(vlan_id=30, untagged_set=[5]),
        ],
        allow_vlan_delete_in_use=True,
        allow_untagged_move=True,
    )
    assert plan.desired_per_port[5]["untagged_vlan"] == 30
    assert plan.desired_per_port[5]["tagged_vlans"] == set()
    assert plan.changed_ports == [5]
    assert [warning["type"] for warning in plan.warnings] == ["untagged_move"]


def test_mode_none_fallback_still_respects_trunk_to_access_protection() -> None:
    current = {5: make_port_state(tagged_vlans={20})}
    plan = plan_vlan_membership_changes(current, [VlanConfig(vlan_id=20, tagged_remove=[5])])
    assert plan.violations[0]["current_mode"] == "trunk"
    assert plan.violations[0]["desired_mode"] == "access"


def test_mode_none_fallback_check_mode_warns_on_trunk_to_access_transition() -> None:
    current = {5: make_port_state(tagged_vlans={20})}
    plan = plan_vlan_membership_changes(
        current,
        [VlanConfig(vlan_id=20, tagged_remove=[5])],
    )
    assert [warning["type"] for warning in plan.warnings] == ["mode_none_mapped_to_vlan1"]
    assert [violation["type"] for violation in plan.violations] == ["port_mode_change"]
    assert plan.desired_per_port[5]["untagged_vlan"] == 1
    assert canonical_to_jtcom_port_vlan_state(plan.desired_per_port[5])["mode"] == "access"


def test_mode_none_fallback_allows_trunk_to_access_transition_with_override() -> None:
    current = {5: make_port_state(tagged_vlans={20})}
    plan = plan_vlan_membership_changes(
        current,
        [VlanConfig(vlan_id=20, tagged_remove=[5])],
        allow_port_mode_change=True,
    )
    assert [warning["type"] for warning in plan.warnings] == [
        "mode_none_mapped_to_vlan1",
        "port_mode_change",
    ]
    assert plan.desired_per_port[5]["untagged_vlan"] == 1
    assert canonical_to_jtcom_port_vlan_state(plan.desired_per_port[5])["mode"] == "access"


def test_verify_vlan_membership_accepts_canonicalized_jtcom_trunk_readback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    switch = JTComSwitch("192.0.2.1", "admin", "admin")
    session = MagicMock()
    membership_plan = VlanMembershipPlan(
        current_per_port={1: make_port_state(untagged_vlan=1)},
        desired_per_port={1: make_port_state(untagged_vlan=1, tagged_vlans={61})},
        changed_ports=[1],
        changed_vlans=[61],
        warnings=[],
    )

    monkeypatch.setattr(
        switch,
        "_read_current_state",
        lambda _session: (
            {
                1: VlanEntry(vlan_id=1, name="default", untagged_ports=["Port 1"]),
                61: VlanEntry(vlan_id=61, name="admin", tagged_ports=["Port 1"]),
            },
            [PortSettings(port_id=1, name="Port 1", admin_up=True)],
        ),
    )

    switch._verify_vlan_membership(session, membership_plan)


def test_verify_expected_state_remains_canonical_not_backend_shaped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    switch = JTComSwitch("192.0.2.1", "admin", "admin")
    session = MagicMock()
    membership_plan = VlanMembershipPlan(
        current_per_port={1: make_port_state(untagged_vlan=1)},
        desired_per_port={1: make_port_state(untagged_vlan=1, tagged_vlans={61})},
        changed_ports=[1],
        changed_vlans=[61],
        warnings=[],
    )

    monkeypatch.setattr(
        switch,
        "_read_current_state",
        lambda _session: (
            {
                1: VlanEntry(vlan_id=1, name="default", untagged_ports=["Port 1"]),
                61: VlanEntry(vlan_id=61, name="admin", tagged_ports=["Port 1"]),
            },
            [PortSettings(port_id=1, name="Port 1", admin_up=True)],
        ),
    )

    captured: dict[str, PortMembershipMap] = {}
    driver_module = __import__("cgiswitch.switch", fromlist=["diff_membership_maps"])
    original_diff = driver_module.diff_membership_maps

    def capture_diff(current: PortMembershipMap, desired: PortMembershipMap) -> dict[str, object]:
        captured["current"] = current
        captured["desired"] = desired
        return original_diff(current, desired)

    monkeypatch.setattr("cgiswitch.switch.diff_membership_maps", capture_diff)

    switch._verify_vlan_membership(session, membership_plan)

    assert captured["desired"][1] == make_port_state(untagged_vlan=1, tagged_vlans={61})
    assert captured["desired"][1]["tagged_vlans"] == {61}


def test_verify_vlan_membership_still_fails_on_real_canonical_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    switch = JTComSwitch("192.0.2.1", "admin", "admin")
    session = MagicMock()
    membership_plan = VlanMembershipPlan(
        current_per_port={1: make_port_state(untagged_vlan=1)},
        desired_per_port={1: make_port_state(untagged_vlan=1, tagged_vlans={61})},
        changed_ports=[1],
        changed_vlans=[61],
        warnings=[],
    )

    monkeypatch.setattr(
        switch,
        "_read_current_state",
        lambda _session: (
            {
                1: VlanEntry(vlan_id=1, name="default", untagged_ports=["Port 1"]),
                61: VlanEntry(vlan_id=61, name="admin"),
            },
            [PortSettings(port_id=1, name="Port 1", admin_up=True)],
        ),
    )

    with pytest.raises(JTComVerificationError) as exc_info:
        switch._verify_vlan_membership(session, membership_plan)

    assert exc_info.value.remaining_diff == {
        "total_changes": 1,
        "changes": {
            "1": {
                "from": {"untagged_vlan": 1, "tagged_vlans": []},
                "to": {"untagged_vlan": 1, "tagged_vlans": [61]},
            }
        },
    }


@pytest.mark.parametrize(
    "path",
    [
        pathlib.Path("galaxy/bronweg/cgiswitch/plugins/action/jtcom_config.py"),
    ],
)
def test_action_plugin_int_list_helper_preserves_missing_none_and_empty_list(
    path: pathlib.Path,
) -> None:
    module = _load_action_plugin_module(path)

    assert module._int_list_or_none({}, "tagged_ports") is None
    assert module._int_list_or_none({"tagged_ports": None}, "tagged_ports") is None
    assert module._int_list_or_none({"tagged_ports": []}, "tagged_ports") == []
    assert module._int_list_or_none({"tagged_ports": ["1"]}, "tagged_ports") == [1]
    assert module._int_or_none({}, "access_vlan") is None
    assert module._int_or_none({"access_vlan": None}, "access_vlan") is None
    assert module._int_or_none({"access_vlan": "10"}, "access_vlan") == 10


@pytest.mark.parametrize(
    ("path", "verify_tls_default", "check_mode"),
    [
        (pathlib.Path("galaxy/bronweg/cgiswitch/plugins/action/jtcom_config.py"), True, False),
        (pathlib.Path("galaxy/bronweg/cgiswitch/plugins/action/jtcom_config.py"), True, True),
    ],
)
def test_action_plugin_passes_typed_options_and_policy(
    monkeypatch: pytest.MonkeyPatch,
    path: pathlib.Path,
    verify_tls_default: bool,
    check_mode: bool,
) -> None:
    module = _load_action_plugin_module(path)
    captured: dict[str, object] = {}

    class FakeSwitch:
        def __init__(
            self,
            hostname: str,
            username: str,
            password: str,
            connection: JTComConnectionOptions,
            policy: ApplyPolicy,
        ) -> None:
            captured["hostname"] = hostname
            captured["username"] = username
            captured["password"] = password
            captured["connection"] = connection
            captured["policy"] = policy

        def open(self) -> None:
            pass

        def close(self) -> None:
            pass

        def apply(
            self,
            desired: object,
            *,
            check_mode: bool,
        ) -> dict[str, object]:
            captured["desired"] = desired
            captured["check_mode"] = check_mode
            return {
                "changed": False,
                "diff": {},
                "backup_file": "",
                "applied": [],
                "warnings": [],
                "changed_ports": [],
                "changed_vlans": [],
            }

    monkeypatch.setattr("cgiswitch.switch.JTComSwitch", FakeSwitch)

    action = module.ActionModule()
    action._task = types.SimpleNamespace(
        args={
            "host": "192.0.2.1",
            "username": "admin",
            "password": "admin",
            "allow_vlan_delete_in_use": True,
        }
    )
    action._play_context = types.SimpleNamespace(check_mode=check_mode)

    result = action.run()

    assert result["changed"] is False
    assert captured["desired"] == DeviceConfig(vlans={}, ports={})
    assert captured["check_mode"] is check_mode
    assert captured["connection"] == JTComConnectionOptions(verify_tls=verify_tls_default)
    assert captured["policy"] == ApplyPolicy(allow_vlan_delete_in_use=True)


@pytest.mark.parametrize(
    ("path", "verify_tls_default"),
    [
        (pathlib.Path("galaxy/bronweg/cgiswitch/plugins/action/jtcom_config.py"), True),
    ],
)
def test_action_plugin_defaults_to_blocking_vlan_delete_in_use(
    monkeypatch: pytest.MonkeyPatch,
    path: pathlib.Path,
    verify_tls_default: bool,
) -> None:
    module = _load_action_plugin_module(path)
    captured: dict[str, object] = {}

    class FakeSwitch:
        def __init__(
            self,
            hostname: str,
            username: str,
            password: str,
            connection: JTComConnectionOptions,
            policy: ApplyPolicy,
        ) -> None:
            captured["hostname"] = hostname
            captured["username"] = username
            captured["password"] = password
            captured["connection"] = connection
            captured["policy"] = policy

        def open(self) -> None:
            pass

        def close(self) -> None:
            pass

        def apply(
            self,
            desired: object,
            *,
            check_mode: bool,
        ) -> dict[str, object]:
            captured["desired"] = desired
            captured["check_mode"] = check_mode
            return {
                "changed": False,
                "diff": {},
                "backup_file": "",
                "applied": [],
                "warnings": [],
                "changed_ports": [],
                "changed_vlans": [],
            }

    monkeypatch.setattr("cgiswitch.switch.JTComSwitch", FakeSwitch)

    action = module.ActionModule()
    action._task = types.SimpleNamespace(
        args={
            "host": "192.0.2.1",
            "username": "admin",
            "password": "admin",
        }
    )
    action._play_context = types.SimpleNamespace(check_mode=False)

    action.run()

    assert captured["connection"] == JTComConnectionOptions(verify_tls=verify_tls_default)
    assert captured["policy"] == ApplyPolicy()
    assert captured["desired"] == DeviceConfig(vlans={}, ports={})
    assert captured["check_mode"] is False


def _load_action_plugin_module(path: pathlib.Path) -> types.ModuleType:
    class ActionBase:
        def run(
            self,
            tmp: str | None = None,
            task_vars: dict[str, object] | None = None,
        ) -> dict[str, object]:
            return {}

    class Display:
        def display(self, _data: str) -> None:
            pass

    ansible_mod = types.ModuleType("ansible")
    plugins_mod = types.ModuleType("ansible.plugins")
    action_mod = types.ModuleType("ansible.plugins.action")
    action_mod.ActionBase = ActionBase
    utils_mod = types.ModuleType("ansible.utils")
    display_mod = types.ModuleType("ansible.utils.display")
    display_mod.Display = Display

    old_modules = {
        name: sys.modules.get(name)
        for name in (
            "ansible",
            "ansible.plugins",
            "ansible.plugins.action",
            "ansible.utils",
            "ansible.utils.display",
        )
    }
    sys.modules.update(
        {
            "ansible": ansible_mod,
            "ansible.plugins": plugins_mod,
            "ansible.plugins.action": action_mod,
            "ansible.utils": utils_mod,
            "ansible.utils.display": display_mod,
        }
    )
    try:
        spec = importlib.util.spec_from_file_location("jtcom_action_under_test", path)
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, old_module in old_modules.items():
            if old_module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old_module
