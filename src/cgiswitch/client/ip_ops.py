"""Internal operations for the JTCom management network page."""

from __future__ import annotations

from cgiswitch.client.management_contracts import build_management_network_payload
from cgiswitch.client.session import JTComSession
from cgiswitch.model.management import ManagementNetworkConfig, ManagementNetworkState
from cgiswitch.parser.management import parse_management_network
from cgiswitch.vendor.jtcom.endpoints import MANAGEMENT_NETWORK


def read_management_network(session: JTComSession) -> ManagementNetworkState:
    """Read and parse the switch management network configuration."""
    return parse_management_network(session.get(MANAGEMENT_NETWORK))


def set_management_network_once(
    session: JTComSession,
    desired: ManagementNetworkConfig,
) -> None:
    """Set a static management IPv4 configuration with one write attempt."""
    state = desired.as_state()
    payload = build_management_network_payload(
        state.ip_address, state.subnet_mask, state.gateway,
    )
    session._post_once(MANAGEMENT_NETWORK, payload)
