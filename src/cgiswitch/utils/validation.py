"""Validate desired port references against the observed device inventory."""

from __future__ import annotations

from cgiswitch.model.config import DeviceConfig
from cgiswitch.model.port import PortSettings


def validate_desired_ports(desired: DeviceConfig, current_ports: list[PortSettings]) -> None:
    """Reject unknown references before normalization or planning can discard them."""
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
            vlan.tagged_ports,
            vlan.untagged_ports,
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
