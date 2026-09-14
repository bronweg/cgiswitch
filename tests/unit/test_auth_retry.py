"""Regression tests for authenticated request retry and backup validation."""

from __future__ import annotations

import json
from typing import cast
from urllib.parse import parse_qsl

import pytest
import requests
import responses

from cgiswitch.client.errors import (
    CODE_AUTH_EXPIRED,
    CODE_OK,
    JTComAuthError,
    JTComParseError,
    JTComRequestError,
    JTComResponseError,
)
from cgiswitch.client.session import JTComCredentials, JTComSession
from cgiswitch.vendor.jtcom.endpoints import CONFIG_BACKUP, LOGIN

BASE_URL = "http://192.168.1.1"
CREDS = JTComCredentials(username="admin", password="secret")


def _session(*, logged_in: bool = True) -> JTComSession:
    session = JTComSession(BASE_URL, CREDS, verify_tls=False)
    session._logged_in = logged_in
    return session


def _json_response(code: int = CODE_OK, data: str = "") -> str:
    return json.dumps({"code": code, "data": data})


def _add_login() -> None:
    responses.add(
        responses.POST,
        f"{BASE_URL}{LOGIN}",
        body=_json_response(),
        status=200,
        content_type="application/json",
    )


@responses.activate
def test_get_normal_request() -> None:
    responses.add(responses.GET, f"{BASE_URL}/info.cgi", body="<html>state</html>")
    assert _session().get("/info.cgi") == "<html>state</html>"
    assert len(responses.calls) == 1


@responses.activate
def test_post_normal_request() -> None:
    responses.add(
        responses.POST,
        f"{BASE_URL}/vlan.cgi",
        body=_json_response(data="ok"),
        status=200,
    )
    assert _session().post("/vlan.cgi")["code"] == CODE_OK
    assert len(responses.calls) == 1


@responses.activate
def test_get_expiry_relogin_and_retry() -> None:
    responses.add(responses.GET, f"{BASE_URL}/info.cgi", body=_json_response(CODE_AUTH_EXPIRED))
    _add_login()
    responses.add(responses.GET, f"{BASE_URL}/info.cgi", body="fresh state")

    assert _session().get("/info.cgi") == "fresh state"
    assert [call.request.method for call in responses.calls] == ["GET", "POST", "GET"]


@responses.activate
def test_post_expiry_relogin_and_retry() -> None:
    responses.add(
        responses.POST,
        f"{BASE_URL}/vlan.cgi",
        body=_json_response(CODE_AUTH_EXPIRED),
        status=200,
    )
    _add_login()
    responses.add(
        responses.POST,
        f"{BASE_URL}/vlan.cgi",
        body=_json_response(),
        status=200,
    )

    assert _session().post("/vlan.cgi")["code"] == CODE_OK
    assert len(responses.calls) == 3


@responses.activate
def test_repeated_get_expiry_raises_typed_auth_error_without_loop() -> None:
    responses.add(responses.GET, f"{BASE_URL}/info.cgi", body=_json_response(CODE_AUTH_EXPIRED))
    _add_login()
    responses.add(responses.GET, f"{BASE_URL}/info.cgi", body=_json_response(CODE_AUTH_EXPIRED))

    with pytest.raises(JTComAuthError):
        _session().get("/info.cgi")
    assert len(responses.calls) == 3


@responses.activate
def test_backup_success_returns_nonempty_bytes() -> None:
    responses.add(responses.GET, f"{BASE_URL}{CONFIG_BACKUP}", body=b"\x00opaque backup\xff")
    assert _session().download_config_backup() == b"\x00opaque backup\xff"


@pytest.mark.parametrize("body", [b"", b"<html><body>login</body></html>"])
@responses.activate
def test_backup_rejects_empty_or_html_body(body: bytes) -> None:
    responses.add(responses.GET, f"{BASE_URL}{CONFIG_BACKUP}", body=body)
    with pytest.raises(JTComParseError):
        _session().download_config_backup()
    assert len(responses.calls) == 1


@responses.activate
def test_backup_expiry_relogin_and_retry() -> None:
    responses.add(
        responses.GET,
        f"{BASE_URL}{CONFIG_BACKUP}",
        body=_json_response(CODE_AUTH_EXPIRED),
    )
    _add_login()
    responses.add(responses.GET, f"{BASE_URL}{CONFIG_BACKUP}", body=b"backup")

    assert _session().download_config_backup() == b"backup"
    assert len(responses.calls) == 3


@pytest.mark.parametrize(
    ("method", "path", "success_body"),
    [
        (responses.GET, "/info.cgi", "state"),
        (responses.POST, "/vlan.cgi", _json_response()),
        (responses.GET, CONFIG_BACKUP, b"backup"),
    ],
)
@responses.activate
def test_http_401_relogin_and_retry(
    method: str, path: str, success_body: str | bytes,
) -> None:
    responses.add(method, f"{BASE_URL}{path}", status=401)
    _add_login()
    responses.add(method, f"{BASE_URL}{path}", body=success_body, status=200)

    session = _session()
    if path == "/info.cgi":
        assert session.get(path) == success_body
    elif path == "/vlan.cgi":
        assert session.post(path)["code"] == CODE_OK
    else:
        assert session.download_config_backup() == success_body
    assert len(responses.calls) == 3


@pytest.mark.parametrize("path", ["/info.cgi", "/vlan.cgi", CONFIG_BACKUP])
@responses.activate
def test_repeated_json_expiry_raises_for_every_request_type(path: str) -> None:
    responses.add(responses.GET if path != "/vlan.cgi" else responses.POST,
                  f"{BASE_URL}{path}", body=_json_response(CODE_AUTH_EXPIRED))
    _add_login()
    responses.add(responses.GET if path != "/vlan.cgi" else responses.POST,
                  f"{BASE_URL}{path}", body=_json_response(CODE_AUTH_EXPIRED))

    session = _session()
    with pytest.raises(JTComAuthError):
        if path == "/info.cgi":
            session.get(path)
        elif path == "/vlan.cgi":
            session.post(path)
        else:
            session.download_config_backup()
    assert session.logged_in is False
    assert len(responses.calls) == 3


@responses.activate
def test_login_html_relogin_and_repeated_html_expiry() -> None:
    login_page = (
        '<form action="/login.cgi"><input name="username">'
        '<input type="password" name="password"></form>'
    )
    responses.add(responses.GET, f"{BASE_URL}/info.cgi", body=login_page)
    _add_login()
    responses.add(responses.GET, f"{BASE_URL}/info.cgi", body=login_page)

    with pytest.raises(JTComAuthError):
        _session().get("/info.cgi")
    assert len(responses.calls) == 3


@responses.activate
def test_failed_relogin_stops_after_one_attempt() -> None:
    responses.add(responses.GET, f"{BASE_URL}/info.cgi", body=_json_response(CODE_AUTH_EXPIRED))
    responses.add(
        responses.POST,
        f"{BASE_URL}{LOGIN}",
        body=_json_response(1, "bad credentials"),
        status=200,
    )
    with pytest.raises(JTComAuthError):
        _session().get("/info.cgi")
    assert len(responses.calls) == 2


@pytest.mark.parametrize("status", [403, 500])
@responses.activate
def test_non_auth_http_error_is_not_retried(status: int) -> None:
    responses.add(responses.GET, f"{BASE_URL}/info.cgi", status=status)
    with pytest.raises(JTComResponseError) as error:
        _session().get("/info.cgi")
    assert error.value.status_code == status
    assert len(responses.calls) == 1


@responses.activate
def test_transport_error_is_not_retried() -> None:
    responses.add(
        responses.GET,
        f"{BASE_URL}/info.cgi",
        body=requests.exceptions.ConnectionError("offline"),
    )
    with pytest.raises(JTComRequestError):
        _session().get("/info.cgi")
    assert len(responses.calls) == 1


@responses.activate
def test_post_retry_preserves_repeated_fields_and_single_page() -> None:
    responses.add(
        responses.POST,
        f"{BASE_URL}/vlan.cgi",
        body=_json_response(CODE_AUTH_EXPIRED),
        status=200,
    )
    _add_login()
    responses.add(
        responses.POST,
        f"{BASE_URL}/vlan.cgi",
        body=_json_response(),
        status=200,
    )
    _session().post("/vlan.cgi", [("del", "10"), ("del", "20"), ("page", "custom")])
    fields = parse_qsl(
        cast(str, responses.calls[2].request.body or ""),
        keep_blank_values=True,
    )
    assert fields.count(("del", "10")) == 1
    assert fields.count(("del", "20")) == 1
    assert fields.count(("page", "inside")) == 1
    assert fields.count(("page", "custom")) == 1


@responses.activate
def test_password_change_html_is_not_treated_as_login_expiry() -> None:
    body = '<form action="/password.cgi"><input type="password" name="new_password"></form>'
    responses.add(responses.GET, f"{BASE_URL}/info.cgi", body=body)
    assert _session().get("/info.cgi") == body
    assert len(responses.calls) == 1
