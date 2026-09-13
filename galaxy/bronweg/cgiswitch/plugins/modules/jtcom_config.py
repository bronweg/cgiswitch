#!/usr/bin/python3
# Copyright: (c) 2024, cgiswitch contributors
# SPDX-License-Identifier: MIT
"""Ansible module stub: bronweg.cgiswitch.jtcom_config.

All execution logic lives in plugins/action/jtcom_config.py which runs in the
Ansible controller Python process and imports cgiswitch directly.
This file exists only for argument documentation (ansible-doc, Galaxy, IDEs).
"""
from __future__ import annotations

DOCUMENTATION = r"""
---
module: jtcom_config
short_description: Configure JTCom CGI Ethernet switches
description:
  - Idempotent configuration of VLANs and ports on JTCom-compatible L2 switches.
  - Wraps cgiswitch C(apply()) for deterministic, diff-aware apply.
  - Supports Ansible check mode (dry-run) natively.
  - Ports are 1-based everywhere.
  - >-
    VLAN membership input uses canonical on-wire semantics: C(untagged) means
    the VLAN sent untagged on wire, and C(tagged) means VLANs sent tagged on wire.
options:
  host:
    description: IP address or hostname of the switch.
    required: true
    type: str
  username:
    description: Login username.
    required: true
    type: str
  password:
    description: Login password.
    required: true
    type: str
    no_log: true
  verify_tls:
    description: Verify TLS certificates when connecting over HTTPS.
    type: bool
    default: true
  backup_before_change:
    description: Download and save a config backup before applying any real change.
    type: bool
    default: true
  allow_port_mode_change:
    description: >
      Allow VLAN membership changes that would move a port between effective
      access and trunk mode. Blocked by default.
    type: bool
    default: false
  allow_untagged_move:
    description: >
      Allow destructive untagged/native VLAN moves. By default, changing a port
      from one untagged/native VLAN to another fails in apply mode.
    type: bool
    default: false
  allow_vlan_delete_in_use:
    description: >
      Allow deleting VLANs still referenced by ports by auto-detaching those
      ports first. This is a destructive override.
    type: bool
    default: false
  auto_create_referenced_vlans:
    description: >
      Create VLANs referenced by port-centric membership fields when they are
      absent from the switch and not explicitly declared under C(vlans).
      Disabled by default; unknown references fail validation.
    type: bool
    default: false
  vlans:
    description: >
      Incremental VLAN changes, keyed by VLAN ID (string or int).
      VLAN-centric membership fields are expressed in canonical on-wire terms
      and may contain C(tagged_ports), C(untagged_ports), C(tagged_add),
      C(tagged_remove), C(tagged_set), C(untagged_add), C(untagged_remove),
      C(untagged_set), C(name), and C(state).
      Ports are 1-based IDs. Omitting C(state) defaults to C(present).
      VLANs not listed are untouched. VLAN 1 cannot be deleted.
    type: dict
  ports:
    description: >
      Incremental port changes, keyed by 1-based port ID (string or int).
      Each entry may contain C(admin_up) (bool), C(speed) (str),
      C(flow_control) (bool), and optional VLAN membership shortcuts:
      C(access_vlan), C(native_vlan), C(trunk_add_vlans), C(trunk_remove_vlans),
      and C(trunk_set_vlans). Port-centric VLAN input is translated to the same
      canonical membership planner used for VLAN-centric syntax.
      C(access_vlan) selects access mode and clears existing tagged memberships.
      It cannot be combined with C(native_vlan) or any C(trunk_*) field.
      A trunk-to-access transition requires C(allow_port_mode_change=true).
      C(native_vlan) + C(trunk_*) configures a canonical trunk.
      Referenced VLANs must already exist or be declared under C(vlans:) with
      C(state: present). Set C(auto_create_referenced_vlans: true) to create
      unknown access/native/add/set references. Remove references never create
      VLANs and fail when unknown.
      Set C(admin_up: false) to administratively disable a port.
      Ports not listed are untouched. Port 6 (management uplink) cannot be
      administratively disabled.
    type: dict
notes:
  - "Run this module on the Ansible controller (C(connection: local))."
  - cgiswitch must be installed in the Python environment used by Ansible.
  - Use C(--check) for a safe dry-run that shows planned changes without applying them.
  - >
    Policy violations are returned as structured C(violations) with C(blocked: true);
    advisory conditions remain in C(warnings).
  - Untagged/native VLAN moves are blocked by default.
  - VLAN delete-in-use is blocked by default.
  - Access/trunk mode changes are blocked by default.
  - If a changed port would otherwise have no VLAN membership, it is mapped to
    access VLAN 1 and a structured warning is returned.
requirements:
  - cgiswitch == 0.1.0
author:
  - cgiswitch contributors
"""

EXAMPLES = r"""
- name: Create VLAN 61 and tag ports 1..5
  bronweg.cgiswitch.jtcom_config:
    host: 192.0.2.1
    username: "{{ jtcom_user }}"
    password: "{{ jtcom_pass }}"
    verify_tls: false
    vlans:
      61:
        name: Admin
        tagged_add: [1, 2, 3, 4, 5]

- name: Configure access port 3 in VLAN 20
  bronweg.cgiswitch.jtcom_config:
    host: 192.0.2.1
    username: "{{ jtcom_user }}"
    password: "{{ jtcom_pass }}"
    verify_tls: false
    vlans:
      20:
        state: present
    ports:
      3:
        access_vlan: 20

- name: Configure trunk port 5 with native VLAN 10 and tagged VLANs 20,30
  bronweg.cgiswitch.jtcom_config:
    host: 192.0.2.1
    username: "{{ jtcom_user }}"
    password: "{{ jtcom_pass }}"
    verify_tls: false
    vlans:
      10:
        state: present
      20:
        state: present
      30:
        state: present
    ports:
      5:
        native_vlan: 10
        trunk_set_vlans: [20, 30]

- name: Allow an explicit untagged move from VLAN 20 to VLAN 30
  bronweg.cgiswitch.jtcom_config:
    host: 192.0.2.1
    username: "{{ jtcom_user }}"
    password: "{{ jtcom_pass }}"
    verify_tls: false
    vlans:
      30:
        state: present
    ports:
      3:
        access_vlan: 30
    allow_untagged_move: true

- name: Allow an access to trunk mode change when intended
  bronweg.cgiswitch.jtcom_config:
    host: 192.0.2.1
    username: "{{ jtcom_user }}"
    password: "{{ jtcom_pass }}"
    verify_tls: false
    vlans:
      10:
        state: present
      20:
        state: present
      30:
        state: present
    ports:
      5:
        native_vlan: 10
        trunk_set_vlans: [20, 30]
    allow_port_mode_change: true

- name: Force-delete a VLAN after detaching it from ports first
  bronweg.cgiswitch.jtcom_config:
    host: 192.0.2.1
    username: "{{ jtcom_user }}"
    password: "{{ jtcom_pass }}"
    verify_tls: false
    vlans:
      20:
        state: absent
    allow_vlan_delete_in_use: true

- name: Dry-run a change and inspect structured warnings
  bronweg.cgiswitch.jtcom_config:
    host: 192.0.2.1
    username: "{{ jtcom_user }}"
    password: "{{ jtcom_pass }}"
    verify_tls: false
    vlans:
      61:
        tagged_add: [1, 2, 3, 4, 5]
  check_mode: true

- name: Create a VLAN referenced only by a port patch
  bronweg.cgiswitch.jtcom_config:
    host: 192.0.2.1
    username: "{{ jtcom_user }}"
    password: "{{ jtcom_pass }}"
    verify_tls: false
    auto_create_referenced_vlans: true
    ports:
      3:
        access_vlan: 61
"""

RETURN = r"""
changed:
  description: Whether any configuration change was made (or would be in check mode).
  type: bool
  returned: always
diff:
  description: >
    Structured diff dict from the cgiswitch plan engine, containing
    C(summary), C(total_changes), and C(changes) list.
  type: dict
  returned: always
backup_file:
  description: Path to the config backup file saved before changes, or empty string.
  type: str
  returned: always
applied:
  description: List of change keys that were applied (empty in check mode).
  type: list
  elements: str
  returned: always
completed_operations:
  description: Ordered operation records completed before a failure, or on success.
  type: list
  elements: dict
  returned: always
failed_operation:
  description: Operation record that failed, when an apply failure occurs.
  type: dict
  returned: on failure
original_exception:
  description: Type and message of the original apply exception.
  type: dict
  returned: on failure
readback:
  description: Best-effort device readback captured after a partial failure.
  type: dict
  returned: on failure
readback_error:
  description: Type and message of a failed best-effort readback.
  type: dict
  returned: on failure
write_attempted:
  description: Whether any write may have been attempted before failure.
  type: bool
  returned: on failure
warnings:
  description: >
    Advisory warning objects for permitted risks and explicit fallback behavior.
    Common fields include C(type), C(entity), C(message), C(hint), and
    C(port_id) or C(vlan_id) when applicable. Typical warning types include
    C(untagged_move), C(vlan_delete_in_use), C(mode_none_mapped_to_vlan1),
    and C(port_mode_change).
  type: list
  returned: always
violations:
  description: >
    Structured policy violations that block an apply. In check mode these are
    reported with C(blocked: true); in normal mode the action fails before
    backup or writes.
  type: list
  returned: always
blocked:
  description: Whether policy violations block the requested operation.
  type: bool
  returned: always
"""

from ansible.module_utils.basic import AnsibleModule  # noqa: E402  # type: ignore[import-untyped]


def main() -> None:
    module = AnsibleModule(
        argument_spec=dict(
            host=dict(type="str", required=True),
            username=dict(type="str", required=True),
            password=dict(type="str", required=True, no_log=True),
            verify_tls=dict(type="bool", default=True),
            backup_before_change=dict(type="bool", default=True),
            allow_port_mode_change=dict(type="bool", default=False),
            allow_untagged_move=dict(type="bool", default=False),
            allow_vlan_delete_in_use=dict(type="bool", default=False),
            auto_create_referenced_vlans=dict(type="bool", default=False),
            vlans=dict(type="dict"),
            ports=dict(type="dict"),
        ),
        supports_check_mode=True,
    )
    # Execution is handled entirely by plugins/action/jtcom_config.py.
    # This stub is reached only when the action plugin is absent.
    module.fail_json(msg="jtcom_config action plugin not found. Check collection installation.")


if __name__ == "__main__":
    main()
