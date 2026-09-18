# bronweg.cgiswitch

Ansible Collection for managing JTCom CGI-based L2 Ethernet switches via
[cgiswitch](https://github.com/bronweg/cgiswitch).

This collection is Alpha software. Hardware validation is still pending, and
some behavior is specific to the switch firmware's CGI interface. The apply
path writes individual operations; it has no transactional commit and does
not perform automatic rollback after a failed write.

## Requirements

- ansible-core >= 2.14.0 (the Ansible controller runtime)
- Python >= 3.11
- A matching `cgiswitch` checkout or package installed in the Ansible
  controller's Python environment. The collection and current Python package
  are both version 0.1.0; the action plugin does not enforce an exact package
  version at runtime.

## Installation

```bash
git clone https://github.com/bronweg/cgiswitch.git
cd cgiswitch
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e . 'ansible-core>=2.14'
ansible-galaxy collection build galaxy/bronweg/cgiswitch
ansible-galaxy collection install bronweg-cgiswitch-0.1.0.tar.gz
```

Run the build and install commands from the repository root. For a packaged
release, install the matching `cgiswitch` package in the controller
environment before installing the collection archive.

## Connection scheme and TLS

For a `host` without a scheme, `verify_tls: true` (the default) selects
HTTPS on port 443; `verify_tls: false` selects HTTP on port 80. An explicit
`http://` or `https://` in `host` determines the scheme directly, regardless
of `verify_tls`. For HTTPS, `verify_tls` also controls certificate
verification. For example, `host: https://192.0.2.1` with `verify_tls: false`
uses HTTPS with certificate verification disabled.

## Modules

### `bronweg.cgiswitch.jtcom_config`

Idempotent, diff-aware PATCH-style configuration of VLANs and ports. The
collection runs in the controller process through an Ansible action plugin;
the module utility parses and validates task input before the action plugin
opens the switch connection.

- **VLANs** support create, rename, delete, and membership add/remove/set
  operations. VLAN definitions not listed are left unchanged, although a
  requested membership operation or permitted delete-in-use policy can also
  affect related port membership.
- **Ports** are patch-only: supply only the fields you want to change
- Port settings support administrative state, speed, and flow control
- `access_vlan` clears tagged membership and is exclusive with native/trunk
  fields. Access/trunk mode changes are blocked by default; set
  `allow_port_mode_change: true` when the transition is intended.
- A tagged-only effective membership is unsupported by the JTCom backend and is
  blocked as a policy violation.
- Port numbering is 1-based everywhere: switch `Port 5` is configured as port `5`
- Supports Ansible `--check` (dry-run) mode
- Strict input types are enforced; values are not silently coerced. In
  particular, booleans, integer IDs, and list members must use their declared
  types.
- Mapping keys may be integers or ASCII decimal strings; duplicate keys after
  normalization are rejected. Optional `null` values leave fields unchanged;
  empty lists apply the field's clear/set behavior.
- The safety port defaults to port 6 and cannot be administratively disabled;
  set `safety_port_id` to protect a different positive integer port ID
- VLAN 1 cannot be deleted
- Port-centric VLAN references must name an existing switch VLAN or a VLAN
  declared under `vlans:` with `state: present`. Unknown references fail before
  backup or writes. Set `auto_create_referenced_vlans: true` to create unknown
  add/set references automatically; the default is `false`.
- `trunk_remove_vlans` never creates VLANs. An unknown remove target fails closed,
  including when auto-creation is enabled. VLAN IDs must be in the 1..4094 range.

Canonical model:

- `untagged_vlan`: VLAN sent untagged on wire
- `tagged_vlans`: VLANs sent tagged on wire

JTCom backend model:

- access mode: `access_vlan`
- trunk mode: `native_vlan` + `permit_vlans`
- on JTCom, `permit_vlans` includes `native_vlan`

The collection accepts VLAN-centric and port-centric input, plans on canonical
state, compiles every planned write to JTCom backend state before backup or any
write, then verifies canonical expected vs canonical actual. The core library
compiles and applies the operation plan; the action plugin supplies validated
controller input.

The backend is the JTCom CGI interface, so supported behavior can depend on
the installed switch firmware. A backup may be taken before writes, but a
backup is not a transaction: there is no commit phase and no automatic
rollback. Review `completed_operations`, `failed_operation`, `readback`, and
`remaining_diff` when an apply fails.

Before backup or any write, the core library compiles and validates the full
operation list. Operations have a deterministic order: VLAN creates by
ascending VLAN ID, VLAN renames by ascending VLAN ID, VLAN membership updates
by ascending port ID, port settings by ascending port ID, and VLAN deletes by
descending VLAN ID. Check mode exposes operation descriptions without taking a
backup or writing to the device.

Successful results include `completed_operations` for writes confirmed by the
client. An apply failure returns structured context with `backup_file` (when a
backup was created, otherwise an empty string), `completed_operations`, `failed_operation`,
`original_exception`, `write_attempted`, and best-effort `readback` or
`readback_error`. If a POST may have been attempted, `changed` is conservatively
`true`, including a failure on the first write. Verification failures include
`remaining_diff`. Policy and preflight failures remain blocked before backup or
writes. Automatic rollback is not performed.

Verification failures retain the exact readback snapshot used to compute
`remaining_diff`. A recovery read is attempted only when no usable verification
snapshot exists, such as when the verification read itself fails. Returned diffs
reflect effective membership after policy/fallback resolution; an effective
no-op has no changes in its diff, while advisory warnings remain available.

VLAN membership policy:

- Untagged/native VLAN moves fail by default; use `allow_untagged_move: true`
  only when the move is intended.
- Deleting a VLAN still used by ports fails by default; use
  `allow_vlan_delete_in_use: true` to auto-detach affected ports before deletion.
- If a changed port would otherwise have no VLAN membership, it is mapped to
  access VLAN 1 and a `mode_none_mapped_to_vlan1` warning is returned. This
  fallback can still trigger access↔trunk protection if the effective result
  changes port mode; set `allow_port_mode_change: true` when that transition is
  intended. A fallback that moves the untagged VLAN can also require
  `allow_untagged_move: true`.

Warnings are structured objects with common fields such as:

- `type`
- `entity`
- `message`
- `port_id` / `vlan_id`
- `hint`

Policy violations are returned separately from advisory warnings. In check
mode, a blocked operation returns `blocked: true`, `changed: true`, the
structured `violations`, an empty `backup_file`, and an empty `applied` list.
In normal mode, the same violations fail before backup or writes. Inspect
`violations` for blocked safety-port shutdowns, mode changes, untagged moves,
and VLAN deletion or membership operations that the backend cannot express.

```yaml
- name: Configure switch
  bronweg.cgiswitch.jtcom_config:
    host: 192.0.2.1
    username: "{{ jtcom_user }}"
    password: "{{ jtcom_pass }}"
    vlans:
      10:
        name: Management
        untagged_set: [1]
      99:
        state: absent
    ports:
      1:
        admin_up: true
        speed: Auto
        flow_control: false
```

Example playbooks use `SWITCH_USER` (default `admin`) and `SWITCH_PASS` from
the environment. Set `switch_host` with `-e` and inspect the preview before
applying a change:

```bash
ansible-playbook -i localhost, examples/access_port.yml -e switch_host=192.0.2.1 --check
```

Run that command from the installed collection directory or replace the example
path with its path in the checkout. Check mode needs device connectivity and
credentials but performs no backup or configuration writes.

Example playbooks:

- [`examples/vlan_create.yml`](examples/vlan_create.yml)
- [`examples/access_port.yml`](examples/access_port.yml)
- [`examples/trunk_port.yml`](examples/trunk_port.yml)
- [`examples/policy_overrides.yml`](examples/policy_overrides.yml)
- [`examples/vlan_delete.yml`](examples/vlan_delete.yml)
- [`examples/port_patch.yml`](examples/port_patch.yml)
- [`examples/check_mode.yml`](examples/check_mode.yml)
- [`examples/auto_create.yml`](examples/auto_create.yml)

## License

MIT
