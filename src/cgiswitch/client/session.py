"""Authenticated HTTP session for JTCom switches."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

from cgiswitch.client.backup import validate_backup_response
from cgiswitch.client.errors import (
    CODE_AUTH_EXPIRED,
    CODE_OK,
    JTComAuthError,
    JTComParseError,
    JTComResponseError,
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
    password: str = field(repr=False)


class JTComSession:
    """Manages a persistent, authenticated HTTP session to a JTCom switch.

    Wraps :class:`.JTComHTTP` and adds:
    - Cookie-based authentication via ``login.cgi``.
    - Automatic ``page=inside`` and ``stamp=<unix_ts>`` injection for GET.
    - Automatic ``page=inside`` injection for POST form data.
    - One transparent re-login/retry on explicit auth expiry for every request type.

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
        self._logged_in = False
        try:
            resp = self._http.post_form(
                LOGIN,
                data={
                    "username": self._credentials.username,
                    "password": self._credentials.password,
                },
            )
        except JTComResponseError as exc:
            if exc.status_code in (401, 403):
                raise JTComAuthError(f"Login rejected with HTTP {exc.status_code}") from exc
            raise
        result = self._parse_json(resp.text, LOGIN)
        if result["code"] != CODE_OK:
            self._logged_in = False
            raise JTComAuthError(
                f"Login rejected by switch: code={result['code']!r}"
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
        Explicit expiry triggers at most one login and retry; repeated expiry
        raises :exc:`JTComAuthError`.

        Args:
            path: CGI path relative to the switch base URL.
            params: Additional query parameters (merged after injection).

        Returns:
            Response body as a string.
        """
        injected: dict[str, str] = {
            "page": _PAGE_PARAM,
            "stamp": str(int(time.time())),
        }
        if params:
            injected.update(params)
        resp = self._authenticated_request(path, lambda: self._http.get(path, params=injected))
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
            JTComAuthError: If authentication expires again after one retry.
            JTComSwitchError: If the switch returns a non-auth operation error.
        """
        response = self._authenticated_request(path, lambda: self._do_post(path, data))
        result = self._parse_json(response.text, path)

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
            Non-empty backup bytes, unchanged. HTML/login/error responses
            are rejected; no undocumented binary signature is required.
        """
        response = self._authenticated_request(
            CONFIG_BACKUP,
            lambda: self._http.get(
                CONFIG_BACKUP,
                params={
                    "cmd": "conf_backup",
                    "page": _PAGE_PARAM,
                    "stamp": str(int(time.time())),
                },
            ),
        )
        return validate_backup_response(response)

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

    def _discard(self) -> None:
        """Close local transport without contacting a possibly changed endpoint."""
        self._logged_in = False
        self._http.close()

    def _do_post(
        self,
        path: str,
        data: dict[str, str] | list[tuple[str, str]] | None,
    ) -> requests.Response:
        """Send one POST with page injection, preserving repeated form fields."""
        form: dict[str, str] | list[tuple[str, str]]
        if isinstance(data, list):
            # Preserve repeated keys (e.g. del=10&del=20); inject page at front.
            form = [("page", _PAGE_PARAM), *data]
        else:
            form_dict: dict[str, str] = {"page": _PAGE_PARAM}
            if data:
                form_dict.update(data)
            form = form_dict
        return self._http.post_form(path, data=form)

    def _post_once(self, path: str, data: dict[str, str]) -> None:
        """Send an internal management command once; never replay its POST.

        Only the observed empty-data success envelope is accepted. Response
        data is deliberately excluded from errors because it can echo secrets.
        """
        self.ensure_session()
        try:
            response = self._do_post(path, data)
        except JTComResponseError as exc:
            if exc.status_code != 401:
                raise
            self._logged_in = False
            raise JTComAuthError("Management command authentication expired") from None
        if _is_auth_expired(response):
            self._logged_in = False
            raise JTComAuthError("Management command authentication expired")
        if response.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
            raise JTComParseError("Unexpected management command response type")
        result = self._parse_json(response.text, path)
        if set(result) != {"code", "data"} or not isinstance(result["data"], str):
            raise JTComParseError("Unexpected management command response envelope")
        if result["code"] != CODE_OK:
            raise JTComSwitchError(
                code=int(str(result["code"])), message="Management command rejected", endpoint=path,
            )
        if result["data"] != "":
            raise JTComParseError("Unexpected management command success data")

    def _authenticated_request(
        self, path: str, send: Callable[[], requests.Response],
    ) -> requests.Response:
        """Retry only explicit expiry, at most once, without recursive request calls."""
        self.ensure_session()
        for attempt in range(2):
            response_error: JTComResponseError | None = None
            try:
                response = send()
            except JTComResponseError as exc:
                if exc.status_code != 401:
                    raise
                response_error = exc
            else:
                if not _is_auth_expired(response):
                    return response
            self._logged_in = False
            if attempt == 1:
                raise JTComAuthError(
                    f"Authentication expired again after one retry for {path!r}"
                ) from response_error
            logger.debug("Authentication expired for %s; re-authenticating once", path)
            self.login()
        raise AssertionError("Authentication retry loop exhausted unexpectedly")

    @staticmethod
    def _parse_json(text: str, endpoint: str) -> dict[str, object]:
        """Validate a CGI JSON envelope and normalize its integer status code."""
        try:
            result = json.loads(text.lstrip("\ufeff \t\r\n"))
        except (json.JSONDecodeError, ValueError) as exc:
            raise JTComParseError(f"Non-JSON response from {endpoint!r}") from exc
        if not isinstance(result, dict) or "code" not in result:
            raise JTComParseError(f"Missing CGI response code from {endpoint!r}")
        try:
            result["code"] = _normalize_cgi_code(result["code"])
        except ValueError as exc:
            raise JTComParseError(f"Invalid CGI response code from {endpoint!r}") from exc
        return result


def _normalize_cgi_code(code: object) -> int:
    """Normalize integer CGI codes, including whitespace in numeric strings."""
    if isinstance(code, bool) or not isinstance(code, (int, str)):
        raise ValueError("CGI response code must be an integer or numeric string")
    return int(code)


def _is_auth_expired(response: requests.Response) -> bool:
    """Recognize explicit auth responses without treating ordinary HTML as login."""
    if urlsplit(response.url or "").path.rstrip("/").endswith(LOGIN):
        return True
    text = response.content.decode("utf-8", errors="replace").lstrip("\ufeff \t\r\n")
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except ValueError:
            pass
        else:
            if isinstance(payload, dict):
                try:
                    return _normalize_cgi_code(payload.get("code")) == CODE_AUTH_EXPIRED
                except ValueError:
                    pass
    if not text.startswith("<"):
        return False
    soup = BeautifulSoup(text, "html.parser")
    for form in soup.find_all("form"):
        password = form.find(
            "input", attrs={"type": lambda value: str(value).lower() == "password"},
        )
        username = form.find("input", attrs={"name": "username"})
        login_action = urlsplit(str(form.get("action", ""))).path.endswith(LOGIN)
        if password is not None and (username is not None or login_action):
            return True
    return False
