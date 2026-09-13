"""Unit tests for cgiswitch.parser.port and cgiswitch.model.port."""

from __future__ import annotations

import pathlib

import pytest

from cgiswitch.client.errors import JTComParseError
from cgiswitch.model.port import PortOperStatus, PortSettings
from cgiswitch.parser.port import (
    _parse_actual_speed,
    parse_port_page,
    parse_port_settings,
)

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures"

# ---------------------------------------------------------------------------
# Minimal synthetic HTML helpers
# ---------------------------------------------------------------------------

_STATUS_TABLE_TMPL = """<!DOCTYPE html>
<html><body>
<table>
  <thead>
    <tr>
      <th rowspan="2">Port</th>
      <th rowspan="2">Admin Status</th>
      <th colspan="2">Speed/Duplex</th>
      <th colspan="2">Flow Control</th>
    </tr>
    <tr><th>Config</th><th>Actual</th><th>Config</th><th>Actual</th></tr>
  </thead>
  <tbody>
{rows}
  </tbody>
</table>
</body></html>
"""


def _row(
    port: str,
    admin: str,
    spd_cfg: str,
    spd_act: str,
    fc_cfg: str,
    fc_act: str,
) -> str:
    return (
        f"    <tr>"
        f"<td>{port}</td><td>{admin}</td>"
        f"<td>{spd_cfg}</td><td>{spd_act}</td>"
        f"<td>{fc_cfg}</td><td>{fc_act}</td>"
        f"</tr>"
    )


def _make_html(*rows: tuple[str, str, str, str, str, str]) -> str:
    return _STATUS_TABLE_TMPL.format(
        rows="\n".join(_row(*r) for r in rows)
    )


# ---------------------------------------------------------------------------
# Fixture-based tests (port_settings.html from real switch)
# ---------------------------------------------------------------------------

def test_fixture_parses_six_ports() -> None:
    html = (FIXTURES / "port_settings.html").read_text()
    settings, oper = parse_port_page(html)
    assert len(settings) == 6
    assert len(oper) == 6


def test_fixture_port1_admin_up() -> None:
    html = (FIXTURES / "port_settings.html").read_text()
    settings, _ = parse_port_page(html)
    p1 = next(s for s in settings if s.port_id == 1)
    assert p1.admin_up is True
    assert p1.name == "Port 1"


def test_fixture_port1_speed_auto() -> None:
    html = (FIXTURES / "port_settings.html").read_text()
    settings, _ = parse_port_page(html)
    p1 = next(s for s in settings if s.port_id == 1)
    assert p1.speed_duplex == "Auto"


def test_fixture_port1_link_down() -> None:
    html = (FIXTURES / "port_settings.html").read_text()
    _, oper = parse_port_page(html)
    o1 = next(o for o in oper if o.port_id == 1)
    assert o1.link_up is False
    assert o1.negotiated_speed_mbps is None
    assert o1.duplex is None


def test_fixture_port6_link_up_10g() -> None:
    """Port 6 in the fixture has Speed/Duplex Actual = 10G/Full."""
    html = (FIXTURES / "port_settings.html").read_text()
    _, oper = parse_port_page(html)
    o6 = next(o for o in oper if o.port_id == 6)
    assert o6.link_up is True
    assert o6.negotiated_speed_mbps == 10000
    assert o6.duplex == "full"


def test_fixture_port6_flow_control_on() -> None:
    html = (FIXTURES / "port_settings.html").read_text()
    settings, _ = parse_port_page(html)
    p6 = next(s for s in settings if s.port_id == 6)
    assert p6.flow_control is True


def test_fixture_returns_correct_types() -> None:
    html = (FIXTURES / "port_settings.html").read_text()
    settings, oper = parse_port_page(html)
    assert all(isinstance(s, PortSettings) for s in settings)
    assert all(isinstance(o, PortOperStatus) for o in oper)


# ---------------------------------------------------------------------------
# Synthetic HTML tests
# ---------------------------------------------------------------------------

def test_single_port_link_down() -> None:
    html = _make_html(("Port 1", "Enable", "Auto", "Link Down", "On", "Off"))
    settings, oper = parse_port_page(html)
    assert len(settings) == 1
    assert settings[0].port_id == 1
    assert settings[0].admin_up is True
    assert settings[0].speed_duplex == "Auto"
    assert settings[0].flow_control is True
    assert oper[0].link_up is False
    assert oper[0].negotiated_speed_mbps is None


def test_single_port_link_up_1000m() -> None:
    html = _make_html(
        ("Port 2", "Enable", "Auto", "1000M/Full", "Off", "Off")
    )
    _, oper = parse_port_page(html)
    assert oper[0].link_up is True
    assert oper[0].negotiated_speed_mbps == 1000
    assert oper[0].duplex == "full"


def test_single_port_link_up_100m_half() -> None:
    html = _make_html(
        ("Port 3", "Enable", "100M/Half", "100M/Half", "Off", "Off")
    )
    _, oper = parse_port_page(html)
    assert oper[0].link_up is True
    assert oper[0].negotiated_speed_mbps == 100
    assert oper[0].duplex == "half"


def test_single_port_disabled() -> None:
    html = _make_html(("Port 4", "Disable", "Auto", "Link Down", "Off", "Off"))
    settings, _ = parse_port_page(html)
    assert settings[0].admin_up is False


def test_two_ports_ids_correct() -> None:
    html = _make_html(
        ("Port 1", "Enable", "Auto", "Link Down", "On", "Off"),
        ("Port 2", "Disable", "1000M/Full", "1000M/Full", "Off", "Off"),
    )
    settings, oper = parse_port_page(html)
    assert settings[0].port_id == 1
    assert settings[1].port_id == 2
    assert oper[1].link_up is True


def test_no_table_raises_parse_error() -> None:
    with pytest.raises(JTComParseError, match="No port status table"):
        parse_port_page("<html><body><p>nothing here</p></body></html>")


def test_empty_tbody_raises_parse_error() -> None:
    html = _STATUS_TABLE_TMPL.format(rows="")
    with pytest.raises(JTComParseError, match="No port status table"):
        parse_port_page(html)


def test_form_wrapped_tables_ignored() -> None:
    """Config-form tables must not be mistaken for the status table."""
    html = """    <!DOCTYPE html><html><body>
    <form>
      <table>
        <tr><td>Port 1</td><td>Enable</td><td>Auto</td>
            <td>Link Down</td><td>On</td><td>Off</td></tr>
      </table>
    </form>
    </body></html>
    """
    with pytest.raises(JTComParseError):
        parse_port_page(html)


# ---------------------------------------------------------------------------
# parse_port_settings() shim
# ---------------------------------------------------------------------------

def test_parse_port_settings_returns_list() -> None:
    html = _make_html(("Port 1", "Enable", "Auto", "Link Down", "On", "Off"))
    result = parse_port_settings(html)
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], PortSettings)


# ---------------------------------------------------------------------------
# _parse_actual_speed unit tests
# ---------------------------------------------------------------------------

def test_parse_actual_link_down() -> None:
    assert _parse_actual_speed("Link Down") == (False, None, None)


def test_parse_actual_link_down_mixed_case() -> None:
    assert _parse_actual_speed("link down") == (False, None, None)


def test_parse_actual_empty_string() -> None:
    assert _parse_actual_speed("") == (False, None, None)


def test_parse_actual_10m_half() -> None:
    lu, spd, dup = _parse_actual_speed("10M/Half")
    assert lu is True and spd == 10 and dup == "half"


def test_parse_actual_100m_full() -> None:
    lu, spd, dup = _parse_actual_speed("100M/Full")
    assert lu is True and spd == 100 and dup == "full"


def test_parse_actual_1000m_full() -> None:
    lu, spd, dup = _parse_actual_speed("1000M/Full")
    assert lu is True and spd == 1000 and dup == "full"


def test_parse_actual_10g_full() -> None:
    lu, spd, dup = _parse_actual_speed("10G/Full")
    assert lu is True and spd == 10000 and dup == "full"


def test_parse_actual_2500m_full() -> None:
    lu, spd, dup = _parse_actual_speed("2500M/Full")
    assert lu is True and spd == 2500 and dup == "full"


def test_parse_actual_unknown_text() -> None:
    assert _parse_actual_speed("Negotiating...") == (None, None, None)


@pytest.mark.parametrize("admin", ["Unknown", "", "--", "disabled-ish"])
def test_unknown_current_admin_status_is_preserved(admin: str) -> None:
    settings, _ = parse_port_page(_make_html(("Port 1", admin, "Auto", "Link Down", "On", "Off")))
    assert settings[0].admin_up is None


@pytest.mark.parametrize("field", ["flow_control", "speed_duplex"])
def test_missing_current_port_fields_are_preserved(field: str) -> None:
    speed, flow = ("", "On") if field == "speed_duplex" else ("Auto", "Unknown")
    settings, _ = parse_port_page(_make_html(("Port 1", "Enable", speed, "Link Down", flow, "Off")))
    assert getattr(settings[0], field) is None


@pytest.mark.parametrize("port", ["Port 0", "Port 2 junk", "unknown port"])
def test_malformed_port_row_is_not_skipped(port: str) -> None:
    html = _make_html(("Port 1", "Enable", "Auto", "Link Down", "On", "Off"),
                      (port, "Enable", "Auto", "Link Down", "On", "Off"))
    with pytest.raises(JTComParseError, match="port_id"):
        parse_port_page(html)


def test_duplicate_current_port_is_rejected() -> None:
    row = ("Port 1", "Enable", "Auto", "Link Down", "On", "Off")
    with pytest.raises(JTComParseError, match="duplicate"):
        parse_port_page(_make_html(row, row))


def test_incomplete_port_row_is_not_skipped() -> None:
    html = _make_html(("Port 1", "Enable", "Auto", "Link Down", "On", "Off"))
    html = html.replace('</tbody>', '<tr><td>Port 2</td></tr></tbody>')
    with pytest.raises(JTComParseError, match="incomplete"):
        parse_port_page(html)
