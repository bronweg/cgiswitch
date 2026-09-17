"""Internal one-shot static IPv4 transition with same-device reconciliation."""

from __future__ import annotations

import ipaddress
import math
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from cgiswitch.bootstrap.errors import JTComTransitionError
from cgiswitch.bootstrap.identity import DeviceIdentity
from cgiswitch.client.errors import JTComRequestError
from cgiswitch.client.ip_ops import read_management_network, set_management_network_once
from cgiswitch.client.session import JTComCredentials, JTComSession
from cgiswitch.model.management import ManagementNetworkConfig
from cgiswitch.parser.device import parse_device_info
from cgiswitch.vendor.jtcom.endpoints import DEVICE_INFO


@dataclass(frozen=True)
class NetworkTransitionResult:
    """Only verified final state is reported as a successful transition."""

    changed: bool
    endpoint: str
    identity: DeviceIdentity


def validate_endpoint(url: str) -> str:
    """Require an explicit IPv4 endpoint without credentials or URL extras."""
    if not isinstance(url, str):
        raise ValueError('Management endpoint must be an explicit HTTP(S) IPv4 URL')
    try:
        parsed = urlsplit(url)
        address = ipaddress.IPv4Address(parsed.hostname or '')
        port = parsed.port
    except ValueError:
        raise ValueError('Invalid management endpoint') from None
    if (
        parsed.scheme not in ('http', 'https') or parsed.username is not None
        or parsed.password is not None or parsed.query or parsed.fragment
        or parsed.path not in ('', '/') or address.is_multicast or address.is_unspecified
        or port == 0
    ):
        raise ValueError('Invalid management endpoint')
    return url.rstrip('/')


def transition_management_network(
    old_url: str, target_url: str, credentials: JTComCredentials,
    desired: ManagementNetworkConfig, *, timeout_s: float = 5.0,
    transition_timeout_s: float = 60.0, poll_interval_s: float = 1.0,
    verify_tls: bool = True,
) -> NetworkTransitionResult:
    """Reconcile one IP POST by observing the same device at the target URL.

    No persistence or reboot policy is inferred. Callers own discovery and
    explicit recovery. This is an internal primitive for the future bootstrap API.
    """
    old_url, target_url = validate_endpoint(old_url), validate_endpoint(target_url)
    if not isinstance(desired, ManagementNetworkConfig):
        raise ValueError('A validated static management configuration is required')
    if urlsplit(target_url).hostname != desired.address:
        raise ValueError('Target endpoint must match the desired management address')
    for value in (timeout_s, transition_timeout_s, poll_interval_s):
        if (
            isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value <= 0
        ):
            raise ValueError('Timeouts and polling interval must be finite positive numbers')
    identity: DeviceIdentity | None = None
    write_attempted = False
    target_reached = False
    stage = 'authenticate'
    current: JTComSession | None = None
    target: JTComSession | None = None
    try:
        current = JTComSession(old_url, credentials, timeout_s=timeout_s, verify_tls=verify_tls)
        current.login()
        stage = 'read_identity'
        identity = DeviceIdentity.from_device(parse_device_info(current.get(DEVICE_INFO)))
        stage = 'read_network'
        state = read_management_network(current)
        if state == desired.as_state():
            if old_url != target_url:
                stage = 'verify_target'
                target = JTComSession(
                    target_url, credentials, timeout_s=timeout_s, verify_tls=verify_tls,
                )
                target.login()
                target_reached = True
                identity.verify(parse_device_info(target.get(DEVICE_INFO)))
                if read_management_network(target) != desired.as_state():
                    raise ValueError('Target management state does not match desired configuration')
            return NetworkTransitionResult(False, target_url, identity)
        # A reachable foreign target must be detected before the disruptive write.
        if old_url != target_url:
            stage = 'target_preflight'
            target = JTComSession(
                    target_url, credentials, timeout_s=timeout_s, verify_tls=verify_tls,
                )
            try:
                target.login()
            except JTComRequestError:
                pass
            else:
                identity.verify(parse_device_info(target.get(DEVICE_INFO)))
            finally:
                target._discard()
                target = None
        stage = 'write_network'
        write_attempted = True
        try:
            set_management_network_once(current, desired)
        except JTComRequestError:
            # A dropped response cannot determine whether the write was accepted.
            pass
        finally:
            current._discard()
            current = None
        deadline = time.monotonic() + transition_timeout_s
        stage = 'reconnect'
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Target verification deadline expired')
            target = JTComSession(
                target_url, credentials, timeout_s=min(timeout_s, remaining), verify_tls=verify_tls,
            )
            try:
                target.login()
                target_reached = True
                stage = 'verify_identity'
                identity.verify(parse_device_info(target.get(DEVICE_INFO)))
                stage = 'verify_network'
                if read_management_network(target) != desired.as_state():
                    raise ValueError('Target management state does not match desired configuration')
                if time.monotonic() > deadline:
                    raise TimeoutError('Target verification deadline expired')
                return NetworkTransitionResult(True, target_url, identity)
            except JTComRequestError:
                stage = 'reconnect'
            finally:
                target._discard()
                target = None
            time.sleep(min(poll_interval_s, max(0.0, deadline - time.monotonic())))
    except Exception as error:
        raise JTComTransitionError(
            stage=stage, write_attempted=write_attempted, old_endpoint=old_url,
            target_endpoint=target_url, identity=identity, target_reached=target_reached,
            verification_completed=False, error=error,
        ) from None
    finally:
        if current is not None:
            current._discard()
        if target is not None:
            target._discard()
