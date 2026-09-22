# VLAN and port configuration

Use `JTComSwitch.apply()` in Python or `bronweg.cgiswitch.jtcom_config` in Ansible.
These interfaces manage VLANs and ports. Use [bootstrap](BOOTSTRAP.md) for
credentials and management IP changes.

The implementation and unit tests cover the inputs below. Hardware evidence is
limited to the device, firmware and operations listed in the
[evidence index](hardware/README.md).

## Connection

Ansible requires non-empty `host`, `username` and `password` strings. Use an
explicit URL such as `http://192.0.2.10` to select the scheme directly.

Without a scheme, `verify_tls: true` selects HTTPS/443 and `false` selects
HTTP/80. With an explicit scheme, `verify_tls` controls certificate verification
for HTTPS; it does not change the scheme. The Ansible default is `true`.

Python takes `hostname`, `username`, `password` and optional
`JTComConnectionOptions(verify_tls=False, port=None, timeout=60)`. These are the
Python defaults. `port` applies only to hosts without an explicit scheme; a URL
must include its own non-default port. `timeout` is the HTTP request timeout in
seconds. The Ansible action uses the 60-second timeout and does not expose a
separate timeout or port option.

Use `with JTComSwitch(...) as switch:` to open and close a session. Explicit
session expiry during normal GET, POST or backup download permits one login and
retry. A second expiry raises an authentication error. Disruptive bootstrap
writes use separate one-shot behavior.

## Desired VLANs

In Python, pass `DeviceConfig(vlans={20: VlanConfig(vlan_id=20, ...)})`.
In Ansible, use `vlans: {20: {...}}`; the map key supplies the VLAN ID.
IDs must be 1–4094. Python map keys must match each config's `vlan_id`.

| Field | Meaning |
| --- | --- |
| `name` | Set the VLAN name; omitted or null leaves it unchanged. |
| `state` | `present` (default) creates/updates; `absent` requests deletion. |
| `tagged_add`, `untagged_add` | Add these port IDs to membership. |
| `tagged_remove`, `untagged_remove` | Remove these port IDs from membership. |
| `tagged_set`, `untagged_set` | Replace the complete membership for that side. |

Membership lists use positive, 1-based integer port IDs present on the device.
Omitted or null membership fields request no change. An empty `*_set: []`
explicitly clears that side; empty add/remove lists do nothing. Set cannot be
combined with add or remove on the same side, even when the lists are empty.
VLANs not mentioned are left alone, except membership changes implied by port
intent. VLAN 1 cannot be deleted.

Observed `VlanEntry` values returned by `read_vlans()` contain `tagged_ports`
and `untagged_ports` with names such as `Port 1`. These are readback fields,
not desired configuration keys.

## Desired ports

In Python, pass `DeviceConfig(ports={2: PortConfig(port_id=2, ...)})`.
In Ansible, use `ports: {2: {...}}`. Omitted or null optional fields leave
that attribute unchanged.

| Ansible field | Meaning |
| --- | --- |
| `admin_up` | Boolean: enable or disable the port. |
| `speed` | Configured speed/duplex; Python calls this `speed_duplex`. |
| `flow_control` | Boolean: enable or disable flow control. |
| `access_vlan` | Set the untagged VLAN and remove all tagged memberships. |
| `native_vlan` | Set the untagged VLAN; keep tagged memberships. |
| `trunk_add_vlans` | Add tagged VLAN memberships. |
| `trunk_remove_vlans` | Remove tagged VLAN memberships. |
| `trunk_set_vlans` | Replace all tagged memberships; `[]` clears them. |

`access_vlan` cannot be combined with `native_vlan` or any `trunk_*` field.
`trunk_set_vlans` cannot be combined with trunk add/remove, including empty lists.

Accepted speed tokens are `Auto`, `10M/Half`, `10M/Full`, `100M/Half`,
`100M/Full`, `1000M/Full`, `2500M/Full` and `10G/Full`. Input normalization also
accepts case variants and shorthand such as `1G/Full`. Accepted tokens do not
prove the hardware can negotiate every listed speed.

Referenced VLANs must exist on the switch or be explicitly declared
`state: present`. Unknown references require `auto_create_referenced_vlans: true`.
An explicitly absent VLAN always conflicts. An unknown `trunk_remove_vlans`
target is rejected, even with auto-create enabled.

## Membership and validation

An access port has one untagged VLAN and no tagged VLANs. A trunk has one
untagged/native VLAN and at least one tagged VLAN. Setting `native_vlan` alone
does not force trunk mode. Tagged-only membership cannot be expressed by this
backend and is blocked. If a changed port would have no membership, the planner
assigns access VLAN 1 and reports a warning; policy still evaluates that result.
Where one VLAN is requested both tagged and untagged on a port, untagged wins.

VLAN-centric and port-centric requests can be combined when compatible.
Contradictory requests fail before backup or writes. Check the returned effective
diff, especially when clearing membership or removing the last VLAN.

The Ansible action validates raw task arguments, including nested maps. Unknown
keys and incorrect types are rejected rather than coerced: use real booleans
and integer list elements. Map keys can be integers or ASCII digit strings;
duplicate numeric IDs after normalization are rejected. Whole `vlans`/`ports`
maps and their entries cannot be null; `state` cannot be null. Python callers
use typed models; do not rely on Ansible-style coercion or schema validation.

## Policy

Set Python policy once when constructing the switch with `ApplyPolicy(...)`.
The Ansible action exposes the following policy fields at task level:

| Option | Default | Effect |
| --- | --- | --- |
| `safety_port_id` | `6` | Block a request to disable this port. It does not protect every membership change. |
| `allow_port_mode_change` | `false` | Permit access/trunk changes when true. |
| `allow_untagged_move` | `false` | Permit moving a port to another untagged/native VLAN when true. |
| `allow_vlan_delete_in_use` | `false` | Permit deleting a VLAN with members when true. |
| `auto_create_referenced_vlans` | `false` | Create unknown VLANs referenced by port add/set intent when true. |
| `backup_before_change` | `true` | Download a backup before a non-empty live apply. |

Allowed risky changes remain warnings. Violations block live apply before
backup and writes. The safety port number must match your actual management
path; it is not discovered automatically. Python also exposes `backup_dir`,
which defaults to `./backups`; Ansible uses that directory on the controller.

## Preview, apply and failures

Check mode authenticates and reads current device state, validates desired
input and returns the effective diff. It makes no configuration writes and
creates no backup. Authentication may use POST requests.

A policy-blocked preview returns `changed: true`, `blocked: true`, structured
`violations`, an empty `backup_file` and `applied: []`. Invalid input or unreadable
state fails instead of producing a successful preview. A no-op returns
`changed: false`; an allowed preview reports the executable `operations`.

Live apply completes planning and payload validation before backup and writes.
It performs a deterministic operation sequence, then verifies readback. Backup
validation rejects empty, HTML/login and error responses. It does not establish
that the bytes can be restored; there is no restore API or automatic rollback.
Normal apply does not issue saveconfig or reboot, and its return value does not
prove persistence across reboot.

Results include `changed`, `diff`, `blocked`, `warnings`, `violations`,
`backup_file`, `applied`, `operations` and `completed_operations`.
Python raises `JTComPolicyError` for blocked live changes. Backup/write/verification
failures raise `JTComApplyError`; its `as_result()` is also the Ansible failure
format. It includes the backup path, confirmed operations, `failed_operation`,
`original_exception`, `write_attempted` and available `readback`.
Verification failures include `remaining_diff`. A usable verification snapshot
is retained; an extra read is attempted only when none is available. A failed
write may have reached the device: `changed` on this error means a write was
attempted, not that every operation succeeded. Inspect state before retrying.

## Examples

All addresses below are documentation addresses. Supply passwords through
Ansible variables or the Python environment. The tasks deliberately preview
changes; remove `check_mode: true` only after reviewing the result.

```yaml
- name: Preview VLAN creation
  bronweg.cgiswitch.jtcom_config:
    host: http://192.0.2.10
    username: admin
    password: "{{ switch_password }}"
    vlans:
      20:
        name: users
  check_mode: true
  no_log: true

- name: Preview an access port with explicit move permission
  bronweg.cgiswitch.jtcom_config:
    host: http://192.0.2.10
    username: admin
    password: "{{ switch_password }}"
    allow_port_mode_change: true
    allow_untagged_move: true
    vlans:
      20: {state: present}
    ports:
      2: {access_vlan: 20}
  check_mode: true
  no_log: true

- name: Preview a trunk and create missing referenced VLANs
  bronweg.cgiswitch.jtcom_config:
    host: http://192.0.2.10
    username: admin
    password: "{{ switch_password }}"
    allow_port_mode_change: true
    allow_untagged_move: true
    auto_create_referenced_vlans: true
    ports:
      2:
        native_vlan: 20
        trunk_set_vlans: [30, 40]
  check_mode: true
  no_log: true
```

Equivalent Python VLAN preview:

```python
import os

from cgiswitch import JTComSwitch
from cgiswitch.model.config import DeviceConfig
from cgiswitch.model.vlan import VlanConfig

desired = DeviceConfig(vlans={20: VlanConfig(vlan_id=20, name="users")})
with JTComSwitch("http://192.0.2.10", "admin", os.environ["SWITCH_PASSWORD"]) as switch:
    result = switch.apply(desired, check_mode=True)
print(result)
```
