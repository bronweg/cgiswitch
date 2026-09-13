# cgiswitch

cgiswitch Python core for **JTCom CGI-based Ethernet switches**.

Provides a typed Python API for managing L2 managed switches
that expose a CGI-based web interface (no SSH/NETCONF/SNMP API).

---

## Overview

`cgiswitch` speaks HTTP to the switch's built-in web UI, parses HTML responses
with BeautifulSoup, and exposes a canonical switch API. This makes it
possible to manage JTCom (and compatible) switches from Ansible and Python scripts.

This project is Alpha software. Hardware validation of this refactoring is
pending. There is no automatic rollback after a failed write. Test changes in check mode and retain
device backups according to your operating procedures.

---

## Supported Devices

| Vendor | Series | Validation |
|--------|--------|--------|
| JTCom  | L2 CGI | Fixture-backed; hardware validation pending |

---

## Installation

```bash
git clone https://github.com/bronweg/cgiswitch.git
cd cgiswitch
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

---

## Key Features

| Capability | Detail |
|---|---|
| Read device facts | `read_device_info()` |
| Read interfaces | `read_ports()` |
| Read VLANs | `read_vlans()` |
| Incremental VLAN changes | `apply(desired, check_mode=False)` |
| VLAN-centric membership ops | `tagged_add/remove/set`, `untagged_add/remove/set` |
| Port-centric membership ops | `access_vlan`, `native_vlan`, `trunk_add_vlans`, `trunk_remove_vlans`, `trunk_set_vlans` |
| Incremental port patching | `apply(DeviceConfig(ports=...))` |
| Full device config apply | `apply(desired, check_mode=False)` |
| Ansible Galaxy collection | `bronweg.cgiswitch.jtcom_config` |

### Port Numbering

Ports are 1-based everywhere in this project:

- switch `Port 5`
- `PortConfig(port_id=5)`
- `VlanConfig(... tagged_add=[5])`
- `changed_ports: [5]`

all refer to the same physical port.

### Canonical Model vs JTCom Backend

User input, planning, policy checks, diffs, and verification all use the same
canonical on-wire VLAN membership model:

- `untagged_vlan`: the single VLAN sent untagged on wire
- `tagged_vlans`: VLANs sent tagged on wire

JTCom itself uses a backend-specific model:

- access mode: `access_vlan`
- trunk mode: `native_vlan` + `permit_vlans`
- on JTCom, `permit_vlans` includes `native_vlan`

You normally do not need to think in backend terms. The core compiles
canonical desired state into JTCom backend state only at the final write
boundary, then normalizes JTCom readback back into canonical state before
verification.

### Incremental Change Model

All write operations use an **incremental / patch model**: only the VLANs and ports you
list are affected. Unlisted items are always left untouched.

- VLANs carry a `state` field: `present` (default) or `absent`.
- Port entries are patch-only — supply only the fields you want to change.
- Port numbering is 1-based across the entire project: switch `Port 5`,
  `PortConfig(port_id=5)`, and VLAN membership port `5` all refer to the same port.
- VLAN 1 is protected and can never be deleted.
- The configured safety port (port 6 by default) cannot be administratively disabled.
  Its requested shutdown remains visible in the plan and diff, but policy blocks apply.
- VLAN membership accepts both VLAN-centric and port-centric input. Both are
  translated into the same canonical membership engine before planning.

### Supported Configuration Styles

- VLAN-centric:
  - `tagged_add`, `tagged_remove`, `tagged_set`
  - `untagged_add`, `untagged_remove`, `untagged_set`
- Port-centric:
  - `access_vlan`
  - `native_vlan`
  - `trunk_add_vlans`
  - `trunk_remove_vlans`
  - `trunk_set_vlans`

### Current-State Validation

Before planning, the core rejects desired port IDs that are absent from the
observed device inventory, including VLAN membership references. Missing or
malformed VLAN data and inconsistent cross-page references stop the operation.

Before backup or any write, all required port payload fields must be known
from current state or explicitly supplied in the desired configuration. Unknown
administrative state and flow control are never replaced with guessed defaults.
These preflight checks also run in check mode.

### Referenced VLANs

Port-centric `access_vlan`, `native_vlan`, `trunk_add_vlans`, and
`trunk_set_vlans` must reference existing VLANs or VLANs explicitly declared
with `state="present"`. Unknown references fail validation by default. Set
`ApplyPolicy(auto_create_referenced_vlans=True)` to include their creation in
the plan. VLAN IDs must be integers in 1..4094.

A reference to a VLAN explicitly marked `state="absent"` is always a conflict.
`trunk_remove_vlans` never creates VLANs: unknown removal targets fail validation
even when auto-creation is enabled.

### VLAN Membership Policy

Potentially destructive or ambiguous VLAN membership changes are policy-gated:

- Access/trunk transitions require `allow_port_mode_change=True`.
- Membership the backend cannot express, including tagged-only ports without
  an untagged/native VLAN, is always blocked.

- Untagged/native VLAN moves fail by default. Set `allow_untagged_move=True`
  only when moving a port from one untagged/native VLAN to another is intended.
- Deleting a VLAN that is still tagged or untagged on any port fails by default.
  Set `allow_vlan_delete_in_use=True` to auto-detach affected ports before deletion.
- If a changed port would otherwise end up with no VLAN membership, the policy
  layer maps it explicitly to access VLAN 1 and emits a structured
  `mode_none_mapped_to_vlan1` warning. This fallback can still trigger
  access/trunk protection or untagged-move protection for the effective result.

### Policy Results

Policy validation runs identically in check mode and real apply. `warnings` are
advisory; `violations` are blocking. Both use structured records with common fields:

- `type`
- `entity`
- `message`
- `port_id` or `vlan_id` when applicable
- `hint`

Risk records include:

- `untagged_move`
- `vlan_delete_in_use`
- `mode_none_mapped_to_vlan1`
- `port_mode_change`
- `safety_port_shutdown` (violation only)
- `unsupported_vlan_port_mode` (violation only)

Override flags move the corresponding permitted risk records into `warnings`.
Safety-port and unsupported-membership violations are not bypassed by those flags.

---

## Python Usage

### Read-Only Example

```python
from cgiswitch import JTComConnectionOptions, JTComSwitch

with JTComSwitch(
    "192.0.2.1",
    "admin",
    "secret",
    connection=JTComConnectionOptions(verify_tls=False),
) as switch:
    print(switch.read_device_info())
    print(switch.read_ports())
    print(switch.read_vlans())
```

### Apply Example

Use `apply()` when you want to combine VLAN changes, port admin
changes, and port-centric VLAN membership in one plan.

```python
from cgiswitch import JTComConnectionOptions, JTComSwitch
from cgiswitch.model.config import DeviceConfig
from cgiswitch.model.port import PortConfig
from cgiswitch.model.vlan import VlanConfig

with JTComSwitch(
    "192.0.2.1", "admin", "secret",
    connection=JTComConnectionOptions(verify_tls=False),
) as switch:
    result = switch.apply(
        DeviceConfig(
            vlans={
                100: VlanConfig(vlan_id=100, name="Servers", state="present"),
                200: VlanConfig(vlan_id=200, name="Voice", state="present"),
                300: VlanConfig(vlan_id=300, name="Storage", state="present"),
            },
            ports={
                1: PortConfig(
                    port_id=1,
                    admin_up=True,
                    access_vlan=100,
                ),
                7: PortConfig(
                    port_id=7,
                    native_vlan=100,
                    trunk_set_vlans=[200, 300],
                ),
            },
        ),
        check_mode=True,
    )
    print(result["diff"])
```

### Instance Policy Example

Set the policy when constructing the switch. Every `apply()` call uses that
instance policy; per-call policy overrides are not supported.

```python
from cgiswitch import ApplyPolicy, JTComConnectionOptions, JTComSwitch
from cgiswitch.model.config import DeviceConfig
from cgiswitch.model.vlan import VlanConfig

desired = DeviceConfig(vlans={20: VlanConfig(vlan_id=20, state="absent")})
policy = ApplyPolicy(allow_vlan_delete_in_use=True)
with JTComSwitch(
    "192.0.2.1", "admin", "secret",
    connection=JTComConnectionOptions(verify_tls=False),
    policy=policy,
) as switch:
    result = switch.apply(desired, check_mode=True)
    print(result["warnings"], result["violations"])
```

### Dry-Run Example

Use `switch.apply(desired, check_mode=True)` for a dry run. It returns planned
diffs, advisory `warnings`, structured `violations`, and `blocked` without backup
or device writes. A forbidden change still has `changed=True` when the requested
plan differs from current state:

```yaml
changed: true
blocked: true
violations:
  - type: safety_port_shutdown
    entity: port
    port_id: 6
    vlan_id: null
    message: Port 6 is the safety port and cannot be disabled.
    hint: Select a different safety_port_id only after securing management access.
backup_file: ""
applied: []
```

The same real apply raises `JTComPolicyError` before backup or any write; inspect
`exc.violations` for the same records. Import it from `cgiswitch`. Validation
errors such as unknown VLAN references still raise `ValueError` in both modes.

Runnable scripts in [`examples/`](examples):
- [`examples/read_device_info.py`](examples/read_device_info.py)
- [`examples/read_ports.py`](examples/read_ports.py)
- [`examples/read_vlans.py`](examples/read_vlans.py)
- [`examples/apply_vlan.py`](examples/apply_vlan.py)
- [`examples/apply.py`](examples/apply.py)
- [`examples/toggle_port_admin.py`](examples/toggle_port_admin.py)

---

## Ansible Collection

The supported Ansible interface is the `bronweg.cgiswitch` Galaxy collection.

A packaged collection lives at `galaxy/bronweg/cgiswitch/`.
FQCN: `bronweg.cgiswitch.jtcom_config`

Build and install:

```bash
ansible-galaxy collection build --force galaxy/bronweg/cgiswitch
ansible-galaxy collection install bronweg-cgiswitch-0.1.0.tar.gz
```

Example task:

```yaml
- name: Configure JTCom switch
  bronweg.cgiswitch.jtcom_config:
    host: "{{ jtcom_host }}"
    username: "{{ jtcom_user }}"
    password: "{{ jtcom_pass }}"
    verify_tls: false
    vlans:
      10:
        name: Management
        untagged_add: [1]
      20:
        name: Data
        tagged_add: [7]
      30:
        name: Voice
        untagged_add: [2, 3]
      99:
        state: absent
    ports:
      7:
        native_vlan: 10
        trunk_add_vlans: [20, 30]
      8:
        admin_up: true
        speed: Auto
        flow_control: false
```

The collection supports Ansible `--check` (dry-run) mode. It uses production-safe
TLS verification by default and protects management port 6 from administrative shutdown.

Collection examples:
- [`galaxy/bronweg/cgiswitch/examples/access_port.yml`](galaxy/bronweg/cgiswitch/examples/access_port.yml)
- [`galaxy/bronweg/cgiswitch/examples/trunk_port.yml`](galaxy/bronweg/cgiswitch/examples/trunk_port.yml)
- [`galaxy/bronweg/cgiswitch/examples/policy_overrides.yml`](galaxy/bronweg/cgiswitch/examples/policy_overrides.yml)
- [`galaxy/bronweg/cgiswitch/examples/vlan_create.yml`](galaxy/bronweg/cgiswitch/examples/vlan_create.yml)
- [`galaxy/bronweg/cgiswitch/examples/vlan_delete.yml`](galaxy/bronweg/cgiswitch/examples/vlan_delete.yml)
- [`galaxy/bronweg/cgiswitch/examples/port_patch.yml`](galaxy/bronweg/cgiswitch/examples/port_patch.yml)

Inspect module documentation:

```bash
ansible-doc bronweg.cgiswitch.jtcom_config
```

---

## Project Structure

```
cgiswitch/
  src/cgiswitch/
    switch.py          # JTComSwitch orchestration API
    client/            # HTTP session, request helpers, VLAN/port write ops
    parser/            # HTML → Python object parsers
    model/             # Typed dataclass models (VlanConfig, PortConfig, DeviceConfig …)
    utils/             # Diff/plan engines (vlan_diff, device_diff, port_diff, render)
    vendor/jtcom/      # JTCom-specific endpoint paths and field mappings
  galaxy/
    bronweg/cgiswitch/ # Ansible Galaxy collection (bronweg.cgiswitch, v0.1.0)
      galaxy.yml       # Collection manifest
      plugins/action/  # Action plugin
      plugins/modules/ # Module stub (ansible-doc / Galaxy)
      examples/        # Ready-to-run playbooks
  tests/
    unit/              # Unit tests for parsers, diff engines, and payloads
    fixtures/          # HTML snapshots from real devices
  examples/            # Runnable Python usage examples
  docs/                # Developer documentation
```

## Architecture Note

Runtime flow:

1. normalize input
2. merge VLAN-centric and port-centric syntax
3. plan and apply policy on canonical state
4. compile canonical state to JTCom backend only at write time
5. read JTCom state back and normalize to canonical state
6. verify canonical expected vs canonical actual

---

## Development

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for setup, testing, and contribution guidelines.

```bash
# Run tests
pytest

# Lint + type-check
ruff check .
mypy src/

# Build the Galaxy collection
cd galaxy/bronweg/cgiswitch
ansible-galaxy collection build --force
```

---

## License

MIT — see [LICENSE](LICENSE).
