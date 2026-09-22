#!/usr/bin/python3
"""Documentation-only module stub for the controller-side bootstrap action."""

from __future__ import annotations

DOCUMENTATION = r"""
module: jtcom_bootstrap
short_description: Bootstrap a known switch with verified credentials and IPv4
  state
description:
- Runs identity-bound discovery, credentials then network transitions in the controller
  Python process.
- Every successful non-check run performs one saveconfig, including logical no-ops.
  No reboot or rollback is performed.
- Check mode permits authentication POSTs and reads, but no configuration or save
  POSTs.
options:
  factory_url:
    description: Explicit HTTP(S) IPv4 URL. Root path only; no credentials, query
      or fragment.
    type: str
    required: true
  target_url:
    description: Same URL rules as factory_url; address must equal management.address.
    type: str
    required: true
  username:
    description: 'Same username at both endpoints: 5-16 ASCII letters, digits
      or underscores.'
    type: str
    required: true
  factory_password:
    description: Non-empty current password, tried at either endpoint during discovery.
    type: str
    required: true
    no_log: true
  password:
    description: 'Target password: 6-16 ASCII letters, digits or characters <=>[]!@#$*().
      Tried at either endpoint.'
    type: str
    required: true
    no_log: true
  management:
    description: Required static IPv4 configuration. Unknown nested keys are rejected.
    type: dict
    required: true
    suboptions:
      address:
        description: IPv4 address; multicast and unspecified addresses are rejected.
        type: str
        required: true
      prefix_length:
        description: Strict integer IPv4 prefix length, 0..32.
        type: int
        required: true
      gateway:
        description: IPv4 address within the management subnet.
        type: str
        required: true
  expected_mac:
    description: Nonzero unicast MAC in colon-separated hex form. At least one
      identity field is required; both are checked when supplied.
    type: str
  expected_serial:
    description: Non-empty serial, matched exactly. At least one identity field
      is required.
    type: str
  timeout_s:
    description: Finite positive request timeout in seconds.
    type: float
    default: 5.0
  transition_timeout_s:
    description: Finite positive target reconnect deadline in seconds.
    type: float
    default: 60.0
  poll_interval_s:
    description: Finite positive delay between target polls in seconds.
    type: float
    default: 1.0
  verify_tls:
    description: Strict boolean for HTTPS certificate verification; explicit URL
      scheme is unchanged.
    type: bool
    default: true
notes:
- The controller network must already provide reachability to factory and target
  networks. This action never configures controller networking.
- Unknown keys, invalid types and null required values are rejected before connection.
  Numeric timeout options accept numbers, not numeric strings or booleans.
- The action censors its result with no_log. Password values are not included
  in bootstrap results.
- Neither a model string nor a responding endpoint proves device identity. Different
  discovered devices fail closed.
requirements:
- Python 3.11+ and cgiswitch in the controller environment; ansible-core 2.14+.
author:
- cgiswitch contributors
"""

EXAMPLES = r"""
- name: Preview bootstrap for a known switch
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
"""

RETURN = r"""
changed:
  description: Logical credential/network change, excluding save. On transition
    failure, may mean a configuration write was attempted.
  type: bool
  returned: success or failure
operations:
  description: Ordered logical operations, empty when runtime state is desired.
  type: list
  returned: success or check mode
completed_operations:
  description: Logical operations confirmed complete before return or failure.
  type: list
  returned: success or structured bootstrap failure
endpoint:
  description: Selected endpoint in check mode; verified target on live success.
  type: str
  returned: success or check mode
device_identity:
  description: Verified device identity; null if discovery failed before verification.
  type: dict
  returned: success or structured bootstrap failure
persistence:
  description: save_required in check mode, even on a no-op; saved on live success.
  type: str
  returned: success or check mode
stage:
  description: Failed stage, including persistence_preflight or persistence.
  type: str
  returned: structured bootstrap failure
failed_operation:
  description: Failed logical operation, configuration:save, or null before an
    operation starts.
  type: dict
  returned: structured bootstrap failure
write_attempted:
  description: Whether any configuration or save POST was attempted.
  type: bool
  returned: structured bootstrap failure
underlying_exception:
  description: Error type and sanitized message, without raw response details.
  type: dict
  returned: structured bootstrap failure
last_verified_endpoint:
  description: Last endpoint with verified identity; network verification may
    not have completed. Null before any verified endpoint.
  type: str
  returned: structured bootstrap failure
target_reached:
  description: Whether the target was reached; does not alone prove identity or
    network verification.
  type: bool
  returned: success or structured bootstrap failure
"""
