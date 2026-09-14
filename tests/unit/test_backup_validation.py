"""Tests for configuration backup response validation."""

import pytest
import requests

from cgiswitch.client.backup import validate_backup_response
from cgiswitch.client.errors import JTComParseError


def _response(body: bytes, content_type: str | None = None) -> requests.Response:
    response = requests.Response()
    response._content = body
    response.headers["Content-Type"] = content_type or "application/octet-stream"
    return response


@pytest.mark.parametrize(
    "body",
    [b"", b" \r\n\t", b"\xef\xbb\xbf \n"],
)
def test_empty_backup_is_rejected(body: bytes) -> None:
    with pytest.raises(JTComParseError, match="Empty"):
        validate_backup_response(_response(body))


@pytest.mark.parametrize(
    "body, content_type",
    [
        (b"<html><body>Login</body></html>", None),
        (b"\xef\xbb\xbf  <!-- login page --><form></form>", None),
        (b"<body>expired</body>", "application/octet-stream"),
        (b"login", "text/html; charset=UTF-8"),
        (b"<html></html>", "application/xhtml+xml"),
    ],
)
def test_html_backup_is_rejected(body: bytes, content_type: str | None) -> None:
    with pytest.raises(JTComParseError, match="HTML"):
        validate_backup_response(_response(body, content_type))


@pytest.mark.parametrize(
    "body",
    [
        b'{"code":11,"data":"login required"}',
        b'{"code":1,"error":"failed"}',
        b'{"error":"login required"}',
    ],
)
def test_json_cgi_error_envelope_is_rejected(body: bytes) -> None:
    with pytest.raises(JTComParseError, match="JSON CGI"):
        validate_backup_response(_response(body))


def test_obvious_plain_text_error_is_rejected() -> None:
    with pytest.raises(JTComParseError, match="textual"):
        validate_backup_response(_response(b"Error: session expired"))


def test_valid_binary_is_preserved_exactly() -> None:
    body = b"\x00\xff\x10error\x80\x01\x02"
    assert validate_backup_response(_response(body)) == body


def test_text_backup_that_contains_error_word_is_preserved() -> None:
    body = b"JTCom backup\ncomment: error handling enabled\n"
    assert validate_backup_response(_response(body)) == body


def test_embedded_html_fragment_in_binary_is_preserved() -> None:
    body = b"\x00\x01\n<form>configuration data</form>\xff"
    assert validate_backup_response(_response(body)) == body


def test_comment_prefixed_html_is_rejected() -> None:
    with pytest.raises(JTComParseError, match="HTML"):
        validate_backup_response(_response(b"<!-- login --><div>Sign in</div>"))


def test_html_fragment_at_start_is_rejected() -> None:
    with pytest.raises(JTComParseError, match="HTML"):
        validate_backup_response(_response(b"<div>Error</div>"))


@pytest.mark.parametrize("body", [b'{"code":1}', b'{"code":0}'])
def test_backup_rejects_bare_cgi_status(body: bytes) -> None:
    response = requests.Response()
    response.status_code = 200
    response._content = body
    with pytest.raises(JTComParseError):
        validate_backup_response(response)
