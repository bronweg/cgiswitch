"""Typed model for the switch management network configuration."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass


@dataclass(frozen=True)
class ManagementNetworkState:
    """Read-only static or DHCP state from the switch IP settings page."""

    dhcp_enabled: bool
    ip_address: str
    subnet_mask: str
    gateway: str


@dataclass(frozen=True)
class ManagementNetworkConfig:
    """Desired static IPv4 management configuration for bootstrap.

    The address, prefix, and gateway are validated as one subnet. DHCP is not
    represented by this desired input model.
    """

    address: str
    prefix_length: int
    gateway: str

    def __post_init__(self) -> None:
        """Validate the address, prefix, and gateway as a single subnet."""
        if not isinstance(self.address, str):
            raise ValueError("address must be an IPv4 address string")
        if (
            isinstance(self.prefix_length, bool)
            or not isinstance(self.prefix_length, int)
            or not 0 <= self.prefix_length <= 32
        ):
            raise ValueError("prefix_length must be an integer from 0 through 32")
        if not isinstance(self.gateway, str):
            raise ValueError("gateway must be an IPv4 address string")

        try:
            address = ipaddress.IPv4Address(self.address)
        except (ipaddress.AddressValueError, ValueError) as exc:
            raise ValueError("address must be an IPv4 address") from exc
        if address.is_multicast:
            raise ValueError("address must not be multicast")
        if address.is_unspecified:
            raise ValueError("address must not be unspecified")

        try:
            gateway = ipaddress.IPv4Address(self.gateway)
        except (ipaddress.AddressValueError, ValueError) as exc:
            raise ValueError("gateway must be an IPv4 address") from exc

        network = ipaddress.IPv4Network((address, self.prefix_length), strict=False)
        if gateway not in network:
            raise ValueError("gateway must be in the management address subnet")

    def as_state(self) -> ManagementNetworkState:
        """Return the corresponding static management network state."""
        network = ipaddress.IPv4Network((self.address, self.prefix_length), strict=False)
        return ManagementNetworkState(
            dhcp_enabled=False,
            ip_address=self.address,
            subnet_mask=str(network.netmask),
            gateway=self.gateway,
        )
