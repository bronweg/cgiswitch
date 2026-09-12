# napalm-jtcom

NAPALM community driver for **JTCom CGI-based Ethernet switches**.

Extends [NAPALM](https://napalm.readthedocs.io/) to support L2 managed switches
that expose a CGI-based web interface (no SSH/NETCONF/SNMP API).

---

## Overview

`napalm-jtcom` speaks HTTP to the switch's built-in web UI, parses HTML responses
with BeautifulSoup, and exposes a standard NAPALM driver interface. This makes it
possible to manage JTCom (and compatible) switches from Ansible, Python scripts, and
any tool built on top of NAPALM.

---

## Supported Devices

| Vendor | Series | Tested |
|--------|--------|--------|
| JTCom  | L2 CGI | ✅     |

---

## Installation

```bash
git clone https://github.com/bronweg/napalm-jtcom.git
cd napalm-jtcom
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

---

## Key Features

| Capability | Detail |
|---|---|
| Read device facts | `get_facts()` |
| Read interfaces | `get_interfaces()` |
| Read VLANs | `get_vlans()` |
| Incremental VLAN changes | `set_vlans(desired, dry_run=False)` |
| VLAN-centric membership ops | `tagged_add/remove/set`, `untagged_add/remove/set` |
| Port-centric membership ops | `access_vlan`, `native_vlan`, `trunk_add_vlans`, `trunk_remove_vlans`, `trunk_set_vlans` |
| Incremental port patching | `apply_device_config()` with `ports=` |
| Full device config apply | `apply_device_config(desired, check_mode=False)` |
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

You normally do not need to think in backend terms. The driver compiles
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
- Port 6 (management uplink) can never be administratively disabled.
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

### VLAN Membership Policy

Potentially destructive or ambiguous VLAN membership changes are policy-gated:

- Untagged/native VLAN moves fail by default. Set `allow_untagged_move=True`
  only when moving a port from one untagged/native VLAN to another is intended.
- Deleting a VLAN that is still tagged or untagged on any port fails by default.
  Set `allow_vlan_delete_in_use=True` to auto-detach affected ports before deletion.
- If a changed port would otherwise end up with no VLAN membership, the policy
  layer maps it explicitly to access VLAN 1 and emits a structured
  `mode_none_mapped_to_vlan1` warning. This fallback can still trigger
  access↔trunk protection if the effective result changes port mode.

### Warning Objects

Write operations return structured warning objects. Common fields:

- `type`
- `entity`
- `message`
- `port_id` or `vlan_id` when applicable
- `hint`

Common warning types:

- `untagged_move`
- `vlan_delete_in_use`
- `mode_none_mapped_to_vlan1`
- `port_mode_change`

---

## Python Usage

### Read-Only Example

```python
from napalm_jtcom.driver import JTComDriver

driver = JTComDriver("192.0.2.1", "admin", "secret", optional_args={"verify_tls": False})
driver.open()

try:
    print(driver.get_facts())
    print(driver.get_interfaces())
    print(driver.get_vlans())
finally:
    driver.close()
```

### `set_vlans()` Example

Use VLAN-centric input when the desired change is easiest to describe per VLAN.

```python
from napalm_jtcom.driver import JTComDriver
from napalm_jtcom.model.vlan import VlanConfig

driver = JTComDriver("192.0.2.1", "admin", "secret", optional_args={"verify_tls": False})
driver.open()

try:
    result = driver.set_vlans(
        {
            10: VlanConfig(vlan_id=10, name="Management", state="present"),
            20: VlanConfig(vlan_id=20, tagged_add=[7, 8], state="present"),
            30: VlanConfig(vlan_id=30, untagged_add=[1, 2, 3], state="present"),
            99: VlanConfig(vlan_id=99, state="absent"),
        },
        dry_run=True,
    )
    print(result)
finally:
    driver.close()
```

### Access Port Example

```python
from napalm_jtcom.driver import JTComDriver
from napalm_jtcom.model.config import DeviceConfig
from napalm_jtcom.model.port import PortConfig

driver = JTComDriver("192.0.2.1", "admin", "secret", optional_args={"verify_tls": False})
driver.open()

try:
    result = driver.apply_device_config(
        DeviceConfig(
            ports={
                3: PortConfig(
                    port_id=3,
                    access_vlan=20,
                ),
            },
        ),
        check_mode=True,
    )
    print(result["warnings"])
finally:
    driver.close()
```

### Trunk Port Example

```python
from napalm_jtcom.driver import JTComDriver
from napalm_jtcom.model.config import DeviceConfig
from napalm_jtcom.model.port import PortConfig

driver = JTComDriver("192.0.2.1", "admin", "secret", optional_args={"verify_tls": False})
driver.open()

try:
    result = driver.apply_device_config(
        DeviceConfig(
            ports={
                5: PortConfig(
                    port_id=5,
                    native_vlan=10,
                    trunk_set_vlans=[20, 30],
                ),
            },
        ),
        check_mode=True,
    )
    print(result["diff"])
finally:
    driver.close()
```

### `apply_device_config()` Example

Use `apply_device_config()` when you want to combine VLAN changes, port admin
changes, and port-centric VLAN membership in one plan.

```python
from napalm_jtcom.driver import JTComDriver
from napalm_jtcom.model.config import DeviceConfig
from napalm_jtcom.model.port import PortConfig
from napalm_jtcom.model.vlan import VlanConfig

driver = JTComDriver("192.0.2.1", "admin", "secret", optional_args={"verify_tls": False})
driver.open()

try:
    result = driver.apply_device_config(
        DeviceConfig(
            vlans={
                100: VlanConfig(vlan_id=100, name="Servers", state="present"),
                200: VlanConfig(vlan_id=200, name="Voice", state="present"),
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
                    trunk_add_vlans=[200, 300],
                ),
            },
        ),
        check_mode=True,
    )
    print(result["diff"])
finally:
    driver.close()
```

### Policy Override Example

```python
from napalm_jtcom.driver import JTComDriver
from napalm_jtcom.model.vlan import VlanConfig

driver = JTComDriver("192.0.2.1", "admin", "secret")
driver.open()

try:
    result = driver.set_vlans(
        {
            20: VlanConfig(vlan_id=20, state="absent"),
        },
        dry_run=False,
        allow_vlan_delete_in_use=True,
    )
    print(result["warnings"])
finally:
    driver.close()
```

### Dry-Run Example

Both `set_vlans(..., dry_run=True)` and `apply_device_config(..., check_mode=True)`
return planned diffs, changed ports/VLANs, and structured warnings without
writing to the device.

Runnable scripts in [`examples/`](examples):
- [`examples/get_facts.py`](examples/get_facts.py)
- [`examples/get_interfaces.py`](examples/get_interfaces.py)
- [`examples/get_vlans.py`](examples/get_vlans.py)
- [`examples/apply_vlan.py`](examples/apply_vlan.py)
- [`examples/apply_device_config.py`](examples/apply_device_config.py)
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
napalm-jtcom/
  src/napalm_jtcom/
    driver.py          # NAPALM NetworkDriver subclass
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
