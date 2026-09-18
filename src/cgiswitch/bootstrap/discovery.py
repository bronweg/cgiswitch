"""Read-only discovery across all endpoint/credential candidates."""

from __future__ import annotations

from dataclasses import dataclass

from cgiswitch.bootstrap.identity import DeviceIdentity
from cgiswitch.bootstrap.model import BootstrapConfig
from cgiswitch.client.errors import JTComAuthError, JTComRequestError
from cgiswitch.client.ip_ops import read_management_network
from cgiswitch.client.session import JTComSession
from cgiswitch.model.management import ManagementNetworkState
from cgiswitch.parser.device import parse_device_info
from cgiswitch.vendor.jtcom.endpoints import DEVICE_INFO


@dataclass(frozen=True)
class Candidate:
    """A verified discovery result without credential values."""

    endpoint: str
    target_credentials: bool
    identity: DeviceIdentity
    network: ManagementNetworkState


def discover(config: BootstrapConfig) -> Candidate:
    """Inspect every candidate before selecting the preferred matching state."""
    found: list[Candidate] = []
    seen: set[tuple[str, bool]] = set()
    for endpoint, use_target in (
        (config.target_url, True), (config.factory_url, True),
        (config.target_url, False), (config.factory_url, False),
    ):
        endpoint = endpoint.rstrip('/')
        if config.factory_password == config.target_password:
            use_target = True
        if (endpoint, use_target) in seen:
            continue
        seen.add((endpoint, use_target))
        session = JTComSession(
            endpoint, config.credentials(use_target),
            timeout_s=config.timeout_s, verify_tls=config.verify_tls,
        )
        try:
            try:
                session.login()
            except (JTComAuthError, JTComRequestError):
                continue
            identity = DeviceIdentity.from_device(parse_device_info(session.get(DEVICE_INFO)))
            config.verify_expected(identity)
            network = read_management_network(session)
            found.append(Candidate(endpoint, use_target, identity, network))
        finally:
            session._discard()
    if not found:
        raise ValueError('No candidate authenticated the expected device')
    selected = found[0]
    if any(candidate.identity != selected.identity for candidate in found):
        raise ValueError('Different physical devices answered discovery')
    if any(candidate.network != selected.network for candidate in found):
        raise ValueError('Management state changed or was inconsistent during discovery')
    if len({candidate.target_credentials for candidate in found}) > 1:
        raise ValueError('Both credentials authenticate; ambiguous security state')
    if selected.network == config.management.as_state() and not any(
        candidate.endpoint == config.target_url.rstrip('/') for candidate in found
    ):
        raise ValueError('Desired management state is not reachable at the target endpoint')
    return selected
