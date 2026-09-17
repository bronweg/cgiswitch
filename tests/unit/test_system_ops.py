"""One-shot management commands must never replay an ambiguous write."""

import json
from unittest.mock import MagicMock

import pytest
import requests

from cgiswitch.client.errors import JTComAuthError, JTComParseError, JTComSwitchError
from cgiswitch.client.session import JTComCredentials, JTComSession
from cgiswitch.client.system_ops import save_config


def session_with_response(body: str, content_type: str = 'application/json') -> JTComSession:
    session = JTComSession('http://192.0.2.1', JTComCredentials('fixture-user', ''))
    session._logged_in = True
    response = requests.Response()
    response.status_code = 200
    response._content = body.encode()
    response.headers['Content-Type'] = content_type
    session._http = MagicMock()
    session._http.post_form.return_value = response
    return session


def test_save_config_exact_one_shot() -> None:
    session = session_with_response('{"code":0,"data":""}')
    save_config(session)
    session._http.post_form.assert_called_once_with(
        '/syscmd.cgi', data={'page': 'inside', 'cmd': 'saveconfig'},
    )


@pytest.mark.parametrize('body,content_type,error', [
    ('{"code":11,"data":""}', 'application/json', JTComAuthError),
    ('{"code":1,"data":"rejected"}', 'application/json', JTComSwitchError),
    ('{"code":0}', 'application/json', JTComParseError),
    ('{"code":0,"data":"unexpected"}', 'application/json', JTComParseError),
    ('{"code":0,"data":"","extra":1}', 'application/json', JTComParseError),
    ('<html>Error</html>', 'text/html', JTComParseError),
])
def test_save_rejection_never_retries(body: str, content_type: str, error: type) -> None:
    session = session_with_response(body, content_type)
    with pytest.raises(error):
        save_config(session)
    assert session._http.post_form.call_count == 1


def test_save_connection_loss_never_retries() -> None:
    session = session_with_response('')
    session._http.post_form.side_effect = TimeoutError('connection lost')
    with pytest.raises(TimeoutError):
        save_config(session)
    assert session._http.post_form.call_count == 1


def test_credentials_repr_and_command_errors_do_not_echo_secret() -> None:
    secret = ''.join(chr(i) for i in [83, 101, 110, 115, 105, 116, 105, 118, 101])
    assert secret not in repr(JTComCredentials('fixture-user', secret))
    session = session_with_response(json.dumps({'code': 1, 'data': secret}))
    with pytest.raises(JTComSwitchError) as caught:
        save_config(session)
    assert secret not in str(caught.value)
    assert caught.value.payload is None


def test_save_http_auth_expiry_does_not_relogin_or_repeat() -> None:
    from cgiswitch.client.errors import JTComResponseError

    session = session_with_response('')
    session._http.post_form.side_effect = JTComResponseError(401, 'http://192.0.2.1/syscmd.cgi')
    with pytest.raises(JTComAuthError):
        save_config(session)
    assert session._http.post_form.call_count == 1
    assert session.logged_in is False
