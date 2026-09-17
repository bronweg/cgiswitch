"""Credential transitions verify authentication and never replay mutations."""

import json
import logging
from unittest.mock import MagicMock

import pytest

from cgiswitch.bootstrap import credentials as module
from cgiswitch.bootstrap.errors import JTComTransitionError
from cgiswitch.bootstrap.identity import DeviceIdentity
from cgiswitch.client.errors import JTComAuthError, JTComRequestError, JTComSwitchError
from cgiswitch.client.session import JTComCredentials
from cgiswitch.model.device import DeviceInfo

URL = 'http://192.0.2.1'
CURRENT = JTComCredentials('admin', 'OldFixture1!')
TARGET = JTComCredentials('admin', 'NewFixture2!')
IDENTITY = DeviceIdentity('02:00:00:00:00:01', 'fixture-id')
DEVICE = DeviceInfo(IDENTITY.mac_address, serial_number=IDENTITY.serial_number)


@pytest.fixture
def setup(monkeypatch: pytest.MonkeyPatch) -> dict:
    sessions = [MagicMock() for _ in range(4)]
    sessions[0].login.side_effect = JTComAuthError('rejected')
    sessions[3].login.side_effect = JTComAuthError('rejected')
    factory = MagicMock(side_effect=sessions)
    monkeypatch.setattr(module, 'JTComSession', factory)
    identity = MagicMock(return_value=DEVICE)
    monkeypatch.setattr(module, 'parse_device_info', identity)
    write = MagicMock()
    monkeypatch.setattr(module, 'change_password_once', write)
    return dict(sessions=sessions, factory=factory, identity=identity, write=write)


def run() -> module.CredentialTransitionResult:
    return module.transition_credentials(URL, CURRENT, TARGET, IDENTITY)


def test_success_exactly_once_discard_and_target_login(setup: dict) -> None:
    result = run()
    assert result.changed
    setup['write'].assert_called_once_with(setup['sessions'][1], TARGET.username, TARGET.password)
    assert [c.args[1] for c in setup['factory'].call_args_list] == [
        TARGET, CURRENT, TARGET, CURRENT,
    ]
    for session in setup['sessions']:
        session._discard.assert_called_once()
    serialized = json.dumps(result.__dict__, default=str)
    assert TARGET.password not in serialized and CURRENT.password not in serialized


def test_already_target_no_write(setup: dict) -> None:
    setup['sessions'][0].login.side_effect = None
    setup['sessions'][1].login.side_effect = JTComAuthError('rejected')
    assert not run().changed
    setup['write'].assert_not_called()


def test_both_invalid_zero_write(setup: dict) -> None:
    setup['sessions'][1].login.side_effect = JTComAuthError('rejected')
    with pytest.raises(JTComTransitionError) as caught:
        run()
    assert not caught.value.write_attempted
    setup['write'].assert_not_called()


@pytest.mark.parametrize('initial_target_works', [False, True])
def test_wrong_device_before_mutation(setup: dict, initial_target_works: bool) -> None:
    if initial_target_works:
        setup['sessions'][0].login.side_effect = None
    setup['identity'].return_value = DeviceInfo('02:00:00:00:00:02')
    with pytest.raises(JTComTransitionError) as caught:
        run()
    assert not caught.value.write_attempted
    setup['write'].assert_not_called()


def test_response_lost_target_auth_reconciles(setup: dict) -> None:
    setup['write'].side_effect = JTComRequestError(URL, TimeoutError('lost'))
    assert run().changed
    assert setup['write'].call_count == 1


def test_response_lost_target_fails_no_retry(setup: dict) -> None:
    setup['write'].side_effect = JTComRequestError(URL, TimeoutError('lost'))
    setup['sessions'][2].login.side_effect = JTComAuthError('rejected')
    with pytest.raises(JTComTransitionError) as caught:
        run()
    assert caught.value.write_attempted
    assert caught.value.stage == 'verify_target_credentials'
    assert setup['write'].call_count == 1


def test_rejected_post_is_typed_failure(setup: dict) -> None:
    setup['write'].side_effect = JTComSwitchError(1, 'rejected', '/user.cgi')
    with pytest.raises(JTComTransitionError) as caught:
        run()
    assert caught.value.stage == 'write_credentials'
    assert setup['write'].call_count == 1


def test_old_password_still_accepted_fails_closed(setup: dict) -> None:
    setup['sessions'][3].login.side_effect = None
    with pytest.raises(JTComTransitionError) as caught:
        run()
    assert caught.value.stage == 'verify_old_rejected'
    assert caught.value.write_attempted


def test_identity_read_auth_failure_is_not_a_rejected_login(setup: dict) -> None:
    setup['sessions'][0].login.side_effect = None
    setup['sessions'][0].get.side_effect = JTComAuthError('expired during read')
    with pytest.raises(JTComTransitionError):
        run()
    setup['write'].assert_not_called()
    assert setup['factory'].call_count == 1


def test_secret_safe_errors_results_and_logs(setup: dict, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    setup['write'].side_effect = RuntimeError(CURRENT.password + TARGET.password)
    with pytest.raises(JTComTransitionError) as caught:
        run()
    for password in [CURRENT.password, TARGET.password]:
        assert password not in repr(CURRENT)
        assert password not in repr(TARGET)
        assert password not in str(caught.value)
        assert password not in json.dumps(caught.value.as_result())
        assert password not in caplog.text
