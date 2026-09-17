"""Internal, hardware-confirmed system operations; no arbitrary command API."""

from cgiswitch.client.management_contracts import build_system_payload
from cgiswitch.client.session import JTComSession
from cgiswitch.vendor.jtcom.endpoints import SYSCMD


def save_config(session: JTComSession) -> None:
    """Save once, requiring the observed success envelope without POST retry."""
    session._post_once(SYSCMD, build_system_payload("saveconfig"))
