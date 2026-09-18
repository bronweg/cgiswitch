#!/usr/bin/python3
"""Documentation-only module stub for the controller-side bootstrap action."""

from __future__ import annotations

DOCUMENTATION = r"""
---
module: jtcom_bootstrap
short_description: Bootstrap a JTCom switch onto a management network
description:
  - >-
    Discovers the factory switch, authenticates, configures the management
    network, and saves the configuration when changed.
  - The action runs on the Ansible controller and calls the cgiswitch Python API.
  - >-
    Check mode performs authentication and GET discovery only; it does not
    POST, save, reboot, or change the network.
  - A no-op emits zero configuration POSTs.
  - >-
    A crash after a write and before save cannot be confirmed as persisted
    because the firmware has no confirmed persisted readback.
options:
  factory_url:
    description: Factory URL used for discovery and initial authentication.
    required: true
    type: str
  target_url:
    description: Target URL used after the management address transition.
    required: true
    type: str
  username:
    description: Login username used at both endpoints.
    required: true
    type: str
  factory_password:
    description: Password used at the factory endpoint.
    required: true
    type: str
    no_log: true
  password:
    description: Password used at the target endpoint.
    required: true
    type: str
    no_log: true
  management:
    description: Static management network with address, prefix_length, and gateway.
    required: true
    type: dict
    no_log: true
  expected_mac:
    description: Optional identity check for the discovered switch MAC address.
    type: str
  expected_serial:
    description: Optional identity check for the discovered switch serial number.
    type: str
  timeout_s:
    description: Request timeout in seconds.
    type: float
    default: 5.0
  transition_timeout_s:
    description: Maximum time to wait for the new management endpoint.
    type: float
    default: 60.0
  poll_interval_s:
    description: Delay between transition endpoint polls.
    type: float
    default: 1.0
  verify_tls:
    description: Verify TLS certificates for HTTPS requests.
    type: bool
    default: true
notes:
  - The action requires either expected_mac or expected_serial.
  - No reboot is performed.
  - The factory and target passwords are kept out of action results.
author:
  - cgiswitch contributors
"""

EXAMPLES = r"""
- name: Bootstrap a factory switch
  bronweg.cgiswitch.jtcom_bootstrap:
    factory_url: http://192.0.2.1
    target_url: https://198.51.100.10
    username: admin
    factory_password: "{{ factory_password }}"
    password: "{{ jtcom_password }}"
    management:
      address: 198.51.100.10
      prefix_length: 24
      gateway: 198.51.100.1
    expected_mac: "00:11:22:33:44:55"
    verify_tls: false
"""

RETURN = r"""
changed:
  description: Whether bootstrap wrote a configuration change.
  type: bool
  returned: always
operations:
  description: Deterministic planned operations.
  type: list
  returned: always
completed_operations:
  description: Operations completed before returning or failing.
  type: list
  returned: always
endpoint:
  description: Endpoint used for the final observed state.
  type: str
  returned: success
device_identity:
  description: Safe discovered device identity fields.
  type: dict
  returned: success
persistence:
  description: Persistence observation state.
  type: str
  returned: success
target_reached:
  description: Whether the target endpoint was reached.
  type: bool
  returned: success
"""
