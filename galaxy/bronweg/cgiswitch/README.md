# bronweg.cgiswitch

Ansible Collection for managing JTCom CGI-based L2 Ethernet switches via
[cgiswitch](https://github.com/bronweg/cgiswitch).

This collection is Alpha software. Hardware validation is still pending, and
the apply path does not promise rollback after a failed write.

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

Canonical model:

- `untagged_vlan`: VLAN sent untagged on wire
- `tagged_vlans`: VLANs sent tagged on wire

JTCom backend model:

- access mode: `access_vlan`
- trunk mode: `native_vlan` + `permit_vlans`
- on JTCom, `permit_vlans` includes `native_vlan`

The collection accepts VLAN-centric and port-centric input, plans on canonical
state, compiles to JTCom backend state only at write time, then verifies
canonical expected vs canonical actual.

VLAN membership policy:

- Untagged/native VLAN moves fail by default; use `allow_untagged_move: true`
  only when the move is intended.
- Deleting a VLAN still used by ports fails by default; use
  `allow_vlan_delete_in_use: true` to auto-detach affected ports before deletion.
- If a changed port would otherwise have no VLAN membership, it is mapped to
  access VLAN 1 and a `mode_none_mapped_to_vlan1` warning is returned. This
  fallback can still trigger access↔trunk protection if the effective result
  changes port mode.

Warnings are structured objects with common fields such as:

- `type`
- `entity`
- `message`
- `port_id` / `vlan_id`
- `hint`

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
