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
    This action runs in the Ansible controller process. The collection parses
    and validates input with module utilities, then calls the cgiswitch Python
    library directly.
  - >-
    The JTCom backend uses the switch firmware's CGI interface. Applies have
    no transactional commit and no automatic rollback after a failed write.
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
    description: >
      Verify TLS certificates when connecting over HTTPS. For a host without
      a scheme, true selects HTTPS on port 443 and false selects HTTP on port 80.
      An explicit http:// or https:// in C(host) determines the scheme directly.
      An explicit HTTPS host with false still uses HTTPS, with certificate
      verification disabled.
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
  safety_port_id:
    description: >
      Positive integer ID of the protected management port. Changes that would
      administratively disable this port are blocked by policy.
      Strings, booleans, and non-integer values are rejected without coercion.
    type: int
    default: 6
  vlans:
    description: >
      Incremental VLAN changes, keyed by VLAN ID. Map keys may be integers or
      ASCII decimal strings and are normalized to integers; duplicate keys
      after normalization are rejected. IDs must be in the range 1..4094.
      Each entry is a map with only these keys: C(name) (string or null),
      C(tagged_ports), C(untagged_ports), C(tagged_add), C(tagged_remove),
      C(tagged_set), C(untagged_add), C(untagged_remove), and
      C(untagged_set) (lists of strict integer port IDs), and C(state)
      (C(present) or C(absent)). A null optional value leaves that field
      unchanged. Null maps and null entries are rejected; an empty map means
      no field-level change. Unknown entry keys are rejected.
      Ports are 1-based and are checked against the device after validation.
      Omitting C(state) defaults to C(present). VLANs not listed are
      untouched. VLAN 1 cannot be deleted.
    type: dict
  ports:
    description: >
      Incremental port changes, keyed by port ID. Map keys may be integers or
      ASCII decimal strings and are normalized to integers; duplicate keys
      after normalization are rejected. IDs must be at least 1 and are checked
      against the device after validation. Each entry is a map containing only
      C(admin_up) (strict bool), C(speed) (string), C(flow_control) (strict
      bool), and the optional VLAN membership shortcuts C(access_vlan),
      C(native_vlan), C(trunk_add_vlans), C(trunk_remove_vlans), and
      C(trunk_set_vlans). VLAN IDs in scalar fields are strict integers in the
      range 1..4094; quoted numeric values are rejected. VLAN lists contain
      strict integer IDs in the same range. Optional null values leave the
      corresponding field unchanged. Null maps and null entries are rejected.
      C(speed) accepts C(Auto), C(10M/Half), C(10M/Full), C(100M/Half),
      C(100M/Full), C(1000M/Full), C(2500M/Full), and C(10G/Full), plus
      existing aliases such as C(1G/Full). Unknown speed strings are rejected.
      C(trunk_set_vlans) cannot be combined with C(trunk_add_vlans) or
      C(trunk_remove_vlans). Empty set lists clear tagged membership.
      Unknown entry keys are rejected.
      Port-centric VLAN input is translated to the same canonical membership
      planner used for VLAN-centric syntax.
      C(access_vlan) selects access mode and clears existing tagged memberships.
      It cannot be combined with C(native_vlan) or any C(trunk_*) field.
      A trunk-to-access transition requires C(allow_port_mode_change=true).
      C(native_vlan) + C(trunk_*) configures a canonical trunk.
      Referenced VLANs must already exist or be declared under C(vlans:) with
      C(state: present). Set C(auto_create_referenced_vlans: true) to create
      unknown access/native/add/set references. Remove references never create
      VLANs and fail when unknown.
      Set C(admin_up: false) to administratively disable a port.
      Ports not listed are untouched. The port selected by C(safety_port_id)
      cannot be administratively disabled.
    type: dict
notes:
  - "Run this module on the Ansible controller (C(connection: local))."
  - >-
    ansible-core 2.14.0 or newer is required. This is the Ansible controller
    runtime, not an Ansible distribution version.
  - >-
    Install a cgiswitch checkout or package matching the collection checkout
    in the Python environment used by the Ansible controller. Both current
    projects are version 0.1.0, but the action plugin does not enforce an
    exact package version at runtime.
  - Raw task arguments are validated by the action plugin before opening a
    switch connection. Unknown top-level and nested keys are rejected.
  - Boolean top-level options are strict booleans; string values are rejected
    instead of being coerced.
  - Use C(--check) for a safe dry-run that shows planned changes without applying them.
  - >
    Policy violations are returned as structured C(violations) with C(blocked: true);
    advisory conditions remain in C(warnings). In check mode a blocked plan is
    inspection-only: it reports the planned change and violations, does not
    save a backup, and does not write to the switch.
  - Untagged/native VLAN moves are blocked by default.
  - VLAN delete-in-use is blocked by default.
  - Access/trunk mode changes are blocked by default.
  - The protected management port defaults to port 6 and can be changed with
    C(safety_port_id).
  - C(safety_port_id) must be a positive integer. Malformed values and wrong
    types are rejected instead of being silently coerced; valid booleans,
    integer IDs, and list members are accepted where their fields require them.
  - If a changed port would otherwise have no VLAN membership, it is mapped to
    access VLAN 1 and a structured warning is returned.
requirements:
  - >-
    A cgiswitch checkout or package matching the collection checkout, installed
    in the Ansible controller Python environment
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
  check_mode: true
  bronweg.cgiswitch.jtcom_config:
    host: 192.0.2.1
    username: "{{ jtcom_user }}"
    password: "{{ jtcom_pass }}"
    verify_tls: false
    vlans:
      61:
        tagged_add: [1, 2, 3, 4, 5]

- name: Inspect a blocked plan with a custom safety port
  check_mode: true
  bronweg.cgiswitch.jtcom_config:
    host: 192.0.2.1
    username: "{{ jtcom_user }}"
    password: "{{ jtcom_pass }}"
    verify_tls: false
    safety_port_id: 5
    ports:
      5:
        admin_up: false
  register: jtcom_preview

- name: Show policy violations without changing the switch
  ansible.builtin.debug:
    var: jtcom_preview.violations
  when: jtcom_preview.blocked | default(false)

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
  description: >
    Whether the plan contains changes, or whether a write may have been
    attempted before an apply failure. In check mode this is true when the
    plan would change the device, including a policy-blocked plan.
  type: bool
  returned: on success, check mode, input validation failure, policy failure, or apply failure
diff:
  description: >
    Structured diff dict from the cgiswitch plan engine, containing
    C(summary), C(total_changes), and C(changes) list.
  type: dict
  returned: on success or check mode
backup_file:
  description: >
    Path to the config backup file saved before changes, or an empty string
    when no backup was made.
  type: str
  returned: on success, check mode, policy failure, or apply failure
applied:
  description: >
    List of operation keys confirmed as completed. It is empty in check mode
    and before the first write; an apply failure includes only operations
    confirmed before the failed operation.
  type: list
  elements: str
  returned: on success, check mode, policy failure, or apply failure
operations:
  description: >
    Deterministically ordered operation records planned for execution. Check
    mode exposes these records without taking a backup or writing to the
    device. A policy-blocked check has no executable operations.
  type: list
  elements: dict
  returned: on success or check mode
completed_operations:
  description: >
    Ordered operation records confirmed by the client. On success this is the
    complete applied operation list; in check mode it is empty; on apply
    failure it contains only operations completed before the failure.
  type: list
  elements: dict
  returned: on success, check mode, or apply failure
failed_operation:
  description: Operation record that failed, when an apply failure occurs.
  type: dict
  returned: on apply failure
original_exception:
  description: Type and message of the original apply exception.
  type: dict
  returned: on apply failure
readback:
  description: >
    Best-effort actual device snapshot captured after an apply failure. It is
    the post-write verification snapshot when verification readback succeeded;
    otherwise it is a recovery readback when one was possible. The key is
    present on every apply failure and is null when no snapshot was obtained.
  type: dict
  returned: on apply failure
readback_error:
  description: >
    Type and message of a failed best-effort readback, or null when no
    recovery read was needed or it succeeded.
  type: dict
  returned: on apply failure
write_attempted:
  description: Whether any write may have been attempted before failure.
  type: bool
  returned: on apply failure
remaining_diff:
  description: >
    Residual canonical diff from a verification failure. It is computed from
    the actual snapshot in C(readback) and is returned only when verification
    found state that did not match the effective target.
  type: dict
  returned: on verification failure
changed_ports:
  description: Sorted 1-based port IDs whose effective VLAN membership changes.
  type: list
  elements: int
  returned: on success or check mode
changed_vlans:
  description: Sorted VLAN IDs whose effective VLAN membership changes.
  type: list
  elements: int
  returned: on success or check mode
warnings:
  description: >
    Advisory warning objects for permitted risks and explicit fallback behavior.
    Common fields include C(type), C(entity), C(message), C(hint), and
    C(port_id) or C(vlan_id) when applicable. Typical warning types include
    C(untagged_move), C(vlan_delete_in_use), C(mode_none_mapped_to_vlan1),
    and C(port_mode_change).
  type: list
  returned: on success, check mode, or policy failure
violations:
  description: >
    Structured policy violations that block an apply. In check mode these are
    reported with C(blocked: true); in normal mode the action fails before
    backup or writes.
  type: list
  returned: on success, check mode, or policy failure
blocked:
  description: Whether policy violations block the requested operation.
  type: bool
  returned: on success, check mode, or policy failure
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
            safety_port_id=dict(type="int", default=6),
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
