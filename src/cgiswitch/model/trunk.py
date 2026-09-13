"""Typed model for trunk/LAG data."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TrunkEntry:
    """Represents a port-channel / LAG trunk group.

    Attributes:
        trunk_id: Trunk group identifier.
        member_ports: List of member port identifiers.
        lacp_enabled: Whether LACP is active on this trunk.
        active: Whether the trunk is operationally active.
    """

    trunk_id: str
    member_ports: list[str] = field(default_factory=list)
    lacp_enabled: bool = False
    active: bool = False
