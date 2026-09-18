"""Secret-safe failures for disruptive management transitions."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from cgiswitch.bootstrap.identity import DeviceIdentity
from cgiswitch.client.errors import JTComError


class JTComTransitionError(JTComError):
    """A failed or ambiguous transition, without credentials or raw response data."""

    def __init__(
        self, *, stage: str, write_attempted: bool, old_endpoint: str,
        target_endpoint: str, identity: DeviceIdentity | None,
        target_reached: bool, verification_completed: bool, error: Exception,
        last_verified_endpoint: str | None,
    ) -> None:
        self.stage = stage
        self.write_attempted = write_attempted
        self.old_endpoint = old_endpoint
        self.target_endpoint = target_endpoint
        self.last_verified_identity = identity
        self.last_verified_endpoint = last_verified_endpoint
        self.target_reached = target_reached
        self.verification_completed = verification_completed
        self.underlying_exception = {
            'type': type(error).__name__,
            'message': 'Management transition could not be verified; raw error details withheld',
        }
        super().__init__(f'Management transition failed during {stage}; no automatic rollback')

    def as_result(self) -> dict[str, Any]:
        return {
            'failed': True, 'changed': self.write_attempted, 'stage': self.stage,
            'write_attempted': self.write_attempted, 'old_endpoint': self.old_endpoint,
            'target_endpoint': self.target_endpoint,
            'last_verified_endpoint': self.last_verified_endpoint,
            'last_verified_identity': (
                asdict(self.last_verified_identity) if self.last_verified_identity else None
            ),
            'target_reached': self.target_reached,
            'verification_completed': self.verification_completed,
            'underlying_exception': self.underlying_exception.copy(),
        }
