"""VLAN change-set planner.

Compares a *current* VLAN state (as returned by :meth:`JTComSwitch.read_vlans`
after parsing) against a *desired* incremental-change state and produces a
:class:`VlanChangeSet` describing what needs to be created, updated or deleted.

Each entry in *desired* carries a ``state`` field:

- ``"present"`` — create or update the VLAN to match the given attributes.
- ``"absent"`` — delete the VLAN if it exists (VLAN 1 is never deleted).

VLANs not mentioned in *desired* are left untouched.

This planner reasons in canonical tagged/untagged VLAN membership semantics.
It does not build JTCom backend ``native_vlan``/``permit_vlans`` state.
"""

from __future__ import annotations

from cgiswitch.model.vlan import VlanChangeSet, VlanConfig, VlanEntry
from cgiswitch.utils.vlan_membership import apply_vlan_membership_config, port_name_to_id


def plan_vlan_changes(
    current: dict[int, VlanEntry],
    desired: dict[int, VlanConfig],
) -> VlanChangeSet:
    """Compute the minimal set of changes needed from the explicit *desired* entries.

    Only VLANs listed in *desired* are considered; unlisted VLANs are never
    touched.  The ``state`` field on each :class:`VlanConfig` controls intent:

    - ``state="present"`` + not in *current* → create.
    - ``state="present"`` + in *current* + name or membership differs → update.
    - ``state="absent"`` + in *current* + ``vlan_id != 1`` → delete.
    - ``state="absent"`` + not in *current* → no-op.

    Args:
        current: Mapping of VLAN ID → :class:`VlanEntry` (current switch state).
        desired: Mapping of VLAN ID → :class:`VlanConfig` (incremental changes).

    Returns:
        A :class:`VlanChangeSet` with ``create`` and ``update`` sorted ascending
        by VID and ``delete`` sorted ascending by VID.
    """
    creates: list[VlanConfig] = []
    updates: list[VlanConfig] = []
    deletes: list[int] = []

    for vid in sorted(desired):
        cfg = desired[vid]

        if cfg.state == "absent":
            if vid in current and vid != 1:
                deletes.append(vid)
            continue

        # state == "present"
        if vid not in current:
            creates.append(cfg)
        else:
            entry = current[vid]
            name_changed = cfg.name is not None and cfg.name != entry.name

            current_untagged_ids = _port_names_to_ids(set(entry.untagged_ports))
            current_tagged_ids = _port_names_to_ids(set(entry.tagged_ports))
            membership_changed = _membership_changed(
                current_tagged_ids,
                current_untagged_ids,
                cfg,
            )

            if name_changed or membership_changed:
                updates.append(cfg)

    return VlanChangeSet(create=creates, update=updates, delete=deletes)


def _port_names_to_ids(names: set[str]) -> set[int]:
    """Convert a set of ``"Port N"`` strings to 1-based port IDs."""
    port_ids: set[int] = set()
    for name in names:
        try:
            port_ids.add(port_name_to_id(name))
        except ValueError:
            continue
    return port_ids


def _membership_changed(
    current_tagged: set[int],
    current_untagged: set[int],
    cfg: VlanConfig,
) -> bool:
    """Return whether *cfg* changes this VLAN's own membership dimension."""
    new_tagged, new_untagged = apply_vlan_membership_config(
        current_tagged,
        current_untagged,
        cfg,
    )
    return new_tagged != current_tagged or new_untagged != current_untagged
