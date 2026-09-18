"""Validate desired configuration structure and port references."""

from __future__ import annotations

from cgiswitch.model.config import DeviceConfig
from cgiswitch.model.port import PortSettings


def validate_desired_config(desired: DeviceConfig, current_ports: list[PortSettings]) -> None:
    """Reject mismatched port/VLAN keys and unknown port references before planning."""
    for vlan_id, vlan_config in sorted(desired.vlans.items()):
        if vlan_id != vlan_config.vlan_id:
            raise ValueError(
                f"vlans[{vlan_id}]: mismatched vlan_id={vlan_config.vlan_id}; "
                "dictionary key must match vlan_id"
            )
    known = {port.port_id for port in current_ports}
    referenced = set(desired.ports)
    for port_id, config in sorted(desired.ports.items()):
        if port_id != config.port_id:
            raise ValueError(
                f"ports[{port_id}]: mismatched port_id={config.port_id}; "
                "dictionary key must match port_id"
            )
    for vlan in desired.vlans.values():
        for ports in (
            vlan.tagged_add,
            vlan.tagged_remove,
            vlan.tagged_set,
            vlan.untagged_add,
            vlan.untagged_remove,
            vlan.untagged_set,
        ):
            if ports is not None:
                referenced.update(ports)
    unknown = referenced - known
    if unknown:
        raise ValueError(
            f"Invalid desired configuration: unknown ports: {sorted(unknown)}; "
            f"known ports: {sorted(known)}"
        )
