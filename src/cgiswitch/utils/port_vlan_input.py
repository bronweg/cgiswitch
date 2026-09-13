"""Port-centric VLAN membership input translation.

The runtime membership engine plans on canonical per-port membership semantics.
This module translates optional VLAN fields on ``PortConfig`` into
VLAN-centric ``VlanConfig`` mutation operations before canonical planning and
policy evaluation.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Literal

from cgiswitch.model.port import PortConfig
from cgiswitch.model.vlan import VlanConfig
from cgiswitch.utils.vlan_membership import PortMembershipMap

MembershipSide = Literal["tagged", "untagged"]
MembershipOp = Literal["add", "remove"]


class DualSyntaxConflictError(ValueError):
    """Raised when VLAN-centric and port-centric membership intents conflict."""


def merge_port_vlan_membership_inputs(
    current_per_port: PortMembershipMap,
    desired_vlans: dict[int, VlanConfig],
    desired_ports: dict[int, PortConfig],
) -> dict[int, VlanConfig]:
    """Return VLAN-centric configs with port-centric membership inputs merged.

    Port IDs are 1-based everywhere in the project.  The resulting
    ``VlanConfig`` membership operations use the same 1-based port IDs that the
    user supplied on ``PortConfig.port_id``.  Conflict detection happens before
    those operations are handed to the canonical membership planner.
    """
    result = {vid: _clone_vlan_config(cfg) for vid, cfg in sorted(desired_vlans.items())}
    tracker = _ConflictTracker()

    for cfg in result.values():
        _record_vlan_config(tracker, cfg, source="vlan")

    for port in sorted(desired_ports.values(), key=lambda item: item.port_id):
        if not port_has_vlan_membership_input(port):
            continue
        port_id = port.port_id

        if port.access_vlan is not None:
            tracker.record_untagged(port_id, port.access_vlan, "port.access_vlan")
            _merge_port_op(result, port.access_vlan, "untagged", "add", port_id)

        if port.native_vlan is not None:
            tracker.record_untagged(port_id, port.native_vlan, "port.native_vlan")
            _merge_port_op(result, port.native_vlan, "untagged", "add", port_id)

        for vlan_id in port.trunk_add_vlans or []:
            tracker.record_tagged(port_id, vlan_id, "add", "port.trunk_add_vlans")
            _merge_port_op(result, vlan_id, "tagged", "add", port_id)

        for vlan_id in port.trunk_remove_vlans or []:
            tracker.record_tagged(port_id, vlan_id, "remove", "port.trunk_remove_vlans")
            _merge_port_op(result, vlan_id, "tagged", "remove", port_id)

        if port.trunk_set_vlans is not None:
            tracker.record_trunk_set(port_id, set(port.trunk_set_vlans))
            _merge_trunk_set_ops(result, current_per_port, tracker, port_id, port.trunk_set_vlans)

    return result


def port_has_vlan_membership_input(port: PortConfig) -> bool:
    """Return ``True`` if a ``PortConfig`` carries port-centric VLAN input."""
    return (
        port.access_vlan is not None
        or port.native_vlan is not None
        or port.trunk_add_vlans is not None
        or port.trunk_remove_vlans is not None
        or port.trunk_set_vlans is not None
    )


def _clone_vlan_config(cfg: VlanConfig) -> VlanConfig:
    return replace(
        cfg,
        tagged_ports=None if cfg.tagged_ports is None else list(cfg.tagged_ports),
        untagged_ports=None if cfg.untagged_ports is None else list(cfg.untagged_ports),
        tagged_add=None if cfg.tagged_add is None else list(cfg.tagged_add),
        tagged_remove=None if cfg.tagged_remove is None else list(cfg.tagged_remove),
        tagged_set=None if cfg.tagged_set is None else list(cfg.tagged_set),
        untagged_add=None if cfg.untagged_add is None else list(cfg.untagged_add),
        untagged_remove=None if cfg.untagged_remove is None else list(cfg.untagged_remove),
        untagged_set=None if cfg.untagged_set is None else list(cfg.untagged_set),
    )


def _record_vlan_config(
    tracker: _ConflictTracker,
    cfg: VlanConfig,
    *,
    source: str,
) -> None:
    membership = cfg.normalized_membership()
    tagged = membership["tagged"]
    untagged = membership["untagged"]

    tagged_set = tagged["set"]
    if tagged_set is not None:
        for port_id in tagged_set:
            tracker.record_tagged(port_id, cfg.vlan_id, "add", source)
    else:
        for port_id in tagged["add"] or set():
            tracker.record_tagged(port_id, cfg.vlan_id, "add", source)
        for port_id in tagged["remove"] or set():
            tracker.record_tagged(port_id, cfg.vlan_id, "remove", source)

    untagged_set = untagged["set"]
    if untagged_set is not None:
        for port_id in untagged_set:
            tracker.record_untagged(port_id, cfg.vlan_id, source)
    else:
        for port_id in untagged["add"] or set():
            tracker.record_untagged(port_id, cfg.vlan_id, source)
        for port_id in untagged["remove"] or set():
            tracker.record_untagged_remove(port_id, cfg.vlan_id, source)


def _merge_trunk_set_ops(
    result: dict[int, VlanConfig],
    current_per_port: PortMembershipMap,
    tracker: _ConflictTracker,
    port_id: int,
    trunk_set_vlans: list[int],
) -> None:
    current_state = current_per_port.get(port_id)
    current_tagged = set()
    if current_state is not None:
        tagged = current_state["tagged_vlans"]
        if not isinstance(tagged, set):
            raise TypeError(f"tagged_vlans must be set[int], got {type(tagged)!r}")
        current_tagged = set(tagged)

    desired_tagged = set(trunk_set_vlans)
    for vlan_id in sorted(current_tagged - desired_tagged):
        tracker.record_tagged(port_id, vlan_id, "remove", "port.trunk_set_vlans")
        _merge_port_op(result, vlan_id, "tagged", "remove", port_id)
    for vlan_id in sorted(desired_tagged - current_tagged):
        tracker.record_tagged(port_id, vlan_id, "add", "port.trunk_set_vlans")
        _merge_port_op(result, vlan_id, "tagged", "add", port_id)


def _merge_port_op(
    vlans: dict[int, VlanConfig],
    vlan_id: int,
    side: MembershipSide,
    op: MembershipOp,
    port_id: int,
) -> None:
    cfg = vlans.get(vlan_id)
    if cfg is None:
        cfg = VlanConfig(vlan_id=vlan_id)
    if cfg.state == "absent":
        raise DualSyntaxConflictError(
            f"Port-centric VLAN membership targets VLAN {vlan_id}, but VLAN-centric input "
            "marks it absent."
        )

    if side == "tagged":
        if cfg.tagged_ports is not None or cfg.tagged_set is not None:
            _assert_set_compatible(cfg, side, op, port_id)
            vlans[vlan_id] = cfg
            return
        tagged_add = _merge_list(cfg.tagged_add, port_id) if op == "add" else cfg.tagged_add
        tagged_remove = (
            _merge_list(cfg.tagged_remove, port_id) if op == "remove" else cfg.tagged_remove
        )
        vlans[vlan_id] = replace(cfg, tagged_add=tagged_add, tagged_remove=tagged_remove)
        return

    if cfg.untagged_ports is not None or cfg.untagged_set is not None:
        _assert_set_compatible(cfg, side, op, port_id)
        vlans[vlan_id] = cfg
        return
    untagged_add = _merge_list(cfg.untagged_add, port_id) if op == "add" else cfg.untagged_add
    untagged_remove = (
        _merge_list(cfg.untagged_remove, port_id) if op == "remove" else cfg.untagged_remove
    )
    vlans[vlan_id] = replace(cfg, untagged_add=untagged_add, untagged_remove=untagged_remove)


def _assert_set_compatible(
    cfg: VlanConfig,
    side: MembershipSide,
    op: MembershipOp,
    port_id: int,
) -> None:
    ports = cfg.tagged_set if side == "tagged" else cfg.untagged_set
    legacy_ports = cfg.tagged_ports if side == "tagged" else cfg.untagged_ports
    set_ports = set(ports if ports is not None else legacy_ports or [])
    if (op == "add" and port_id in set_ports) or (op == "remove" and port_id not in set_ports):
        return
    raise DualSyntaxConflictError(
        f"Port-centric {side}_{op} for port_id={port_id} VLAN {cfg.vlan_id} conflicts with "
        f"VLAN-centric {side}_set/{side}_ports."
    )


def _merge_list(values: list[int] | None, port_id: int) -> list[int]:
    return sorted(set(values or []) | {port_id})


class _ConflictTracker:
    def __init__(self) -> None:
        self._untagged_assignments: dict[int, tuple[int, str]] = {}
        self._untagged_removes: dict[tuple[int, int], str] = {}
        self._tagged_ops: dict[tuple[int, int], tuple[MembershipOp, str]] = {}
        self._trunk_set_ports: dict[int, set[int]] = {}

    def record_untagged(self, port_id: int, vlan_id: int, source: str) -> None:
        existing = self._untagged_assignments.get(port_id)
        if existing is not None and existing[0] != vlan_id:
            raise DualSyntaxConflictError(
                f"Conflicting untagged VLANs for port_id={port_id}: VLAN {existing[0]} "
                f"from {existing[1]} vs VLAN {vlan_id} from {source}."
            )
        remove_source = self._untagged_removes.get((port_id, vlan_id))
        if remove_source is not None:
            raise DualSyntaxConflictError(
                f"Conflicting untagged add/remove for port_id={port_id} VLAN {vlan_id} "
                f"from {remove_source} and {source}."
            )
        self._untagged_assignments[port_id] = (vlan_id, source)

    def record_untagged_remove(self, port_id: int, vlan_id: int, source: str) -> None:
        existing = self._untagged_assignments.get(port_id)
        if existing is not None and existing[0] == vlan_id:
            raise DualSyntaxConflictError(
                f"Conflicting untagged add/remove for port_id={port_id} VLAN {vlan_id} "
                f"from {existing[1]} and {source}."
            )
        self._untagged_removes[(port_id, vlan_id)] = source

    def record_tagged(
        self,
        port_id: int,
        vlan_id: int,
        op: MembershipOp,
        source: str,
    ) -> None:
        key = (port_id, vlan_id)
        if port_id in self._trunk_set_ports and source != "port.trunk_set_vlans":
            raise DualSyntaxConflictError(
                f"trunk_set_vlans for port_id={port_id} cannot be combined with other "
                "tagged VLAN-centric or port-centric operations for that port."
            )
        existing = self._tagged_ops.get(key)
        if existing is not None and existing[0] != op:
            raise DualSyntaxConflictError(
                f"Conflicting tagged add/remove for port_id={port_id} VLAN {vlan_id}: "
                f"{existing[0]} from {existing[1]} vs {op} from {source}."
            )
        self._tagged_ops[key] = (op, source)

    def record_trunk_set(self, port_id: int, vlan_ids: set[int]) -> None:
        for (existing_port_id, _vlan_id), (_op, source) in self._tagged_ops.items():
            if existing_port_id == port_id:
                raise DualSyntaxConflictError(
                    f"trunk_set_vlans for port_id={port_id} conflicts with existing tagged "
                    f"operation from {source}; use one syntax for this port."
                )
        if port_id in self._trunk_set_ports and self._trunk_set_ports[port_id] != vlan_ids:
            raise DualSyntaxConflictError(
                f"Conflicting trunk_set_vlans declarations for port_id={port_id}."
            )
        self._trunk_set_ports[port_id] = vlan_ids
