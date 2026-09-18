# bronweg.cgiswitch

Controller-side Ansible actions for JTCom CGI Ethernet switches:

- `jtcom_config`: VLAN and port configuration.
- `jtcom_bootstrap`: identity-verified credentials and management IPv4 transitions.

The project is Alpha. Hardware validation covers ONTi ONT-S207CW-62TS-SE,
firmware V100SP11240725; see the
[hardware evidence](https://github.com/bronweg/cgiswitch/blob/main/docs/hardware/README.md).
Writes are not transactional and there is no automatic rollback.

## Install

Requires Python 3.11+ and ansible-core 2.14+. Install the Python package in the
same environment as `ansible-playbook`; actions execute there, not on the switch.
Install matching source revisions of the package and collection:

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

## Preview configuration

Use these tasks in a play with `hosts: localhost`. Supply passwords through
Ansible variables. Both examples preview changes; remove `check_mode: true`
only after reviewing the plan.

```yaml
- name: Preview a VLAN
  bronweg.cgiswitch.jtcom_config:
    host: http://192.0.2.10
    username: admin
    password: "{{ switch_password }}"
    vlans:
      20: {name: users}
  check_mode: true
  no_log: true
```

[Configuration guide](https://github.com/bronweg/cgiswitch/blob/main/docs/CONFIGURATION.md)
explains membership, policy, backups and failure results.

## Preview bootstrap

```yaml
- name: Preview a known switch bootstrap
  bronweg.cgiswitch.jtcom_bootstrap:
    factory_url: http://192.0.2.1
    target_url: http://198.51.100.10
    username: admin
    factory_password: "{{ factory_password }}"
    password: "{{ target_password }}"
    expected_mac: "00:11:22:33:44:55"
    management:
      address: 198.51.100.10
      prefix_length: 24
      gateway: 198.51.100.1
  check_mode: true
  no_log: true
```

The controller must reach the factory and target networks. Bootstrap never
configures controller networking. Every successful non-check run saves,
including `changed=false` runs. See the
[bootstrap guide](https://github.com/bronweg/cgiswitch/blob/main/docs/BOOTSTRAP.md).
