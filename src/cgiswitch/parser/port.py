"""Parser for JTCom port/interface settings pages (port.cgi)."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from cgiswitch.client.errors import JTComParseError
from cgiswitch.model.port import PortOperStatus, PortSettings

# Matches "Port N" port names (case-insensitive), capturing the number.
_PORT_NAME_RE: re.Pattern[str] = re.compile(r"Port\s*(\d+)", re.IGNORECASE)

# Matches speed/duplex strings like "1000M/Full", "10G/Full", "100M/Half".
# Group 1: numeric speed; Group 2: unit (M or G); Group 3: duplex (Full/Half).
_SPEED_RE: re.Pattern[str] = re.compile(
    r"(\d+(?:\.\d+)?)(G|M)/(Full|Half)",
    re.IGNORECASE,
)


def parse_port_page(
    html: str,
) -> tuple[list[PortSettings], list[PortOperStatus]]:
    """Parse the port settings page and return parallel settings/oper lists.

    Locates the standalone status table in ``port.cgi`` (the table that is
    *not* wrapped in a ``<form>`` element) and extracts one row per port.

    Args:
        html: Raw HTML from ``port.cgi``.

    Returns:
        A ``(settings, oper)`` tuple where both lists have the same length and
        the same ordering by port_id.

    Raises:
        JTComParseError: If the status table cannot be found or yields no rows.
    """
    soup = BeautifulSoup(html, "lxml")
    table = _find_status_table(soup)
    if table is None:
        raise JTComParseError(
            "No port status table found in port.cgi response; "
            "expected a standalone <table> with 6 data columns."
        )

    settings_list: list[PortSettings] = []
    oper_list: list[PortOperStatus] = []

    seen_ids: set[int] = set()
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if not cells:
            continue  # header rows or spacer rows
        if len(cells) < 6:
            raise JTComParseError(
                f"parse_port_page field='row' raw={row.get_text()!r}: incomplete port row"
            )
        port_text = cells[0].get_text(strip=True)
        m = _PORT_NAME_RE.fullmatch(port_text)
        if not m or int(m.group(1)) < 1:
            raise JTComParseError(
                f"parse_port_page field='port_id' raw={port_text!r}: expected positive Port N"
            )
        port_id = int(m.group(1))
        if port_id in seen_ids:
            raise JTComParseError(
                f"parse_port_page field='port_id' raw={port_text!r}: duplicate port {port_id}"
            )
        seen_ids.add(port_id)

        admin_text = cells[1].get_text(strip=True).lower()
        admin_up = admin_text == "enable" if admin_text in ("enable", "disable") else None
        speed_config = cells[2].get_text(strip=True) or None
        speed_actual = cells[3].get_text(strip=True)
        flow_text = cells[4].get_text(strip=True).lower()
        flow_control: bool | None = (
            flow_text == "on" if flow_text in ("on", "off") else None
        )

        link_up, speed_mbps, duplex = _parse_actual_speed(speed_actual)

        settings_list.append(
            PortSettings(
                port_id=port_id,
                name=port_text,
                admin_up=admin_up,
                speed_duplex=speed_config,
                flow_control=flow_control,
            )
        )
        oper_list.append(
            PortOperStatus(
                port_id=port_id,
                link_up=link_up,
                negotiated_speed_mbps=speed_mbps,
                duplex=duplex,
            )
        )

    if not settings_list:
        raise JTComParseError(
            "Zero ports parsed from port.cgi — "
            "HTML structure may have changed."
        )

    return settings_list, oper_list


# ---------------------------------------------------------------------------
# Legacy shim — keep old function name so existing callers compile.
# Will be removed once all call sites are updated.
# ---------------------------------------------------------------------------

def parse_port_settings(html: str) -> list[PortSettings]:
    """Parse port settings; returns only the settings list.

    Prefer :func:`parse_port_page` for full settings + oper data.

    Args:
        html: Raw HTML from ``port.cgi``.

    Returns:
        List of :class:`.PortSettings` objects.
    """
    settings, _ = parse_port_page(html)
    return settings


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _find_status_table(soup: BeautifulSoup) -> Tag | None:
    """Find the port status ``<table>`` that is NOT inside a ``<form>``.

    The status table has data rows with exactly 6 ``<td>`` cells where the
    first cell matches the "Port N" pattern.
    """
    for table in soup.find_all("table"):
        if table.find_parent("form"):
            continue  # skip config-form tables
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) >= 6 and _PORT_NAME_RE.match(
                cells[0].get_text(strip=True)
            ):
                return table
    return None


def _parse_actual_speed(
    actual: str,
) -> tuple[bool | None, int | None, str | None]:
    """Convert the Speed/Duplex *Actual* column value to structured fields.

    Args:
        actual: Raw text from the Actual speed/duplex cell (e.g.
            ``"Link Down"``, ``"1000M/Full"``, ``"10G/Full"``).

    Returns:
        ``(link_up, speed_mbps, duplex)`` triple.
        Returns ``(False, None, None)`` for "Link Down" variants.
        Returns ``(None, None, None)`` for unrecognised text.
    """
    text = actual.strip()
    if not text or "link down" in text.lower():
        return False, None, None
    sm = _SPEED_RE.match(text)
    if not sm:
        return None, None, None
    raw_speed = float(sm.group(1))
    unit = sm.group(2).upper()
    duplex = sm.group(3).lower()
    speed_mbps = int(raw_speed * 1000) if unit == "G" else int(raw_speed)
    return True, speed_mbps, duplex
