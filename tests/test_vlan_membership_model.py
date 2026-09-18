"""Tests for VlanConfig membership normalization and validation."""

import pytest

from cgiswitch.model.vlan import VlanConfig


class TestVlanConfigMembershipModel:
    def test_tagged_add_only(self) -> None:
        vlan = VlanConfig(vlan_id=20, tagged_add=[5, 6, 6])
        normalized = vlan.normalized_membership()
        assert normalized["tagged"] == {"add": {5, 6}, "remove": set(), "set": None}

    def test_tagged_remove_only(self) -> None:
        vlan = VlanConfig(vlan_id=20, tagged_remove=[7, 7])
        normalized = vlan.normalized_membership()
        assert normalized["tagged"] == {"add": set(), "remove": {7}, "set": None}

    def test_tagged_set_replaces_membership(self) -> None:
        vlan = VlanConfig(vlan_id=20, tagged_set=[1, 2, 2])
        normalized = vlan.normalized_membership()
        assert normalized["tagged"] == {"add": set(), "remove": set(), "set": {1, 2}}

    def test_empty_tagged_set_clears_membership(self) -> None:
        assert (
            VlanConfig(vlan_id=20, tagged_set=[]).normalized_membership()["tagged"]["set"]
            == set()
        )

    def test_untagged_add_only(self) -> None:
        vlan = VlanConfig(vlan_id=20, untagged_add=[1])
        normalized = vlan.normalized_membership()
        assert normalized["untagged"] == {"add": {1}, "remove": set(), "set": None}

    def test_untagged_remove_only(self) -> None:
        vlan = VlanConfig(vlan_id=20, untagged_remove=[1])
        normalized = vlan.normalized_membership()
        assert normalized["untagged"] == {"add": set(), "remove": {1}, "set": None}

    def test_untagged_set_replaces_membership(self) -> None:
        vlan = VlanConfig(vlan_id=20, untagged_set=[2, 2])
        normalized = vlan.normalized_membership()
        assert normalized["untagged"] == {"add": set(), "remove": set(), "set": {2}}

    def test_empty_untagged_set_clears_membership(self) -> None:
        assert (
            VlanConfig(vlan_id=20, untagged_set=[]).normalized_membership()["untagged"]["set"]
            == set()
        )

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"tagged_set": [1], "tagged_add": [2]},
            {"tagged_set": [], "tagged_add": []},
            {"tagged_set": [1], "tagged_remove": [2]},
            {"tagged_set": [], "tagged_remove": []},
        ],
    )
    def test_invalid_tagged_set_with_add_remove(self, kwargs: dict) -> None:
        with pytest.raises(
            ValueError, match="tagged_set cannot be combined with tagged_add or tagged_remove"
        ):
            VlanConfig(vlan_id=20, **kwargs)

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"untagged_set": [1], "untagged_add": [2]},
            {"untagged_set": [], "untagged_add": []},
            {"untagged_set": [1], "untagged_remove": [2]},
            {"untagged_set": [], "untagged_remove": []},
        ],
    )
    def test_invalid_untagged_set_with_add_remove(self, kwargs: dict) -> None:
        with pytest.raises(
            ValueError,
            match="untagged_set cannot be combined with untagged_add or untagged_remove",
        ):
            VlanConfig(vlan_id=20, **kwargs)

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"tagged_add": [-1]},
            {"tagged_set": ["1"]},
            {"untagged_remove": [1.5]},
            {"untagged_set": [True]},
        ],
    )
    def test_invalid_port_types_or_values(self, kwargs: dict) -> None:
        with pytest.raises(ValueError, match="1-based positive integers"):
            VlanConfig(vlan_id=20, **kwargs)

    @pytest.mark.parametrize("kwargs", [{"tagged_add": [0]}, {"untagged_set": [0]}])
    def test_port_zero_is_invalid(self, kwargs: dict) -> None:
        with pytest.raises(ValueError, match="1-based positive integers"):
            VlanConfig(vlan_id=20, **kwargs)

    def test_port_one_is_valid(self) -> None:
        vlan = VlanConfig(vlan_id=20, tagged_add=[1], untagged_remove=[1])
        normalized = vlan.normalized_membership()
        assert normalized["tagged"]["add"] == {1}
        assert normalized["untagged"]["remove"] == {1}

    @pytest.mark.parametrize("vlan_id", [0, 4095])
    def test_invalid_vlan_id(self, vlan_id: int) -> None:
        with pytest.raises(ValueError, match="vlan_id must be 1-4094"):
            VlanConfig(vlan_id=vlan_id)

    def test_invalid_state(self) -> None:
        with pytest.raises(ValueError, match="state must be 'present' or 'absent'"):
            VlanConfig(vlan_id=20, state="foo")

    @pytest.mark.parametrize("state", ["present", "absent"])
    def test_valid_state(self, state: str) -> None:
        vlan = VlanConfig(vlan_id=20, state=state)
        assert vlan.state == state

    def test_empty_config_is_noop(self) -> None:
        normalized = VlanConfig(vlan_id=20).normalized_membership()
        assert normalized == {
            "tagged": {"add": set(), "remove": set(), "set": None},
            "untagged": {"add": set(), "remove": set(), "set": None},
        }
