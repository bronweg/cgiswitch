"""Parser for the JTCom management IP settings page."""

from __future__ import annotations

import ipaddress

from bs4 import Tag

from cgiswitch.client.errors import JTComParseError
from cgiswitch.model.management import ManagementNetworkState
from cgiswitch.parser.html import parse_html

_EXPECTED_FIELDS = {"dhcp_state", "ip", "netmask", "gateway", "cmd"}
_EXPECTED_TAGS = {
    "dhcp_state": "select",
    "ip": "input",
    "netmask": "input",
    "gateway": "input",
    "cmd": "input",
}


def _parse_ipv4(raw: str, *, field: str) -> str:
    """Parse one strict dotted-decimal IPv4 value."""
    try:
        address = ipaddress.IPv4Address(raw)
    except ipaddress.AddressValueError as exc:
        raise JTComParseError(
            f"parse_management_network field={field!r} raw={raw!r}: malformed IPv4 address"
        ) from exc
    return str(address)


def _parse_netmask(raw: str) -> str:
    """Parse a dotted IPv4 netmask and require contiguous one bits."""
    canonical = _parse_ipv4(raw, field="subnet_mask")
    value = int(ipaddress.IPv4Address(canonical))
    inverted = (~value) & 0xFFFFFFFF
    if inverted & (inverted + 1):
        raise JTComParseError(
            f"parse_management_network field='subnet_mask' raw={raw!r}: "
            "netmask must have contiguous one bits"
        )
    return canonical


def _control_value(control: Tag, *, field: str) -> str:
    """Extract a required value from a named form control."""
    if control.name == "select":
        options = control.find_all("option", recursive=False)
        selected = [option for option in options if option.has_attr("selected")]
        if len(selected) != 1:
            raise JTComParseError(
                f"parse_management_network field={field!r}: expected exactly one selected option"
            )
        value = selected[0].get("value")
    else:
        value = control.get("value")
    if not isinstance(value, str) or not value:
        raise JTComParseError(
            f"parse_management_network field={field!r}: missing control value"
        )
    return value


def parse_management_network(html: str) -> ManagementNetworkState:
    """Parse the exact management network form from ``ip.cgi`` HTML.

    The parser rejects ambiguous or unknown form data so incomplete pages cannot
    be mistaken for a complete current-state read.
    """
    soup = parse_html(html)
    forms = soup.find_all("form", id="ip_form")
    if len(forms) != 1:
        raise JTComParseError(
            "parse_management_network: expected exactly one ip_form form"
        )
    form = forms[0]
    if form.get("action") != "ip.cgi" or str(form.get("method", "")).lower() != "post":
        raise JTComParseError(
            "parse_management_network: ip_form must use POST action ip.cgi"
        )

    controls = form.find_all(["input", "select", "textarea"])
    values: dict[str, str] = {}
    for control in controls:
        name = control.get("name")
        if not isinstance(name, str) or not name:
            continue
        if name not in _EXPECTED_FIELDS:
            raise JTComParseError(
                f"parse_management_network field={name!r}: unrecognized named control"
            )
        if control.name != _EXPECTED_TAGS[name]:
            raise JTComParseError(
                f"parse_management_network field={name!r}: unexpected control type"
            )
        control_type = str(control.get("type", "text")).lower()
        if name == "cmd" and control_type != "hidden":
            raise JTComParseError(
                "parse_management_network field='cmd': expected hidden input"
            )
        if name in {"ip", "netmask", "gateway"} and control_type != "text":
            raise JTComParseError(
                f"parse_management_network field={name!r}: expected text input"
            )
        if name in values:
            raise JTComParseError(
                f"parse_management_network field={name!r}: duplicate control"
            )
        values[name] = _control_value(control, field=name)

    missing = _EXPECTED_FIELDS - values.keys()
    if missing:
        raise JTComParseError(
            f"parse_management_network: missing fields {sorted(missing)!r}"
        )
    if values["cmd"] != "ip":
        raise JTComParseError(
            f"parse_management_network field='cmd' raw={values['cmd']!r}: expected 'ip'"
        )
    if values["dhcp_state"] not in ("0", "1"):
        raise JTComParseError(
            f"parse_management_network field='dhcp_state' raw={values['dhcp_state']!r}: "
            "expected 0 or 1"
        )

    return ManagementNetworkState(
        dhcp_enabled=values["dhcp_state"] == "1",
        ip_address=_parse_ipv4(values["ip"], field="ip_address"),
        subnet_mask=_parse_netmask(values["netmask"]),
        gateway=_parse_ipv4(values["gateway"], field="gateway"),
    )
