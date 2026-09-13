"""Low-level HTTP client wrapper for JTCom CGI endpoints."""

from __future__ import annotations

import importlib.metadata
import logging

import requests

from cgiswitch.client.errors import JTComRequestError, JTComResponseError

logger = logging.getLogger(__name__)

try:
    _VERSION: str = importlib.metadata.version("cgiswitch")
except importlib.metadata.PackageNotFoundError:
    _VERSION = "0.0.0"

_USER_AGENT: str = f"cgiswitch/{_VERSION}"


def _normalise_base_url(url: str) -> str:
    """Ensure the URL has a scheme and no trailing slash."""
    url = url.rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    return url


class JTComHTTP:
    """Low-level HTTP wrapper around :class:`requests.Session`.

    Handles cookie persistence, a default ``User-Agent`` header, timeout,
    TLS verification, and maps transport/HTTP errors to :mod:`.errors` types.

    Args:
        base_url: Switch base URL, e.g. ``http://192.168.1.1``.
        timeout_s: Request timeout in seconds (default 30).
        verify_tls: Whether to verify TLS certificates (default True).
    """

    def __init__(
        self,
        base_url: str,
        timeout_s: float = 30.0,
        verify_tls: bool = True,
    ) -> None:
        self.base_url: str = _normalise_base_url(base_url)
        self.timeout_s: float = timeout_s
        self.verify_tls: bool = verify_tls
        self._session: requests.Session = requests.Session()
        self._session.headers.update({"User-Agent": _USER_AGENT})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(
        self,
        path: str,
        params: dict[str, str] | None = None,
    ) -> requests.Response:
        """Send an HTTP GET to *path* and return the response.

        Args:
            path: URL path relative to :attr:`base_url`.
            params: Optional query-string parameters.

        Returns:
            The :class:`requests.Response`.

        Raises:
            JTComRequestError: On any transport-level failure.
            JTComResponseError: On a non-2xx HTTP status code.
        """
        url = self.base_url + path
        try:
            resp = self._session.get(
                url,
                params=params,
                timeout=self.timeout_s,
                verify=self.verify_tls,
            )
        except requests.exceptions.RequestException as exc:
            raise JTComRequestError(url, exc) from exc
        self._raise_for_status(resp)
        return resp

    def post_form(
        self,
        path: str,
        data: dict[str, str] | list[tuple[str, str]] | None = None,
    ) -> requests.Response:
        """Send an HTTP POST with form-encoded *data* to *path*.

        Args:
            path: URL path relative to :attr:`base_url`.
            data: Optional form fields.  May be a ``dict`` for simple payloads
                or a ``list[tuple[str, str]]`` when repeated keys are needed
                (e.g. multiple ``del=`` fields for bulk VLAN deletion).

        Returns:
            The :class:`requests.Response`.

        Raises:
            JTComRequestError: On any transport-level failure.
            JTComResponseError: On a non-2xx HTTP status code.
        """
        url = self.base_url + path
        try:
            resp = self._session.post(
                url,
                data=data,
                timeout=self.timeout_s,
                verify=self.verify_tls,
            )
        except requests.exceptions.RequestException as exc:
            raise JTComRequestError(url, exc) from exc
        self._raise_for_status(resp)
        return resp

    def close(self) -> None:
        """Close the underlying :class:`requests.Session`."""
        self._session.close()

    def __enter__(self) -> JTComHTTP:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _raise_for_status(resp: requests.Response) -> None:
        if not resp.ok:
            raise JTComResponseError(resp.status_code, resp.url)
