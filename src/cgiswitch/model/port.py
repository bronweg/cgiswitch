"""Typed models for port/interface data."""

from __future__ import annotations

from dataclasses import dataclass, field


def _validate_vlan_id(vlan_id: int | None, field_name: str) -> None:
    """Validate an optional 802.1Q VLAN ID."""
    if vlan_id is None:
        return
    if not isinstance(vlan_id, int) or not 1 <= vlan_id <= 4094:
        raise ValueError(f"{field_name} must be 1-4094, got {vlan_id}")


def _validate_vlan_list(vlan_list: list[int] | None, field_name: str) -> None:
    """Validate an optional list of 802.1Q VLAN IDs."""
    if vlan_list is None:
        return
    for vlan_id in vlan_list:
        if not isinstance(vlan_id, int) or not 1 <= vlan_id <= 4094:
            raise ValueError(
                f"Invalid VLAN '{vlan_id}' in '{field_name}'. VLAN IDs must be 1-4094."
            )


@dataclass
class PortSettings:
    """Administrative configuration for a single switch port.

    Attributes:
        port_id: 1-based port number as reported by the switch.
        name: Human-readable port name (e.g. ``"Port 1"``).
        admin_up: ``True`` if enabled, ``False`` if disabled, ``None`` if unknown.
        speed_duplex: Configured speed/duplex string (e.g. ``"Auto"``,
            ``"1000M/Full"``), or ``None`` if unknown.
        flow_control: ``True`` if flow control is enabled, ``None`` if unknown.
    """

    port_id: int
    name: str
    admin_up: bool | None
    speed_duplex: str | None = None
    flow_control: bool | None = None

    def __post_init__(self) -> None:
        if self.port_id < 1:
            raise ValueError(f"port_id must be >= 1, got {self.port_id}")


@dataclass
class PortOperStatus:
    """Operational status for a single switch port.

    Attributes:
        port_id: 1-based port number matching :attr:`PortSettings.port_id`.
        link_up: ``True`` if the link is up, ``False`` if down, ``None`` if
            the state could not be determined.
        negotiated_speed_mbps: Negotiated link speed in Mbps
            (e.g. 10, 100, 1000, 10000), or ``None`` if link is down.
        duplex: Negotiated duplex: ``"full"``, ``"half"``, or ``None``.
    """

    port_id: int
    link_up: bool | None = None
    negotiated_speed_mbps: int | None = None
    duplex: str | None = None


@dataclass
class PortConfig:
    """Desired configuration for a single switch port.

    Used as input to :func:`~cgiswitch.utils.port_diff.plan_port_changes`.
    Any field set to ``None`` means "do not change this attribute".

    Attributes:
        port_id: 1-based port number, matching :attr:`PortSettings.port_id`.
        admin_up: ``True`` to enable the port, ``False`` to disable it,
            ``None`` to leave unchanged.
        speed_duplex: Configured speed/duplex token as shown in the switch UI
            (e.g. ``"Auto"``, ``"1000M/Full"``), or ``None`` to leave unchanged.
        flow_control: ``True`` to enable flow control, ``False`` to disable,
            ``None`` to leave unchanged.
        access_vlan: Assign this port as untagged member of the VLAN. This is
            translated to VLAN-centric ``untagged_add`` by the merge layer.
        native_vlan: Assign this port's trunk native VLAN. This is translated
            to VLAN-centric ``untagged_add`` by the merge layer.
        trunk_add_vlans: Add this port as tagged member of these VLANs.
        trunk_remove_vlans: Remove this port from tagged membership of these VLANs.
        trunk_set_vlans: Set this port's tagged VLAN membership to exactly these VLANs.
    """

    port_id: int
    admin_up: bool | None = None
    speed_duplex: str | None = None
    flow_control: bool | None = None
    access_vlan: int | None = None
    native_vlan: int | None = None
    trunk_add_vlans: list[int] | None = None
    trunk_remove_vlans: list[int] | None = None
    trunk_set_vlans: list[int] | None = None

    def __post_init__(self) -> None:
        if self.port_id < 1:
            raise ValueError(f"port_id must be >= 1, got {self.port_id}")
        _validate_vlan_id(self.access_vlan, "access_vlan")
        _validate_vlan_id(self.native_vlan, "native_vlan")
        _validate_vlan_list(self.trunk_add_vlans, "trunk_add_vlans")
        _validate_vlan_list(self.trunk_remove_vlans, "trunk_remove_vlans")
        _validate_vlan_list(self.trunk_set_vlans, "trunk_set_vlans")
        if self.trunk_set_vlans is not None and (
            self.trunk_add_vlans is not None or self.trunk_remove_vlans is not None
        ):
            raise ValueError(
                "trunk_set_vlans cannot be combined with trunk_add_vlans or trunk_remove_vlans"
            )


@dataclass
class PortChangeSet:
    """A set of planned port configuration changes.

    Attributes:
        update: Ports whose configuration differs from the desired state.
            Sorted ascending by :attr:`PortConfig.port_id`.
    """

    update: list[PortConfig] = field(default_factory=list)
