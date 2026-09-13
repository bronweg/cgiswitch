"""Unit tests for cgiswitch.utils.vlan_diff.plan_vlan_changes."""

from __future__ import annotations

from cgiswitch.model.vlan import VlanChangeSet, VlanConfig, VlanEntry
from cgiswitch.utils.vlan_diff import plan_vlan_changes

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_entry(vid: int, name: str = "", **kwargs: object) -> VlanEntry:
    return VlanEntry(vlan_id=vid, name=name, **kwargs)  # type: ignore[arg-type]


def make_cfg(vid: int, name: str | None = None, **kwargs: object) -> VlanConfig:
    return VlanConfig(vlan_id=vid, name=name, **kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


class TestCreate:
    def test_new_vlan_appears_in_create(self) -> None:
        current = {1: make_entry(1), 10: make_entry(10, "Management")}
        desired = {1: make_cfg(1), 10: make_cfg(10), 20: make_cfg(20, "Dev")}
        cs = plan_vlan_changes(current, desired)
        assert [c.vlan_id for c in cs.create] == [20]

    def test_multiple_new_vlans_sorted_ascending(self) -> None:
        current = {1: make_entry(1)}
        desired = {1: make_cfg(1), 30: make_cfg(30), 20: make_cfg(20)}
        cs = plan_vlan_changes(current, desired)
        assert [c.vlan_id for c in cs.create] == [20, 30]

    def test_no_creates_when_already_present(self) -> None:
        current = {1: make_entry(1), 10: make_entry(10)}
        desired = {1: make_cfg(1), 10: make_cfg(10)}
        cs = plan_vlan_changes(current, desired)
        assert cs.create == []


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


class TestDelete:
    def test_delete_when_state_absent(self) -> None:
        current = {1: make_entry(1), 10: make_entry(10), 20: make_entry(20)}
        desired = {10: make_cfg(10, state="absent")}
        cs = plan_vlan_changes(current, desired)
        assert cs.delete == [10]

    def test_unlisted_vlans_not_deleted(self) -> None:
        """VLANs not mentioned in desired are never touched."""
        current = {1: make_entry(1), 10: make_entry(10), 20: make_entry(20)}
        desired = {10: make_cfg(10, state="absent")}  # 20 not listed
        cs = plan_vlan_changes(current, desired)
        assert 20 not in cs.delete

    def test_vlan1_never_deleted_even_when_absent(self) -> None:
        current = {1: make_entry(1), 10: make_entry(10)}
        desired = {1: make_cfg(1, state="absent")}
        cs = plan_vlan_changes(current, desired)
        assert 1 not in cs.delete

    def test_absent_vlan_not_in_current_is_noop(self) -> None:
        """state=absent on a VLAN not in current is silently ignored."""
        current = {1: make_entry(1)}
        desired = {99: make_cfg(99, state="absent")}
        cs = plan_vlan_changes(current, desired)
        assert cs.delete == []

    def test_multiple_deletes_sorted_ascending(self) -> None:
        current = {
            1: make_entry(1),
            10: make_entry(10),
            20: make_entry(20),
            30: make_entry(30),
        }
        desired = {
            10: make_cfg(10, state="absent"),
            20: make_cfg(20, state="absent"),
            30: make_cfg(30, state="absent"),
        }
        cs = plan_vlan_changes(current, desired)
        assert cs.delete == [10, 20, 30]


# ---------------------------------------------------------------------------
# Update — name changes
# ---------------------------------------------------------------------------


class TestUpdateName:
    def test_rename_detected(self) -> None:
        current = {10: make_entry(10, "OldName")}
        desired = {10: make_cfg(10, "NewName")}
        cs = plan_vlan_changes(current, desired)
        assert [u.vlan_id for u in cs.update] == [10]

    def test_none_name_does_not_trigger_rename(self) -> None:
        current = {10: make_entry(10, "Existing")}
        desired = {10: make_cfg(10, None)}  # name=None means "do not change"
        cs = plan_vlan_changes(current, desired)
        assert cs.update == []

    def test_empty_string_name_triggers_rename(self) -> None:
        current = {10: make_entry(10, "Existing")}
        desired = {10: make_cfg(10, "")}
        cs = plan_vlan_changes(current, desired)
        assert [u.vlan_id for u in cs.update] == [10]


# ---------------------------------------------------------------------------
# Update — membership changes
# ---------------------------------------------------------------------------


class TestUpdateMembership:
    def test_membership_change_detected(self) -> None:
        current = {10: make_entry(10, untagged_ports=["Port 1"])}
        # desired: Port 1 unchanged, Port 2 added.
        desired = {10: make_cfg(10, untagged_ports=[1, 2])}
        cs = plan_vlan_changes(current, desired)
        assert [u.vlan_id for u in cs.update] == [10]

    def test_membership_same_not_flagged(self) -> None:
        current = {10: make_entry(10, untagged_ports=["Port 1"])}
        desired = {10: make_cfg(10, untagged_ports=[1])}
        cs = plan_vlan_changes(current, desired)
        assert cs.update == []

    def test_tagged_remove_only_detected(self) -> None:
        current = {
            10: make_entry(
                10,
                tagged_ports=["Port 11", "Port 21", "Port 31"],
            )
        }
        desired = {10: make_cfg(10, tagged_remove=[21])}
        cs = plan_vlan_changes(current, desired)
        assert [u.vlan_id for u in cs.update] == [10]

    def test_tagged_add_remove_detected(self) -> None:
        current = {10: make_entry(10, tagged_ports=["Port 11", "Port 21"])}
        desired = {10: make_cfg(10, tagged_add=[31], tagged_remove=[11])}
        cs = plan_vlan_changes(current, desired)
        assert [u.vlan_id for u in cs.update] == [10]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_current_empty_desired(self) -> None:
        cs = plan_vlan_changes({}, {})
        assert cs == VlanChangeSet()

    def test_empty_desired_is_noop(self) -> None:
        """With the partial model, empty desired leaves everything untouched."""
        current = {1: make_entry(1), 10: make_entry(10)}
        cs = plan_vlan_changes(current, {})
        assert cs.create == []
        assert cs.update == []
        assert cs.delete == []

    def test_result_is_deterministic(self) -> None:
        import random

        vids = list(range(2, 20))
        random.shuffle(vids)
        current = {v: make_entry(v) for v in vids}
        current[1] = make_entry(1)
        desired = {v: make_cfg(v, state="absent") for v in vids}
        cs1 = plan_vlan_changes(current, desired)
        cs2 = plan_vlan_changes(current, desired)
        assert cs1.delete == cs2.delete == sorted(vids)
