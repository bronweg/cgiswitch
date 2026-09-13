"""Low-level port write operations for JTCom CGI switches.

Each function translates a strongly-typed request into the exact form-field
payload captured from the real switch and delegates to
:class:`~cgiswitch.client.session.JTComSession` for dispatch.

Confirmed payloads (real switch <switch-ip>):

    DISABLE PORT 1: POST /port.cgi
        portid=0&state=0&speed_duplex=0&flow=1&page=inside
        → {"code":0,"data":""}

    ENABLE PORT 1: POST /port.cgi
        portid=0&state=1&speed_duplex=0&flow=1&page=inside
        → {"code":0,"data":""}

    MULTIPLE PORTS (same settings): POST /port.cgi
        portid=0&portid=1&state=1&speed_duplex=0&flow=1&page=inside
        → {"code":0,"data":""}

Fields:
    portid:       0-based port index (Port 1 = 0, …, Port 6 = 5)
    state:        "1" = Enable, "0" = Disable
    speed_duplex: CGI integer code (see SPEED_TOKEN_TO_CODE below)
    flow:         "1" = On, "0" = Off
"""

from __future__ import annotations

import logging

from cgiswitch.client.session import JTComSession
from cgiswitch.model.port import PortChangeSet, PortConfig, PortSettings
from cgiswitch.vendor.jtcom.endpoints import PORT_SETTINGS

logger = logging.getLogger(__name__)

# Maps the speed/duplex display token (as stored in PortSettings.speed_duplex
# and shown in the switch UI) to the integer code expected by the CGI endpoint.
# Confirmed from port.cgi form option values.
SPEED_TOKEN_TO_CODE: dict[str, str] = {
    "Auto": "0",
    "10M/Half": "1",
    "10M/Full": "2",
    "100M/Half": "3",
    "100M/Full": "4",
    "1000M/Full": "5",
    "2500M/Full": "6",
    "10G/Full": "7",
}


def apply_port_changes(
    session: JTComSession,
    current_settings: list[PortSettings],
    change_set: PortChangeSet,
) -> None:
    """Apply port configuration changes to the switch.

    For each port in *change_set.update*, merges the desired change with the
    current settings (filling in ``None`` fields) and issues a single POST to
    ``port.cgi``.  Ports are processed in ascending ``port_id`` order.

    Args:
        session: Active authenticated session.
        current_settings: Current port settings from ``port.cgi`` (used to fill
            in any ``None`` fields in :class:`PortConfig`).
        change_set: Planned changes as returned by
            :func:`~cgiswitch.utils.port_diff.plan_port_changes`.

    Raises:
        ValueError: If a required speed/duplex token is unknown.
        JTComSwitchError: If the switch returns a non-zero response code.
    """
    if not change_set.update:
        return

    settings_by_id: dict[int, PortSettings] = {s.port_id: s for s in current_settings}

    for cfg in change_set.update:
        current = settings_by_id.get(cfg.port_id)
        payload = _build_port_payload(cfg, current)
        logger.debug("Setting port %d: %s", cfg.port_id, payload)
        session.post(PORT_SETTINGS, data=payload)
        logger.info("Port %d configuration applied", cfg.port_id)


def _build_port_payload(
    desired: PortConfig,
    current: PortSettings | None,
) -> dict[str, str]:
    """Build the CGI form dict for a single port POST.

    Merges *desired* (non-None fields) with *current* (fallback for None fields).
    The ``portid`` value is 0-based (CGI convention), converted from the
    1-based :attr:`PortConfig.port_id`.

    Args:
        desired: The desired port configuration (may have ``None`` fields).
        current: Current port settings used as fallback for ``None`` fields.
            If ``None``, all fields in *desired* must be non-``None``.

    Returns:
        A ``dict[str, str]`` ready to pass to ``session.post()``.

    Raises:
        ValueError: If a required field is ``None`` in both *desired* and
            *current*, or if the speed/duplex token is not recognised.
    """
    # Resolve admin_up
    admin_up: bool
    if desired.admin_up is not None:
        admin_up = desired.admin_up
    elif current is not None:
        admin_up = current.admin_up
    else:
        raise ValueError(f"port_id={desired.port_id}: admin_up is None and no current settings")

    # Resolve speed_duplex
    speed_token: str | None = desired.speed_duplex
    if speed_token is None:
        speed_token = current.speed_duplex if current is not None else None
    if speed_token is None:
        raise ValueError(f"port_id={desired.port_id}: speed_duplex is None and no current settings")
    speed_code = SPEED_TOKEN_TO_CODE.get(speed_token)
    if speed_code is None:
        raise ValueError(
            f"port_id={desired.port_id}: unknown speed/duplex token {speed_token!r}; "
            f"valid tokens: {sorted(SPEED_TOKEN_TO_CODE)}"
        )

    # Resolve flow_control
    flow_control: bool
    if desired.flow_control is not None:
        flow_control = desired.flow_control
    elif current is not None and current.flow_control is not None:
        flow_control = current.flow_control
    else:
        # Default to Off when unknown (safer than enabling flow control)
        flow_control = False

    return {
        "portid": str(desired.port_id - 1),   # CGI uses 0-based index
        "state": "1" if admin_up else "0",
        "speed_duplex": speed_code,
        "flow": "1" if flow_control else "0",
    }
