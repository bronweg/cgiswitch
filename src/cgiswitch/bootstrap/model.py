"""Typed public inputs for explicit, identity-bound bootstrap."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from cgiswitch.bootstrap.identity import DeviceIdentity
from cgiswitch.bootstrap.network import validate_endpoint
from cgiswitch.client.management_contracts import build_user_account_payload
from cgiswitch.client.session import JTComCredentials
from cgiswitch.model.management import ManagementNetworkConfig


@dataclass(frozen=True)
class BootstrapConfig:
    """Bootstrap a known device without managing the controller's network."""

    factory_url: str
    target_url: str
    username: str
    factory_password: str = field(repr=False)
    target_password: str = field(repr=False)
    management: ManagementNetworkConfig
    expected_mac: str | None = None
    expected_serial: str | None = None
    timeout_s: float = 5.0
    transition_timeout_s: float = 60.0
    poll_interval_s: float = 1.0
    verify_tls: bool = True

    def __post_init__(self) -> None:
        validate_endpoint(self.factory_url)
        validate_endpoint(self.target_url)
        if not isinstance(self.management, ManagementNetworkConfig):
            raise ValueError('management must be a validated static IPv4 configuration')
        if urlsplit(self.target_url).hostname != self.management.address:
            raise ValueError('target_url must match the management address')
        if not isinstance(self.factory_password, str) or not self.factory_password:
            raise ValueError('factory_password must be a non-empty string')
        build_user_account_payload(self.username, self.target_password)
        if self.expected_mac is None and self.expected_serial is None:
            raise ValueError('expected_mac or expected_serial is required')
        if self.expected_mac is not None and (
            not isinstance(self.expected_mac, str)
            or not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}', self.expected_mac)
            or self.expected_mac.lower() == '00:00:00:00:00:00'
            or int(self.expected_mac[:2], 16) & 1
        ):
            raise ValueError('expected_mac must be a unicast MAC address')
        if self.expected_serial is not None and (
            not isinstance(self.expected_serial, str) or not self.expected_serial.strip()
        ):
            raise ValueError('expected_serial must be a non-empty string')
        if type(self.verify_tls) is not bool:
            raise ValueError('verify_tls must be a boolean')
        for value in (self.timeout_s, self.transition_timeout_s, self.poll_interval_s):
            if (
                isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value <= 0
            ):
                raise ValueError('Timeouts and polling interval must be finite positive numbers')

    def credentials(self, target: bool) -> JTComCredentials:
        return JTComCredentials(
            self.username, self.target_password if target else self.factory_password,
        )

    def verify_expected(self, identity: DeviceIdentity) -> None:
        if (
            self.expected_mac is not None
            and identity.mac_address != self.expected_mac.lower()
        ) or (
            self.expected_serial is not None and identity.serial_number != self.expected_serial
        ):
            raise ValueError('Discovered device does not match expected identity')
