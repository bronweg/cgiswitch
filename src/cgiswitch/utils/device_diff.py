"""Device-level diff / plan engine for cgiswitch.

Compares a *current* :class:`~cgiswitch.model.config.DeviceConfig` against
a *desired* incremental-change config and produces an ordered
:class:`DevicePlan` with the minimal set of changes needed.

Each VLAN/port entry in *desired* carries a ``state`` field:

- ``"present"`` — create or update to match the given attributes.
- ``"absent"`` — delete the VLAN (ports: administratively disable).

Items **not** mentioned in *desired* are left completely untouched.

Membership diffs in this module are expressed in canonical tagged/untagged
terms rather than JTCom backend native/permit fields.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any, Literal

from cgiswitch.model.config import DeviceConfig
from cgiswitch.model.vlan import VlanConfig
from cgiswitch.utils.vlan_membership import NullablePortSet, apply_vlan_membership_config

ChangeKind = Literal["vlan_create", "vlan_update", "vlan_delete", "port_update"]


@dataclass
class Change:
    """A single configuration change.

    Attributes:
        kind: Category of change.
        key: Unique string key (e.g. ``"vlan:10"``, ``"port:3"``).
        details: Freeform metadata describing what changed.
    """

    kind: ChangeKind
    key: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class DevicePlan:
    """Ordered list of changes to apply to reach the desired config.

    Apply ordering:

    1. ``vlan_create`` — ascending VLAN ID
    2. ``vlan_update`` — ascending VLAN ID
    3. ``port_update`` — ascending port_id
    4. ``vlan_delete`` — descending VLAN ID

    Attributes:
        changes: Ordered :class:`Change` list.
        summary: Count per change kind.
    """

    changes: list[Change] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)


def build_device_plan(
    current: DeviceConfig,
    desired: DeviceConfig,
    *,
    safety_port_id: int | None = None,
) -> DevicePlan:
    """Compute the minimal ordered plan from the explicit *desired* entries.

    Only VLANs and ports listed in *desired* are considered; unlisted items
    are never touched.  The ``state`` field on each entry controls intent:

    **VLANs**:

    - ``state="present"`` + not in *current* → ``vlan_create``.
    - ``state="present"`` + in *current* + name or membership differs
      → ``vlan_update``.
    - ``state="absent"`` + in *current* + ``vlan_id != 1`` → ``vlan_delete``.
    - ``state="absent"`` + not in *current* → no-op.
    - VLAN 1 is **never** deleted.

    **Ports**:

    - Compare each non-``None`` field; emit ``port_update`` if any differs.
    - Set ``admin_up=False`` to administratively disable a port.
    - If ``safety_port_id`` matches a disable (``admin_up=False``), the change is silently skipped.

    Args:
        current: Current device config (as read from the switch).
        desired: Desired incremental-change config.
        safety_port_id: 1-based port ID that must never be disabled.  A desired
            change that would set ``admin_up=False`` for this port is silently
            skipped (with a warning).

    Returns:
        A :class:`DevicePlan` with changes in apply order.
    """
    creates: list[Change] = []
    updates: list[Change] = []
    port_changes: list[Change] = []
    deletes: list[Change] = []

    # ------------------------------------------------------------------ VLANs
    for vid in sorted(desired.vlans):
        cfg = desired.vlans[vid]

        if cfg.state == "absent":
            if vid in current.vlans and vid != 1:
                deletes.append(
                    Change(
                        kind="vlan_delete",
                        key=f"vlan:{vid}",
                        details={"vlan_id": vid},
                    )
                )
            continue

        # state == "present"
        if vid not in current.vlans:
            tagged, untagged = apply_vlan_membership_config(set(), set(), cfg)
            if tagged is None or untagged is None:
                raise AssertionError(
                    f"Internal invariant violated: new VLAN {vid} membership must be concrete"
                )
            creates.append(
                Change(
                    kind="vlan_create",
                    key=f"vlan:{vid}",
                    details={
                        "vlan_id": vid,
                        "name": cfg.name,
                        "tagged_ports": sorted(tagged),
                        "untagged_ports": sorted(untagged),
                    },
                )
            )
            continue

        entry = current.vlans[vid]
        diffs: dict[str, Any] = {}

        if cfg.name is not None and cfg.name != entry.name:
            diffs["name"] = {"from": entry.name, "to": cfg.name}

        membership_diffs = _vlan_membership_diffs(entry, cfg)
        diffs.update(membership_diffs)

        if diffs:
            updates.append(
                Change(
                    kind="vlan_update",
                    key=f"vlan:{vid}",
                    details={"vlan_id": vid, **diffs},
                )
            )

    # ------------------------------------------------------------------ Ports
    for pid in sorted(desired.ports):
        cfg_p = desired.ports[pid]
        cur_p = current.ports.get(pid)
        if cur_p is None:
            continue

        field_diffs: dict[str, Any] = {}

        if cfg_p.admin_up is not None and cfg_p.admin_up != cur_p.admin_up:
            if not cfg_p.admin_up and safety_port_id is not None and pid == safety_port_id:
                warnings.warn(
                    f"Refusing to disable safety port {pid}; skipping admin_up change.",
                    stacklevel=2,
                )
            else:
                field_diffs["admin_up"] = {"from": cur_p.admin_up, "to": cfg_p.admin_up}

        if cfg_p.speed_duplex is not None and cfg_p.speed_duplex != cur_p.speed_duplex:
            field_diffs["speed_duplex"] = {
                "from": cur_p.speed_duplex,
                "to": cfg_p.speed_duplex,
            }

        if cfg_p.flow_control is not None and cfg_p.flow_control != cur_p.flow_control:
            field_diffs["flow_control"] = {
                "from": cur_p.flow_control,
                "to": cfg_p.flow_control,
            }

        if field_diffs:
            port_changes.append(
                Change(
                    kind="port_update",
                    key=f"port:{pid}",
                    details={"port_id": pid, **field_diffs},
                )
            )

    # Deletes are collected in ascending order above; apply in descending VID order
    deletes_desc = list(reversed(deletes))

    all_changes = creates + updates + port_changes + deletes_desc
    summary: dict[str, int] = {
        "vlan_create": len(creates),
        "vlan_update": len(updates),
        "port_update": len(port_changes),
        "vlan_delete": len(deletes),
    }
    return DevicePlan(changes=all_changes, summary=summary)


def _vlan_membership_diffs(current: VlanConfig, desired: VlanConfig) -> dict[str, Any]:
    """Return VLAN membership diffs while preserving omitted-field semantics."""
    current_tagged: NullablePortSet = (
        None if current.tagged_ports is None else set(current.tagged_ports)
    )
    current_untagged: NullablePortSet = (
        None if current.untagged_ports is None else set(current.untagged_ports)
    )

    new_tagged, new_untagged = apply_vlan_membership_config(
        current_tagged,
        current_untagged,
        desired,
    )
    membership = desired.normalized_membership()

    diffs: dict[str, Any] = {}
    tagged_diff = _membership_side_diff(
        current_tagged,
        new_tagged,
        _side_touched(membership["tagged"]),
    )
    if tagged_diff is not None:
        diffs["tagged_ports"] = tagged_diff

    untagged_diff = _membership_side_diff(
        current_untagged,
        new_untagged,
        _side_touched(membership["untagged"]),
    )
    if untagged_diff is not None:
        diffs["untagged_ports"] = untagged_diff
    return diffs


def _membership_side_diff(
    current: NullablePortSet,
    new: NullablePortSet,
    touched: bool,
) -> dict[str, Any] | None:
    if current == new and not (touched and current is None):
        return None

    diff: dict[str, Any] = {
        "from": None if current is None else sorted(current),
        "to": None if new is None else sorted(new),
    }
    if touched and new is None:
        diff["note"] = "unknown current membership; add/remove target cannot be rendered fully"
        diff["meta"] = {
            "unknown_membership": True,
            "reason": "unknown_current_baseline_with_add_remove",
        }
    return diff


def _side_touched(operation: dict[str, set[int] | None]) -> bool:
    return operation["set"] is not None or bool(operation["add"]) or bool(operation["remove"])
