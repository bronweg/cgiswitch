"""Strong device identity checks shared by internal management transitions."""

from __future__ import annotations

import re
from dataclasses import dataclass

from cgiswitch.model.device import DeviceInfo


@dataclass(frozen=True)
class DeviceIdentity:
    """Observed physical identity; a model name is never an identity anchor."""

    mac_address: str
    serial_number: str | None

    @classmethod
    def from_device(cls, device: DeviceInfo) -> DeviceIdentity:
        mac = device.mac_address
        if not isinstance(mac, str) or not re.fullmatch(
            r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}', mac,
        ):
            raise ValueError('Device did not provide an unambiguous MAC address')
        if mac.lower() == '00:00:00:00:00:00' or int(mac[:2], 16) & 1:
            raise ValueError('Device did not provide a unicast MAC address')
        serial = device.serial_number
        if serial is not None and (not isinstance(serial, str) or not serial.strip()):
            raise ValueError('Device supplied an invalid serial number')
        return cls(mac.lower(), serial)

    def verify(self, device: DeviceInfo) -> None:
        observed = self.from_device(device)
        if observed.mac_address != self.mac_address or (
            self.serial_number is not None and observed.serial_number != self.serial_number
        ):
            raise ValueError('Endpoint identity does not match the original device')
