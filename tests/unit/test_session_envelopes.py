"""Typed login and CGI envelope failures do not leave stale auth state."""

import pytest
import responses

from cgiswitch.client.errors import JTComAuthError, JTComParseError
from cgiswitch.client.session import JTComCredentials, JTComSession

BASE = "http://192.0.2.1"


@pytest.mark.parametrize("body", ["<html>not json</html>", "[]", "null", '{}',
                                  '{"code": true}', '{"code": 0.5}', '{"code": "bad"}'])
@responses.activate
def test_failed_login_parse_clears_previous_authenticated_state(body: str) -> None:
    session = JTComSession(BASE, JTComCredentials("admin", "secret"))
    session._logged_in = True
    responses.add(responses.POST, BASE + "/login.cgi", body=body)
    with pytest.raises(JTComParseError):
        session.login()
    assert session.logged_in is False
    assert len(responses.calls) == 1


@pytest.mark.parametrize("status", [401, 403])
@responses.activate
def test_login_http_auth_failure_is_typed_and_not_retried(status: int) -> None:
    session = JTComSession(BASE, JTComCredentials("admin", "secret"))
    session._logged_in = True
    responses.add(responses.POST, BASE + "/login.cgi", status=status)
    with pytest.raises(JTComAuthError):
        session.login()
    assert session.logged_in is False
    assert len(responses.calls) == 1


@responses.activate
def test_string_cgi_codes_follow_the_same_bounded_retry() -> None:
    session = JTComSession(BASE, JTComCredentials("admin", "secret"))
    session._logged_in = True
    responses.add(responses.POST, BASE + "/port.cgi", body='{"code":"11"}')
    responses.add(responses.POST, BASE + "/login.cgi", body='{"code":"0"}')
    responses.add(responses.POST, BASE + "/port.cgi", body='{"code":"0", "data":"ok"}')
    assert session.post("/port.cgi") == {"code": 0, "data": "ok"}
    assert len(responses.calls) == 3


@responses.activate
def test_malformed_expiry_code_does_not_replay_post() -> None:
    session = JTComSession(BASE, JTComCredentials("admin", "secret"))
    session._logged_in = True
    responses.add(responses.POST, BASE + "/port.cgi", body='{"code":11.0}')
    with pytest.raises(JTComParseError):
        session.post("/port.cgi")
    assert len(responses.calls) == 1


@responses.activate
def test_redirect_to_login_is_reauthenticated_once() -> None:
    session = JTComSession(BASE, JTComCredentials("admin", "secret"))
    session._logged_in = True
    responses.add(responses.GET, BASE + "/info.cgi", status=302,
                  headers={"Location": "/login.cgi"})
    responses.add(responses.GET, BASE + "/login.cgi", body="login screen")
    responses.add(responses.POST, BASE + "/login.cgi", body='{"code":0}')
    responses.add(responses.GET, BASE + "/info.cgi", body="fresh state")
    assert session.get("/info.cgi") == "fresh state"
    assert len(responses.calls) == 4


@responses.activate
def test_ambiguous_post_transport_failure_is_never_replayed() -> None:
    import requests

    from cgiswitch.client.errors import JTComRequestError

    session = JTComSession(BASE, JTComCredentials("admin", "secret"))
    session._logged_in = True
    timeout = requests.exceptions.Timeout("write outcome unknown")
    responses.add(responses.POST, BASE + "/port.cgi", body=timeout)
    with pytest.raises(JTComRequestError) as captured:
        session.post("/port.cgi", {"portid": "0", "state": "0"})
    assert captured.value.cause is timeout
    assert len(responses.calls) == 1


@responses.activate
def test_success_payload_containing_login_markup_does_not_trigger_replay() -> None:
    import json

    session = JTComSession(BASE, JTComCredentials("admin", "secret"))
    session._logged_in = True
    data = '<form action=/login.cgi><input type=password></form>'
    responses.add(responses.POST, BASE + "/port.cgi", body=json.dumps({"code": 0, "data": data}))
    assert session.post("/port.cgi")["data"] == data
    assert len(responses.calls) == 1


@responses.activate
def test_binary_backup_containing_login_markup_does_not_trigger_relogin() -> None:
    session = JTComSession(BASE, JTComCredentials("admin", "secret"))
    session._logged_in = True
    body = b'\x00opaque <form action=/login.cgi><input type=password></form>\xff'
    responses.add(responses.GET, BASE + "/config.cgi", body=body)
    assert session.download_config_backup() == body
    assert len(responses.calls) == 1
