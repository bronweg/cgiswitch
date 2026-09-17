"""Unit tests for the management network parser."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from cgiswitch.client.errors import JTComParseError
from cgiswitch.model.management import ManagementNetworkState
from cgiswitch.parser.management import parse_management_network

FIXTURE = Path(__file__).parents[1] / "fixtures" / "management_ip.html"


def _html(*, extra: str = "", fields: str | None = None) -> str:
    body = fields or """
      <select name="dhcp_state">
        <option value="0" selected>Disable</option><option value="1">Enable</option>
      </select>
      <input name="ip" value="192.0.2.10">
      <input name="netmask" value="255.255.255.0">
      <input name="gateway" value="192.0.2.1">
      <input type="hidden" name="cmd" value="ip">
    """
    return f'<form id="ip_form" action="ip.cgi" method="post">{body}{extra}</form>'


def test_fixture_returns_management_state() -> None:
    state = parse_management_network(FIXTURE.read_text())
    assert state == ManagementNetworkState(False, "192.0.2.10", "255.255.255.0", "192.0.2.254")


def test_model_is_frozen() -> None:
    state = ManagementNetworkState(False, "192.0.2.10", "255.255.255.0", "192.0.2.1")
    with pytest.raises(FrozenInstanceError):
        state.gateway = "192.0.2.2"  # type: ignore[misc]


@pytest.mark.parametrize("change", [
    '<input name="ip" value="192.0.2.11">',
    '<input name="extra" value="x">',
])
def test_duplicate_or_unknown_fields_fail_closed(change: str) -> None:
    with pytest.raises(JTComParseError):
        parse_management_network(_html(extra=change))


@pytest.mark.parametrize("field,value", [
    ("ip", "192.0.2.999"),
    ("gateway", "192.0.2"),
    ("netmask", "255.0.255.0"),
])
def test_invalid_ipv4_or_noncontiguous_mask_is_rejected(field: str, value: str) -> None:
    fields = _html().replace(
        f'name="{field}" value="192.0.2.10"', f'name="{field}" value="{value}"'
    )
    fields = fields.replace(
        f'name="{field}" value="255.255.255.0"', f'name="{field}" value="{value}"'
    )
    fields = fields.replace(
        f'name="{field}" value="192.0.2.1"', f'name="{field}" value="{value}"'
    )
    with pytest.raises(JTComParseError):
        parse_management_network(fields)


def test_missing_and_unknown_dhcp_state_fail() -> None:
    with pytest.raises(JTComParseError):
        parse_management_network(_html(fields=_html().split(">", 1)[0]))
    with pytest.raises(JTComParseError):
        parse_management_network(
            _html(fields=_html().replace('value="0" selected', 'value="2" selected'))
        )


@pytest.mark.parametrize("name", ["ip", "netmask", "gateway", "cmd", "dhcp_state"])
def test_every_required_field_is_required(name: str) -> None:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(_html(), "html.parser")
    soup.find(attrs={"name": name}).decompose()
    with pytest.raises(JTComParseError, match="missing fields"):
        parse_management_network(str(soup))


def test_dhcp_selection_is_explicit_and_unambiguous() -> None:
    enabled = _html().replace('value="0" selected', 'value="0"').replace(
        'value="1"', 'value="1" selected',
    )
    assert parse_management_network(enabled).dhcp_enabled is True
    for invalid in [
        _html().replace(' selected', ''),
        _html().replace('value="1"', 'value="1" selected'),
        _html() + _html(),
    ]:
        with pytest.raises(JTComParseError):
            parse_management_network(invalid)
