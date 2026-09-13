"""Normalization helpers for device configuration models.

Normalization produces a stable, canonical form suitable for reliable diff
comparisons: sorted port lists, no duplicates, canonical speed/duplex tokens.
"""

from __future__ import annotations

from dataclasses import replace

from cgiswitch.model.config import DeviceConfig
from cgiswitch.model.port import PortConfig
from cgiswitch.model.vlan import VlanConfig
from cgiswitch.vendor.jtcom.mappings import SPEED_DUPLEX_ALIASES, SPEED_DUPLEX_CANONICAL


def normalize_vlan_config(cfg: VlanConfig) -> VlanConfig:
    """Return a normalized copy of *cfg*.

    Normalization rules:

    - Deduplicate and sort ``tagged_ports`` and ``untagged_ports`` if they are lists.
    - If a port appears in both lists, it is removed from ``tagged_ports`` (untagged wins).
    - ``None`` values for port lists are preserved.
    """
    tagged = None if cfg.tagged_ports is None else sorted(set(cfg.tagged_ports))
    untagged = None if cfg.untagged_ports is None else sorted(set(cfg.untagged_ports))

    if tagged is not None and untagged is not None:
        untagged_set = set(untagged)
        tagged = [p for p in tagged if p not in untagged_set]

    return replace(cfg, tagged_ports=tagged, untagged_ports=untagged)


def normalize_port_config(cfg: PortConfig) -> PortConfig:
    """Return a normalized copy of *cfg*.

    Normalization rules:

    - Canonicalize ``speed_duplex`` via
      :data:`~cgiswitch.vendor.jtcom.mappings.SPEED_DUPLEX_ALIASES`.
    - Unknown tokens are left unchanged.
    - ``None`` speed_duplex is left unchanged.
    """
    trunk_add = _normalize_optional_int_list(cfg.trunk_add_vlans)
    trunk_remove = _normalize_optional_int_list(cfg.trunk_remove_vlans)
    trunk_set = _normalize_optional_int_list(cfg.trunk_set_vlans)
    normalized = cfg
    if (
        trunk_add != cfg.trunk_add_vlans
        or trunk_remove != cfg.trunk_remove_vlans
        or trunk_set != cfg.trunk_set_vlans
    ):
        normalized = replace(
            cfg,
            trunk_add_vlans=trunk_add,
            trunk_remove_vlans=trunk_remove,
            trunk_set_vlans=trunk_set,
        )

    if normalized.speed_duplex is None:
        return normalized
    if normalized.speed_duplex in SPEED_DUPLEX_CANONICAL:
        return normalized
    canonical = SPEED_DUPLEX_ALIASES.get(normalized.speed_duplex.lower())
    if canonical is not None:
        return replace(normalized, speed_duplex=canonical)
    return normalized


def _normalize_optional_int_list(values: list[int] | None) -> list[int] | None:
    if values is None:
        return None
    return sorted(set(values))


def normalize_device_config(cfg: DeviceConfig) -> DeviceConfig:
    """Return a fully normalized copy of *cfg*.

    Applies :func:`normalize_vlan_config` to each VLAN and
    :func:`normalize_port_config` to each port.  Both dicts are rebuilt
    with keys sorted ascending.
    """
    vlans = {vid: normalize_vlan_config(v) for vid, v in sorted(cfg.vlans.items())}
    ports = {pid: normalize_port_config(p) for pid, p in sorted(cfg.ports.items())}
    return DeviceConfig(vlans=vlans, ports=ports, metadata=dict(cfg.metadata))
