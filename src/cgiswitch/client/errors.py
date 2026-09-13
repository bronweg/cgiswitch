"""Custom exceptions for the cgiswitch HTTP client."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Switch JSON response codes
CODE_OK: int = 0
CODE_PARAM_ERR: int = 1
CODE_AUTH_EXPIRED: int = 11


class JTComError(Exception):
    """Base exception for all cgiswitch errors."""


class JTComPolicyError(JTComError):
    """Raised before backup or writes when a plan violates apply policy.

    ``violations`` contains the same structured records returned by check mode.
    """

    def __init__(self, violations: list[dict[str, Any]]) -> None:
        self.violations = violations
        self.blocked = True
        super().__init__("Apply blocked by policy: " + "; ".join(
            violation["message"] for violation in violations
        ))


class JTComApplyError(JTComError):
    """Describe a failure after an apply operation may have started.

    The original exception is retained for callers that need its concrete
    type, while :meth:`as_result` provides a JSON-serializable summary for
    automation interfaces.
    """

    def __init__(
        self,
        *,
        backup_file: str,
        completed_operations: list[dict[str, str]],
        failed_operation: dict[str, str],
        original_exception: Exception,
        write_attempted: bool,
        readback: dict[str, Any] | None = None,
        readback_error: Exception | None = None,
    ) -> None:
        self.backup_file = backup_file
        self.completed_operations = completed_operations
        self.failed_operation = failed_operation
        self.original_exception = original_exception
        self.write_attempted = write_attempted
        self.readback = readback
        self.readback_error = readback_error
        self.applied = [operation["key"] for operation in completed_operations]
        super().__init__(
            f"Apply failed during {failed_operation.get('key', 'unknown operation')}: "
            f"{original_exception}"
        )

    @staticmethod
    def _exception_result(error: Exception | None) -> dict[str, str] | None:
        if error is None:
            return None
        return {"type": type(error).__name__, "message": str(error)}

    def as_result(self) -> dict[str, Any]:
        """Return a stable, JSON-serializable failure result."""
        result: dict[str, Any] = {
            "failed": True,
            "msg": str(self),
            "changed": self.write_attempted,
            "backup_file": self.backup_file,
            "applied": self.applied,
            "completed_operations": self.completed_operations,
            "failed_operation": self.failed_operation,
            "original_exception": self._exception_result(self.original_exception),
            "readback": self.readback,
            "readback_error": self._exception_result(self.readback_error),
            "write_attempted": self.write_attempted,
        }
        if isinstance(self.original_exception, JTComVerificationError):
            result["remaining_diff"] = self.original_exception.remaining_diff
        return result


class JTComStateError(JTComError):
    """Raised when parsed device pages describe inconsistent current state."""


class JTComAuthError(JTComError):
    """Raised when authentication with the switch fails."""


class JTComRequestError(JTComError):
    """Raised when a network-level error occurs (connection refused, timeout, etc.)."""

    def __init__(self, url: str, cause: Exception) -> None:
        self.url = url
        self.cause = cause
        super().__init__(f"Request to {url!r} failed: {cause}")


class JTComResponseError(JTComError):
    """Raised when the switch returns a non-2xx HTTP status code."""

    def __init__(self, status_code: int, url: str) -> None:
        self.status_code = status_code
        self.url = url
        super().__init__(f"HTTP {status_code} for {url!r}")


class JTComParseError(JTComError):
    """Raised when HTML/JSON parsing fails or expected elements are not found."""


@dataclass
class JTComSwitchError(JTComError):
    """Raised when the switch returns a JSON payload with a non-zero error code."""

    code: int
    message: str
    endpoint: str
    payload: dict[str, object] | None = None

    def __post_init__(self) -> None:
        super().__init__(
            f"Switch error code={self.code} at {self.endpoint!r}: {self.message}"
        )


@dataclass
class JTComVerificationError(JTComError):
    """Raised when post-apply verification finds residual differences.

    Attributes:
        remaining_diff: Rendered diff (from :func:`~cgiswitch.utils.render.render_diff`)
            showing what still differs after the apply attempt.
    """

    remaining_diff: dict[str, object]

    def __post_init__(self) -> None:
        n = self.remaining_diff.get("total_changes", "?")
        super().__init__(
            f"Post-apply verification failed: {n} change(s) still outstanding. "
            "See .remaining_diff for details."
        )
