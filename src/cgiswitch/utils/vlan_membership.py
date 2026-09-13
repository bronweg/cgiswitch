"""Canonical VLAN membership semantics, policy, and conversion helpers.

Canonical truth in this module is the on-wire VLAN membership semantics for a
port:

- ``untagged_vlan`` is the single VLAN transmitted untagged on wire, if any
- ``tagged_vlans`` are the VLANs transmitted tagged on wire

This is intentionally different from a device/backend representation such as
JTCom CGI trunk state:

- backend trunk state is expressed as ``native_vlan`` + ``permit_vlans``
- on JTCom, ``permit_vlans`` includes the native VLAN
- therefore backend readback must be normalized before it becomes canonical

Port IDs are 1-based everywhere in the domain model and planner.

Architecture summary:

- canonical current/desired state uses ``untagged_vlan`` + ``tagged_vlans``
- Step 4 policy operates only on canonical state
- JTCom backend state uses ``access_vlan`` or ``native_vlan`` + ``permit_vlans``
- canonical -> JTCom compilation happens only via
  :func:`canonical_to_jtcom_port_vlan_state`
- JTCom readback -> canonical normalization happens only via
  :func:`jtcom_to_canonical_port_vlan_state`
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, TypedDict

from cgiswitch.model.vlan import VlanConfig, VlanEntry, VlanPortConfig

PortMode = Literal["access", "trunk", "none"]
BackendPortMode = Literal["access", "trunk"]
PortMembershipState = dict[str, int | set[int] | None]
PortMembershipMap = dict[int, PortMembershipState]
NullablePortSet = set[int] | None
DEFAULT_FALLBACK_VLAN_ID = 1


class Membership(StrEnum):
    """Canonical per-(port, vlan) membership type."""

    ABSENT = "absent"
    UNTAGGED = "untagged"
    TAGGED = "tagged"


class JTComPortVlanState(TypedDict):
    """JTCom backend VLAN representation for one 1-based port.

    This is not canonical truth.  It matches the vendor-oriented trunk/access
    model used by ``vlanport.cgi``:

    - Access mode carries a single ``access_vlan``
    - Trunk mode carries ``native_vlan`` plus ``permit_vlans``
    - On JTCom, ``permit_vlans`` includes ``native_vlan``
    """

    mode: BackendPortMode
    access_vlan: int | None
    native_vlan: int | None
    permit_vlans: list[int]


_MODE_CHANGE_HINT = "Set allow_port_mode_change=true to allow this access/trunk transition."
_UNTAGGED_MOVE_HINT = "Set allow_untagged_move=True to allow this untagged/native VLAN move."
_VLAN_DELETE_IN_USE_HINT = (
    "Set allow_vlan_delete_in_use=True to detach this VLAN from affected ports before deletion."
)
_NONE_MODE_HINT = (
    "Policy fallback maps ports with no VLAN membership to access VLAN 1."
)


class VlanMembershipModeChangeError(ValueError):
    """Raised when a dangerous access/trunk mode change is blocked."""

    def __init__(self, warnings: list[dict[str, Any]]) -> None:
        self.warnings = warnings
        details = "; ".join(
            (
                f"port_id={w['port_id']} current_mode={w['current_mode']} "
                f"desired_mode={w['desired_mode']}"
            )
            for w in warnings
        )
        super().__init__(f"VLAN port mode change blocked: {details}. {_MODE_CHANGE_HINT}")


class VlanMembershipUnsupportedModeError(ValueError):
    """Raised when the desired VLAN membership cannot be represented on JTCom CGI."""

    def __init__(self, warnings: list[dict[str, Any]]) -> None:
        self.warnings = warnings
        details = "; ".join(
            (
                f"port_id={w['port_id']} desired_state={w['desired_state']} "
                f"hint={w['hint']}"
            )
            for w in warnings
        )
        super().__init__(f"Unsupported VLAN port mode requested: {details}")


class VlanMembershipUntaggedMoveError(ValueError):
    """Raised when an untagged/native VLAN move is blocked by policy."""

    def __init__(self, warnings: list[dict[str, Any]]) -> None:
        self.warnings = warnings
        details = "; ".join(
            (
                f"port_id={w['port_id']} current_untagged_vlan={w['current_untagged_vlan']} "
                f"desired_untagged_vlan={w['desired_untagged_vlan']}"
            )
            for w in warnings
        )
        super().__init__(f"Untagged/native VLAN move blocked: {details}. {_UNTAGGED_MOVE_HINT}")


class VlanDeleteInUseError(ValueError):
    """Raised when deleting a VLAN that is still referenced by ports is blocked."""

    def __init__(self, warnings: list[dict[str, Any]]) -> None:
        self.warnings = warnings
        details = "; ".join(
            (
                f"vlan_id={w['vlan_id']} tagged={w['affected_ports_tagged']} "
                f"untagged={w['affected_ports_untagged']}"
            )
            for w in warnings
        )
        super().__init__(f"VLAN delete blocked because VLAN is still in use: {details}. "
                         f"{_VLAN_DELETE_IN_USE_HINT}")


@dataclass
class VlanMembershipPlan:
    """Computed VLAN membership plan.

    Canonical ``desired_per_port`` is the vendor-independent source of truth
    for planning and policy. Backend-specific representations must not be
    constructed outside conversion helpers.
    """

    current_per_port: PortMembershipMap
    desired_per_port: PortMembershipMap
    changed_ports: list[int]
    changed_vlans: list[int]
    warnings: list[dict[str, Any]]


def make_port_state(
    untagged_vlan: int | None = None,
    tagged_vlans: Iterable[int] | None = None,
) -> PortMembershipState:
    """Return one canonical per-port membership state.

    Canonical state describes on-wire membership semantics only:

    - ``untagged_vlan`` is the VLAN sent untagged on wire
    - ``tagged_vlans`` are VLANs sent tagged on wire
    - the same VLAN must not appear in both places
    """
    state: PortMembershipState = {
        "untagged_vlan": untagged_vlan,
        "tagged_vlans": set(tagged_vlans or ()),
    }
    validate_canonical_port_state(state)
    return state


def validate_canonical_port_state(state: PortMembershipState) -> None:
    """Validate canonical on-wire VLAN membership invariants.

    NOTE:
    The current canonical model assumes at most one untagged VLAN per port.
    This matches the currently supported device capabilities, but may need
    extension in the future for more advanced switching models.

    Invariants:
    - at most one untagged VLAN
    - a VLAN cannot be both untagged and tagged on the same port
    """
    untagged_value = state["untagged_vlan"]
    tagged_value = state["tagged_vlans"]

    if untagged_value is not None and not isinstance(untagged_value, int):
        raise ValueError("untagged_vlan must be int | None in canonical port state")
    if untagged_value is not None and not 1 <= untagged_value <= 4094:
        raise ValueError(f"untagged_vlan must be 1..4094, got {untagged_value}")
    if not isinstance(tagged_value, set):
        raise ValueError("tagged_vlans must be set[int] in canonical port state")
    for vlan_id in tagged_value:
        if not isinstance(vlan_id, int):
            raise ValueError("tagged_vlans must contain only int VLAN IDs")
        if not 1 <= vlan_id <= 4094:
            raise ValueError(f"tagged_vlans must contain VLAN IDs in 1..4094, got {vlan_id}")

    untagged = _untagged_vlan(state)
    tagged = _tagged_vlans(state)
    if untagged is not None and untagged in tagged:
        raise ValueError(
            f"Canonical VLAN membership invariant violated: vlan_id={untagged} "
            "cannot be both untagged and tagged on the same port"
        )


def get_vlan_membership_type(
    state: PortMembershipState,
    vlan_id: int,
) -> Membership:
    """Return canonical per-(port, vlan) membership semantics."""
    validate_canonical_port_state(state)
    if _untagged_vlan(state) == vlan_id:
        return Membership.UNTAGGED
    if vlan_id in _tagged_vlans(state):
        return Membership.TAGGED
    return Membership.ABSENT


def canonical_to_jtcom_port_vlan_state(
    state: PortMembershipState,
) -> JTComPortVlanState:
    """Convert canonical on-wire semantics into JTCom backend representation.

    This helper compiles canonical membership semantics into the current JTCom
    backend trunk/access model.

    IMPORTANT:
    On JTCom trunk ports, ``permit_vlans`` includes ``native_vlan``.
    Canonical ``tagged_vlans`` represents on-wire tagged VLANs only.
    Therefore canonical ``tagged_vlans`` must never be treated as a permit list.

    Supported cases:
    - access: one untagged VLAN, no tagged VLANs
    - trunk: one untagged VLAN, one or more tagged VLANs

    Unsupported JTCom backend cases:
    - tagged-only canonical state
    - empty canonical state

    Canonically, both of those states are meaningful. They are rejected here
    only because the current JTCom backend compiler cannot express them safely
    without prior policy resolution.

    Example:
    - canonical: ``untagged_vlan=1``, ``tagged_vlans={61}``
    - JTCom: ``mode="trunk"``, ``native_vlan=1``, ``permit_vlans=[1, 61]``

    The empty canonical port state is valid canonical truth. It simply cannot
    be converted directly to JTCom backend state until the policy layer
    resolves it first.
    """
    validate_canonical_port_state(state)
    untagged = _untagged_vlan(state)
    tagged = set(_tagged_vlans(state))

    if untagged is not None and not tagged:
        return {
            "mode": "access",
            "access_vlan": untagged,
            "native_vlan": None,
            "permit_vlans": [],
        }
    if untagged is not None and tagged:
        permit_vlans = sorted(tagged | {untagged})
        return {
            "mode": "trunk",
            "access_vlan": None,
            "native_vlan": untagged,
            "permit_vlans": permit_vlans,
        }
    if untagged is None and tagged:
        raise ValueError(
            "JTCom backend does not support tagged-only port state without an "
            "untagged/native VLAN."
        )
    raise ValueError(
        "Empty canonical port state cannot be converted directly to JTCom backend "
        "state; policy layer must resolve it first."
    )


def jtcom_to_canonical_port_vlan_state(
    backend_state: JTComPortVlanState,
) -> PortMembershipState:
    """Convert JTCom backend trunk/access representation into canonical semantics.

    JTCom trunk readback is backend-oriented:
    - ``native_vlan`` is the untagged VLAN
    - ``permit_vlans`` includes ``native_vlan``

    Canonical truth is derived as:
    - ``untagged_vlan = native_vlan``
    - ``tagged_vlans = set(permit_vlans) - {native_vlan}``

    Example:
    - JTCom: ``mode="trunk"``, ``native_vlan=1``, ``permit_vlans=[1, 61]``
    - canonical: ``untagged_vlan=1``, ``tagged_vlans={61}``
    """
    mode = backend_state["mode"]
    access_vlan = backend_state["access_vlan"]
    native_vlan = backend_state["native_vlan"]
    permit_vlans = sorted(set(backend_state["permit_vlans"]))

    if mode == "access":
        if access_vlan is None:
            raise ValueError("JTCom access state requires access_vlan")
        if native_vlan is not None or permit_vlans:
            raise ValueError(
                "JTCom access state must not carry native_vlan or permit_vlans"
            )
        return make_port_state(untagged_vlan=access_vlan)

    if native_vlan is None:
        raise ValueError("JTCom trunk state requires native_vlan")
    if native_vlan not in permit_vlans:
        raise ValueError(
            f"JTCom trunk state invariant violated: native_vlan={native_vlan} "
            "must be present in permit_vlans"
        )
    # IMPORTANT: permit_vlans != tagged_vlans on JTCom trunk ports.
    # JTCom includes native_vlan inside permit_vlans, while canonical
    # tagged_vlans represents on-wire tagged VLANs only.
    return make_port_state(
        untagged_vlan=native_vlan,
        tagged_vlans=[vlan_id for vlan_id in permit_vlans if vlan_id != native_vlan],
    )


def build_current_per_port_from_vlans(
    vlans: dict[int, VlanEntry],
    known_ports: Iterable[int],
) -> PortMembershipMap:
    """Build canonical current membership from VLAN-centric parsed state.

    The parsed ``VlanEntry`` membership lists are already interpreted as
    canonical on-wire semantics:

    - ``untagged_ports`` -> ``untagged_vlan``
    - ``tagged_ports`` -> ``tagged_vlans``

    This helper does not interpret backend/device trunk fields such as
    ``native_vlan`` or ``permit_vlans``.

    Args:
        vlans: Current VLAN entries, including tagged/untagged port names.
        known_ports: Known 1-based port IDs.  Every listed port is initialized
            even if it has no membership in *vlans*.

    Raises:
        ValueError: If a port name is unparseable or a port is untagged in more
            than one VLAN.
    """
    current: PortMembershipMap = {port_id: make_port_state() for port_id in known_ports}

    for vlan_id, entry in sorted(vlans.items()):
        for port_name in entry.untagged_ports:
            try:
                port_id = port_name_to_id(port_name)
            except ValueError:
                raise ValueError(
                    f"Cannot parse untagged port name {port_name!r} in VLAN {vlan_id}"
                ) from None
            current.setdefault(port_id, make_port_state())
            state = current[port_id]
            existing = _untagged_vlan(state)
            if existing is not None and existing != vlan_id:
                raise ValueError(
                    f"Impossible VLAN state: port_id={port_id} is untagged in "
                    f"both VLAN {existing} and VLAN {vlan_id}"
                )
            state["untagged_vlan"] = vlan_id

        for port_name in entry.tagged_ports:
            try:
                port_id = port_name_to_id(port_name)
            except ValueError:
                raise ValueError(
                    f"Cannot parse tagged port name {port_name!r} in VLAN {vlan_id}"
                ) from None
            current.setdefault(port_id, make_port_state())
            _tagged_vlans(current[port_id]).add(vlan_id)

    return current


def build_current_per_port_from_jtcom_readback(
    port_configs: Iterable[VlanPortConfig],
    known_ports: Iterable[int],
) -> PortMembershipMap:
    """Build canonical current membership from JTCom backend port readback.

    JTCom backend trunk readback is expressed as ``native_vlan`` plus
    ``permit_vlans`` where ``permit_vlans`` includes ``native_vlan``.
    This helper normalizes that backend representation into canonical on-wire
    semantics via :func:`jtcom_to_canonical_port_vlan_state`.
    """
    current: PortMembershipMap = {port_id: make_port_state() for port_id in known_ports}

    for backend_port in port_configs:
        try:
            port_id = port_name_to_id(backend_port.port_name)
        except ValueError:
            raise ValueError(
                f"Cannot parse backend port name {backend_port.port_name!r}"
            ) from None
        backend_mode = backend_port.vlan_type.lower()
        if backend_mode == "access":
            backend_state: JTComPortVlanState = {
                "mode": "access",
                "access_vlan": backend_port.access_vlan,
                "native_vlan": None,
                "permit_vlans": [],
            }
        elif backend_mode == "trunk":
            backend_state = {
                "mode": "trunk",
                "access_vlan": None,
                "native_vlan": backend_port.native_vlan,
                "permit_vlans": list(backend_port.permit_vlans),
            }
        else:
            raise ValueError(
                f"Unsupported JTCom backend VLAN mode {backend_port.vlan_type!r} "
                f"for port {backend_port.port_name!r}"
            )
        current[port_id] = jtcom_to_canonical_port_vlan_state(backend_state)

    return current


def plan_vlan_membership_changes(
    current_per_port: PortMembershipMap,
    vlan_configs: Iterable[VlanConfig],
    *,
    allow_port_mode_change: bool = False,
    allow_untagged_move: bool = False,
    allow_vlan_delete_in_use: bool = False,
    check_mode: bool = False,
) -> VlanMembershipPlan:
    """Apply VLAN membership operations in memory and produce a canonical plan.

    The engine starts from *current_per_port*, applies every present
    :class:`VlanConfig` operation via ``normalized_membership()``, runs Step 4
    policy checks on canonical state, and never talks to the device during
    planning.
    """
    current = copy_membership_map(current_per_port)
    desired = copy_membership_map(current_per_port)
    configs = sorted(vlan_configs, key=lambda item: item.vlan_id)

    for cfg in configs:
        if cfg.state != "present":
            continue
        _apply_vlan_config(desired, cfg)

    normalize_tagged_untagged_consistency(desired)
    delete_in_use_warnings = detect_vlan_delete_in_use_warnings(desired, configs)
    if delete_in_use_warnings and not allow_vlan_delete_in_use and not check_mode:
        raise VlanDeleteInUseError(delete_in_use_warnings)
    if allow_vlan_delete_in_use:
        for warning in delete_in_use_warnings:
            _detach_vlan(desired, int(warning["vlan_id"]))

    untagged_move_warnings = detect_untagged_move_warnings(current, desired)
    if untagged_move_warnings and not allow_untagged_move and not check_mode:
        raise VlanMembershipUntaggedMoveError(untagged_move_warnings)

    # Step 4 policy operates only on canonical desired_per_port.
    # Backend-specific JTCom state is compiled later at the write boundary.
    mode_none_warnings = apply_mode_none_fallback(desired, changed_ports(current, desired))
    changed = changed_ports(current, desired)
    mode_change_warnings = detect_mode_change_warnings(current, desired)
    unsupported_mode_warnings = detect_unsupported_mode_warnings(desired, changed)
    warnings = (
        delete_in_use_warnings
        + untagged_move_warnings
        + mode_none_warnings
        + mode_change_warnings
        + unsupported_mode_warnings
    )

    if unsupported_mode_warnings and not check_mode:
        raise VlanMembershipUnsupportedModeError(unsupported_mode_warnings)
    if mode_change_warnings and not allow_port_mode_change and not check_mode:
        raise VlanMembershipModeChangeError(mode_change_warnings)

    return VlanMembershipPlan(
        current_per_port=current,
        desired_per_port=desired,
        changed_ports=changed,
        changed_vlans=changed_vlans(current, desired),
        warnings=warnings,
    )


def copy_membership_map(source: PortMembershipMap) -> PortMembershipMap:
    """Deep-copy a canonical membership map."""
    return {
        port_id: make_port_state(_untagged_vlan(state), _tagged_vlans(state))
        for port_id, state in sorted(source.items())
    }


def copy_port_state(state: PortMembershipState) -> PortMembershipState:
    """Return a deep copy of one canonical port membership state."""
    return make_port_state(_untagged_vlan(state), _tagged_vlans(state))


def normalize_tagged_untagged_consistency(per_port: PortMembershipMap) -> None:
    """Ensure a port never carries the same VLAN tagged and untagged."""
    for state in per_port.values():
        untagged = _untagged_vlan(state)
        if untagged is not None:
            _tagged_vlans(state).discard(untagged)


def classify_port_mode(port_state: PortMembershipState) -> PortMode:
    """Classify a canonical per-port membership state."""
    if _tagged_vlans(port_state):
        return "trunk"
    if _untagged_vlan(port_state) is not None:
        return "access"
    return "none"


def detect_mode_change_warnings(
    current_per_port: PortMembershipMap,
    desired_per_port: PortMembershipMap,
) -> list[dict[str, Any]]:
    """Return dangerous access/trunk transitions from canonical state."""
    warnings: list[dict[str, Any]] = []
    for port_id in sorted(set(current_per_port) | set(desired_per_port)):
        current_state = current_per_port.get(port_id, make_port_state())
        desired_state = desired_per_port.get(port_id, make_port_state())
        current_mode = classify_port_mode(current_state)
        desired_mode = classify_port_mode(desired_state)
        if (current_mode, desired_mode) in {("access", "trunk"), ("trunk", "access")}:
            warnings.append(
                {
                    "type": "port_mode_change",
                    "entity": "port",
                    "port_id": port_id,
                    "vlan_id": None,
                    "message": (
                        f"Port {port_id} would change mode from {current_mode} to {desired_mode}."
                    ),
                    "current_mode": current_mode,
                    "desired_mode": desired_mode,
                    "hint": _MODE_CHANGE_HINT,
                }
            )
    return warnings


def detect_untagged_move_warnings(
    current_per_port: PortMembershipMap,
    desired_per_port: PortMembershipMap,
) -> list[dict[str, Any]]:
    """Return canonical untagged/native VLAN moves requiring explicit override."""
    warnings: list[dict[str, Any]] = []
    for port_id in sorted(set(current_per_port) | set(desired_per_port)):
        current_vlan = _untagged_vlan(current_per_port.get(port_id, make_port_state()))
        desired_vlan = _untagged_vlan(desired_per_port.get(port_id, make_port_state()))
        if current_vlan is not None and desired_vlan is not None and current_vlan != desired_vlan:
            warnings.append(
                {
                    "type": "untagged_move",
                    "entity": "port",
                    "port_id": port_id,
                    "vlan_id": None,
                    "message": (
                        f"Port {port_id} would move untagged VLAN from "
                        f"{current_vlan} to {desired_vlan}."
                    ),
                    "current_untagged_vlan": current_vlan,
                    "desired_untagged_vlan": desired_vlan,
                    "hint": _UNTAGGED_MOVE_HINT,
                }
            )
    return warnings


def detect_vlan_delete_in_use_warnings(
    desired_per_port: PortMembershipMap,
    vlan_configs: Iterable[VlanConfig],
) -> list[dict[str, Any]]:
    """Return absent VLANs still referenced in effective canonical state."""
    absent_vlans = sorted({cfg.vlan_id for cfg in vlan_configs if cfg.state == "absent"})
    warnings: list[dict[str, Any]] = []
    for vlan_id in absent_vlans:
        tagged_ports: list[int] = []
        untagged_ports: list[int] = []
        for port_id, state in sorted(desired_per_port.items()):
            if vlan_id in _tagged_vlans(state):
                tagged_ports.append(port_id)
            if _untagged_vlan(state) == vlan_id:
                untagged_ports.append(port_id)
        if tagged_ports or untagged_ports:
            warnings.append(
                {
                    "type": "vlan_delete_in_use",
                    "entity": "vlan",
                    "port_id": None,
                    "vlan_id": vlan_id,
                    "message": f"VLAN {vlan_id} is still in use.",
                    "affected_ports_tagged": tagged_ports,
                    "affected_ports_untagged": untagged_ports,
                    "hint": _VLAN_DELETE_IN_USE_HINT,
                }
            )
    return warnings


def apply_mode_none_fallback(
    desired_per_port: PortMembershipMap,
    candidate_port_ids: Iterable[int],
) -> list[dict[str, Any]]:
    """Map canonical empty port state to VLAN 1 fallback and return warnings."""
    warnings: list[dict[str, Any]] = []
    for port_id in sorted(set(candidate_port_ids)):
        state = desired_per_port.get(port_id, make_port_state())
        if classify_port_mode(state) != "none":
            continue
        desired_per_port[port_id] = state
        state["untagged_vlan"] = DEFAULT_FALLBACK_VLAN_ID
        _tagged_vlans(state).clear()
        warnings.append(
            {
                "type": "mode_none_mapped_to_vlan1",
                "entity": "port",
                "port_id": port_id,
                "vlan_id": DEFAULT_FALLBACK_VLAN_ID,
                "message": (
                    f"Port {port_id} would otherwise have no VLAN membership and was "
                    f"mapped to access VLAN {DEFAULT_FALLBACK_VLAN_ID}."
                ),
                "mapped_vlan": DEFAULT_FALLBACK_VLAN_ID,
                "reason": "policy_default_vlan1_fallback",
                "hint": _NONE_MODE_HINT,
            }
        )
    return warnings


def detect_unsupported_mode_warnings(
    desired_per_port: PortMembershipMap,
    changed_port_ids: Iterable[int],
) -> list[dict[str, Any]]:
    """Return changed ports whose canonical desired state cannot be compiled."""
    warnings: list[dict[str, Any]] = []
    for port_id in sorted(changed_port_ids):
        desired_state = desired_per_port[port_id]
        if classify_port_mode(desired_state) == "none":
            warnings.append(
                {
                    "type": "unsupported_vlan_port_mode",
                    "entity": "port",
                    "port_id": port_id,
                    "vlan_id": None,
                    "message": (
                        f"Port {port_id} resolved to unsupported VLAN mode "
                        "'none'."
                    ),
                    "desired_mode": "none",
                    "desired_state": serialize_port_state(desired_state),
                    "hint": _NONE_MODE_HINT,
                }
            )
    return warnings


def _detach_vlan(per_port: PortMembershipMap, vlan_id: int) -> None:
    for state in per_port.values():
        _tagged_vlans(state).discard(vlan_id)
        if _untagged_vlan(state) == vlan_id:
            state["untagged_vlan"] = None


def changed_ports(
    current_per_port: PortMembershipMap,
    desired_per_port: PortMembershipMap,
) -> list[int]:
    """Return 1-based ports whose membership changed."""
    ports: list[int] = []
    for port_id in sorted(set(current_per_port) | set(desired_per_port)):
        if not _same_state(
            current_per_port.get(port_id, make_port_state()),
            desired_per_port.get(port_id, make_port_state()),
        ):
            ports.append(port_id)
    return ports


def changed_vlans(
    current_per_port: PortMembershipMap,
    desired_per_port: PortMembershipMap,
) -> list[int]:
    """Return VLAN IDs touched by a membership diff."""
    vlans: set[int] = set()
    for port_id in sorted(set(current_per_port) | set(desired_per_port)):
        current_state = current_per_port.get(port_id, make_port_state())
        desired_state = desired_per_port.get(port_id, make_port_state())
        vlans.update(_tagged_vlans(current_state) ^ _tagged_vlans(desired_state))
        cur_untagged = _untagged_vlan(current_state)
        des_untagged = _untagged_vlan(desired_state)
        if cur_untagged != des_untagged:
            if cur_untagged is not None:
                vlans.add(cur_untagged)
            if des_untagged is not None:
                vlans.add(des_untagged)
    return sorted(vlans)


def serialize_membership_map(per_port: PortMembershipMap) -> dict[int, dict[str, Any]]:
    """Return a JSON-friendly representation of a membership map."""
    return {
        port_id: serialize_port_state(state)
        for port_id, state in sorted(per_port.items())
    }


def serialize_port_state(state: PortMembershipState) -> dict[str, Any]:
    """Return one canonical port membership state as JSON-friendly data."""
    return {
        "untagged_vlan": _untagged_vlan(state),
        "tagged_vlans": sorted(_tagged_vlans(state)),
    }


def diff_membership_maps(
    current_per_port: PortMembershipMap,
    desired_per_port: PortMembershipMap,
) -> dict[str, Any]:
    """Return a JSON-friendly per-port membership diff."""
    diffs: dict[str, Any] = {}
    for port_id in changed_ports(current_per_port, desired_per_port):
        current_state = current_per_port.get(port_id, make_port_state())
        desired_state = desired_per_port.get(port_id, make_port_state())
        diffs[str(port_id)] = {
            "from": {
                "untagged_vlan": _untagged_vlan(current_state),
                "tagged_vlans": sorted(_tagged_vlans(current_state)),
            },
            "to": {
                "untagged_vlan": _untagged_vlan(desired_state),
                "tagged_vlans": sorted(_tagged_vlans(desired_state)),
            },
        }
    return diffs


def apply_vlan_membership_config(
    current_tagged: NullablePortSet,
    current_untagged: NullablePortSet,
    cfg: VlanConfig,
) -> tuple[NullablePortSet, NullablePortSet]:
    """Apply one VLAN config to current VLAN-centric port sets.

    ``None`` current values are preserved as an unknown baseline when the
    desired operation is add/remove.  A resulting diff can therefore report an
    unknown target rather than fabricating ``[]``.
    """
    membership = cfg.normalized_membership()
    new_tagged = apply_vlan_membership_side(current_tagged, membership["tagged"])
    new_untagged = apply_vlan_membership_side(current_untagged, membership["untagged"])
    if new_tagged is not None and new_untagged is not None:
        new_tagged.difference_update(new_untagged)
    return new_tagged, new_untagged


def apply_vlan_membership_side(
    current: NullablePortSet,
    operation: dict[str, set[int] | None],
) -> NullablePortSet:
    """Apply set/add/remove to one VLAN membership side.

    If *current* is ``None`` and the operation is additive/subtractive, the
    resulting full membership remains unknown.  Explicit ``set`` always yields
    a concrete set, including an explicit empty set.
    """
    explicit_set = operation["set"]
    if explicit_set is not None:
        return set(explicit_set)

    add = operation["add"] or set()
    remove = operation["remove"] or set()
    if current is None:
        return None

    result = set(current)
    result.update(add)
    result.difference_update(remove)
    return result


def _apply_vlan_config(desired_per_port: PortMembershipMap, cfg: VlanConfig) -> None:
    membership = cfg.normalized_membership()
    tagged = membership["tagged"]
    untagged = membership["untagged"]

    tagged_set = tagged["set"]
    if tagged_set is not None:
        for state in desired_per_port.values():
            _tagged_vlans(state).discard(cfg.vlan_id)
        for port_id in tagged_set:
            _require_known_port(desired_per_port, port_id)
            _tagged_vlans(desired_per_port[port_id]).add(cfg.vlan_id)
    else:
        for port_id in tagged["add"] or set():
            _require_known_port(desired_per_port, port_id)
            _tagged_vlans(desired_per_port[port_id]).add(cfg.vlan_id)
        for port_id in tagged["remove"] or set():
            _require_known_port(desired_per_port, port_id)
            _tagged_vlans(desired_per_port[port_id]).discard(cfg.vlan_id)

    untagged_set = untagged["set"]
    if untagged_set is not None:
        for state in desired_per_port.values():
            if _untagged_vlan(state) == cfg.vlan_id:
                state["untagged_vlan"] = None
        for port_id in untagged_set:
            _require_known_port(desired_per_port, port_id)
            desired_per_port[port_id]["untagged_vlan"] = cfg.vlan_id
    else:
        for port_id in untagged["add"] or set():
            _require_known_port(desired_per_port, port_id)
            desired_per_port[port_id]["untagged_vlan"] = cfg.vlan_id
        for port_id in untagged["remove"] or set():
            _require_known_port(desired_per_port, port_id)
            if _untagged_vlan(desired_per_port[port_id]) == cfg.vlan_id:
                desired_per_port[port_id]["untagged_vlan"] = None


def _same_state(left: PortMembershipState, right: PortMembershipState) -> bool:
    return _untagged_vlan(left) == _untagged_vlan(right) and _tagged_vlans(
        left
    ) == _tagged_vlans(right)


def _require_known_port(per_port: PortMembershipMap, port_id: int) -> None:
    if port_id not in per_port:
        raise ValueError(f"Unknown VLAN membership port_id={port_id}")


def _untagged_vlan(state: PortMembershipState) -> int | None:
    value = state["untagged_vlan"]
    if value is not None and not isinstance(value, int):
        raise TypeError(f"untagged_vlan must be int or None, got {type(value)!r}")
    return value


def _tagged_vlans(state: PortMembershipState) -> set[int]:
    value = state["tagged_vlans"]
    if not isinstance(value, set):
        raise TypeError(f"tagged_vlans must be set[int], got {type(value)!r}")
    return value


def port_name_to_id(name: str) -> int:
    """Convert a JTCom-style port label into the canonical 1-based port ID.

    This helper converts labels like ``"Port 5"`` into the project-standard
    1-based port IDs used throughout the canonical/domain model. Callers must
    use this helper instead of ad hoc parsing.
    """
    parts = name.rsplit(" ", 1)
    if len(parts) == 2 and parts[0] == "Port" and parts[1].isdigit():
        return int(parts[1])
    raise ValueError(f"Invalid JTCom port name {name!r}; expected 'Port N'")
