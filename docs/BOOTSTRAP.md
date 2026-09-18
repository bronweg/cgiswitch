# JTCom bootstrap

The bootstrap workflow moves a JTCom switch from its factory management
endpoint to its target management endpoint. It can transition credentials and
the management network, then saves the configuration when either value
changed. The workflow is intended to be called by the controller's external
IaC; it does not configure the controller network.

Hardware validation for the complete workflow is still pending. The examples
below use documentation addresses and placeholders. Keep credentials in the
controller's secret mechanism; never put passwords in a playbook, source file,
or command line.

## Python API

The public API is `BootstrapConfig` and `bootstrap_switch`:

```python
from cgiswitch import BootstrapConfig, ManagementNetworkConfig, bootstrap_switch

config = BootstrapConfig(
    factory_url="https://192.0.2.10",
    target_url="https://192.0.2.20",
    username="{{ managed by the controller }}",
    factory_password="{{ factory secret }}",
    target_password="{{ target secret }}",
    management=ManagementNetworkConfig(
        address="192.0.2.20",
        prefix_length=24,
        gateway="192.0.2.1",
    ),
    expected_mac="00:11:22:33:44:55",
    timeout_s=5.0,
    transition_timeout_s=60.0,
    poll_interval_s=1.0,
    verify_tls=True,
)

result = bootstrap_switch(config)
```

`expected_mac` and/or `expected_serial` is required. If both are supplied,
both must identify the same device. `management` is optional when only the
credential transition is needed; when supplied it contains `address`,
`prefix_length`, and `gateway`.

Factory and target endpoints must be explicit IPv4 URLs. When `management` is
supplied, `target_url`'s host must equal `management.address`; the factory URL
must point to the factory endpoint being discovered. Do not use a hostname, an
implicit scheme, or an endpoint that can resolve to another address.
`verify_tls` controls certificate verification for HTTPS. The timeout values
control individual requests, the transition wait, and polling interval.

## Discovery and identity

The workflow probes every credential and endpoint combination in this order:

1. target endpoint with the target credential
2. factory endpoint with the target credential
3. target endpoint with the factory credential
4. factory endpoint with the factory credential

It does not stop at the first successful HTTP response. Every probe is used to
establish identity. A foreign identity, or evidence that the factory and
target endpoints are different devices, fails the workflow before writes.

The resulting state is classified as one of `factory`, `passworddone`,
`networkdone`, or `fulltarget`. Credential changes are planned before network
changes. The workflow writes credentials, then the management network, and
saves only if at least one of those values changed. A no-op has zero
configuration POSTs.

## Ansible interface

The supported Ansible entry point is `bronweg.cgiswitch.jtcom_bootstrap`. It
has the same endpoint, credential, identity, timeout, and TLS fields as the
Python configuration. Its target credential field is named `password`, and
the management network is a nested mapping:

```yaml
- name: Bootstrap a JTCom switch
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
    verify_tls: true
```

Password variables must come from Ansible variables, a vault, or another
secret provider. Do not replace the placeholders with literal passwords.

Check mode performs authentication and GET discovery only. It can report the
planned primary operations `credentials:update` and
`management_network:update`; save is represented as a postcondition, not as a
third planned operation. No configuration POST is made in check mode.

## Persistence and failures

The underlying hardware transitions require a subsequent save to persist
credential and management-network writes, and the workflow does not reboot the
switch automatically. A successful save is therefore part of the
postcondition for a changed run.

Failures retain structured context: `stage`, `completed_operations`,
`failed_operation`, `write_attempted`, `last_endpoint`, and the verified
identity. This distinguishes discovery, credential, network, and save
failures from transport errors.

If a process is interrupted after a credential or network POST but before the
save, a later run may observe `fulltarget` while the earlier writes are not
known to be durable. The workflow cannot confirm flash durability from that
observation alone. A zero-write no-op on rerun must not be treated as proof
that the interrupted state was persisted; use an explicit repair decision if
the operator needs to address that ambiguity.

Bootstrap does not restore or reset a switch, upgrade firmware, or choose
production or homelab addressing. Those actions and the controller's network
path remain external IaC responsibilities.
