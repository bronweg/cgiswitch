"""Parser for JTCom device information pages (system_info.cgi)."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from cgiswitch.client.errors import JTComParseError
from cgiswitch.model.device import DeviceInfo

# ---------------------------------------------------------------------------
# Label → canonical field name mapping (keys must be lowercase and stripped)
# ---------------------------------------------------------------------------

_LABEL_MAP: dict[str, str] = {
    # mac_address
    "mac address": "mac_address",
    "mac": "mac_address",
    "device mac": "mac_address",
    "hw address": "mac_address",
    "hardware address": "mac_address",
    # serial_number
    "serial number": "serial_number",
    "serial no": "serial_number",
    "serial no.": "serial_number",
    "serial": "serial_number",
    "sn": "serial_number",
    # firmware_version
    "firmware version": "firmware_version",
    "firmware": "firmware_version",
    "software version": "firmware_version",
    "sw version": "firmware_version",
    "version": "firmware_version",
    # model
    "model": "model",
    "device model": "model",
    "product model": "model",
    "product name": "model",
    # ip_address
    "ip address": "ip_address",
    "ip": "ip_address",
    "management ip": "ip_address",
    "mgmt ip": "ip_address",
    "ipv4 address": "ip_address",
    # uptime
    "uptime": "uptime",
    "system uptime": "uptime",
    "running time": "uptime",
}

# MAC address: XX:XX:XX:XX:XX:XX or XX-XX-XX-XX-XX-XX
_MAC_RE: re.Pattern[str] = re.compile(
    r"^([0-9a-fA-F]{2}[:\-]){5}[0-9a-fA-F]{2}$"
)

# Uptime: "N days, HH:MM:SS" or "HH:MM:SS"
_UPTIME_RE: re.Pattern[str] = re.compile(
    r"(?:(\d+)\s*days?\s*[,]?\s*)?(\d+):(\d+):(\d+)"
)

# Uptime compact format: "XD YH:ZM:WS" (e.g. "0D 14H:36M:26S")
_UPTIME_RE2: re.Pattern[str] = re.compile(
    r"(\d+)D\s*(\d+)H:(\d+)M:(\d+)S",
    re.IGNORECASE,
)


def parse_device_info(html: str) -> DeviceInfo:
    """Parse the device information page into a :class:`.DeviceInfo`.

    Scans all ``<table>`` rows for two-column label/value pairs and maps
    known labels to :class:`.DeviceInfo` fields.

    Args:
        html: Raw HTML from ``system_info.cgi`` (or compatible page).

    Returns:
        Populated :class:`.DeviceInfo` instance.

    Raises:
        JTComParseError: If the MAC address is absent or malformed.
    """
    soup = BeautifulSoup(html, "lxml")
    raw: dict[str, str] = _extract_table_pairs(soup)
    fields = _map_fields(raw)
    return _build_device_info(fields)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _extract_table_pairs(soup: BeautifulSoup) -> dict[str, str]:
    """Walk all tables and collect (label, value) pairs from two-cell rows."""
    pairs: dict[str, str] = {}
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        label = cells[0].get_text(strip=True)
        value = cells[1].get_text(strip=True)
        if label and value:
            pairs[label.lower()] = value
    return pairs


def _map_fields(raw: dict[str, str]) -> dict[str, str]:
    """Map raw table labels to canonical DeviceInfo field names."""
    fields: dict[str, str] = {}
    for label, value in raw.items():
        canonical = _LABEL_MAP.get(label.strip())
        if canonical and value:
            fields[canonical] = value
    return fields


def _build_device_info(fields: dict[str, str]) -> DeviceInfo:
    """Construct a :class:`.DeviceInfo` from mapped fields, validating MAC."""
    mac = fields.get("mac_address", "")
    if not mac or not _MAC_RE.match(mac):
        raise JTComParseError(
            f"MAC address missing or malformed in device info page: {mac!r}"
        )
    return DeviceInfo(
        mac_address=mac.upper(),
        serial_number=fields.get("serial_number"),
        firmware_version=fields.get("firmware_version"),
        model=fields.get("model"),
        ip_address=fields.get("ip_address"),
        uptime=fields.get("uptime"),
    )


def parse_uptime_seconds(uptime_str: str | None) -> float:
    """Convert a raw uptime string to total seconds.

    Supports formats like ``"7 days, 03:42:11"``, ``"03:42:11"``, and
    the compact switch format ``"0D 14H:36M:26S"``.
    Returns ``0.0`` if *uptime_str* is ``None`` or cannot be parsed.

    Args:
        uptime_str: Raw uptime string from :attr:`.DeviceInfo.uptime`.

    Returns:
        Total uptime in seconds as a :class:`float`.
    """
    if not uptime_str:
        return 0.0
    # Try compact "XD YH:ZM:WS" format first (real JTCom switch format)
    m2 = _UPTIME_RE2.search(uptime_str)
    if m2:
        days = int(m2.group(1))
        hours = int(m2.group(2))
        minutes = int(m2.group(3))
        seconds = int(m2.group(4))
        return float(days * 86400 + hours * 3600 + minutes * 60 + seconds)
    # Fall back to "N days, HH:MM:SS" format
    m = _UPTIME_RE.search(uptime_str)
    if not m:
        return 0.0
    days = int(m.group(1) or 0)
    hours = int(m.group(2))
    minutes = int(m.group(3))
    seconds = int(m.group(4))
    return float(days * 86400 + hours * 3600 + minutes * 60 + seconds)
