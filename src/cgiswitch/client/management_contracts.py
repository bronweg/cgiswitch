"""Form payload contracts for the JTCom management pages.

These builders only construct validated form data.  Dispatching management
changes is intentionally owned by a higher-level operation layer.
"""

from __future__ import annotations

import ipaddress
import re

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
_PASSWORD_RE = re.compile(r"^[0-9A-Za-z<=>\[\]!@#$*().]+$")
_SYSTEM_COMMANDS = frozenset(("saveconfig", "reboot"))


def _ipv4(value: str, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be an IPv4 address")
    try:
        address = ipaddress.IPv4Address(value)
    except (ipaddress.AddressValueError, ValueError) as exc:
        raise ValueError(f"{field} must be an IPv4 address") from exc
    return str(address)


def _netmask(value: str) -> str:
    canonical = _ipv4(value, "netmask")
    mask = int(ipaddress.IPv4Address(canonical))
    inverse = (~mask) & 0xFFFFFFFF
    if inverse & (inverse + 1):
        raise ValueError("netmask must contain contiguous one bits")
    return canonical


def build_management_network_payload(
    ip: str,
    netmask: str,
    gateway: str,
) -> dict[str, str]:
    """Build the static management network form payload."""
    address = _ipv4(ip, "ip")
    mask = _netmask(netmask)
    route = _ipv4(gateway, "gateway")
    network = ipaddress.IPv4Network(f"{address}/{mask}", strict=False)
    if ipaddress.IPv4Address(route) not in network:
        raise ValueError("gateway must be in the management address subnet")
    return {
        "dhcp_state": "0",
        "ip": address,
        "netmask": mask,
        "gateway": route,
        "cmd": "ip",
        "page": "inside",
    }


def build_user_account_payload(username: str, password: str) -> dict[str, str]:
    """Build the account/password form payload accepted by ``user.cgi``."""
    if not isinstance(username, str) or not 5 <= len(username) <= 16:
        raise ValueError("username must be 5-16 characters")
    if _USERNAME_RE.fullmatch(username) is None:
        raise ValueError("username must contain only letters, numbers, and underscores")
    if not isinstance(password, str) or not 6 <= len(password) <= 16:
        raise ValueError("password must be 6-16 characters")
    if _PASSWORD_RE.fullmatch(password) is None:
        raise ValueError("password contains an unsupported character")
    return {
        "mname": username,
        "mpass": password,
        "mpass2": password,
        "page": "inside",
    }


def build_system_payload(command: str) -> dict[str, str]:
    """Build a supported device-management command payload."""
    if command not in _SYSTEM_COMMANDS:
        raise ValueError("command must be 'saveconfig' or 'reboot'")
    return {"cmd": command, "page": "inside"}
