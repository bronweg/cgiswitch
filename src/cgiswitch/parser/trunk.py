"""Parser for JTCom trunk/LAG configuration pages."""

from __future__ import annotations

from cgiswitch.model.trunk import TrunkEntry


def parse_trunk_groups(html: str) -> list[TrunkEntry]:
    """Parse the trunk group configuration page.

    Args:
        html: Raw HTML from the trunk group page.

    Returns:
        List of parsed TrunkEntry objects.
    """
    raise NotImplementedError("parse_trunk_groups() not yet implemented")


def parse_lacp_status(html: str) -> list[TrunkEntry]:
    """Parse LACP status page.

    Args:
        html: Raw HTML from the LACP status page.

    Returns:
        List of parsed TrunkEntry objects.
    """
    raise NotImplementedError("parse_lacp_status() not yet implemented")
