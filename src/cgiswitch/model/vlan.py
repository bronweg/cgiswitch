"""Typed model for VLAN data."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


def _validate_port_list(port_list: list[int] | None, field_name: str) -> None:
    """Helper to validate port lists."""
    if port_list is None:
        return
    for port in port_list:
        if not isinstance(port, int) or port < 1:
            raise ValueError(
                f"Invalid port '{port}' in '{field_name}'. Ports must be 1-based positive integers."
            )


def _normalize_op_list(op_list: list[int] | None, field_name: str) -> set[int]:
    """Helper to normalize an operation list to a set of non-negative integers."""
    if op_list is None:
        return set()
    _validate_port_list(op_list, field_name)
    return set(op_list)


@dataclass
class VlanEntry:
    """Represents a single VLAN configuration entry.

    Attributes:
        vlan_id: 802.1Q VLAN identifier (1-4094).
        name: Human-readable VLAN name.
        tagged_ports: Ports that carry this VLAN tagged (trunk ports).
        untagged_ports: Ports that carry this VLAN untagged (access ports).
        active: Whether the VLAN is administratively active.
    """

    vlan_id: int
    name: str
    tagged_ports: list[str] = field(default_factory=list)
    untagged_ports: list[str] = field(default_factory=list)
    active: bool = True

    def __post_init__(self) -> None:
        if not 1 <= self.vlan_id <= 4094:
            raise ValueError(f"vlan_id must be 1-4094, got {self.vlan_id}")


@dataclass
class VlanPortConfig:
    """Per-port VLAN configuration parsed from the port-based VLAN page.

    Attributes:
        port_name: Human-readable port name (e.g. "Port 1").
        vlan_type: VLAN mode — "Access" or "Trunk".
        access_vlan: Access VLAN ID (Access mode only; None if not set).
        native_vlan: Native/untagged VLAN ID (Trunk mode only; None if not set).
        permit_vlans: List of tagged VLAN IDs allowed on this trunk port.
    """

    port_name: str
    vlan_type: str
    access_vlan: int | None = None
    native_vlan: int | None = None
    permit_vlans: list[int] = field(default_factory=list)


@dataclass
class VlanConfig:
    """Desired VLAN state used as input to :func:`plan_vlan_changes`.

    The class handles two types of membership fields:
    1. Legacy fields (`tagged_ports`, `untagged_ports`): These are for backward
       compatibility. When provided (even as an empty list), they imply a full
       replacement of the port membership. `None` means the field is unspecified.
    2. New operation fields (`add`, `remove`, `set`): These provide fine-grained
       control over membership changes. `add` is additive, `remove` is
       subtractive, and `set` is an explicit replacement.

    These field types are mutually exclusive for a given membership type (tagged
    or untagged).

    Attributes:
        vlan_id: 802.1Q VLAN identifier (1-4094).
        name: Human-readable VLAN name; ``None`` means "do not change".
        state: ``"present"`` to create/update this VLAN; ``"absent"`` to delete it.

        tagged_ports: (Legacy) Replace tagged ports with this list of 1-based port IDs.
        untagged_ports: (Legacy) Replace untagged ports with this list of 1-based port IDs.

        tagged_add: Add these 1-based port IDs to tagged membership.
        tagged_remove: Remove these 1-based port IDs from tagged membership.
        tagged_set: Explicitly set tagged membership to these 1-based port IDs.
        untagged_add: Add these 1-based port IDs to untagged membership.
        untagged_remove: Remove these 1-based port IDs from untagged membership.
        untagged_set: Explicitly set untagged membership to these 1-based port IDs.
    """

    vlan_id: int
    name: str | None = None
    state: Literal["present", "absent"] = "present"

    # Legacy backward-compatible fields (full replacement)
    tagged_ports: list[int] | None = None
    untagged_ports: list[int] | None = None

    # New canonical membership operation fields
    tagged_add: list[int] | None = None
    tagged_remove: list[int] | None = None
    tagged_set: list[int] | None = None

    untagged_add: list[int] | None = None
    untagged_remove: list[int] | None = None
    untagged_set: list[int] | None = None

    def __post_init__(self) -> None:
        # VLAN ID validation
        if not 1 <= self.vlan_id <= 4094:
            raise ValueError(f"vlan_id must be 1-4094, got {self.vlan_id}")

        # State validation
        if self.state not in ("present", "absent"):
            raise ValueError(f"state must be 'present' or 'absent', got '{self.state}'")

        # Validate port values are valid integers
        port_fields = [
            ("tagged_ports", self.tagged_ports),
            ("untagged_ports", self.untagged_ports),
            ("tagged_add", self.tagged_add),
            ("tagged_remove", self.tagged_remove),
            ("tagged_set", self.tagged_set),
            ("untagged_add", self.untagged_add),
            ("untagged_remove", self.untagged_remove),
            ("untagged_set", self.untagged_set),
        ]
        for name, ports in port_fields:
            _validate_port_list(ports, name)

        # Conflict validation for tagged fields
        if self.tagged_set is not None and (
            self.tagged_add is not None or self.tagged_remove is not None
        ):
            raise ValueError("tagged_set cannot be combined with tagged_add or tagged_remove")
        if self.tagged_ports is not None and (
            self.tagged_add is not None
            or self.tagged_remove is not None
            or self.tagged_set is not None
        ):
            raise ValueError(
                "legacy tagged_ports cannot be combined with tagged_add, "
                "tagged_remove, or tagged_set"
            )

        # Conflict validation for untagged fields
        if self.untagged_set is not None and (
            self.untagged_add is not None or self.untagged_remove is not None
        ):
            raise ValueError("untagged_set cannot be combined with untagged_add or untagged_remove")
        if self.untagged_ports is not None and (
            self.untagged_add is not None
            or self.untagged_remove is not None
            or self.untagged_set is not None
        ):
            raise ValueError(
                "legacy untagged_ports cannot be combined with untagged_add, "
                "untagged_remove, or untagged_set"
            )

    def normalized_membership(self) -> dict[str, dict[str, set[int] | None]]:
        """Returns a canonical representation of VLAN membership operations.

        This method normalizes legacy fields (tagged_ports, untagged_ports) and
        new explicit operation fields (add, remove, set) into a consistent
        dictionary structure.

        - A provided legacy field (e.g., `tagged_ports=[]`) implies replacement
          and results in `{"set": set()}`.
        - Omitted fields result in `{"set": None}`.

        Returns:
            A dictionary with 'tagged' and 'untagged' keys, each containing
            'add', 'remove', and 'set' operations as sets of port indices.
            'set' can be None if no replacement is requested.
        """
        normalized: dict[str, dict[str, set[int] | None]] = {
            "tagged": {"add": set(), "remove": set(), "set": None},
            "untagged": {"add": set(), "remove": set(), "set": None},
        }

        # Tagged side
        if self.tagged_set is not None:
            normalized["tagged"]["set"] = _normalize_op_list(self.tagged_set, "tagged_set")
        elif self.tagged_ports is not None:
            normalized["tagged"]["set"] = _normalize_op_list(self.tagged_ports, "tagged_ports")
        else:
            normalized["tagged"]["add"] = _normalize_op_list(self.tagged_add, "tagged_add")
            normalized["tagged"]["remove"] = _normalize_op_list(self.tagged_remove, "tagged_remove")

        # Untagged side
        if self.untagged_set is not None:
            normalized["untagged"]["set"] = _normalize_op_list(self.untagged_set, "untagged_set")
        elif self.untagged_ports is not None:
            normalized["untagged"]["set"] = _normalize_op_list(
                self.untagged_ports, "untagged_ports"
            )
        else:
            normalized["untagged"]["add"] = _normalize_op_list(self.untagged_add, "untagged_add")
            normalized["untagged"]["remove"] = _normalize_op_list(
                self.untagged_remove, "untagged_remove"
            )

        return normalized


@dataclass
class VlanChangeSet:
    """A set of planned VLAN changes produced by :func:`plan_vlan_changes`.

    Attributes:
        create: VLANs that exist in *desired* but not in *current*.
        update: VLANs present in both where name or membership differs.
        delete: VLAN IDs present in *current* but not in *desired*
                VLAN 1 is never included.
    """

    create: list[VlanConfig] = field(default_factory=list)
    update: list[VlanConfig] = field(default_factory=list)
    delete: list[int] = field(default_factory=list)
