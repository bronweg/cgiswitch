"""Typed model for device information parsed from info.cgi."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DeviceInfo:
    """General device information parsed from the switch system page.

    Attributes:
        mac_address: Base MAC address of the switch (e.g. ``A8:F7:E0:12:34:56``).
        serial_number: Serial number, if present in the page.
        firmware_version: Firmware / software version string, if present.
        model: Device model string, if present.
        ip_address: Management IP address, if present.
        uptime: Raw uptime string as returned by the switch
                (e.g. ``"7 days, 03:42:11"``).
    """

    mac_address: str
    serial_number: str | None = None
    firmware_version: str | None = None
    model: str | None = None
    ip_address: str | None = None
    uptime: str | None = None
