"""Tests for VlanConfig membership normalization and validation."""

import pytest

from cgiswitch.model.vlan import VlanConfig


class TestVlanConfigMembershipModel:
    # ==============================================================================
    # A. Legacy field semantics
    # ==============================================================================

    def test_legacy_tagged_ports_becomes_tagged_set(self) -> None:
        vlan = VlanConfig(vlan_id=20, tagged_ports=[1, 2, 2, 3])
        normalized = vlan.normalized_membership()
        assert normalized["tagged"]["set"] == {1, 2, 3}
        assert normalized["tagged"]["add"] == set()
        assert normalized["tagged"]["remove"] == set()
        assert normalized["untagged"]["set"] is None

    def test_legacy_tagged_ports_empty_list_becomes_empty_set(self) -> None:
        vlan = VlanConfig(vlan_id=20, tagged_ports=[])
        normalized = vlan.normalized_membership()
        assert normalized["tagged"]["set"] == set()
        assert normalized["tagged"]["add"] == set()
        assert normalized["tagged"]["remove"] == set()

    def test_legacy_untagged_ports_becomes_untagged_set(self) -> None:
        vlan = VlanConfig(vlan_id=20, untagged_ports=[1, 1, 2])
        normalized = vlan.normalized_membership()
        assert normalized["untagged"]["set"] == {1, 2}
        assert normalized["untagged"]["add"] == set()
        assert normalized["untagged"]["remove"] == set()
        assert normalized["tagged"]["set"] is None

    def test_legacy_untagged_ports_empty_list_becomes_empty_set(self) -> None:
        vlan = VlanConfig(vlan_id=20, untagged_ports=[])
        normalized = vlan.normalized_membership()
        assert normalized["untagged"]["set"] == set()
        assert normalized["untagged"]["add"] == set()
        assert normalized["untagged"]["remove"] == set()

    # ==============================================================================
    # B. New operation semantics
    # ==============================================================================

    def test_tagged_add_only(self) -> None:
        vlan = VlanConfig(vlan_id=20, tagged_add=[5, 6, 6])
        normalized = vlan.normalized_membership()
        assert normalized["tagged"]["add"] == {5, 6}
        assert normalized["tagged"]["remove"] == set()
        assert normalized["tagged"]["set"] is None

    def test_tagged_remove_only(self) -> None:
        vlan = VlanConfig(vlan_id=20, tagged_remove=[7, 7])
        normalized = vlan.normalized_membership()
        assert normalized["tagged"]["remove"] == {7}
        assert normalized["tagged"]["add"] == set()
        assert normalized["tagged"]["set"] is None

    def test_tagged_set_only(self) -> None:
        vlan = VlanConfig(vlan_id=20, tagged_set=[1, 2, 2])
        normalized = vlan.normalized_membership()
        assert normalized["tagged"]["set"] == {1, 2}
        assert normalized["tagged"]["add"] == set()
        assert normalized["tagged"]["remove"] == set()

    def test_tagged_set_empty_list_becomes_empty_set(self) -> None:
        vlan = VlanConfig(vlan_id=20, tagged_set=[])
        normalized = vlan.normalized_membership()
        assert normalized["tagged"]["set"] == set()

    def test_untagged_add_only(self) -> None:
        vlan = VlanConfig(vlan_id=20, untagged_add=[1])
        normalized = vlan.normalized_membership()
        assert normalized["untagged"]["add"] == {1}
        assert normalized["untagged"]["remove"] == set()
        assert normalized["untagged"]["set"] is None

    def test_untagged_remove_only(self) -> None:
        vlan = VlanConfig(vlan_id=20, untagged_remove=[1])
        normalized = vlan.normalized_membership()
        assert normalized["untagged"]["remove"] == {1}
        assert normalized["untagged"]["add"] == set()
        assert normalized["untagged"]["set"] is None

    def test_untagged_set_only(self) -> None:
        vlan = VlanConfig(vlan_id=20, untagged_set=[2, 2])
        normalized = vlan.normalized_membership()
        assert normalized["untagged"]["set"] == {2}
        assert normalized["untagged"]["add"] == set()
        assert normalized["untagged"]["remove"] == set()

    def test_untagged_set_empty_list_becomes_empty_set(self) -> None:
        vlan = VlanConfig(vlan_id=20, untagged_set=[])
        normalized = vlan.normalized_membership()
        assert normalized["untagged"]["set"] == set()

    # ==============================================================================
    # C. Conflict validation (presence-based)
    # ==============================================================================

    @pytest.mark.parametrize(
        "kwargs",
        [
            dict(tagged_set=[1], tagged_add=[2]),
            dict(tagged_set=[], tagged_add=[]),
            dict(tagged_set=[1], tagged_remove=[2]),
            dict(tagged_set=[], tagged_remove=[]),
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
            dict(tagged_ports=[1], tagged_add=[2]),
            dict(tagged_ports=[], tagged_add=[]),
            dict(tagged_ports=[1], tagged_remove=[2]),
            dict(tagged_ports=[], tagged_remove=[]),
            dict(tagged_ports=[1], tagged_set=[2]),
            dict(tagged_ports=[], tagged_set=[]),
        ],
    )
    def test_invalid_legacy_tagged_ports_with_new_ops(self, kwargs: dict) -> None:
        with pytest.raises(ValueError, match="legacy tagged_ports cannot be combined with"):
            VlanConfig(vlan_id=20, **kwargs)

    @pytest.mark.parametrize(
        "kwargs",
        [
            dict(untagged_set=[1], untagged_add=[2]),
            dict(untagged_set=[], untagged_add=[]),
            dict(untagged_set=[1], untagged_remove=[2]),
            dict(untagged_set=[], untagged_remove=[]),
        ],
    )
    def test_invalid_untagged_set_with_add_remove(self, kwargs: dict) -> None:
        with pytest.raises(
            ValueError, match="untagged_set cannot be combined with untagged_add or untagged_remove"
        ):
            VlanConfig(vlan_id=20, **kwargs)

    @pytest.mark.parametrize(
        "kwargs",
        [
            dict(untagged_ports=[1], untagged_add=[2]),
            dict(untagged_ports=[], untagged_add=[]),
            dict(untagged_ports=[1], untagged_remove=[2]),
            dict(untagged_ports=[], untagged_remove=[]),
            dict(untagged_ports=[1], untagged_set=[2]),
            dict(untagged_ports=[], untagged_set=[]),
        ],
    )
    def test_invalid_legacy_untagged_ports_with_new_ops(self, kwargs: dict) -> None:
        with pytest.raises(ValueError, match="legacy untagged_ports cannot be combined with"):
            VlanConfig(vlan_id=20, **kwargs)

    # ==============================================================================
    # D. Port validation
    # ==============================================================================

    @pytest.mark.parametrize(
        "kwargs",
        [
            dict(tagged_add=[-1]),
            dict(untagged_ports=[-1]),
            dict(tagged_set=["1"]),
            dict(untagged_remove=[1.5]),
        ],
    )
    def test_invalid_port_types_or_values(self, kwargs: dict) -> None:
        with pytest.raises(ValueError, match="1-based positive integers"):
            VlanConfig(vlan_id=20, **kwargs)

    @pytest.mark.parametrize(
        "kwargs",
        [
            dict(tagged_add=[0]),
            dict(untagged_set=[0]),
        ],
    )
    def test_port_zero_is_invalid(self, kwargs: dict) -> None:
        with pytest.raises(ValueError, match="1-based positive integers"):
            VlanConfig(vlan_id=20, **kwargs)

    def test_port_one_is_valid(self) -> None:
        vlan = VlanConfig(vlan_id=20, tagged_add=[1], untagged_remove=[1])
        normalized = vlan.normalized_membership()
        assert normalized["tagged"]["add"] == {1}
        assert normalized["untagged"]["remove"] == {1}

    # ==============================================================================
    # E. VLAN/state validation
    # ==============================================================================

    @pytest.mark.parametrize("vlan_id", [0, 4095])
    def test_invalid_vlan_id(self, vlan_id: int) -> None:
        with pytest.raises(ValueError, match="vlan_id must be 1-4094"):
            VlanConfig(vlan_id=vlan_id)

    def test_invalid_state(self) -> None:
        with pytest.raises(ValueError, match="state must be 'present' or 'absent'"):
            VlanConfig(vlan_id=20, state="foo")

    @pytest.mark.parametrize("state", ["present", "absent"])
    def test_valid_state(self, state: str) -> None:
        # Should not raise
        vlan = VlanConfig(vlan_id=20, state=state)
        assert vlan.state == state

    # ==============================================================================
    # F. Empty config
    # ==============================================================================

    def test_empty_config_is_noop(self) -> None:
        vlan = VlanConfig(vlan_id=20)
        normalized = vlan.normalized_membership()
        assert normalized["tagged"]["add"] == set()
        assert normalized["tagged"]["remove"] == set()
        assert normalized["tagged"]["set"] is None
        assert normalized["untagged"]["add"] == set()
        assert normalized["untagged"]["remove"] == set()
        assert normalized["untagged"]["set"] is None
