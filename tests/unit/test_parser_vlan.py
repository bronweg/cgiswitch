"""Unit tests for cgiswitch.parser.vlan."""

from __future__ import annotations

import pathlib

import pytest

from cgiswitch.client.errors import JTComParseError
from cgiswitch.parser.vlan import parse_port_vlan_settings, parse_static_vlans

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures"

# ---------------------------------------------------------------------------
# Helpers — synthetic HTML builders
# ---------------------------------------------------------------------------

_STATIC_TEMPLATE = """
<div class="ip-setting">
  <form method="post" name="vlanCreate" id="vlanCreate">
    <table><tbody>
      <tr><td><b>VLAN ID</b></td><td><input type="text" name="vlanid"></td></tr>
      <tr><td><b>VLAN Name</b></td><td><input type="text" name="vlanname"></td></tr>
    </tbody></table>
  </form>
  <form method="post" name="vlanDel" id="vlanDel" action="vlanDel.cgi">
    <table class="sw-table">
      <thead>
        <tr><th>Chk</th><th>No.</th><th>VLAN ID</th><th>VLAN Name</th></tr>
      </thead>
      {rows}
    </table>
  </form>
</div>
"""

_PORT_BASED_TEMPLATE = """
<div>
  <form method="post" id="vlanMenber" name="vlanMenber">
    <table border="1" class="sw-table">
      <thead>
        <tr><th>Port</th><th>VLAN Type</th><th>Access VLAN</th>
            <th>Native VLAN</th><th>Permit VLAN</th></tr>
      </thead>
      <tbody><tr>
        <td><select name="PortId" multiple><option value="0">Port 1</select></td>
        <td><select name="VlanType"><option value="0">Access</select></td>
        <td><select name="AccessVlan"><option value="1">VLAN 1</select></td>
        <td><select name="NativeVlan" disabled></select></td>
        <td><select name="PermitVlan" multiple></select></td>
      </tr></tbody>
    </table>
  </form>
  <table class="sw-table">
    <tr>
      <td>Port</td><td>VLAN Type</td><td>Access VLAN</td>
      <td>Native VLAN</td><td>Permit VLAN</td>
    </tr>
    {rows}
  </table>
</div>
"""


def _make_static_row(checkbox_val: str, num: int, vid: int, name: str) -> str:
    return (
        f"<tr>"
        f"<td><input type=\"checkbox\" name=\"del\" value=\"{checkbox_val}\"></td>"
        f"<td>{num}</td><td>{vid}</td><td>{name}</td>"
        f"</tr>"
    )


def _make_port_row(port: str, vtype: str, access: str, native: str, permit: str) -> str:
    return (
        f"<tr>"
        f"<td>{port}</td><td>{vtype}</td>"
        f"<td>{access}</td><td>{native}</td><td>{permit}</td>"
        f"</tr>"
    )


# ---------------------------------------------------------------------------
# parse_static_vlans — fixture-based
# ---------------------------------------------------------------------------


def test_static_fixture_returns_two_vlans() -> None:
    """Fixture has VLAN 1 and VLAN 10; two entries must be returned."""
    html = (FIXTURES / "vlan_static.html").read_text()
    entries = parse_static_vlans(html)
    assert len(entries) == 2


def test_static_fixture_vlan1_id() -> None:
    """VLAN 1 must be present with correct ID."""
    html = (FIXTURES / "vlan_static.html").read_text()
    entries = parse_static_vlans(html)
    ids = [e.vlan_id for e in entries]
    assert 1 in ids


def test_static_fixture_vlan1_empty_name() -> None:
    """VLAN 1 on the switch has no name — name field must be empty string."""
    html = (FIXTURES / "vlan_static.html").read_text()
    entries = parse_static_vlans(html)
    vlan1 = next(e for e in entries if e.vlan_id == 1)
    assert vlan1.name == ""


def test_static_fixture_vlan10_id() -> None:
    """VLAN 10 must be present with correct ID."""
    html = (FIXTURES / "vlan_static.html").read_text()
    entries = parse_static_vlans(html)
    ids = [e.vlan_id for e in entries]
    assert 10 in ids


def test_static_fixture_vlan10_name() -> None:
    """VLAN 10 must carry the name 'Management'."""
    html = (FIXTURES / "vlan_static.html").read_text()
    entries = parse_static_vlans(html)
    vlan10 = next(e for e in entries if e.vlan_id == 10)
    assert vlan10.name == "Management"


def test_static_fixture_empty_port_lists() -> None:
    """Static parser must return VLANs with empty tagged/untagged port lists."""
    html = (FIXTURES / "vlan_static.html").read_text()
    for entry in parse_static_vlans(html):
        assert entry.tagged_ports == []
        assert entry.untagged_ports == []


# ---------------------------------------------------------------------------
# parse_static_vlans — synthetic HTML
# ---------------------------------------------------------------------------


def test_static_single_vlan() -> None:
    """One-VLAN synthetic page returns exactly one entry."""
    rows = _make_static_row("1", 1, 1, "")
    html = _STATIC_TEMPLATE.format(rows=rows)
    entries = parse_static_vlans(html)
    assert len(entries) == 1
    assert entries[0].vlan_id == 1
    assert entries[0].name == ""


def test_static_named_vlan() -> None:
    """VLAN name is returned correctly for named VLANs."""
    rows = _make_static_row("20", 1, 20, "DMZ")
    html = _STATIC_TEMPLATE.format(rows=rows)
    entries = parse_static_vlans(html)
    assert entries[0].vlan_id == 20
    assert entries[0].name == "DMZ"


def test_static_multiple_vlans_ordering() -> None:
    """Multiple VLANs are returned in document order."""
    rows = (
        _make_static_row("1", 1, 1, "")
        + _make_static_row("10", 2, 10, "Mgmt")
        + _make_static_row("20", 3, 20, "DMZ")
    )
    html = _STATIC_TEMPLATE.format(rows=rows)
    entries = parse_static_vlans(html)
    assert [e.vlan_id for e in entries] == [1, 10, 20]
    assert [e.name for e in entries] == ["", "Mgmt", "DMZ"]


def test_static_no_form_raises() -> None:
    """Missing vlanDel form must raise JTComParseError."""
    with pytest.raises(JTComParseError, match="vlanDel"):
        parse_static_vlans("<div><p>no form here</p></div>")


def test_static_no_table_raises() -> None:
    """vlanDel form without inner table must raise JTComParseError."""
    html = '<form id="vlanDel"><p>no table</p></form>'
    with pytest.raises(JTComParseError, match="table"):
        parse_static_vlans(html)


# ---------------------------------------------------------------------------
# parse_port_vlan_settings — fixture-based
# ---------------------------------------------------------------------------


def test_port_fixture_six_configs() -> None:
    """Fixture has 6 ports; six VlanPortConfig objects must be returned."""
    html = (FIXTURES / "vlan_port_based.html").read_text()
    configs = parse_port_vlan_settings(html)
    assert len(configs) == 6


def test_port_fixture_all_access_mode() -> None:
    """All 6 ports in the fixture are in Access mode."""
    html = (FIXTURES / "vlan_port_based.html").read_text()
    for cfg in parse_port_vlan_settings(html):
        assert cfg.vlan_type == "Access"


def test_port_fixture_all_access_vlan1() -> None:
    """All ports in the fixture have Access VLAN = 1."""
    html = (FIXTURES / "vlan_port_based.html").read_text()
    for cfg in parse_port_vlan_settings(html):
        assert cfg.access_vlan == 1


def test_port_fixture_no_native_no_permit() -> None:
    """Access ports must have native_vlan=None and empty permit_vlans."""
    html = (FIXTURES / "vlan_port_based.html").read_text()
    for cfg in parse_port_vlan_settings(html):
        assert cfg.native_vlan is None
        assert cfg.permit_vlans == []


def test_port_fixture_port_names() -> None:
    """Port names must be 'Port 1' … 'Port 6'."""
    html = (FIXTURES / "vlan_port_based.html").read_text()
    names = [cfg.port_name for cfg in parse_port_vlan_settings(html)]
    assert names == ["Port 1", "Port 2", "Port 3", "Port 4", "Port 5", "Port 6"]


# ---------------------------------------------------------------------------
# parse_port_vlan_settings — synthetic HTML (access mode)
# ---------------------------------------------------------------------------


def test_port_access_mode() -> None:
    """Access-mode row is parsed correctly."""
    rows = _make_port_row("Port 1", "Access", "5", "--", "--")
    html = _PORT_BASED_TEMPLATE.format(rows=rows)
    configs = parse_port_vlan_settings(html)
    assert len(configs) == 1
    cfg = configs[0]
    assert cfg.port_name == "Port 1"
    assert cfg.vlan_type == "Access"
    assert cfg.access_vlan == 5
    assert cfg.native_vlan is None
    assert cfg.permit_vlans == []


# ---------------------------------------------------------------------------
# parse_port_vlan_settings — synthetic HTML (trunk mode)
# ---------------------------------------------------------------------------


def test_port_trunk_mode_native_only() -> None:
    """Trunk port with no permitted VLANs (just native) parses correctly."""
    rows = _make_port_row("Port 2", "Trunk", "--", "10", "--")
    html = _PORT_BASED_TEMPLATE.format(rows=rows)
    cfg = parse_port_vlan_settings(html)[0]
    assert cfg.vlan_type == "Trunk"
    assert cfg.native_vlan == 10
    assert cfg.access_vlan is None
    assert cfg.permit_vlans == []


def test_port_trunk_mode_permit_comma_separated() -> None:
    """Comma-separated permit VLAN list is split correctly."""
    rows = _make_port_row("Port 3", "Trunk", "--", "1", "10,20,30")
    html = _PORT_BASED_TEMPLATE.format(rows=rows)
    cfg = parse_port_vlan_settings(html)[0]
    assert cfg.permit_vlans == [10, 20, 30]


def test_port_trunk_mode_permit_underscore_separated() -> None:
    """Underscore-separated permit VLAN list (JS serialised) is split correctly."""
    rows = _make_port_row("Port 4", "Trunk", "--", "1", "10_20_30")
    html = _PORT_BASED_TEMPLATE.format(rows=rows)
    cfg = parse_port_vlan_settings(html)[0]
    assert cfg.permit_vlans == [10, 20, 30]


def test_port_trunk_mode_single_permit() -> None:
    """Single permit VLAN is returned as a one-element list."""
    rows = _make_port_row("Port 5", "Trunk", "--", "1", "100")
    html = _PORT_BASED_TEMPLATE.format(rows=rows)
    cfg = parse_port_vlan_settings(html)[0]
    assert cfg.permit_vlans == [100]


def test_port_no_status_table_raises() -> None:
    """HTML without a standalone status table raises JTComParseError."""
    html = "<div><form id=\"vlanMenber\"><table><tr><td>x</td></tr></table></form></div>"
    with pytest.raises(JTComParseError, match="status table"):
        parse_port_vlan_settings(html)


@pytest.mark.parametrize("filename,field,raw", [
    ("malformed_vlan_id.html", "vlan_id", "bad-id"),
    ("malformed_vlan_access.html", "access_vlan", "bad-access"),
    ("malformed_vlan_native.html", "native_vlan", "bad-native"),
    ("malformed_vlan_permit.html", "permit_vlans", "1,bad-permit"),
    ("malformed_vlan_mode.html", "vlan_type", "Hybrid"),
])
def test_malformed_fixtures_report_parser_field_and_raw_value(
    filename: str, field: str, raw: str,
) -> None:
    parser = parse_static_vlans if field == "vlan_id" else parse_port_vlan_settings
    with pytest.raises(JTComParseError) as exc:
        parser((FIXTURES / filename).read_text())
    message = str(exc.value)
    assert parser.__name__ in message
    assert field in message
    assert raw in message
    if field != "vlan_id":
        assert "Port 3" in message


@pytest.mark.parametrize("value", ["", "--", "0", "4095", "-1", "1.5"])
def test_invalid_static_vlan_ids_are_not_discarded(value: str) -> None:
    row = _make_static_row("1", 1, 1, "default").replace('<td>1</td><td>default',
                                                           f'<td>{value}</td><td>default')
    with pytest.raises(JTComParseError, match="vlan_id"):
        parse_static_vlans(_STATIC_TEMPLATE.format(rows=row))


@pytest.mark.parametrize("value", ["", "0", "4095", "1,,10", "1__10", "1,", ",1", "1,bad"])
def test_invalid_permit_list_is_not_partially_accepted(value: str) -> None:
    row = _make_port_row("Port 3", "Trunk", "--", "1", value)
    with pytest.raises(JTComParseError, match="permit_vlans") as exc:
        parse_port_vlan_settings(_PORT_BASED_TEMPLATE.format(rows=row))
    assert repr(value) in str(exc.value)


@pytest.mark.parametrize("mode,access,native,permit", [
    ("Access", "--", "--", "--"),
    ("Access", "", "--", "--"),
    ("Access", "4095", "--", "--"),
    ("Access", "1", "10", "--"),
    ("Access", "1", "--", "10"),
    ("Trunk", "--", "--", "1"),
    ("Trunk", "--", "", "1"),
    ("Trunk", "--", "4095", "1"),
    ("Trunk", "1", "1", "1"),
])
def test_missing_or_conflicting_mode_fields_fail(
    mode: str, access: str, native: str, permit: str,
) -> None:
    row = _make_port_row("Port 3", mode, access, native, permit)
    with pytest.raises(JTComParseError):
        parse_port_vlan_settings(_PORT_BASED_TEMPLATE.format(rows=row))


def test_duplicate_static_vlan_id_fails() -> None:
    rows = _make_static_row("1", 1, 1, "default") + _make_static_row("1", 2, 1, "other")
    with pytest.raises(JTComParseError, match="duplicate"):
        parse_static_vlans(_STATIC_TEMPLATE.format(rows=rows))


@pytest.mark.parametrize("name", ["Port 3", "port3"])
def test_duplicate_vlan_port_id_fails(name: str) -> None:
    rows = _make_port_row("Port 3", "Access", "1", "--", "--")
    rows += _make_port_row(name, "Access", "10", "--", "--")
    with pytest.raises(JTComParseError, match="duplicate"):
        parse_port_vlan_settings(_PORT_BASED_TEMPLATE.format(rows=rows))


@pytest.mark.parametrize("name", ["Port 0", "Port 3suffix", "unknown"])
def test_malformed_vlan_port_name_fails(name: str) -> None:
    rows = _make_port_row(name, "Access", "1", "--", "--")
    with pytest.raises(JTComParseError, match="port_name"):
        parse_port_vlan_settings(_PORT_BASED_TEMPLATE.format(rows=rows))


@pytest.mark.parametrize("rows", ["", "<tr><td>incomplete</td></tr>"])
def test_empty_or_incomplete_static_table_fails(rows: str) -> None:
    with pytest.raises(JTComParseError):
        parse_static_vlans(_STATIC_TEMPLATE.format(rows=rows))


@pytest.mark.parametrize("rows", ["", "<tr><td>Port 3</td></tr>"])
def test_empty_or_incomplete_port_vlan_table_fails(rows: str) -> None:
    with pytest.raises(JTComParseError):
        parse_port_vlan_settings(_PORT_BASED_TEMPLATE.format(rows=rows))
