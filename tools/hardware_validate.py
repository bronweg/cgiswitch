"""Capture hardware evidence and run explicitly scoped, operator-approved patches."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from cgiswitch import ApplyPolicy, JTComApplyError, JTComConnectionOptions, JTComSwitch
from cgiswitch.client.session import JTComCredentials, JTComSession
from cgiswitch.model.config import DeviceConfig
from cgiswitch.model.port import PortConfig
from cgiswitch.model.vlan import VlanConfig


def arguments() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['read', 'backup', 'apply'])
    parser.add_argument('--url', required=True, help='Explicit http:// or https:// device URL')
    parser.add_argument('--output', type=Path, required=True, help='New private evidence directory')
    parser.add_argument('--insecure', action='store_true', help='Disable HTTPS certificate checks')
    parser.add_argument('--desired', type=Path, help='JSON with Python config model fields')
    parser.add_argument('--baseline', type=Path, help='Initial read-mode before.json')
    parser.add_argument('--test-port', type=int)
    parser.add_argument('--management-port', type=int)
    parser.add_argument('--vlan-ids', type=int, nargs='+', default=[])
    parser.add_argument('--allow-port-mode-change', action='store_true')
    parser.add_argument('--allow-untagged-move', action='store_true')
    parser.add_argument('--idle-seconds', type=int, default=0,
                        help='Natural-expiry wait after login, read/backup modes only')
    parser.add_argument('--execute', action='store_true', help='Enable one patch and repeat check')
    for name in ('isolated-port', 'recovery-access', 'backup-restorable'):
        parser.add_argument(f'--confirm-{name}', action='store_true')
    return parser


def validate_scope(args: argparse.Namespace) -> None:
    """Reject unsafe or ambiguous invocations before connecting."""
    url = urlsplit(args.url)
    if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password:
        raise ValueError('Use an explicit HTTP(S) URL without embedded credentials')
    if url.query or url.fragment or url.path not in ('', '/'):
        raise ValueError('Use a device base URL without path, query, or fragment')
    if not 0 <= args.idle_seconds <= 86400 or (args.mode == 'apply' and args.idle_seconds):
        raise ValueError('--idle-seconds must be 0..86400 and is for read/backup only')
    if args.execute and args.mode != 'apply':
        raise ValueError('--execute is only supported in apply mode')
    if args.mode != 'apply':
        return
    if args.desired is None or args.baseline is None:
        raise ValueError('Apply mode requires --desired and --baseline')
    if not args.test_port or args.test_port < 1:
        raise ValueError('Select a positive --test-port')
    if not args.management_port or args.management_port < 1:
        raise ValueError('Select a positive --management-port')
    if args.test_port == args.management_port:
        raise ValueError('The management port cannot be the test port')
    if not args.vlan_ids or any(not 2 <= vid <= 4094 for vid in args.vlan_ids):
        raise ValueError('Declare disposable --vlan-ids in range 2..4094')
    if args.execute and not all((
        args.confirm_isolated_port, args.confirm_recovery_access, args.confirm_backup_restorable,
    )):
        raise ValueError('Writes require all three operator confirmations; see hardware checklist')


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate JSON key: {key}')
        result[key] = value
    return result


def load_desired(path: Path, test_port: int, vlan_ids: set[int]) -> DeviceConfig:
    """Accept only a narrow patch for the isolated port and disposable VLANs."""
    raw = json.loads(path.read_text(), object_pairs_hook=unique_object)
    if not isinstance(raw, dict) or set(raw) - {'ports', 'vlans'}:
        raise ValueError('Desired input must contain only ports and vlans maps')
    vlans: dict[int, VlanConfig] = {}
    ports: dict[int, PortConfig] = {}
    for kind in ('vlans', 'ports'):
        entries = raw.get(kind, {})
        if not isinstance(entries, dict):
            raise ValueError(f'{kind} must be a map')
        for key, entry in entries.items():
            if not key.isascii() or not key.isdecimal() or not isinstance(entry, dict):
                raise ValueError(f'Invalid {kind} entry')
            identifier = int(key)
            if identifier in (vlans if kind == 'vlans' else ports):
                raise ValueError(f'Duplicate normalized {kind} ID')
            if identifier not in (vlan_ids if kind == 'vlans' else {test_port}):
                raise ValueError(f'{kind} ID outside declared disposable scope')
            fields = dict(entry)
            for name, value in fields.items():
                if value is None:
                    continue
                if name in ('name', 'state', 'speed_duplex'):
                    if not isinstance(value, str):
                        raise ValueError(f'{name} must be a string')
                elif name in ('admin_up', 'flow_control'):
                    if type(value) is not bool:
                        raise ValueError(f'{name} must be a boolean')
                elif name in ('access_vlan', 'native_vlan'):
                    if type(value) is not int or value not in vlan_ids:
                        raise ValueError(f'{name} must reference a declared disposable VLAN')
                else:
                    allowed = {test_port} if kind == 'vlans' else vlan_ids
                    if not isinstance(value, list) or any(
                        type(item) is not int or item not in allowed for item in value
                    ):
                        raise ValueError(f'{name} must be a list within declared scope')
            if kind == 'vlans':
                vlans[identifier] = VlanConfig(vlan_id=identifier, **fields)
            else:
                ports[identifier] = PortConfig(port_id=identifier, **fields)
    return DeviceConfig(vlans=vlans, ports=ports)


def save(directory: Path, name: str, value: object) -> None:
    with (directory / name).open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def snapshot(switch: JTComSwitch) -> dict[str, Any]:
    settings, operational = switch.read_ports()
    return {
        'device': asdict(switch.read_device_info()),
        'ports': [asdict(port) for port in settings],
        'operational': [asdict(port) for port in operational],
        'vlans': {str(vid): asdict(vlan) for vid, vlan in switch.read_vlans().items()},
    }


def check_preview(preview: dict[str, Any], args: argparse.Namespace) -> None:
    if preview.get('blocked'):
        raise ValueError('Policy blocked the preview; inspect preview.json')
    if set(preview.get('changed_ports', [])) - {args.test_port}:
        raise ValueError('Preview would affect another port')
    for operation in preview['operations']:
        key = operation['key'].removeprefix('vlan_membership:')
        entity, identifier = key.split(':')
        allowed = {'port': {args.test_port}, 'vlan': set(args.vlan_ids)}
        if entity not in allowed or int(identifier) not in allowed[entity]:
            raise ValueError('Preview operation escaped declared scope')


def check_test_membership(observed: dict[str, Any], args: argparse.Namespace) -> None:
    """Allow only disposable tags and one default/disposable native VLAN for live tests."""
    port = f'Port {args.test_port}'
    tagged: set[int] = set()
    untagged: set[int] = set()
    for key, vlan in observed['vlans'].items():
        if port in vlan['tagged_ports']:
            tagged.add(int(key))
        if port in vlan['untagged_ports']:
            untagged.add(int(key))
    disposable = set(args.vlan_ids)
    if tagged - disposable:
        raise ValueError('Test port has non-disposable tagged membership; live test refused')
    if len(untagged) != 1 or not untagged <= disposable | {1}:
        raise ValueError('Unexpected or unknown test-port untagged/native VLAN; live test refused')


def check_baseline(
    baseline: dict[str, Any], observed: dict[str, Any], args: argparse.Namespace,
) -> None:
    """Require an initial baseline with absent disposable IDs on the same device."""
    mac = baseline['device'].get('mac_address')
    if not mac or mac != observed['device'].get('mac_address'):
        raise ValueError('Baseline device identity does not match')
    if set(map(str, args.vlan_ids)) & set(baseline['vlans']):
        raise ValueError('Disposable VLAN IDs were already present in the baseline')
    for state in (baseline, observed):
        known = {port['port_id'] for port in state['ports']}
        if not {args.test_port, args.management_port} <= known:
            raise ValueError('Test and management ports must exist in both snapshots')
    if args.execute:
        check_test_membership(baseline, args)
        check_test_membership(observed, args)
    for vid in args.vlan_ids:
        vlan = observed['vlans'].get(str(vid))
        if vlan is not None:
            members = set(vlan['tagged_ports']) | set(vlan['untagged_ports'])
            if members - {f'Port {args.test_port}'}:
                raise ValueError('Disposable VLAN is now used by another port')


def run(args: argparse.Namespace) -> None:
    args.evidence_created = False
    validate_scope(args)
    desired = None
    if args.mode == 'apply':
        desired = load_desired(args.desired, args.test_port, set(args.vlan_ids))
    username = os.environ['JTCOM_USERNAME']
    password = os.environ['JTCOM_PASSWORD']
    if not username or not password:
        raise ValueError('Credentials must not be empty')
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    args.evidence_created = True
    revision = subprocess.run(
        ['git', '-C', str(Path(__file__).resolve().parents[1]), 'rev-parse', 'HEAD'],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    save(args.output, 'run.json', {
        'started_utc': datetime.now(UTC).isoformat(), 'revision': revision,
        'url': args.url, 'mode': args.mode, 'execute': args.execute,
        'test_port': args.test_port, 'management_port': args.management_port,
        'vlan_ids': args.vlan_ids, 'verify_tls': not args.insecure,
        'idle_seconds': args.idle_seconds,
        'allow_port_mode_change': args.allow_port_mode_change,
        'allow_untagged_move': args.allow_untagged_move,
        'operator_confirmations': {
            'isolated_port': args.confirm_isolated_port,
            'recovery_access': args.confirm_recovery_access,
            'backup_restorable': args.confirm_backup_restorable,
        },
        'hardware_validation_status': 'INCOMPLETE: operator comparison and sign-off required',
    })
    try:
        if args.mode == 'backup':
            session = JTComSession(
                args.url, JTComCredentials(username, password), verify_tls=not args.insecure,
            )
            try:
                session.login()
                if args.idle_seconds:
                    time.sleep(args.idle_seconds)
                body = session.download_config_backup()
                (args.output / 'config.bin').write_bytes(body)
                save(args.output, 'backup.json', {
                    'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
                    'restore_verified': False,
                })
            finally:
                session.close()
            return
        policy = ApplyPolicy(
            safety_port_id=args.management_port or 6, backup_dir=args.output / 'backups',
            allow_port_mode_change=args.allow_port_mode_change,
            allow_untagged_move=args.allow_untagged_move,
        )
        with JTComSwitch(
            args.url, username, password,
            connection=JTComConnectionOptions(verify_tls=not args.insecure), policy=policy,
        ) as switch:
            observed = snapshot(switch)
            save(args.output, 'before.json', observed)
            if desired is None:
                if args.idle_seconds:
                    time.sleep(args.idle_seconds)
                    save(args.output, 'after-idle.json', snapshot(switch))
                return
            baseline = json.loads(args.baseline.read_text())
            check_baseline(baseline, observed, args)
            save(args.output, 'baseline.json', baseline)
            save(args.output, 'desired.json', asdict(desired))
            preview = switch.apply(desired, check_mode=True)
            save(args.output, 'preview.json', preview)
            check_preview(preview, args)
            if not args.execute:
                return
            live_state = snapshot(switch)
            save(args.output, 'pre-apply.json', live_state)
            check_baseline(baseline, live_state, args)
            result = switch.apply(desired)
            save(args.output, 'apply.json', result)
            save(args.output, 'after.json', snapshot(switch))
            repeated_preview = switch.apply(desired, check_mode=True)
            save(args.output, 'repeat-preview.json', repeated_preview)
            if repeated_preview['changed'] or repeated_preview['blocked']:
                raise ValueError('Repeat preview is not an unblocked no-op; stopping')
            repeat_state = snapshot(switch)
            save(args.output, 'pre-repeat-apply.json', repeat_state)
            check_baseline(baseline, repeat_state, args)
            repeated = switch.apply(desired)
            save(args.output, 'repeat-apply.json', repeated)
            if repeated['changed'] or repeated['applied'] or repeated['backup_file']:
                raise ValueError('Repeated apply was not a no-op; stop hardware testing')
    except Exception as exc:
        detail = exc.as_result() if isinstance(exc, JTComApplyError) else {
            'type': type(exc).__name__, 'message': str(exc),
        }
        save(args.output, 'failure.json', detail)
        raise


def sanitized_error(exc: Exception) -> str:
    """Remove environment credentials and control characters from early diagnostics."""
    message = str(exc)
    for key in ('JTCOM_USERNAME', 'JTCOM_PASSWORD'):
        secret = os.environ.get(key)
        if secret:
            message = message.replace(secret, '[redacted]')
            message = message.replace(repr(secret)[1:-1], '[redacted]')
    message = re.sub(r'(https?://)[^/\s]*@', r'\1[redacted]@', message)
    message = ''.join(char if char.isprintable() else ' ' for char in message)
    return f'{type(exc).__name__}: {message}'


def main() -> None:
    args = arguments().parse_args()
    try:
        run(args)
    except Exception as exc:
        if getattr(args, 'evidence_created', False):
            message = f'{type(exc).__name__}: stopped; inspect private evidence directory'
        else:
            message = sanitized_error(exc)
        raise SystemExit(message) from None
    print('Evidence captured. Hardware validation remains incomplete until operator sign-off.')


if __name__ == '__main__':
    main()
