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
