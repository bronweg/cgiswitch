"""Unit tests for the static management network configuration model."""

from __future__ import annotations

import ipaddress

import pytest

from cgiswitch.model.management import ManagementNetworkConfig, ManagementNetworkState


def test_management_config_as_state() -> None:
    config = ManagementNetworkConfig("192.0.2.10", 24, "192.0.2.1")

    assert config.as_state() == ManagementNetworkState(
        dhcp_enabled=False,
        ip_address="192.0.2.10",
        subnet_mask="255.255.255.0",
        gateway="192.0.2.1",
    )


@pytest.mark.parametrize("address", [None, 123, "192.0.2", "192.0.2.999", "2001:db8::1"])
def test_management_config_rejects_invalid_address(address: object) -> None:
    with pytest.raises(ValueError):
        ManagementNetworkConfig(address, 24, "192.0.2.1")  # type: ignore[arg-type]


@pytest.mark.parametrize("address", ["0.0.0.0", "224.0.0.1", "239.255.255.255"])
def test_management_config_rejects_unspecified_or_multicast_address(address: str) -> None:
    with pytest.raises(ValueError):
        ManagementNetworkConfig(address, 24, "192.0.2.1")


@pytest.mark.parametrize("prefix_length", [None, True, False, -1, 33, 24.0, "24"])
def test_management_config_rejects_invalid_prefix(prefix_length: object) -> None:
    with pytest.raises(ValueError):
        ManagementNetworkConfig("192.0.2.10", prefix_length, "192.0.2.1")  # type: ignore[arg-type]


@pytest.mark.parametrize("gateway", [None, 123, "192.0.2", "192.0.2.999", "2001:db8::1"])
def test_management_config_rejects_invalid_gateway(gateway: object) -> None:
    with pytest.raises(ValueError):
        ManagementNetworkConfig("192.0.2.10", 24, gateway)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("address", "prefix_length", "gateway"),
    [("192.0.2.10", 24, "198.51.100.1"), ("192.0.2.10", 32, "192.0.2.1")],
)
def test_management_config_rejects_gateway_outside_subnet(
    address: str, prefix_length: int, gateway: str,
) -> None:
    with pytest.raises(ValueError, match="subnet"):
        ManagementNetworkConfig(address, prefix_length, gateway)


@pytest.mark.parametrize("prefix_length", [0, 1, 8, 16, 24, 31, 32])
def test_management_config_allows_valid_prefixes(prefix_length: int) -> None:
    address = "128.0.0.1" if prefix_length == 1 else "192.0.2.10"
    gateway = "128.0.0.2" if prefix_length == 1 else address
    config = ManagementNetworkConfig(address, prefix_length, gateway)

    assert config.as_state().subnet_mask == str(
        ipaddress.IPv4Network(f"{address}/{prefix_length}", strict=False).netmask
    )
