"""Secret-safe credential CGI requests use exactly one POST."""

import logging
from urllib.parse import parse_qs

import pytest
import requests
import responses

from cgiswitch.client.errors import JTComAuthError, JTComRequestError
from cgiswitch.client.session import JTComCredentials, JTComSession
from cgiswitch.client.user_ops import change_password_once

URL = 'http://192.0.2.1'
SECRET = 'TestValue123!'


@responses.activate
def test_password_form_and_debug_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    responses.add(responses.POST, URL + '/user.cgi', json={'code': 0, 'data': ''})
    session = JTComSession(URL, JTComCredentials('admin', SECRET))
    session._logged_in = True
    change_password_once(session, 'admin', SECRET)
    assert len(responses.calls) == 1
    assert parse_qs(responses.calls[0].request.body) == {
        'page': ['inside'], 'mname': ['admin'], 'mpass': [SECRET], 'mpass2': [SECRET],
    }
    assert SECRET not in caplog.text
    session._discard()


@responses.activate
def test_credential_transport_error_does_not_retain_secret() -> None:
    responses.add(responses.POST, URL + '/user.cgi', body=requests.Timeout(SECRET))
    session = JTComSession(URL, JTComCredentials('admin', SECRET))
    session._logged_in = True
    with pytest.raises(JTComRequestError) as caught:
        change_password_once(session, 'admin', SECRET)
    assert SECRET not in str(caught.value)
    assert SECRET not in str(caught.value.cause)
    assert len(responses.calls) == 1
    session._discard()


@responses.activate
def test_login_rejection_does_not_echo_response_data(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    responses.add(responses.POST, URL + '/login.cgi', json={'code': 1, 'data': SECRET})
    session = JTComSession(URL, JTComCredentials('admin', SECRET))
    with pytest.raises(JTComAuthError) as caught:
        session.login()
    assert SECRET not in str(caught.value)
    assert SECRET not in caplog.text
    session._discard()
