"""Authenticated HTTP session for JTCom switches."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from cgiswitch.client.errors import (
    CODE_AUTH_EXPIRED,
    CODE_OK,
    JTComAuthError,
    JTComParseError,
    JTComSwitchError,
)
from cgiswitch.client.http import JTComHTTP
from cgiswitch.vendor.jtcom.endpoints import CONFIG_BACKUP, LOGIN, SYSCMD

logger = logging.getLogger(__name__)

# Query / form field injected into every request so the switch accepts it.
_PAGE_PARAM: str = "inside"


@dataclass(frozen=True)
class JTComCredentials:
    """Immutable credential pair for a JTCom switch.

    Args:
        username: Login username.
        password: Login password.
    """

    username: str
    password: str


class JTComSession:
    """Manages a persistent, authenticated HTTP session to a JTCom switch.

    Wraps :class:`.JTComHTTP` and adds:
    - Cookie-based authentication via ``login.cgi``.
    - Automatic ``page=inside`` and ``stamp=<unix_ts>`` injection for GET.
    - Automatic ``page=inside`` injection for POST form data.
    - Single transparent re-login on ``code=11`` (auth expired) responses.

    Args:
        base_url: Switch base URL, e.g. ``http://192.168.1.1``.
        credentials: Username/password pair.
        timeout_s: Request timeout in seconds (default 30).
        verify_tls: Whether to verify TLS certificates (default True).
    """

    def __init__(
        self,
        base_url: str,
        credentials: JTComCredentials,
        timeout_s: float = 30.0,
        verify_tls: bool = True,
    ) -> None:
        self._http: JTComHTTP = JTComHTTP(
            base_url=base_url,
            timeout_s=timeout_s,
            verify_tls=verify_tls,
        )
        self._credentials: JTComCredentials = credentials
        self._logged_in: bool = False

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def login(self) -> None:
        """Authenticate to the switch.

        Sends credentials to ``LOGIN`` endpoint and validates the JSON response.

        Raises:
            JTComAuthError: If the switch rejects the credentials.
            JTComParseError: If the response cannot be decoded as JSON.
        """
        resp = self._http.post_form(
            LOGIN,
            data={
                "username": self._credentials.username,
                "password": self._credentials.password,
            },
        )
        result = self._parse_json(resp.text, LOGIN)
        if result["code"] != CODE_OK:
            self._logged_in = False
            raise JTComAuthError(
                f"Login rejected by switch: code={result['code']!r} "
                f"data={result.get('data')!r}"
            )
        self._logged_in = True
        logger.debug("Logged in to %s", self._http.base_url)

    def logout(self) -> None:
        """Log out from the switch (best-effort; never raises).

        Sends a ``cmd=logout`` POST to ``LOGOUT`` endpoint and marks the
        session as logged out regardless of the outcome.
        """
        try:
            self._http.post_form(SYSCMD, data={"cmd": "logout"})
        except Exception:  # noqa: BLE001
            logger.debug("Logout request failed (ignored)", exc_info=True)
        finally:
            self._logged_in = False
            logger.debug("Logged out from %s", self._http.base_url)

    def ensure_session(self) -> None:
        """Log in if not already logged in."""
        if not self._logged_in:
            self.login()

    # ------------------------------------------------------------------
    # Public request methods
    # ------------------------------------------------------------------

    def get(
        self,
        path: str,
        params: dict[str, str] | None = None,
    ) -> str:
        """Perform an authenticated GET and return the response text.

        Injects ``page=inside`` and ``stamp=<unix_timestamp>`` query params.

        Args:
            path: CGI path relative to the switch base URL.
            params: Additional query parameters (merged after injection).

        Returns:
            Response body as a string.
        """
        self.ensure_session()
        injected: dict[str, str] = {
            "page": _PAGE_PARAM,
            "stamp": str(int(time.time())),
        }
        if params:
            injected.update(params)
        resp = self._http.get(path, params=injected)
        return resp.text

    def post(
        self,
        path: str,
        data: dict[str, str] | list[tuple[str, str]] | None = None,
    ) -> dict[str, object]:
        """Perform an authenticated POST and return the parsed JSON payload.

        Injects ``page=inside`` into the form data.  On ``code=11``
        (auth expired), re-authenticates once and retries the request.

        Args:
            path: CGI path relative to the switch base URL.
            data: Additional form fields.  Either a ``dict`` for simple payloads
                or a ``list[tuple[str, str]]`` when repeated keys are needed
                (e.g. multiple ``del=`` fields for bulk VLAN deletion).

        Returns:
            Parsed JSON response as ``{"code": int, "data": str, ...}``.

        Raises:
            JTComSwitchError: If the switch returns a non-zero, non-11 code
                              (or still fails after the retry).
        """
        self.ensure_session()
        result = self._do_post(path, data)

        if result["code"] == CODE_AUTH_EXPIRED:
            logger.debug("Auth expired (%s); re-logging in", path)
            self.login()
            result = self._do_post(path, data)

        if result["code"] != CODE_OK:
            raise JTComSwitchError(
                code=int(str(result["code"])),
                message=str(result.get("data", "")),
                endpoint=path,
                payload=result,
            )

        return result

    def download_config_backup(self) -> bytes:
        """Download a raw binary configuration backup from the switch.

        Issues ``GET /config.cgi?cmd=conf_backup`` and returns the raw response
        bytes (the switch sends no ``Content-Type`` or ``Content-Disposition``
        headers, so callers are responsible for choosing a filename).

        Returns:
            Raw binary content of the switch configuration backup.
        """
        self.ensure_session()
        resp = self._http.get(
            CONFIG_BACKUP,
            params={
                "cmd": "conf_backup",
                "page": _PAGE_PARAM,
                "stamp": str(int(time.time())),
            },
        )
        return resp.content

    def close(self) -> None:
        """Logout and close the underlying HTTP session."""
        self.logout()
        self._http.close()

    def __enter__(self) -> JTComSession:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def logged_in(self) -> bool:
        """True if the session is currently authenticated."""
        return self._logged_in

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _do_post(
        self,
        path: str,
        data: dict[str, str] | list[tuple[str, str]] | None,
    ) -> dict[str, object]:
        """Send one POST (with page injection) and parse JSON."""
        form: dict[str, str] | list[tuple[str, str]]
        if isinstance(data, list):
            # Preserve repeated keys (e.g. del=10&del=20); inject page at front.
            form = [("page", _PAGE_PARAM), *data]
        else:
            form_dict: dict[str, str] = {"page": _PAGE_PARAM}
            if data:
                form_dict.update(data)
            form = form_dict
        resp = self._http.post_form(path, data=form)
        return self._parse_json(resp.text, path)

    @staticmethod
    def _parse_json(text: str, endpoint: str) -> dict[str, object]:
        """Parse *text* as JSON, raising :exc:`.JTComParseError` on failure."""
        import json

        try:
            result: dict[str, object] = json.loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            raise JTComParseError(
                f"Non-JSON response from {endpoint!r}: {text[:200]!r}"
            ) from exc
        return result
