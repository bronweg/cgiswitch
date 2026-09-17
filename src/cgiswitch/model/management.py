"""Typed model for the switch management network configuration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ManagementNetworkState:
    """Management network state read from the switch IP settings page."""

    dhcp_enabled: bool
    ip_address: str
    subnet_mask: str
    gateway: str
