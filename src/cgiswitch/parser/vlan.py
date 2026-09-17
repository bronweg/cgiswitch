"""Parser for JTCom VLAN configuration pages."""

from __future__ import annotations

import re

from cgiswitch.client.errors import JTComParseError
from cgiswitch.model.vlan import VlanEntry, VlanPortConfig
from cgiswitch.parser.html import normalize_text, parse_html


def _parse_vlan_id(raw: str, *, field: str, context: str) -> int:
    """Parse a VLAN ID and report malformed switch data consistently."""
    if not re.fullmatch(r"[0-9]+", raw):
        raise JTComParseError(
            f"{context} field={field!r} raw={raw!r}: "
            "expected an integer VLAN ID"
        )
    vlan_id = int(raw)
    if not 1 <= vlan_id <= 4094:
        raise JTComParseError(
            f"{context} field={field!r} raw={raw!r}: "
            "VLAN ID must be in range 1-4094"
        )
    return vlan_id


def _parse_permit_vlan_token(raw: str, *, context: str) -> list[int]:
    """Parse one permit VLAN ID or inclusive VLAN range."""
    range_match = re.fullmatch(r"([0-9]+)\s*-\s*([0-9]+)", raw)
    if range_match is None:
        return [_parse_vlan_id(raw, field="permit_vlans", context=context)]

    start = _parse_vlan_id(
        range_match.group(1), field="permit_vlans", context=context
    )
    end = _parse_vlan_id(
        range_match.group(2), field="permit_vlans", context=context
    )
    if start > end:
        raise JTComParseError(
            f"{context} field='permit_vlans' raw={raw!r}: "
            "VLAN range start must not exceed its end"
        )
    return list(range(start, end + 1))


def parse_static_vlans(html: str) -> list[VlanEntry]:
    """Parse the static VLAN list page and return VLAN entries.

    Locates the ``<form id="vlanDel">`` element and extracts each VLAN row
    from its embedded ``<table>``.  The table structure is:

    +----------+-----+---------+-----------+
    | checkbox | No. | VLAN ID | VLAN Name |
    +----------+-----+---------+-----------+

    Args:
        html: Raw HTML from the VLAN static configuration page.

    Returns:
        List of :class:`~cgiswitch.model.vlan.VlanEntry` objects with
        empty ``tagged_ports`` and ``untagged_ports`` (port membership is
        derived from the port-based VLAN page).

    Raises:
        JTComParseError: If the VLAN list is missing, malformed, or ambiguous.
    """
    soup = parse_html(html)
    form = soup.find("form", id="vlanDel")
    if form is None:
        raise JTComParseError("Could not find vlanDel form in VLAN static page")

    table = form.find("table")
    if table is None:
        raise JTComParseError("Could not find VLAN table inside vlanDel form")

    entries: list[VlanEntry] = []
    seen_ids: set[int] = set()
    for row_number, tr in enumerate(table.find_all("tr"), start=1):
        tds = tr.find_all("td")
        if len(tds) != 4:
            if not tds and tr.find_all("th"):
                continue  # genuine header row
            if not tds:
                continue  # whitespace-only structural row
            raise JTComParseError(
                f"parse_static_vlans field='row' raw={tr.get_text()!r} "
                f"context=VLAN row {row_number}: unexpected data row column count"
            )
        vlan_id_text = normalize_text(tds[2].get_text())
        vlan_name_text = normalize_text(tds[3].get_text())
        if vlan_id_text.lower() == "vlan id" and vlan_name_text.lower() == "vlan name":
            continue  # a legacy table may use <td> for its header
        vlan_id = _parse_vlan_id(
            vlan_id_text,
            field="vlan_id",
            context=f"parse_static_vlans VLAN row {row_number}",
        )
        if vlan_id in seen_ids:
            raise JTComParseError(
                f"parse_static_vlans field='vlan_id' raw={vlan_id_text!r} "
                f"context=VLAN row {row_number}: duplicate VLAN ID {vlan_id}"
            )
        seen_ids.add(vlan_id)
        entries.append(VlanEntry(vlan_id=vlan_id, name=vlan_name_text))

    if not entries:
        raise JTComParseError(
            "parse_static_vlans field='rows' raw=[]: no VLAN entries found"
        )
    return entries


def parse_port_vlan_settings(html: str) -> list[VlanPortConfig]:
    """Parse the port-based VLAN status table and return per-port config.

    Locates the *standalone* ``<table>`` (not inside any ``<form>``) that has
    "Port" and "VLAN Type" column headers and extracts each row.  The table
    structure is:

    +------+-----------+-------------+-------------+-------------+
    | Port | VLAN Type | Access VLAN | Native VLAN | Permit VLAN |
    +------+-----------+-------------+-------------+-------------+

    Permit VLANs may be ``--`` (none), a single integer, or a
    comma- / underscore-separated list of IDs and inclusive ranges
    (e.g. ``1,10-12`` or ``1_10_12``).

    Args:
        html: Raw HTML from the port-based VLAN configuration page.

    Returns:
        List of :class:`~cgiswitch.model.vlan.VlanPortConfig` objects.

    Raises:
        JTComParseError: If the port VLAN table is missing, malformed, or ambiguous.
    """
    soup = parse_html(html)

    # Find standalone table (not inside a form) with the right headers
    status_table = None
    for table in soup.find_all("table"):
        if table.find_parent("form") is not None:
            continue
        cell_texts = [
            normalize_text(cell.get_text()).lower()
            for cell in table.find_all(["th", "td"])
        ]
        if any(t == "port" for t in cell_texts) and any(
            "vlan type" in t for t in cell_texts
        ):
            status_table = table
            break

    if status_table is None:
        raise JTComParseError(
            "Could not find port VLAN status table in port-based VLAN page"
        )

    configs: list[VlanPortConfig] = []
    seen_ports: set[int] = set()
    for row_number, tr in enumerate(status_table.find_all("tr"), start=1):
        tds = tr.find_all("td")
        if len(tds) != 5:
            if not tds and tr.find_all("th"):
                continue
            if not tds:
                continue
            raise JTComParseError(
                f"parse_port_vlan_settings field='row' raw={tr.get_text()!r} "
                f"context=port row {row_number}: unexpected data row column count"
            )
        port_name = normalize_text(tds[0].get_text())
        vlan_type = normalize_text(tds[1].get_text())

        if port_name.lower() == "port" and vlan_type.lower() == "vlan type":
            continue
        access_vlan_text = normalize_text(tds[2].get_text())
        native_vlan_text = normalize_text(tds[3].get_text())
        permit_vlan_text = normalize_text(tds[4].get_text())

        context = f"parse_port_vlan_settings port={port_name!r} row {row_number}"
        port_match = re.fullmatch(r"Port\s*([1-9][0-9]*)", port_name, re.IGNORECASE)
        if port_match is None:
            raise JTComParseError(
                f"parse_port_vlan_settings field='port_name' raw={port_name!r} "
                f"context=port row {row_number}: expected a positive Port N identifier"
            )
        if vlan_type.lower() not in ("access", "trunk"):
            raise JTComParseError(
                f"parse_port_vlan_settings field='vlan_type' raw={vlan_type!r} "
                f"context={context}: expected Access or Trunk"
            )
        port_id = int(port_match.group(1))
        if port_id in seen_ports:
            raise JTComParseError(
                f"parse_port_vlan_settings field='port_name' raw={port_name!r} "
                f"context={context}: duplicate port row"
            )
        seen_ports.add(port_id)
        port_name = f"Port {port_id}"

        if vlan_type.lower() == "access":
            if access_vlan_text == "--":
                raise JTComParseError(
                    f"parse_port_vlan_settings field='access_vlan' raw={access_vlan_text!r} "
                    f"context={context}: required for Access mode"
                )
            access_vlan = _parse_vlan_id(
                access_vlan_text, field="access_vlan", context=context
            )
            if native_vlan_text != "--" or permit_vlan_text != "--":
                raise JTComParseError(
                    f"parse_port_vlan_settings field='inactive_vlan' "
                    f"raw={(native_vlan_text, permit_vlan_text)!r} context={context}: "
                    "Access mode requires inactive fields to be '--'"
                )
            native_vlan = None
        else:
            if native_vlan_text == "--":
                raise JTComParseError(
                    f"parse_port_vlan_settings field='native_vlan' raw={native_vlan_text!r} "
                    f"context={context}: required for Trunk mode"
                )
            native_vlan = _parse_vlan_id(
                native_vlan_text, field="native_vlan", context=context
            )
            if access_vlan_text != "--":
                raise JTComParseError(
                    f"parse_port_vlan_settings field='access_vlan' raw={access_vlan_text!r} "
                    f"context={context}: inactive for Trunk mode"
                )
            access_vlan = None

        permit_vlans: list[int] = []
        if permit_vlan_text != "--":
            for token in re.split(r"[,_]", permit_vlan_text):
                token = token.strip()
                if not token:
                    raise JTComParseError(
                        f"parse_port_vlan_settings field='permit_vlans' "
                        f"raw={permit_vlan_text!r} context={context}: empty token"
                    )
                try:
                    permit_vlans.extend(
                        _parse_permit_vlan_token(token, context=context)
                    )
                except JTComParseError as exc:
                    raise JTComParseError(
                        f"{context} field='permit_vlans' raw={permit_vlan_text!r}: {exc}"
                    ) from exc

        configs.append(
            VlanPortConfig(
                port_name=port_name,
                vlan_type=vlan_type,
                access_vlan=access_vlan,
                native_vlan=native_vlan,
                permit_vlans=permit_vlans,
            )
        )

    if not configs:
        raise JTComParseError(
            "parse_port_vlan_settings field='rows' raw=[]: no port VLAN entries found"
        )
    return configs


def parse_port_based_vlans(html: str) -> list[VlanPortConfig]:
    """Compatibility shim — delegates to :func:`parse_port_vlan_settings`.

    Args:
        html: Raw HTML from the port-based VLAN configuration page.

    Returns:
        List of :class:`~cgiswitch.model.vlan.VlanPortConfig` objects.
    """
    return parse_port_vlan_settings(html)
