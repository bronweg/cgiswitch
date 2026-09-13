"""Unit tests for cgiswitch.parser.device and cgiswitch.model.device."""

from __future__ import annotations

import pathlib

import pytest

from cgiswitch.client.errors import JTComParseError
from cgiswitch.model.device import DeviceInfo
from cgiswitch.parser.device import (
    parse_device_info,
    parse_uptime_seconds,
)

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures"

# ---------------------------------------------------------------------------
# Minimal synthetic HTML helpers
# ---------------------------------------------------------------------------

_TWO_COL_TEMPLATE = """\
<!DOCTYPE html>
<html><body>
<table>
{rows}
</table>
</body></html>
"""


def _row(label: str, value: str) -> str:
    return f"  <tr><td>{label}</td><td>{value}</td></tr>"


def _make_html(*pairs: tuple[str, str]) -> str:
    """Build a minimal two-column HTML table from (label, value) pairs."""
    rows = "\n".join(_row(k, v) for k, v in pairs)
    return _TWO_COL_TEMPLATE.format(rows=rows)


# ---------------------------------------------------------------------------
# Fixture-based tests
# ---------------------------------------------------------------------------

def test_fixture_parse_mac_address() -> None:
    html = (FIXTURES / "device_info.html").read_text()
    info = parse_device_info(html)
    assert info.mac_address == "A8:F7:E0:12:34:56"


def test_fixture_parse_firmware_version() -> None:
    html = (FIXTURES / "device_info.html").read_text()
    info = parse_device_info(html)
    assert info.firmware_version == "v2.3.1-20240115"


def test_fixture_parse_model() -> None:
    html = (FIXTURES / "device_info.html").read_text()
    info = parse_device_info(html)
    assert info.model == "JTCom-S1024G"


def test_fixture_parse_serial_number() -> None:
    html = (FIXTURES / "device_info.html").read_text()
    info = parse_device_info(html)
    assert info.serial_number == "JTC20240001234"


def test_fixture_parse_ip_address() -> None:
    html = (FIXTURES / "device_info.html").read_text()
    info = parse_device_info(html)
    assert info.ip_address == "192.168.61.10"


def test_fixture_parse_uptime() -> None:
    html = (FIXTURES / "device_info.html").read_text()
    info = parse_device_info(html)
    assert info.uptime == "7 days, 03:42:11"


def test_fixture_returns_device_info_instance() -> None:
    html = (FIXTURES / "device_info.html").read_text()
    info = parse_device_info(html)
    assert isinstance(info, DeviceInfo)


# ---------------------------------------------------------------------------
# Synthetic HTML tests
# ---------------------------------------------------------------------------

def test_minimal_mac_only() -> None:
    """A page with only a MAC row is parsed successfully."""
    html = _make_html(("MAC Address", "AA:BB:CC:DD:EE:FF"))
    info = parse_device_info(html)
    assert info.mac_address == "AA:BB:CC:DD:EE:FF"
    assert info.serial_number is None
    assert info.firmware_version is None
    assert info.model is None


def test_mac_uppercased() -> None:
    """MAC addresses are normalised to uppercase."""
    html = _make_html(("MAC Address", "aa:bb:cc:dd:ee:ff"))
    info = parse_device_info(html)
    assert info.mac_address == "AA:BB:CC:DD:EE:FF"


def test_mac_with_dashes() -> None:
    """MACs with dashes are accepted."""
    html = _make_html(("MAC Address", "AA-BB-CC-DD-EE-FF"))
    info = parse_device_info(html)
    assert info.mac_address == "AA-BB-CC-DD-EE-FF"


def test_all_known_labels_parsed() -> None:
    html = _make_html(
        ("MAC Address", "11:22:33:44:55:66"),
        ("Serial Number", "SN-9999"),
        ("Firmware Version", "v1.0.0"),
        ("Model", "TestModel-48"),
        ("IP Address", "10.0.0.1"),
        ("Uptime", "1 days, 00:00:00"),
    )
    info = parse_device_info(html)
    assert info.mac_address == "11:22:33:44:55:66"
    assert info.serial_number == "SN-9999"
    assert info.firmware_version == "v1.0.0"
    assert info.model == "TestModel-48"
    assert info.ip_address == "10.0.0.1"
    assert info.uptime == "1 days, 00:00:00"


def test_alternative_label_device_mac() -> None:
    html = _make_html(("Device MAC", "CC:DD:EE:FF:00:11"))
    info = parse_device_info(html)
    assert info.mac_address == "CC:DD:EE:FF:00:11"


def test_alternative_label_sw_version() -> None:
    html = _make_html(
        ("MAC", "CC:DD:EE:FF:00:11"),
        ("SW Version", "3.5.0"),
    )
    info = parse_device_info(html)
    assert info.firmware_version == "3.5.0"


def test_extra_unknown_rows_ignored() -> None:
    """Rows with unknown labels are silently ignored."""
    html = _make_html(
        ("MAC Address", "DE:AD:BE:EF:CA:FE"),
        ("Subnet Mask", "255.255.255.0"),
        ("Default Gateway", "192.168.1.1"),
    )
    info = parse_device_info(html)
    assert info.mac_address == "DE:AD:BE:EF:CA:FE"
    assert info.ip_address is None


def test_missing_mac_raises_parse_error() -> None:
    """A page with no MAC address raises JTComParseError."""
    html = _make_html(("Model", "SomeSwitch"), ("Firmware Version", "v1.0"))
    with pytest.raises(JTComParseError, match="MAC address"):
        parse_device_info(html)


def test_malformed_mac_raises_parse_error() -> None:
    """A page with a malformed MAC address raises JTComParseError."""
    html = _make_html(("MAC Address", "ZZ:ZZ:ZZ:ZZ:ZZ:ZZ"))
    with pytest.raises(JTComParseError, match="MAC address"):
        parse_device_info(html)


def test_empty_html_raises_parse_error() -> None:
    """Empty HTML raises JTComParseError."""
    with pytest.raises(JTComParseError):
        parse_device_info("<html></html>")


def test_multi_table_html() -> None:
    """Parser scans all tables and finds MAC in a second table."""
    html = """\
    <!DOCTYPE html><html><body>
    <table><tr><td>Subnet Mask</td><td>255.255.0.0</td></tr></table>
    <table>
      <tr><td>MAC Address</td><td>AA:BB:CC:DD:EE:FF</td></tr>
      <tr><td>Model</td><td>Multi-Table-Switch</td></tr>
    </table>
    </body></html>
    """
    info = parse_device_info(html)
    assert info.mac_address == "AA:BB:CC:DD:EE:FF"
    assert info.model == "Multi-Table-Switch"


# ---------------------------------------------------------------------------
# parse_uptime_seconds tests
# ---------------------------------------------------------------------------

def test_uptime_days_hours_minutes_seconds() -> None:
    assert parse_uptime_seconds("7 days, 03:42:11") == pytest.approx(
        7 * 86400 + 3 * 3600 + 42 * 60 + 11
    )


def test_uptime_zero_days() -> None:
    assert parse_uptime_seconds("0 days, 00:00:00") == pytest.approx(0.0)


def test_uptime_hours_only() -> None:
    assert parse_uptime_seconds("02:30:00") == pytest.approx(2 * 3600 + 30 * 60)


def test_uptime_one_day() -> None:
    assert parse_uptime_seconds("1 day, 00:00:00") == pytest.approx(86400.0)


def test_uptime_none_returns_zero() -> None:
    assert parse_uptime_seconds(None) == pytest.approx(0.0)


def test_uptime_unparseable_returns_zero() -> None:
    assert parse_uptime_seconds("unknown") == pytest.approx(0.0)

def test_uptime_compact_xd_format() -> None:
    """Real JTCom switch uptime format: '0D 14H:36M:26S'."""
    assert parse_uptime_seconds("0D 14H:36M:26S") == pytest.approx(14 * 3600 + 36 * 60 + 26)


def test_uptime_compact_nonzero_days() -> None:
    """Compact format with non-zero days."""
    expected = 3 * 86400 + 2 * 3600 + 10 * 60 + 5
    assert parse_uptime_seconds("3D 2H:10M:05S") == pytest.approx(expected)
