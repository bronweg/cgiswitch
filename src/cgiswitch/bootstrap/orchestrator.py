"""Canonical bootstrap API: discovery, credentials, network, then persistence."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from cgiswitch.bootstrap.credentials import CredentialTransitionResult, transition_credentials
from cgiswitch.bootstrap.discovery import discover
from cgiswitch.bootstrap.errors import JTComTransitionError
from cgiswitch.bootstrap.identity import DeviceIdentity
from cgiswitch.bootstrap.model import BootstrapConfig
from cgiswitch.bootstrap.network import NetworkTransitionResult, transition_management_network
from cgiswitch.client.errors import JTComError
from cgiswitch.client.ip_ops import read_management_network
from cgiswitch.client.session import JTComSession
from cgiswitch.client.system_ops import save_config
from cgiswitch.parser.device import parse_device_info
from cgiswitch.vendor.jtcom.endpoints import DEVICE_INFO


class JTComBootstrapError(JTComError):
    """Structured partial progress without rollback or sensitive error data."""

    def __init__(self, result: dict[str, Any]) -> None:
        self._result = result
        super().__init__('Bootstrap failed; rerun discovery to reconcile partial progress')

    def as_result(self) -> dict[str, Any]:
        return {**self._result, 'msg': str(self)}


def bootstrap_switch(config: BootstrapConfig, *, check_mode: bool = False) -> dict[str, Any]:
    """Converge a known switch using one public, controller-side bootstrap path.

    Every non-check run verifies the final identity and network before one
    save barrier, including a logically unchanged rerun. Runtime readback cannot
    prove prior persistence. Check mode never saves or changes configuration.
    """
    if not isinstance(config, BootstrapConfig) or type(check_mode) is not bool:
        raise ValueError('Validated BootstrapConfig and boolean check_mode are required')
    stage = 'discovery'
    failed_operation: dict[str, str] | None = None
    completed: list[dict[str, str]] = []
    write_attempted = False
    logical_changed = False
    endpoint: str | None = None
    identity: DeviceIdentity | None = None
    try:
        candidate = discover(config)
        endpoint, identity = candidate.endpoint, candidate.identity
        operations: list[dict[str, str]] = []
        if not candidate.target_credentials:
            operations.append({'key': 'credentials:update'})
        if candidate.network != config.management.as_state():
            operations.append({'key': 'management_network:update'})
        if check_mode:
            return {
                'changed': bool(operations), 'operations': operations,
                'completed_operations': [], 'endpoint': endpoint,
                'device_identity': asdict(identity),
                'target_reached': endpoint == config.target_url.rstrip('/'),
                'persistence': 'save_required',
            }
        result: CredentialTransitionResult | NetworkTransitionResult
        for operation in operations:
            failed_operation = operation
            if operation['key'] == 'credentials:update':
                stage = 'credentials'
                result = transition_credentials(
                    endpoint, config.credentials(False), config.credentials(True), identity,
                    timeout_s=config.timeout_s, verify_tls=config.verify_tls,
                )
            else:
                stage = 'management_network'
                result = transition_management_network(
                    endpoint, config.target_url, config.credentials(True), config.management,
                    timeout_s=config.timeout_s, transition_timeout_s=config.transition_timeout_s,
                    poll_interval_s=config.poll_interval_s, verify_tls=config.verify_tls,
                    expected_identity=identity,
                )
            logical_changed = logical_changed or result.changed
            write_attempted = write_attempted or result.changed
            endpoint = result.endpoint
            completed.append(operation.copy())
        stage = 'persistence'
        failed_operation = {'key': 'configuration:save'}
        session = JTComSession(
            config.target_url, config.credentials(True),
            timeout_s=config.timeout_s, verify_tls=config.verify_tls,
        )
        try:
            session.login()
            identity.verify(parse_device_info(session.get(DEVICE_INFO)))
            if read_management_network(session) != config.management.as_state():
                raise ValueError('Final management state changed before save')
            # One-shot save is a required postcondition, not another user intent.
            write_attempted = True
            save_config(session)
        finally:
            session._discard()
        return {
            'changed': logical_changed, 'operations': operations, 'completed_operations': completed,
            'endpoint': config.target_url.rstrip('/'), 'device_identity': asdict(identity),
            'target_reached': True, 'persistence': 'saved',
        }
    except Exception as error:
        if isinstance(error, JTComTransitionError):
            logical_changed = logical_changed or error.write_attempted
            write_attempted = write_attempted or error.write_attempted
            if error.last_verified_identity is not None:
                identity = error.last_verified_identity
        raise JTComBootstrapError({
            'failed': True, 'changed': logical_changed, 'stage': stage,
            'write_attempted': write_attempted, 'completed_operations': completed,
            'failed_operation': failed_operation, 'last_verified_endpoint': endpoint,
            'device_identity': asdict(identity) if identity else None,
            'target_reached': endpoint == config.target_url.rstrip('/'),
            'underlying_exception': {'type': type(error).__name__,
                                     'message': 'Raw exception details withheld'},
        }) from None
