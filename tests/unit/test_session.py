"""Unit tests for cgiswitch.client.session and cgiswitch.client.http."""

from __future__ import annotations

import dataclasses
import json

import pytest
import requests
import responses as rsps_lib

from cgiswitch.client.errors import (
    CODE_AUTH_EXPIRED,
    CODE_OK,
    CODE_PARAM_ERR,
    JTComAuthError,
    JTComParseError,
    JTComRequestError,
    JTComResponseError,
    JTComSwitchError,
)
from cgiswitch.client.http import JTComHTTP, _normalise_base_url
from cgiswitch.client.session import JTComCredentials, JTComSession
from cgiswitch.vendor.jtcom.endpoints import LOGIN, LOGOUT

BASE_URL = "http://192.168.1.1"
CREDS = JTComCredentials(username="admin", password="secret")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session() -> JTComSession:
    return JTComSession(base_url=BASE_URL, credentials=CREDS, verify_tls=False)


def _json(payload: dict[str, object]) -> str:
    return json.dumps(payload)


# ---------------------------------------------------------------------------
# errors.py — constants and exception hierarchy
# ---------------------------------------------------------------------------

def test_error_constants() -> None:
    assert CODE_OK == 0
    assert CODE_PARAM_ERR == 1
    assert CODE_AUTH_EXPIRED == 11


def test_switch_error_message() -> None:
    err = JTComSwitchError(code=1, message="bad param", endpoint="/cgi-bin/vlan.cgi")
    assert "code=1" in str(err)
    assert "/cgi-bin/vlan.cgi" in str(err)
    assert isinstance(err, Exception)


def test_request_error_wraps_cause() -> None:
    cause = ConnectionError("refused")
    err = JTComRequestError(url="http://host/path", cause=cause)
    assert "http://host/path" in str(err)
    assert err.cause is cause


def test_response_error_stores_status() -> None:
    err = JTComResponseError(status_code=403, url="http://host/path")
    assert err.status_code == 403
    assert "403" in str(err)


# ---------------------------------------------------------------------------
# http.py — URL normalisation
# ---------------------------------------------------------------------------

def test_normalise_base_url_strips_slash() -> None:
    assert _normalise_base_url("http://192.168.1.1/") == "http://192.168.1.1"


def test_normalise_base_url_adds_scheme() -> None:
    assert _normalise_base_url("192.168.1.1") == "http://192.168.1.1"


def test_normalise_base_url_preserves_https() -> None:
    assert _normalise_base_url("https://192.168.1.1/") == "https://192.168.1.1"


# ---------------------------------------------------------------------------
# http.py — JTComHTTP
# ---------------------------------------------------------------------------

@rsps_lib.activate
def test_http_get_success() -> None:
    rsps_lib.add(rsps_lib.GET, f"{BASE_URL}/cgi-bin/info.cgi", body="<html/>", status=200)
    http = JTComHTTP(BASE_URL, verify_tls=False)
    resp = http.get("/cgi-bin/info.cgi")
    assert resp.status_code == 200
    assert resp.text == "<html/>"
    http.close()


@rsps_lib.activate
def test_http_get_non2xx_raises_response_error() -> None:
    rsps_lib.add(rsps_lib.GET, f"{BASE_URL}/cgi-bin/info.cgi", status=403)
    http = JTComHTTP(BASE_URL, verify_tls=False)
    with pytest.raises(JTComResponseError) as exc_info:
        http.get("/cgi-bin/info.cgi")
    assert exc_info.value.status_code == 403
    http.close()


@rsps_lib.activate
def test_http_get_connection_error_raises_request_error() -> None:
    rsps_lib.add(
        rsps_lib.GET,
        f"{BASE_URL}/cgi-bin/info.cgi",
        body=requests.exceptions.ConnectionError("refused"),
    )
    http = JTComHTTP(BASE_URL, verify_tls=False)
    with pytest.raises(JTComRequestError):
        http.get("/cgi-bin/info.cgi")
    http.close()


@rsps_lib.activate
def test_http_post_form_success() -> None:
    rsps_lib.add(
        rsps_lib.POST,
        f"{BASE_URL}{LOGIN}",
        body=_json({"code": 0, "data": ""}),
        status=200,
        content_type="application/json",
    )
    http = JTComHTTP(BASE_URL, verify_tls=False)
    resp = http.post_form(LOGIN, data={"username": "admin", "password": "pw"})
    assert resp.status_code == 200
    http.close()


@rsps_lib.activate
def test_http_user_agent_header_sent() -> None:
    rsps_lib.add(rsps_lib.GET, f"{BASE_URL}/cgi-bin/info.cgi", body="ok", status=200)
    http = JTComHTTP(BASE_URL, verify_tls=False)
    http.get("/cgi-bin/info.cgi")
    assert rsps_lib.calls[0].request.headers["User-Agent"].startswith("cgiswitch/")
    http.close()


# ---------------------------------------------------------------------------
# session.py — JTComCredentials
# ---------------------------------------------------------------------------

def test_credentials_frozen() -> None:
    creds = JTComCredentials(username="u", password="p")
    with pytest.raises(dataclasses.FrozenInstanceError):
        creds.username = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# session.py — JTComSession construction
# ---------------------------------------------------------------------------

def test_session_not_logged_in_by_default() -> None:
    session = _make_session()
    assert session.logged_in is False


def test_session_base_url_normalised() -> None:
    session = JTComSession(base_url="192.168.1.1/", credentials=CREDS)
    assert session._http.base_url == "http://192.168.1.1"


# ---------------------------------------------------------------------------
# session.py — login / logout
# ---------------------------------------------------------------------------

@rsps_lib.activate
def test_login_success_json() -> None:
    rsps_lib.add(
        rsps_lib.POST,
        f"{BASE_URL}{LOGIN}",
        body=_json({"code": CODE_OK, "data": ""}),
        status=200,
    )
    session = _make_session()
    session.login()
    assert session.logged_in is True


@rsps_lib.activate
def test_login_failure_json_raises_auth_error() -> None:
    rsps_lib.add(
        rsps_lib.POST,
        f"{BASE_URL}{LOGIN}",
        body=_json({"code": CODE_PARAM_ERR, "data": "bad credentials"}),
        status=200,
    )
    session = _make_session()
    with pytest.raises(JTComAuthError):
        session.login()
    assert session.logged_in is False


@rsps_lib.activate
def test_login_non_json_raises_parse_error() -> None:
    rsps_lib.add(
        rsps_lib.POST,
        f"{BASE_URL}{LOGIN}",
        body="<html>error</html>",
        status=200,
    )
    session = _make_session()
    with pytest.raises(JTComParseError):
        session.login()


@rsps_lib.activate
def test_logout_best_effort_no_raise() -> None:
    """logout() should never raise even if the request fails."""
    rsps_lib.add(
        rsps_lib.POST,
        f"{BASE_URL}{LOGOUT}",
        body=requests.exceptions.ConnectionError("gone"),
    )
    session = _make_session()
    session._logged_in = True
    session.logout()  # must not raise
    assert session.logged_in is False


@rsps_lib.activate
def test_logout_marks_logged_out_on_success() -> None:
    rsps_lib.add(
        rsps_lib.POST,
        f"{BASE_URL}{LOGOUT}",
        body=_json({"code": CODE_OK, "data": ""}),
        status=200,
    )
    session = _make_session()
    session._logged_in = True
    session.logout()
    assert session.logged_in is False


# ---------------------------------------------------------------------------
# session.py — GET param injection
# ---------------------------------------------------------------------------

@rsps_lib.activate
def test_get_injects_page_and_stamp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cgiswitch.client.session.time.time", lambda: 1700000000.0)
    rsps_lib.add(
        rsps_lib.POST,
        f"{BASE_URL}{LOGIN}",
        body=_json({"code": CODE_OK, "data": ""}),
        status=200,
    )
    rsps_lib.add(
        rsps_lib.GET,
        f"{BASE_URL}/cgi-bin/vlan_static.cgi",
        body="<html/>",
        status=200,
    )
    session = _make_session()
    session.get("/cgi-bin/vlan_static.cgi")

    get_call = rsps_lib.calls[1]
    assert "page=inside" in get_call.request.url
    assert "stamp=1700000000" in get_call.request.url


@rsps_lib.activate
def test_get_passes_extra_params(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cgiswitch.client.session.time.time", lambda: 1700000000.0)
    rsps_lib.add(
        rsps_lib.POST,
        f"{BASE_URL}{LOGIN}",
        body=_json({"code": CODE_OK, "data": ""}),
        status=200,
    )
    rsps_lib.add(
        rsps_lib.GET,
        f"{BASE_URL}/cgi-bin/vlan_static.cgi",
        body="<html/>",
        status=200,
    )
    session = _make_session()
    session.get("/cgi-bin/vlan_static.cgi", params={"vid": "10"})

    get_call = rsps_lib.calls[1]
    assert "vid=10" in get_call.request.url


# ---------------------------------------------------------------------------
# session.py — POST JSON parse + retry on code=11
# ---------------------------------------------------------------------------

@rsps_lib.activate
def test_post_success_returns_parsed_json() -> None:
    rsps_lib.add(
        rsps_lib.POST,
        f"{BASE_URL}{LOGIN}",
        body=_json({"code": CODE_OK, "data": ""}),
        status=200,
    )
    rsps_lib.add(
        rsps_lib.POST,
        f"{BASE_URL}/cgi-bin/vlan_static.cgi",
        body=_json({"code": CODE_OK, "data": "vlan list"}),
        status=200,
    )
    session = _make_session()
    result = session.post("/cgi-bin/vlan_static.cgi")
    assert result["code"] == CODE_OK
    assert result["data"] == "vlan list"


@rsps_lib.activate
def test_post_injects_page_inside() -> None:
    rsps_lib.add(
        rsps_lib.POST,
        f"{BASE_URL}{LOGIN}",
        body=_json({"code": CODE_OK, "data": ""}),
        status=200,
    )
    rsps_lib.add(
        rsps_lib.POST,
        f"{BASE_URL}/cgi-bin/vlan_static.cgi",
        body=_json({"code": CODE_OK, "data": ""}),
        status=200,
    )
    session = _make_session()
    session.post("/cgi-bin/vlan_static.cgi")

    vlan_call = rsps_lib.calls[1]
    assert "page=inside" in vlan_call.request.body


@rsps_lib.activate
def test_post_retry_on_auth_expiry() -> None:
    """On code=11 the session re-logs in and retries exactly once."""
    # First vlan call → auth expired
    rsps_lib.add(
        rsps_lib.POST,
        f"{BASE_URL}/cgi-bin/vlan_static.cgi",
        body=_json({"code": CODE_AUTH_EXPIRED, "data": ""}),
        status=200,
    )
    # Re-login
    rsps_lib.add(
        rsps_lib.POST,
        f"{BASE_URL}{LOGIN}",
        body=_json({"code": CODE_OK, "data": ""}),
        status=200,
    )
    # Retry vlan call → success
    rsps_lib.add(
        rsps_lib.POST,
        f"{BASE_URL}/cgi-bin/vlan_static.cgi",
        body=_json({"code": CODE_OK, "data": "vlans"}),
        status=200,
    )
    session = _make_session()
    session._logged_in = True  # bypass initial login

    result = session.post("/cgi-bin/vlan_static.cgi")

    assert result["code"] == CODE_OK
    assert len(rsps_lib.calls) == 3  # vlan(11) + login(0) + vlan(0)


@rsps_lib.activate
def test_post_switch_error_raises_jtcom_switch_error() -> None:
    rsps_lib.add(
        rsps_lib.POST,
        f"{BASE_URL}{LOGIN}",
        body=_json({"code": CODE_OK, "data": ""}),
        status=200,
    )
    rsps_lib.add(
        rsps_lib.POST,
        f"{BASE_URL}/cgi-bin/vlan_static.cgi",
        body=_json({"code": CODE_PARAM_ERR, "data": "invalid vid"}),
        status=200,
    )
    session = _make_session()
    with pytest.raises(JTComSwitchError) as exc_info:
        session.post("/cgi-bin/vlan_static.cgi")
    assert exc_info.value.code == CODE_PARAM_ERR


# ---------------------------------------------------------------------------
# session.py — ensure_session
# ---------------------------------------------------------------------------

@rsps_lib.activate
def test_ensure_session_logs_in_when_not_logged_in() -> None:
    rsps_lib.add(
        rsps_lib.POST,
        f"{BASE_URL}{LOGIN}",
        body=_json({"code": CODE_OK, "data": ""}),
        status=200,
    )
    session = _make_session()
    assert session.logged_in is False
    session.ensure_session()
    assert session.logged_in is True


@rsps_lib.activate
def test_ensure_session_skips_login_when_already_logged_in() -> None:
    session = _make_session()
    session._logged_in = True
    session.ensure_session()
    # No HTTP calls should have been made
    assert len(rsps_lib.calls) == 0


# ---------------------------------------------------------------------------
# session.py — close
# ---------------------------------------------------------------------------

@rsps_lib.activate
def test_close_calls_logout() -> None:
    rsps_lib.add(
        rsps_lib.POST,
        f"{BASE_URL}{LOGOUT}",
        body=_json({"code": CODE_OK, "data": ""}),
        status=200,
    )
    session = _make_session()
    session._logged_in = True
    session.close()
    assert session.logged_in is False
    assert any(LOGOUT in call.request.url for call in rsps_lib.calls)
