"""Internal same-username credential transition with authentication readback."""

from __future__ import annotations

import math
from dataclasses import dataclass

from cgiswitch.bootstrap.errors import JTComTransitionError
from cgiswitch.bootstrap.identity import DeviceIdentity
from cgiswitch.bootstrap.network import validate_endpoint
from cgiswitch.client.errors import JTComAuthError, JTComRequestError
from cgiswitch.client.management_contracts import build_user_account_payload
from cgiswitch.client.session import JTComCredentials, JTComSession
from cgiswitch.client.user_ops import change_password_once
from cgiswitch.parser.device import parse_device_info
from cgiswitch.vendor.jtcom.endpoints import DEVICE_INFO


class _CredentialRejected(JTComAuthError):
    """Only a login rejection, not expiry during identity verification."""


@dataclass(frozen=True)
class CredentialTransitionResult:
    """Verified identity and change status; no credential material."""

    changed: bool
    endpoint: str
    identity: DeviceIdentity


def transition_credentials(
    url: str, current: JTComCredentials, target: JTComCredentials,
    expected_identity: DeviceIdentity, *, timeout_s: float = 5.0,
    verify_tls: bool = True,
) -> CredentialTransitionResult:
    """Try desired authentication first, then perform at most one password POST."""
    url = validate_endpoint(url)
    if not isinstance(expected_identity, DeviceIdentity):
        raise ValueError('Expected identity is required for credential transition')
    if current.username != target.username:
        raise ValueError('Username rotation is not supported')
    build_user_account_payload(target.username, target.password)
    if (
        isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float))
        or not math.isfinite(timeout_s) or timeout_s <= 0
    ):
        raise ValueError('Timeout must be a finite positive number')
    stage = 'target_authenticate'
    write_attempted = False
    target_reached = False
    verified: DeviceIdentity | None = None
    active: JTComSession | None = None

    def authenticate(credentials: JTComCredentials) -> JTComSession:
        session = JTComSession(url, credentials, timeout_s=timeout_s, verify_tls=verify_tls)
        try:
            try:
                session.login()
            except JTComAuthError:
                raise _CredentialRejected("Authentication rejected") from None
            expected_identity.verify(parse_device_info(session.get(DEVICE_INFO)))
        except Exception:
            session._discard()
            raise
        return session

    def verify_old_rejected() -> None:
        if current == target:
            return
        try:
            old_session = authenticate(current)
        except _CredentialRejected:
            return
        old_session._discard()
        raise ValueError('Both old and target credentials remain valid')

    try:
        try:
            active = authenticate(target)
        except _CredentialRejected:
            pass
        else:
            verified = expected_identity
            target_reached = True
            active._discard()
            active = None
            stage = 'verify_old_rejected'
            verify_old_rejected()
            return CredentialTransitionResult(False, url, expected_identity)
        stage = 'current_authenticate'
        active = authenticate(current)
        verified = expected_identity
        stage = 'write_credentials'
        write_attempted = True
        try:
            change_password_once(active, target.username, target.password)
        except JTComRequestError:
            # Authentication at the target reconciles an ambiguous write outcome.
            pass
        finally:
            active._discard()
            active = None
        stage = 'verify_target_credentials'
        active = authenticate(target)
        verified = expected_identity
        target_reached = True
        active._discard()
        active = None
        stage = 'verify_old_rejected'
        verify_old_rejected()
        return CredentialTransitionResult(True, url, expected_identity)
    except Exception as error:
        raise JTComTransitionError(
            stage=stage, write_attempted=write_attempted, old_endpoint=url,
            target_endpoint=url, identity=verified, target_reached=target_reached,
            verification_completed=False, error=error,
        ) from None
    finally:
        if active is not None:
            active._discard()
