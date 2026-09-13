"""Parser for JTCom VLAN configuration pages."""

from __future__ import annotations

import contextlib
import re

from cgiswitch.client.errors import JTComParseError
from cgiswitch.model.vlan import VlanEntry, VlanPortConfig
from cgiswitch.parser.html import normalize_text, parse_html


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
        JTComParseError: If the VLAN list table cannot be found.
    """
    soup = parse_html(html)
    form = soup.find("form", id="vlanDel")
    if form is None:
        raise JTComParseError("Could not find vlanDel form in VLAN static page")

    table = form.find("table")
    if table is None:
        raise JTComParseError("Could not find VLAN table inside vlanDel form")

    entries: list[VlanEntry] = []
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue  # skip header rows (only <th>) or incomplete rows
        vlan_id_text = normalize_text(tds[2].get_text())
        vlan_name_text = normalize_text(tds[3].get_text())
        try:
            vlan_id = int(vlan_id_text)
        except ValueError:
            continue  # skip non-numeric rows
        entries.append(VlanEntry(vlan_id=vlan_id, name=vlan_name_text))

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
    comma- / underscore-separated list (e.g. ``1,10`` or ``1_10``).

    Args:
        html: Raw HTML from the port-based VLAN configuration page.

    Returns:
        List of :class:`~cgiswitch.model.vlan.VlanPortConfig` objects.

    Raises:
        JTComParseError: If the port VLAN status table cannot be found.
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
    first_row = True
    for tr in status_table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue
        port_name = normalize_text(tds[0].get_text())
        vlan_type = normalize_text(tds[1].get_text())

        # Skip header row if it uses <td> instead of <th>
        if first_row and port_name.lower() == "port":
            first_row = False
            continue
        first_row = False

        access_vlan_text = normalize_text(tds[2].get_text())
        native_vlan_text = normalize_text(tds[3].get_text())
        permit_vlan_text = normalize_text(tds[4].get_text())

        access_vlan: int | None = None
        if access_vlan_text not in ("--", ""):
            with contextlib.suppress(ValueError):
                access_vlan = int(access_vlan_text)

        native_vlan: int | None = None
        if native_vlan_text not in ("--", ""):
            with contextlib.suppress(ValueError):
                native_vlan = int(native_vlan_text)

        permit_vlans: list[int] = []
        if permit_vlan_text not in ("--", ""):
            for token in re.split(r"[,_]+", permit_vlan_text):
                token = token.strip()
                if token:
                    with contextlib.suppress(ValueError):
                        permit_vlans.append(int(token))

        configs.append(
            VlanPortConfig(
                port_name=port_name,
                vlan_type=vlan_type,
                access_vlan=access_vlan,
                native_vlan=native_vlan,
                permit_vlans=permit_vlans,
            )
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
