# bronweg.cgiswitch

Ansible Collection for managing JTCom CGI-based L2 Ethernet switches via
[cgiswitch](https://github.com/bronweg/cgiswitch).

This collection is Alpha software. Hardware validation is still pending, and
the apply path does not perform automatic rollback after a failed write.

## Requirements

- Ansible >= 2.14
- Python >= 3.11
- `cgiswitch == 0.1.0` installed in the Ansible controller's Python environment

## Installation

```bash
ansible-galaxy collection install bronweg-cgiswitch-0.1.0.tar.gz
cd /path/to/cgiswitch
python -m pip install -e .
```

## Modules

### `bronweg.cgiswitch.jtcom_config`

Idempotent, diff-aware PATCH-style configuration of VLANs and ports.

- **VLANs** support `state: present | absent` (incremental — unlisted VLANs untouched)
- **Ports** are patch-only: supply only the fields you want to change
- Port numbering is 1-based everywhere: switch `Port 5` is configured as port `5`
- Supports Ansible `--check` (dry-run) mode
- Port 6 (management uplink) cannot be administratively disabled
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
write, then verifies canonical expected vs canonical actual.

Before backup or any write, the action plugin compiles and validates the full
operation list. Operations have a deterministic order: VLAN creates by
ascending VLAN ID, VLAN renames by ascending VLAN ID, VLAN membership updates
by ascending port ID, port settings by ascending port ID, and VLAN deletes by
descending VLAN ID. Check mode exposes operation descriptions without taking a
backup or writing to the device.

Successful results include `completed_operations` for writes confirmed by the
client. A failure after writes begin returns structured context with
`backup_file`, `completed_operations`, `failed_operation`,
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
    verify_tls: false
    vlans:
      10:
        name: Management
        untagged_ports: [1]
      99:
        state: absent
    ports:
      1:
        admin_up: true
        speed: Auto
        flow_control: false
```

Ready-to-run examples:

- `examples/vlan_create.yml`
- `examples/access_port.yml`
- `examples/trunk_port.yml`
- `examples/policy_overrides.yml`
- `examples/vlan_delete.yml`
- `examples/port_patch.yml`

## License

MIT
