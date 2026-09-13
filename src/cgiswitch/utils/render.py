"""Diff renderer for device plans."""

from __future__ import annotations

from typing import Any

from cgiswitch.utils.device_diff import DevicePlan


def render_diff(plan: DevicePlan) -> dict[str, Any]:
    """Serialize *plan* to a JSON-serializable dict.

    Returns:
        A dict with keys:

        - ``"summary"`` — count of each change kind.
        - ``"total_changes"`` — total number of changes.
        - ``"changes"`` — list of change dicts (``kind``, ``key``, ``details``).
    """
    return {
        "summary": dict(plan.summary),
        "total_changes": len(plan.changes),
        "changes": [
            {"kind": c.kind, "key": c.key, "details": c.details}
            for c in plan.changes
        ],
    }
