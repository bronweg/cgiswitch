"""Unit tests for canonical VLAN membership semantics and JTCom conversions."""

from __future__ import annotations

import pytest

from cgiswitch.utils.vlan_membership import (
    Membership,
    canonical_to_jtcom_port_vlan_state,
    get_vlan_membership_type,
    jtcom_to_canonical_port_vlan_state,
    make_port_state,
    validate_canonical_port_state,
)


def test_canonical_to_jtcom_access() -> None:
    backend = canonical_to_jtcom_port_vlan_state(make_port_state(untagged_vlan=10))
    assert backend == {
        "mode": "access",
        "access_vlan": 10,
        "native_vlan": None,
        "permit_vlans": [],
    }


def test_canonical_to_jtcom_trunk() -> None:
    backend = canonical_to_jtcom_port_vlan_state(
        make_port_state(untagged_vlan=1, tagged_vlans={61})
    )
    assert backend == {
        "mode": "trunk",
        "access_vlan": None,
        "native_vlan": 1,
        "permit_vlans": [1, 61],
    }


def test_jtcom_to_canonical_access() -> None:
    canonical = jtcom_to_canonical_port_vlan_state(
        {
            "mode": "access",
            "access_vlan": 10,
            "native_vlan": None,
            "permit_vlans": [],
        }
    )
    assert canonical == make_port_state(untagged_vlan=10)


def test_jtcom_to_canonical_trunk() -> None:
    canonical = jtcom_to_canonical_port_vlan_state(
        {
            "mode": "trunk",
            "access_vlan": None,
            "native_vlan": 1,
            "permit_vlans": [1, 61],
        }
    )
    assert canonical == make_port_state(untagged_vlan=1, tagged_vlans={61})


def test_round_trip_trunk_preserves_canonical_semantics() -> None:
    canonical = make_port_state(untagged_vlan=10, tagged_vlans={20, 30})
    round_trip = jtcom_to_canonical_port_vlan_state(
        canonical_to_jtcom_port_vlan_state(canonical)
    )
    assert round_trip == canonical


def test_invalid_jtcom_trunk_requires_native_vlan_in_permit_list() -> None:
    with pytest.raises(ValueError, match="native_vlan=10"):
        jtcom_to_canonical_port_vlan_state(
            {
                "mode": "trunk",
                "access_vlan": None,
                "native_vlan": 10,
                "permit_vlans": [20, 30],
            }
        )


def test_tagged_only_canonical_state_is_not_supported_for_jtcom_conversion() -> None:
    with pytest.raises(
        ValueError,
        match="does not support tagged-only port state without an untagged/native VLAN",
    ):
        canonical_to_jtcom_port_vlan_state(make_port_state(tagged_vlans={20}))


def test_empty_canonical_state_is_not_supported_for_jtcom_conversion() -> None:
    with pytest.raises(ValueError, match="policy layer must resolve it first"):
        canonical_to_jtcom_port_vlan_state(make_port_state())


def test_canonical_invariant_rejects_same_vlan_as_tagged_and_untagged() -> None:
    with pytest.raises(ValueError, match="cannot be both untagged and tagged"):
        make_port_state(untagged_vlan=10, tagged_vlans={10, 20})


def test_get_vlan_membership_type_reports_absent_untagged_and_tagged() -> None:
    state = make_port_state(untagged_vlan=10, tagged_vlans={20, 30})
    assert get_vlan_membership_type(state, 10) is Membership.UNTAGGED
    assert get_vlan_membership_type(state, 20) is Membership.TAGGED
    assert get_vlan_membership_type(state, 99) is Membership.ABSENT


def test_validate_canonical_port_state_accepts_valid_state() -> None:
    validate_canonical_port_state(make_port_state(untagged_vlan=10, tagged_vlans={20}))


def test_validate_canonical_port_state_rejects_non_int_untagged_vlan() -> None:
    with pytest.raises(ValueError, match="untagged_vlan must be int"):
        validate_canonical_port_state({"untagged_vlan": "10", "tagged_vlans": set()})  # type: ignore[arg-type]


def test_validate_canonical_port_state_rejects_untagged_vlan_out_of_range() -> None:
    with pytest.raises(ValueError, match="untagged_vlan must be 1..4094"):
        validate_canonical_port_state({"untagged_vlan": 0, "tagged_vlans": set()})


def test_validate_canonical_port_state_rejects_non_set_tagged_vlans() -> None:
    with pytest.raises(ValueError, match="tagged_vlans must be set\\[int\\]"):
        validate_canonical_port_state({"untagged_vlan": None, "tagged_vlans": [10]})  # type: ignore[arg-type]


def test_validate_canonical_port_state_rejects_non_int_tagged_vlan_member() -> None:
    with pytest.raises(ValueError, match="tagged_vlans must contain only int VLAN IDs"):
        validate_canonical_port_state({"untagged_vlan": None, "tagged_vlans": {1, "20"}})  # type: ignore[arg-type]


def test_validate_canonical_port_state_rejects_tagged_vlan_out_of_range() -> None:
    with pytest.raises(ValueError, match="tagged_vlans must contain VLAN IDs in 1..4094"):
        validate_canonical_port_state({"untagged_vlan": None, "tagged_vlans": {4095}})
