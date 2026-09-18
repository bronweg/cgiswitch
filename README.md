# cgiswitch

`cgiswitch` is a typed Python client and Ansible collection for JTCom L2
Ethernet switches that expose an HTTP CGI web interface. The project is Alpha
software; fixture-backed tests and controlled hardware validation are available
for one device/firmware. Backup restore and session-expiry validation remain pending.

The apply path takes a backup before changes by default, verifies the result by
reading the switch again, and does not attempt automatic rollback. It does not
provide a transactional commit or a general configuration restore workflow.
The implementation targets the observed JTCom CGI endpoints and makes no
generic compatibility guarantee for other firmware.

## Installation

The package version in this checkout is `0.1.0` and requires Python 3.11 or
newer. To use the core from a source checkout:

```bash
git clone https://github.com/bronweg/cgiswitch.git
cd cgiswitch
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

The Ansible collection is in `galaxy/bronweg/cgiswitch`. Install
`ansible-core` first so that `ansible-galaxy` is available, then build and
install the collection from the checkout:

```bash
python -m pip install 'ansible-core>=2.14'
ansible-galaxy collection build --force galaxy/bronweg/cgiswitch
ansible-galaxy collection install bronweg-cgiswitch-0.1.0.tar.gz
```

The collection declares `requires_ansible: ">=2.14.0"`. The action plugin runs
the core in the Ansible controller's Python environment, so this checkout's
`cgiswitch` package must be installed there as well. The supported Ansible interface is
`bronweg.cgiswitch.jtcom_config`.

## Bootstrap

The `BootstrapConfig` / `bootstrap_switch` API and the
`bronweg.cgiswitch.jtcom_bootstrap` Ansible interface can transition JTCom
credentials and management addressing from factory to target endpoints. The
workflow verifies device identity across all credential and endpoint probes,
orders credential changes before network changes, and saves only when a
change is required. See [the bootstrap guide](docs/BOOTSTRAP.md) for endpoint
requirements, check-mode behavior, persistence limits, and secret handling.

Complete hardware validation of this workflow is still pending.

## Connection scheme and TLS

For an Ansible `host` without a scheme, `verify_tls: true` (the default)
selects HTTPS/443, while `verify_tls: false` selects HTTP/80. Explicit
`http://` or `https://` in `host` sets the scheme directly. On HTTPS,
`verify_tls` controls certificate verification: an explicit HTTPS URL with
`verify_tls: false` still uses HTTPS, with verification disabled.

The Python API has the same behavior through `hostname` and
`JTComConnectionOptions.verify_tls`; `connection.port` can override the
default port for a hostname without a scheme.

## What is supported

The core provides these read operations:

- `read_device_info()`
- `read_ports()`
- `read_vlans()`

`apply(DeviceConfig(...))` provides idempotent, incremental writes for VLAN
creation, renaming, membership updates, VLAN deletion, port administrative
state, speed/duplex, flow control, and port-centric access/trunk membership. The same operations are
available through the Ansible module. Port IDs are 1-based throughout the
project and VLAN IDs must be in `1..4094`.

Desired VLAN entries use `state: "present"` (the default) or `state: "absent"`.
Port entries are patches: omit a port field to leave that setting unchanged.
VLAN membership can be expressed either by VLAN (`tagged_add`,
`tagged_remove`, `tagged_set`, `untagged_add`, `untagged_remove`,
`untagged_set`) or by port (`access_vlan`, `native_vlan`,
`trunk_add_vlans`, `trunk_remove_vlans`, `trunk_set_vlans`).

`access_vlan` sets the untagged VLAN and clears all tagged memberships.
It cannot be combined with `native_vlan` or any `trunk_*` field.
Set fields replace membership; add/remove fields patch it. The supported
`tagged_ports` and `untagged_ports` fields are replacement aliases.

Both forms are converted to the canonical on-wire model:

- `untagged_vlan`: the one VLAN sent untagged on a port
- `tagged_vlans`: VLANs sent tagged on a port

The JTCom backend represents access mode as `access_vlan` and trunk mode as a
`native_vlan` plus permitted VLANs. The core translates at the write boundary
and normalizes readback before verification.

The operation is incremental, but an explicit request can have related
effects. Deleting an in-use VLAN with `allow_vlan_delete_in_use=True` first
detaches its affected ports. A membership request can update the other side of
the same relationship, and the no-membership fallback maps an affected port to
access VLAN 1 with a warning. Consequently, an item omitted from the request
can appear in the effective plan when it must be changed to satisfy the
requested membership or deletion.

## Safety and validation

The default `ApplyPolicy` blocks access/trunk mode changes, untagged/native
VLAN moves, and deletion of an in-use VLAN. These can be enabled explicitly
with `allow_port_mode_change`, `allow_untagged_move`, and
`allow_vlan_delete_in_use`. Unknown VLANs referenced by port-centric input
fail validation by default; `auto_create_referenced_vlans=True` can create
access/native/add/set references. Removal references never auto-create VLANs.
A reference explicitly declared `state="absent"` is always a conflict.
VLAN 1 cannot be deleted.

The safety port defaults to port 6 and cannot be administratively disabled.
Set `ApplyPolicy(safety_port_id=...)` in Python or `safety_port_id` in the
collection when the protected management port is different. This setting does
not silently substitute another port when the configured port is unknown.

Check mode performs the same state reads, normalization, validation, planning,
and policy checks as a real apply. It returns the planned diff, ordered
operations, advisory `warnings`, and blocking `violations` without taking a
backup or writing to the switch. A blocked check-mode plan can still report
`changed: true` when the requested state differs from the current state.

Membership the backend cannot express, such as tagged-only membership without
an untagged/native VLAN, is always blocked. If a changed port would otherwise
have no membership, the planner maps it to access VLAN 1 and emits a structured
warning; that effective fallback is included in policy checks and the diff.

The collection action plugin validates top-level arguments and every nested
VLAN and port field before opening a switch connection. This strict validation
is owned by `galaxy/bronweg/cgiswitch/plugins/module_utils/ansible_input.py`;
the module file supplies documentation while execution stays in the action
plugin. Unknown keys, booleans used as integers, quoted numeric values,
malformed maps, and invalid ranges are rejected. Integer or ASCII decimal map
keys are accepted and normalized; duplicate keys after normalization are
rejected.

## Backups, errors, and verification

Before a real change, the core compiles and validates all operations, then
saves a non-empty, non-HTML backup when `backup_before_change=True`. A backup
or write failure is reported without pretending that the device is unchanged.
If a POST may have been attempted, `changed` is conservatively true.

Backup validation rejects empty and recognizable HTML/login/error responses.
It assumes no undocumented signature and does not prove restorability.

Failures during backup, writes, or verification are represented by `JTComApplyError` in Python and by the
structured result returned by the collection. The result includes the backup
path, completed operations, failed operation, original exception, whether a
write was attempted, and best-effort readback information. Verification
failures retain the exact readback snapshot used to calculate `remaining_diff`;
a recovery read is attempted only when no usable verification snapshot exists.
There is no automatic rollback after a failed write.

Invalid desired configuration raises `ValueError`; malformed device responses
raise typed parse errors. A policy-blocked real apply raises `JTComPolicyError`
before backup or writes; check mode returns the violations instead. Authentication expiry gets at
most one login and retry of the original request; repeated expiry raises an
authentication error. Network, authentication, malformed device state, and
operation errors fail closed rather than being replaced with guessed state.

Policy failures are separate structured violations, while non-blocking policy
conditions are warnings.

## Python example

```python
from cgiswitch import ApplyPolicy, JTComConnectionOptions, JTComSwitch
from cgiswitch.model.config import DeviceConfig
from cgiswitch.model.port import PortConfig
from cgiswitch.model.vlan import VlanConfig

desired = DeviceConfig(
    vlans={
        10: VlanConfig(vlan_id=10, state="present"),
        20: VlanConfig(vlan_id=20, state="present"),
    },
    ports={
        7: PortConfig(
            port_id=7,
            native_vlan=10,
            trunk_set_vlans=[20],
        ),
    },
)

with JTComSwitch(
    "192.0.2.1",
    "admin",
    "secret",
    connection=JTComConnectionOptions(verify_tls=False),
    policy=ApplyPolicy(safety_port_id=6),
) as switch:
    preview = switch.apply(desired, check_mode=True)
    print(preview["diff"], preview["warnings"], preview["violations"])
```

Use `check_mode=True` for a dry run. A real apply repeats planning and policy
checks against fresh device state before issuing writes. See the runnable scripts
in [`examples/`](examples/).

## Ansible examples

Use the collection through a local connection. Store credentials in Ansible
variables or a vault rather than in a playbook.

```yaml
- name: Preview an incremental change
  hosts: localhost
  connection: local
  gather_facts: false
  tasks:
    - name: Plan switch changes
      check_mode: true
      bronweg.cgiswitch.jtcom_config:
        host: "{{ jtcom_host }}"
        username: "{{ jtcom_user }}"
        password: "{{ jtcom_pass }}"
        vlans:
          10:
            state: present
          20:
            state: present
        ports:
          7:
            native_vlan: 10
            trunk_set_vlans: [20]
```

Collection examples include [check mode](galaxy/bronweg/cgiswitch/examples/check_mode.yml),
[automatic referenced-VLAN creation](galaxy/bronweg/cgiswitch/examples/auto_create.yml),
[access ports](galaxy/bronweg/cgiswitch/examples/access_port.yml),
[trunks](galaxy/bronweg/cgiswitch/examples/trunk_port.yml),
[policy overrides](galaxy/bronweg/cgiswitch/examples/policy_overrides.yml),
[VLAN creation](galaxy/bronweg/cgiswitch/examples/vlan_create.yml),
[VLAN deletion](galaxy/bronweg/cgiswitch/examples/vlan_delete.yml), and
[port patches](galaxy/bronweg/cgiswitch/examples/port_patch.yml).

Inspect module arguments with:

```bash
ansible-doc bronweg.cgiswitch.jtcom_config
```

## Hardware validation

The [hardware checklist](docs/HARDWARE_VALIDATION.md) and
[evidence template](docs/hardware/RESULTS_TEMPLATE.md) track real-device
validation. [Read-only results](docs/hardware/2026-09-17-ONT-S207CW-62TS-SE-readonly.md)
and [controlled write results](docs/hardware/2026-09-17-controlled-live.md) are
recorded for ONT-S207CW-62TS-SE firmware V100SP11240725, including VLAN/port
changes, repeated real apply as a no-op, and restoration of the original
port/VLAN configuration. Manual backup restore, session expiry, and traffic
forwarding/link negotiation on the isolated test port remain unvalidated.

## Development

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for development setup and
checks. The main implementation is under `src/cgiswitch`; the collection is
under `galaxy/bronweg/cgiswitch`; parser and apply behavior is covered by
fixture-backed tests under `tests/`.

```bash
pytest
ruff check .
mypy src galaxy/bronweg/cgiswitch/plugins/module_utils
ansible-galaxy collection build --force galaxy/bronweg/cgiswitch
```

## License

MIT; see [LICENSE](LICENSE).
