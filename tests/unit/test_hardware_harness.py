"""Offline guard tests for the hardware runner; these are not hardware results."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cgiswitch import JTComApplyError

SPEC = importlib.util.spec_from_file_location('hardware_runner', 'tools/hardware_validate.py')
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def arguments(tmp_path: Path, *extra: str) -> SimpleNamespace:
    return runner.arguments().parse_args([
        'apply', '--url', 'http://192.0.2.1', '--output', str(tmp_path / 'evidence'),
        '--desired', str(tmp_path / 'desired.json'), '--baseline', str(tmp_path / 'baseline.json'),
        '--test-port', '2', '--management-port', '6', '--vlan-ids', '3000', *extra,
    ])


@pytest.mark.parametrize('extra', [
    ['--test-port', '6'], ['--test-port', '0'], ['--management-port', '-1'],
    ['--vlan-ids', '1'], ['--vlan-ids', '4095'], ['--execute'],
    ['--url', '192.0.2.1'], ['--url', 'http://admin:secret@192.0.2.1'],
    ['--url', 'https://192.0.2.1/login.cgi'],
])
def test_invocation_guards_precede_connection(tmp_path: Path, extra: list[str]) -> None:
    with pytest.raises(ValueError):
        runner.validate_scope(arguments(tmp_path, *extra))
    assert not (tmp_path / 'evidence').exists()


@pytest.mark.parametrize('desired', [
    {'ports': {'6': {'admin_up': False}}},
    {'vlans': {'20': {'state': 'absent'}}},
    {'vlans': {'3000': {'tagged_add': [6]}}},
    {'ports': {'2': {'access_vlan': 20}}},
    {'ports': {'2': {'admin_up': 'false'}}},
    {'vlans': {'3000': {'tagged_add': [True]}}},
    {'ports': {'2': {'flow_controll': True}}},
    {'ports': {'2': {}, '02': {}}},
])
def test_desired_scope_rejection(tmp_path: Path, desired: dict) -> None:
    path = tmp_path / 'desired.json'
    path.write_text(json.dumps(desired))
    with pytest.raises((ValueError, TypeError)):
        runner.load_desired(path, 2, {3000})


def state() -> dict:
    return {
        'device': {'mac_address': '00:11:22:33:44:55'},
        'ports': [{'port_id': 2}, {'port_id': 6}], 'vlans': {},
    }


@pytest.mark.parametrize('fault', ['device', 'allocated', 'shared', 'unknown_port'])
def test_baseline_guards(tmp_path: Path, fault: str) -> None:
    baseline, observed = state(), state()
    if fault == 'device':
        observed['device']['mac_address'] = 'other'
    elif fault == 'allocated':
        baseline['vlans']['3000'] = {}
    elif fault == 'shared':
        observed['vlans']['3000'] = {'tagged_ports': ['Port 6'], 'untagged_ports': []}
    else:
        observed['ports'] = [{'port_id': 6}]
    with pytest.raises(ValueError):
        runner.check_baseline(baseline, observed, arguments(tmp_path))


def test_preview_accepts_test_membership_but_rejects_other_port(tmp_path: Path) -> None:
    preview = {'operations': [{'key': 'vlan_membership:port:2'}], 'changed_ports': [2]}
    runner.check_preview(preview, arguments(tmp_path))
    preview['operations'][0]['key'] = 'port:6'
    with pytest.raises(ValueError):
        runner.check_preview(preview, arguments(tmp_path))


def prepare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    (tmp_path / 'desired.json').write_text('{"vlans":{"3000":{"name":"lab"}}}')
    (tmp_path / 'baseline.json').write_text(json.dumps(state()))
    monkeypatch.setenv('JTCOM_USERNAME', 'lab-user')
    monkeypatch.setenv('JTCOM_PASSWORD', 'secret-never-in-metadata')
    switch = MagicMock()
    switch.__enter__.return_value = switch
    monkeypatch.setattr(runner, 'JTComSwitch', MagicMock(return_value=switch))
    monkeypatch.setattr(runner, 'snapshot', lambda _: state())
    return switch


def preview(changed: bool = True) -> dict:
    return {
        'changed': changed, 'blocked': False, 'changed_ports': [],
        'operations': [{'key': 'vlan:3000'}] if changed else [],
        'applied': [], 'backup_file': '',
    }


def test_default_apply_only_previews(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    switch = prepare(tmp_path, monkeypatch)
    switch.apply.return_value = preview()
    runner.run(arguments(tmp_path))
    assert len(switch.apply.call_args_list) == 1
    assert switch.apply.call_args.kwargs == {'check_mode': True}
    metadata = (tmp_path / 'evidence/run.json').read_text()
    assert 'secret-never-in-metadata' not in metadata
    assert 'INCOMPLETE' in metadata


def execute_args(tmp_path: Path) -> SimpleNamespace:
    return arguments(tmp_path, '--execute', '--confirm-isolated-port',
                     '--confirm-recovery-access', '--confirm-backup-restorable')


def test_success_repeats_apply_as_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    switch = prepare(tmp_path, monkeypatch)
    switch.apply.side_effect = [preview(), preview(), preview(False), preview(False)]
    runner.run(execute_args(tmp_path))
    assert [c.kwargs for c in switch.apply.call_args_list] == [
        {'check_mode': True}, {}, {'check_mode': True}, {},
    ]
    assert (tmp_path / 'evidence/repeat-apply.json').exists()


def test_non_idempotent_preview_stops_before_second_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    switch = prepare(tmp_path, monkeypatch)
    switch.apply.side_effect = [preview(), preview(), preview()]
    with pytest.raises(ValueError, match='Repeat preview'):
        runner.run(execute_args(tmp_path))
    assert switch.apply.call_count == 3
    assert (tmp_path / 'evidence/failure.json').exists()


def test_partial_failure_retains_context_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    switch = prepare(tmp_path, monkeypatch)
    error = JTComApplyError(
        backup_file='private/config.bin', completed_operations=[],
        failed_operation={'key': 'vlan:3000'}, original_exception=RuntimeError('write failed'),
        write_attempted=True,
    )
    switch.apply.side_effect = [preview(), error]
    with pytest.raises(JTComApplyError):
        runner.run(execute_args(tmp_path))
    assert switch.apply.call_count == 2
    assert json.loads((tmp_path / 'evidence/failure.json').read_text()) == error.as_result()


def test_backup_waits_in_authenticated_session_and_preserves_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare(tmp_path, monkeypatch)
    session = MagicMock()
    session.download_config_backup.return_value = b'opaque backup bytes'
    monkeypatch.setattr(runner, 'JTComSession', MagicMock(return_value=session))
    wait = MagicMock(side_effect=lambda _: session.login.assert_called_once())
    monkeypatch.setattr(runner.time, 'sleep', wait)
    args = arguments(tmp_path)
    args.mode, args.idle_seconds = 'backup', 123
    runner.run(args)
    wait.assert_called_once_with(123)
    session.download_config_backup.assert_called_once()
    session.close.assert_called_once()
    assert (tmp_path / 'evidence/config.bin').read_bytes() == b'opaque backup bytes'
    assert json.loads((tmp_path / 'evidence/backup.json').read_text())['restore_verified'] is False


def test_read_idle_is_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    switch = prepare(tmp_path, monkeypatch)
    wait = MagicMock()
    monkeypatch.setattr(runner.time, 'sleep', wait)
    args = arguments(tmp_path)
    args.mode, args.idle_seconds = 'read', 123
    runner.run(args)
    switch.apply.assert_not_called()
    wait.assert_called_once_with(123)
    assert (tmp_path / 'evidence/after-idle.json').exists()


def test_blocked_preview_never_applies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    switch = prepare(tmp_path, monkeypatch)
    switch.apply.return_value = {**preview(), 'blocked': True}
    with pytest.raises(ValueError, match='Policy blocked'):
        runner.run(execute_args(tmp_path))
    assert switch.apply.call_count == 1
    assert switch.apply.call_args.kwargs == {'check_mode': True}
