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
            "expected a standalone port table with recognized headers."
        )

    columns, width = _header_columns(table)
    settings_list: list[PortSettings] = []
    oper_list: list[PortOperStatus] = []

    seen_ids: set[int] = set()
    for row in table.find_all("tr"):
        if row.find("th") or row.find_parent("thead"):
            continue
        cells = row.find_all("td", recursive=False)
        if not cells:
            continue  # header rows or spacer rows
        if len(cells) != width:
            raise JTComParseError(
                f"parse_port_page field='row' raw={row.get_text()!r}: "
                "incomplete or misaligned port row"
            )
        port_text = cells[columns["port"]].get_text(strip=True)
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

        admin_text = cells[columns["admin status"]].get_text(strip=True).lower()
        admin_up = admin_text == "enable" if admin_text in ("enable", "disable") else None
        speed_config = cells[columns["speed/duplex config"]].get_text(strip=True) or None
        speed_actual = cells[columns["speed/duplex actual"]].get_text(strip=True)
        flow_text = cells[columns["flow control config"]].get_text(strip=True).lower()
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
# Internals
# ---------------------------------------------------------------------------

_REQUIRED_HEADERS = (
    "port", "admin status", "speed/duplex config", "speed/duplex actual",
    "flow control config", "flow control actual",
)


def _find_status_table(soup: BeautifulSoup) -> Tag | None:
    """Locate a standalone port table without relying on column positions."""
    candidates = []
    for table in soup.find_all("table"):
        if table.find_parent("form"):
            continue
        labels = [cell.get_text(" ", strip=True).lower() for cell in table.find_all("th")]
        if any(label in {"port", "admin status", "speed/duplex"} for label in labels) or any(
            _PORT_NAME_RE.fullmatch(cell.get_text(strip=True)) for cell in table.find_all("td")
        ):
            candidates.append(table)
    if len(candidates) > 1:
        raise JTComParseError("parse_port_page: ambiguous port status tables")
    return candidates[0] if candidates else None


def _header_columns(table: Tag) -> tuple[dict[str, int], int]:
    """Expand grouped HTML headers and resolve required semantic column names."""
    rows = [row for row in table.find_all("tr") if row.find("th")]
    grid: dict[tuple[int, int], str] = {}
    for row_index, row in enumerate(rows):
        column = 0
        for cell in row.find_all("th", recursive=False):
            while (row_index, column) in grid:
                column += 1
            raw = cell.get_text(" ", strip=True)
            label = " ".join(raw.lower().split())
            try:
                rowspan = int(str(cell.get("rowspan", "1")))
                colspan = int(str(cell.get("colspan", "1")))
                if not 1 <= rowspan <= len(rows) - row_index or not 1 <= colspan <= 256:
                    raise ValueError("invalid header span")
            except ValueError as exc:
                raise JTComParseError(
                    f"parse_port_page field='header' raw={raw!r}: invalid span"
                ) from exc
            for r in range(row_index, row_index + rowspan):
                for c in range(column, column + colspan):
                    if (r, c) in grid:
                        raise JTComParseError("parse_port_page field='header': overlapping spans")
                    grid[r, c] = label
            column += colspan
    width = max((column + 1 for _, column in grid), default=0)
    columns: dict[str, int] = {}
    for column in range(width):
        parts: list[str] = []
        for row_index in range(len(rows)):
            if (row_index, column) not in grid:
                raise JTComParseError("parse_port_page field='header': incomplete header grid")
            label = grid[row_index, column]
            if not parts or label != parts[-1]:
                parts.append(label)
        name = " ".join(parts)
        if name in _REQUIRED_HEADERS:
            if name in columns:
                raise JTComParseError(
                    f"parse_port_page field='header' raw={name!r}: duplicate required header"
                )
            columns[name] = column
    missing = sorted(set(_REQUIRED_HEADERS) - columns.keys())
    if missing:
        raise JTComParseError(
            f"parse_port_page field='header' raw={list(grid.values())!r}: "
            f"missing or unrecognized required headers: {missing}"
        )
    return columns, width


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
