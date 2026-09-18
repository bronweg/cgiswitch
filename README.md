# cgiswitch

`cgiswitch` is a Python client and Ansible collection for the HTTP CGI interface
used by JTCom-based Ethernet switches. It provides two workflows:

- **Configuration:** VLANs, port membership, admin state, speed and flow control.
- **Bootstrap:** verified credential and static management IPv4 transitions,
  followed by a persistence save.

The project is **Alpha**. Hardware validation covers one ONTi
**ONT-S207CW-62TS-SE**, firmware **V100SP11240725**. Controlled tests verified
VLAN/port configuration, repeated no-op apply, bootstrap, reboot persistence,
and restoration to the test baseline. Other firmware may use different CGI
fields or behavior. See the [hardware evidence index](docs/hardware/README.md)
for the tested scope and exclusions.

## Install

Use Python **3.11 or newer**. For Ansible, install both the Python package and
collection in the controller environment. The action plugins run in the Python
process that runs `ansible-playbook`, not on the switch.

Install from a source checkout; the commands do not require a published package:

```sh
git clone https://github.com/bronweg/cgiswitch.git
cd cgiswitch
python3 -m venv .venv
. .venv/bin/activate
python -m pip install . 'ansible-core>=2.15'
ansible-galaxy collection build --force --output-path /tmp/cgiswitch-galaxy-dist \
  galaxy/bronweg/cgiswitch
ansible-galaxy collection install /tmp/cgiswitch-galaxy-dist/bronweg-cgiswitch-*.tar.gz --force
```

The collection declares Ansible **2.14+**; CI installs compatible versions of
`ansible-core>=2.15` on Python 3.11–3.13. A Python-only installation needs just
`python -m pip install .` in the chosen environment.

## Start with a preview

Supply `switch_password` through your Ansible variables. This play creates no
configuration writes because the task runs in check mode:

```yaml
- name: Preview switch configuration
  hosts: localhost
  gather_facts: false
  tasks:
    - name: Plan a VLAN
      bronweg.cgiswitch.jtcom_config:
        host: http://192.0.2.10
        username: admin
        password: "{{ switch_password }}"
        vlans:
          20:
            name: users
      check_mode: true
      no_log: true
```

The public configuration interfaces are `JTComSwitch.apply()` and
`bronweg.cgiswitch.jtcom_config`. Bootstrap uses `BootstrapConfig` with
`bootstrap_switch()`, or `bronweg.cgiswitch.jtcom_bootstrap`.

## Guides

- [Configuration](docs/CONFIGURATION.md): inputs, policies, check mode and failures.
- [Bootstrap](docs/BOOTSTRAP.md): identity, credentials, management IP and persistence.
- [Development](docs/DEVELOPMENT.md): source layout, tests and builds.
- [Hardware validation](docs/HARDWARE_VALIDATION.md): safe test procedure.

## Limits

Writes are not transactional. There is no automatic rollback, configuration
restore API, factory-reset automation or firmware upgrade API. Backup download
has been tested; manual restore and natural session expiry have not been
hardware-tested. Port configuration readback does not prove traffic forwarding.

Bootstrap does not configure the controller network or store secrets. Every
successful non-check bootstrap run saves, including runs with `changed=false`.
Normal VLAN/port apply does not issue that bootstrap save barrier.
