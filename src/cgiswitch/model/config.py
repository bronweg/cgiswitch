"""Canonical device configuration model for cgiswitch."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from cgiswitch.model.port import PortConfig, PortSettings
from cgiswitch.model.vlan import VlanConfig, VlanEntry
from cgiswitch.utils.vlan_membership import port_name_to_id

logger = logging.getLogger(__name__)


@dataclass
class DeviceConfig:
    """Full device configuration snapshot: VLANs + ports.

    Attributes:
        vlans: Mapping of VLAN ID to :class:`~cgiswitch.model.vlan.VlanConfig`.
        ports: Mapping of 1-based port ID to :class:`~cgiswitch.model.port.PortConfig`.
        metadata: Arbitrary string key-value metadata (e.g. capture timestamp).
    """

    vlans: dict[int, VlanConfig] = field(default_factory=dict)
    ports: dict[int, PortConfig] = field(default_factory=dict)
    metadata: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_current(
        cls,
        current_vlans: dict[int, VlanEntry],
        current_ports: list[PortSettings],
    ) -> DeviceConfig:
        """Build a :class:`DeviceConfig` from the switch current state.

        Converts :class:`~cgiswitch.model.vlan.VlanEntry` port name strings
        (``"Port N"``) to the same 1-based port IDs used everywhere in the
        project, including :class:`~cgiswitch.model.vlan.VlanConfig`.
        ``VlanEntry`` membership is already interpreted canonically here:
        tagged ports mean on-wire tagged membership and untagged ports mean the
        single on-wire untagged VLAN.

        Args:
            current_vlans: VLAN ID to :class:`VlanEntry` mapping from the parser.
            current_ports: List of :class:`PortSettings` from the port parser.

        Returns:
            A fully-populated :class:`DeviceConfig`.
        """
        vlans: dict[int, VlanConfig] = {}
        for vid, entry in current_vlans.items():
            tagged: list[int] = []
            for name in entry.tagged_ports:
                try:
                    port_id = port_name_to_id(name)
                    tagged.append(port_id)
                except ValueError:
                    logger.warning("Skipping unparseable tagged port name %r in VLAN %d", name, vid)
            untagged: list[int] = []
            for name in entry.untagged_ports:
                try:
                    port_id = port_name_to_id(name)
                    untagged.append(port_id)
                except ValueError:
                    logger.warning(
                        "Skipping unparseable untagged port name %r in VLAN %d", name, vid
                    )
            vlans[vid] = VlanConfig(
                vlan_id=vid,
                name=entry.name,
                tagged_set=sorted(tagged),
                untagged_set=sorted(untagged),
            )

        ports: dict[int, PortConfig] = {}
        for s in current_ports:
            ports[s.port_id] = PortConfig(
                port_id=s.port_id,
                admin_up=s.admin_up,
                speed_duplex=s.speed_duplex,
                flow_control=s.flow_control,
            )

        return cls(vlans=vlans, ports=ports)
