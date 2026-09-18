# Bootstrap

`bronweg.cgiswitch.jtcom_bootstrap` moves a known switch from its current
management endpoint and credentials to a desired static IPv4 configuration.
The Python API and the Ansible action use the same workflow:

1. discover the switch and verify its identity;
2. change credentials when needed;
3. change the management address when needed;
4. verify the final state and run one `saveconfig` persistence barrier.

The workflow does not configure the controller network. The controller must have network access to both endpoint addresses; the target
may become reachable only after the IP transition. It does not store secrets,
reset the device, restore a backup, upgrade firmware, or roll back a partial
change.

## Requirements

The caller supplies explicit `http://` or `https://` URLs for both endpoints.
URLs must contain IPv4 addresses, use the root path, and contain no credentials,
fragment, or query string. The target URL host must equal
`management.address`.

Bootstrap accepts only a static IPv4 management configuration:

```python
from cgiswitch import ManagementNetworkConfig

management = ManagementNetworkConfig(
    address="192.0.2.20",
    prefix_length=24,
    gateway="192.0.2.1",
)
```

The `gateway` must be an IPv4 address in the management subnet. DHCP is not a
supported bootstrap mode. `verify_tls` controls certificate verification for
HTTPS requests and defaults to `True`; it has no effect on HTTP requests.

At least one of `expected_mac` and `expected_serial` is required. If both are
provided, both must match the same device. The MAC must be a unicast address.
The username must be 5-16 ASCII letters, numbers, or underscores. The target password
must be 6-16 characters from the firmware contract's observed character set:
ASCII letters, numbers, and `<=>[]!@#$*().`. The current/factory password
only needs to be a non-empty string.
The expected identity is checked on connection and immediately before the IP
write, then verified again when
the workflow reconnects after an address change.

## Python API

`BootstrapConfig`, `ManagementNetworkConfig`, and `bootstrap_switch` are
exported by the top-level `cgiswitch` package. Keep passwords outside source
files and command lines; the example uses environment variables only to show
the boundary where a secret provider supplies them.

```python
import os

from cgiswitch import BootstrapConfig, ManagementNetworkConfig, bootstrap_switch

config = BootstrapConfig(
    factory_url="http://192.0.2.1",
    target_url="http://192.0.2.20",
    username="admin",
    factory_password=os.environ["JTCOM_FACTORY_PASSWORD"],
    target_password=os.environ["JTCOM_TARGET_PASSWORD"],
    management=ManagementNetworkConfig("192.0.2.20", 24, "192.0.2.1"),
    expected_mac="00:11:22:33:44:55",
)

result = bootstrap_switch(config, check_mode=True)
```

The timeout fields are `timeout_s` for individual requests,
`transition_timeout_s` for reconnecting to the new endpoint, and
`poll_interval_s` between reconnect attempts. Their defaults are 5, 60, and 1
second respectively.

## Ansible API

The supported collection entry point is
`bronweg.cgiswitch.jtcom_bootstrap`. Its action plugin runs in the controller
Python environment and calls the `cgiswitch` package there.

```yaml
- name: Bootstrap a switch
  bronweg.cgiswitch.jtcom_bootstrap:
    factory_url: "{{ jtcom_factory_url }}"
    target_url: "{{ jtcom_target_url }}"
    username: "{{ jtcom_username }}"
    factory_password: "{{ jtcom_factory_password }}"
    password: "{{ jtcom_target_password }}"
    expected_mac: "{{ jtcom_expected_mac }}"
    management:
      address: "{{ jtcom_target_address }}"
      prefix_length: 24
      gateway: "{{ jtcom_gateway }}"
    verify_tls: false
  check_mode: true
  no_log: true
```

`factory_password` and `password` are secret inputs. Supply them through
Ansible variables, Vault, or another secret provider. The collection rejects
unknown nested keys and invalid types before connecting.

## Discovery and operation order

Discovery checks these combinations in deterministic order:

1. target endpoint with target credentials;
2. factory endpoint with target credentials;
3. target endpoint with factory credentials;
4. factory endpoint with factory credentials.

The four useful states are:

| Endpoint | Credentials | Meaning |
| --- | --- | --- |
| factory | factory | Neither transition is complete |
| factory | target | Credentials changed; network remains at factory |
| target | factory | Network changed; credentials remain at factory |
| target | target | Runtime state is fully desired |

Discovery verifies identity on every authenticated candidate. A wrong identity,
inconsistent network readback, or acceptance of both distinct passwords fails
closed. It does not select the first responding switch.

When a mutation is needed, credentials are changed first and the management
network second. The final identity and network readback is a separate
preflight. Only after that preflight succeeds does the workflow send the one
`configuration:save` request.

The tested firmware requires `saveconfig` for credential and management
network persistence. Every successful non-check run performs one save barrier,
including a logical no-op. `changed` describes password and network changes;
the save does not count as a logical change. Therefore a successful no-op can
return:

```yaml
changed: false
operations: []
persistence: saved
```

## Check mode

Check mode performs authentication requests and read-only discovery. It does
not send a credential mutation, management-network mutation, or save request.
It reports the logical operations that would be needed and returns
`persistence: save_required`, including when no logical operation is planned.

## Results and recovery

Successful results include `changed`, `operations`,
`completed_operations`, `endpoint`, `device_identity`, `target_reached`, and
`persistence`. Python workflow failures raise `JTComBootstrapError`;
`as_result()` returns the same structured failure used by Ansible. Invalid
inputs can raise `ValueError` before discovery. Workflow failures include `stage`, `write_attempted`,
`completed_operations`, `failed_operation`, `target_reached`, and the safe
identity context.

`last_verified_endpoint` means the last endpoint where device identity was
successfully verified. Network verification at that endpoint may still have
failed. `target_reached` preserves the transition's observation that the
target endpoint answered, even if identity or network verification failed
afterward. A failure in the final preflight is reported under
`persistence_preflight`; it is not reported as a failed save. A failed save is
reported under `persistence` with `configuration:save`.

If a process stops after a mutation and before save, rerun the same bootstrap.
Discovery reconciles the runtime state and a successful non-check run performs
the persistence barrier. There is no automatic rollback.

## Hardware evidence

The complete workflow was hardware-validated on an ONTi ONT-S207CW-62TS-SE
running firmware `V100SP11240725`. The validation covered credential and
management-network transitions, no-op reruns, save persistence, reboot
persistence, and exact restoration of the pre-test baseline. This evidence is
specific to that tested device and firmware; unit-tested behavior and hardware
validation are separate claims. See
[`docs/hardware/2026-09-18-bootstrap-validation.md`](hardware/2026-09-18-bootstrap-validation.md)
for the sanitized record.
