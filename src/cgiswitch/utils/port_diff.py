"""Port configuration change-set planner.

Compares a *current* port state (as returned by the port.cgi parser) against
a *desired* declarative state and produces a :class:`PortChangeSet` describing
which ports need to be reconfigured.
"""

from __future__ import annotations

from cgiswitch.model.port import PortChangeSet, PortConfig, PortSettings


def plan_port_changes(
    current: list[PortSettings],
    desired: list[PortConfig],
) -> PortChangeSet:
    """Compute the minimal set of port changes needed to reach *desired*.

    Matches ports by :attr:`~.PortSettings.port_id` (1-based).  A port is
    included in :attr:`~.PortChangeSet.update` if at least one non-``None``
    field in *desired* differs from the corresponding value in *current*.
    Ports present in *desired* but absent from *current* are silently ignored.
    Ports present in *current* but absent from *desired* are left unchanged.

    Args:
        current: List of :class:`PortSettings` representing the current state.
        desired: List of :class:`PortConfig` representing the target state.

    Returns:
        A :class:`PortChangeSet` with :attr:`~.PortChangeSet.update` sorted
        ascending by ``port_id``.
    """
    current_by_id: dict[int, PortSettings] = {s.port_id: s for s in current}
    updates: list[PortConfig] = []

    for cfg in sorted(desired, key=lambda c: c.port_id):
        existing = current_by_id.get(cfg.port_id)
        if existing is None:
            continue  # unknown port — skip silently
        if _needs_update(existing, cfg):
            updates.append(cfg)

    return PortChangeSet(update=updates)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _needs_update(current: PortSettings, desired: PortConfig) -> bool:
    """Return ``True`` if any non-``None`` desired field differs from current."""
    if desired.admin_up is not None and desired.admin_up != current.admin_up:
        return True
    if (
        desired.speed_duplex is not None
        and desired.speed_duplex != current.speed_duplex
    ):
        return True
    return (
        desired.flow_control is not None
        and desired.flow_control != current.flow_control
    )
