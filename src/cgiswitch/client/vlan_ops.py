"""Low-level VLAN write operations for JTCom CGI switches.

Each function translates a strongly-typed request into the exact form-field
payload captured from the real switch and delegates to
:class:`~cgiswitch.client.session.JTComSession` for dispatch.

Confirmed payloads (real switch <switch-ip>):

    CREATE: POST /staticvlan.cgi
        vlanid=<id>&vlanname=<name>&cmd=add&page=inside
        → {"code":0,"data":""}

    DELETE: POST /staticvlan.cgi
        del=<id>[&del=<id2>…]&cmd=del&page=inside
        → {"code":0,"data":""}

    PORT ACCESS: POST /vlanport.cgi
        PortId=<0_1_…>&VlanType=0&AccessVlan=<id>&NativeVlan=1&PermitVlan=&page=inside
        → {"code":0,"data":""}

    PORT TRUNK: POST /vlanport.cgi
        PortId=<0_1_…>&VlanType=1&AccessVlan=1&NativeVlan=<id>&PermitVlan=<id1_id2_…>&page=inside
        → {"code":0,"data":""}
"""

from __future__ import annotations

import logging

from cgiswitch.client.session import JTComSession
from cgiswitch.vendor.jtcom.endpoints import VLAN_CREATE_DELETE, VLAN_PORT_SET

logger = logging.getLogger(__name__)

# VlanType values understood by the switch firmware.
_VLAN_TYPE_ACCESS: str = "0"
_VLAN_TYPE_TRUNK: str = "1"


def build_vlan_create_payload(
    vlan_id: int,
    name: str | None = None,
) -> dict[str, str]:
    """Build the form payload used to create or rename a static VLAN."""
    return {"vlanid": str(vlan_id), "vlanname": name or "", "cmd": "add"}


def build_vlan_delete_payload(vlan_ids: list[int]) -> list[tuple[str, str]]:
    """Build a form payload that deletes the supplied static VLANs."""
    safe_ids = [vlan_id for vlan_id in vlan_ids if vlan_id != 1]
    if not safe_ids:
        raise ValueError("vlan_ids must contain at least one deletable VLAN (not 1)")
    form_fields = [("del", str(vlan_id)) for vlan_id in sorted(safe_ids)]
    form_fields.append(("cmd", "del"))
    return form_fields


def build_vlan_port_payload(
    port_ids: list[int],
    vlan_type: str,
    access_vlan: int | None,
    native_vlan: int | None,
    permit_vlans: list[int],
) -> dict[str, str]:
    """Build the JTCom form payload for one or more port VLAN settings."""
    if not port_ids:
        raise ValueError("port_ids must not be empty")
    if any(port_id < 1 for port_id in port_ids):
        raise ValueError(f"port_ids must be 1-based positive integers, got {port_ids!r}")
    vt_lower = vlan_type.lower()
    if vt_lower not in {"access", "trunk"}:
        raise ValueError(f"vlan_type must be 'access' or 'trunk', got {vlan_type!r}")

    port_id_str = "_".join(str(port_id - 1) for port_id in sorted(port_ids))
    if vt_lower == "access":
        vlan_type_val = _VLAN_TYPE_ACCESS
        av = str(access_vlan) if access_vlan is not None else "1"
        nv, pv = "1", ""
    else:
        vlan_type_val = _VLAN_TYPE_TRUNK
        av, nv = "1", str(native_vlan) if native_vlan is not None else "1"
        pv = "_".join(str(vlan_id) for vlan_id in sorted(permit_vlans))
    return {
        "PortId": port_id_str,
        "VlanType": vlan_type_val,
        "AccessVlan": av,
        "NativeVlan": nv,
        "PermitVlan": pv,
    }


def vlan_create(
    session: JTComSession,
    vlan_id: int,
    name: str | None = None,
) -> None:
    """Create a static VLAN on the switch.

    Args:
        session: Active authenticated session.
        vlan_id: 802.1Q VLAN identifier (2–4094; 1 is reserved).
        name: Optional human-readable VLAN name.  Defaults to an empty
            string if not provided (switch displays blank).

    Raises:
        JTComSwitchError: If the switch returns a non-zero response code.
    """
    logger.debug("Creating VLAN %d (name=%r)", vlan_id, name)
    session.post(VLAN_CREATE_DELETE, data=build_vlan_create_payload(vlan_id, name))


def vlan_delete(
    session: JTComSession,
    vlan_ids: list[int],
) -> None:
    """Delete one or more static VLANs from the switch.

    The switch accepts multiple ``del`` keys in a single POST body.
    VLAN 1 is silently skipped even if included in *vlan_ids*.

    Args:
        session: Active authenticated session.
        vlan_ids: List of VLAN IDs to delete.  Must not be empty.

    Raises:
        ValueError: If *vlan_ids* is empty after filtering out VLAN 1.
        JTComSwitchError: If the switch returns a non-zero response code.
    """
    logger.debug("Deleting VLANs %s", vlan_ids)
    session.post(VLAN_CREATE_DELETE, data=build_vlan_delete_payload(vlan_ids))


def vlan_set_port(
    session: JTComSession,
    port_ids: list[int],
    vlan_type: str,
    access_vlan: int | None,
    native_vlan: int | None,
    permit_vlans: list[int],
) -> None:
    """Set VLAN membership for one or more ports.

    The public helper accepts 1-based port IDs like the rest of the project.
    The JTCom CGI payload uses 0-based port values; conversion is intentionally
    localized here at the vendor transport boundary.

    Args:
        session: Active authenticated session.
        port_ids: 1-based port IDs.
        vlan_type: ``"access"`` or ``"trunk"`` (case-insensitive).
        access_vlan: VLAN ID for Access mode (ignored in Trunk mode).
        native_vlan: Native VLAN ID for Trunk mode (ignored in Access mode).
        permit_vlans: Full JTCom trunk permit list. On JTCom this includes
            ``native_vlan``.

    Raises:
        ValueError: If *port_ids* is empty or *vlan_type* is invalid.
        JTComSwitchError: If the switch returns a non-zero response code.
    """
    payload = build_vlan_port_payload(
        port_ids, vlan_type, access_vlan, native_vlan, permit_vlans,
    )

    logger.debug(
        "Setting port(s) %s → %s (AccessVlan=%s NativeVlan=%s PermitVlan=%s)",
        payload["PortId"],
        vlan_type,
        payload["AccessVlan"],
        payload["NativeVlan"],
        payload["PermitVlan"],
    )
    session.post(
        VLAN_PORT_SET,
        data=payload,
    )
