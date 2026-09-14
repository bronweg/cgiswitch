"""Validation helpers for configuration backup responses."""

from __future__ import annotations

import json
import re

import requests

from cgiswitch.client.errors import JTComParseError

_HTML_CONTENT_TYPES = {"text/html", "application/xhtml+xml"}
_HTML_MARKUP = re.compile(
    rb"\A(?:[ \t\r\n]*<!--.*?-->)*[ \t\r\n]*(?:<!doctype\s+html\b|<\s*"
    rb"(?:html|head|header|body|form|title|script|meta|div|p|table|h[1-6])\b)",
    re.IGNORECASE | re.DOTALL,
)
_PLAIN_ERROR_START = re.compile(
    r"^(?:error|failure|failed|forbidden|unauthorized|not found|invalid|"
    r"login required|session expired|authentication required)\b",
    re.IGNORECASE,
)


def validate_backup_response(response: requests.Response) -> bytes:
    """Return backup bytes after rejecting empty or login/error responses.

    The switch does not provide a documented backup signature.  Validation is
    therefore limited to transport-level and recognizable error-page checks;
    arbitrary non-empty binary content is preserved byte-for-byte.

    Raises:
        JTComParseError: If the response is empty or is an HTML/CGI error page.
    """
    body = response.content
    if not body or not body.removeprefix(b"\xef\xbb\xbf").strip():
        raise JTComParseError("Empty configuration backup response")

    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type in _HTML_CONTENT_TYPES:
        raise JTComParseError("Configuration backup response is an HTML page")

    markup_body = body.removeprefix(b"\xef\xbb\xbf").lstrip(b" \t\r\n")
    if _HTML_MARKUP.search(markup_body):
        raise JTComParseError("Configuration backup response contains HTML markup")

    _reject_json_error_envelope(body)
    _reject_plain_error(body)
    return body


def _reject_json_error_envelope(body: bytes) -> None:
    """Reject a JSON CGI status/error envelope without inspecting binaries."""
    try:
        parsed = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return
    if isinstance(parsed, dict) and (
        "error" in parsed or ("code" in parsed and ("data" in parsed or len(parsed) == 1))
    ):
        raise JTComParseError("Configuration backup response is a JSON CGI error envelope")


def _reject_plain_error(body: bytes) -> None:
    """Reject clearly textual error responses while allowing arbitrary bytes."""
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        return
    stripped = text.strip()
    if not stripped:
        return
    printable = sum(char.isprintable() or char.isspace() for char in stripped)
    if printable == len(stripped) and (
        _PLAIN_ERROR_START.match(stripped)
        or stripped.lower().startswith("internal server error")
    ):
        raise JTComParseError("Configuration backup response is a textual error")
