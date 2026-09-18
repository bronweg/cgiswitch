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
module: jtcom_config
short_description: Configure VLANs and ports through JTCom CGI
description:
- Runs in the Ansible controller Python process using cgiswitch.
- Check mode reads state and reports the effective plan without backup or configuration
  writes.
- Writes are verified but are not transactional; no automatic rollback or saveconfig
  is performed.
options:
  host:
    description: Non-empty hostname or explicit HTTP(S) URL.
    type: str
    required: true
  username:
    description: Non-empty login username.
    type: str
    required: true
  password:
    description: Non-empty login password. Use task-level no_log to hide task
      inputs and output.
    type: str
    required: true
    no_log: true
  verify_tls:
    description: For a host without a scheme, true selects HTTPS/443 and false
      HTTP/80. An explicit URL selects its own scheme and port. For HTTPS this
      option also controls certificate verification.
    type: bool
    default: true
  backup_before_change:
    description: Download a backup to ./backups on the controller before a non-empty
      live apply. No backup in check mode or on a no-op.
    type: bool
    default: true
  safety_port_id:
    description: Positive integer port ID. Policy blocks administrative shutdown
      of this port, not every membership change.
    type: int
    default: 6
  allow_port_mode_change:
    description: Permit access/trunk transitions; allowed risks remain warnings.
    type: bool
    default: false
  allow_untagged_move:
    description: Permit moving a port to another untagged/native VLAN.
    type: bool
    default: false
  allow_vlan_delete_in_use:
    description: Permit deletion after detaching VLAN members; other policies
      still apply.
    type: bool
    default: false
  auto_create_referenced_vlans:
    description: Create unknown port access/native/add/set references. Explicitly
      absent VLANs conflict. Unknown remove targets always fail.
    type: bool
    default: false
  vlans:
    description:
    - Map of VLAN ID (1..4094) to a non-null entry map; omitted means no VLAN
      entries.
    - Entry keys are name (string or null), state (present by default, or absent),
      tagged_add, tagged_remove, tagged_set, untagged_add, untagged_remove, untagged_set.
    - Membership values are lists of positive integer port IDs or null. Omitted/null
      means unchanged; empty set clears that membership side. Set cannot coexist
      with add/remove on the same side, including empty lists.
    - An empty entry ensures the VLAN exists. Unlisted VLANs are untouched except
      changes implied by port intent. VLAN 1 cannot be deleted.
    type: dict
  ports:
    description:
    - Map of positive port ID to a non-null entry map; omitted means no port entries.
      IDs must exist on the device.
    - Entry keys are admin_up and flow_control (booleans), speed (string), access_vlan,
      native_vlan, trunk_add_vlans, trunk_remove_vlans, trunk_set_vlans. Optional
      null values mean unchanged.
    - Speed accepts Auto, 10M/Half, 10M/Full, 100M/Half, 100M/Full, 1000M/Full,
      2500M/Full, 10G/Full and accepted shorthand such as 1G/Full.
    - VLAN scalar/list values are strict integer IDs in 1..4094. access_vlan sets
      untagged membership and removes all tags; it cannot coexist with native_vlan
      or any trunk field.
    - native_vlan sets untagged membership without changing tags. trunk_add/remove
      patch tagged membership; trunk_set replaces it and cannot coexist with trunk_add/remove,
      including empty lists.
    - Referenced VLANs must exist or be declared present, unless auto_create_referenced_vlans
      permits creation.
    type: dict
notes:
- Unknown top-level/nested keys and wrong types are rejected by the action before
  connecting. Booleans and list members are not coerced.
- Map keys may be integers or ASCII digit strings. Duplicate numeric IDs after
  normalization, null maps/entries and null state are rejected.
- Policy-blocked check mode returns changed=true, blocked=true and violations.
  Live policy failure happens before backup and writes.
- A port left with no membership maps to access VLAN 1 with a warning. Tagged-only
  membership is blocked.
- Connection timeout is 60 seconds. Separate timeout, port and backup_dir options
  are not exposed by this action.
requirements:
- Python 3.11+ and cgiswitch in the controller environment; ansible-core 2.14+.
author:
- cgiswitch contributors
"""

EXAMPLES = r"""
- name: Preview VLAN creation
  bronweg.cgiswitch.jtcom_config:
    host: http://192.0.2.10
    username: admin
    password: "{{ switch_password }}"
    vlans:
      20: {name: users}
  check_mode: true
  no_log: true

- name: Preview an access port
  bronweg.cgiswitch.jtcom_config:
    host: http://192.0.2.10
    username: admin
    password: "{{ switch_password }}"
    allow_untagged_move: true
    allow_port_mode_change: true
    vlans:
      20: {state: present}
    ports:
      2: {access_vlan: 20}
  check_mode: true
  no_log: true
"""

RETURN = r"""
changed:
  description: Logical change on success/preview; on apply failure, whether a
    write was attempted.
  type: bool
  returned: success, input/policy validation failure, or structured apply failure
diff:
  description: Effective plan with summary, total_changes and changes.
  type: dict
  returned: success or check mode
backup_file:
  description: Saved backup path, or empty string when none was created.
  type: str
  returned: success, policy failure or apply failure
applied:
  description: Confirmed operation keys; empty in check mode.
  type: list
  returned: success, policy failure or apply failure
operations:
  description: Ordered executable operation descriptions; empty on blocked preview.
  type: list
  returned: success or check mode
completed_operations:
  description: Confirmed write descriptions, including partial progress on failure.
  type: list
  returned: success or apply failure
warnings:
  description: Advisory records for permitted risks and fallback behavior.
  type: list
  returned: success or policy failure
violations:
  description: Structured policy records blocking the plan.
  type: list
  returned: success or policy failure
blocked:
  description: Whether policy blocks the plan.
  type: bool
  returned: success or policy failure
changed_ports:
  description: Port IDs with effective membership changes.
  type: list
  returned: success or check mode
changed_vlans:
  description: VLAN IDs with effective membership changes.
  type: list
  returned: success or check mode
failed_operation:
  description: Failed write, backup or verification operation.
  type: dict
  returned: structured apply failure
original_exception:
  description: Original error type and message.
  type: dict
  returned: structured apply failure
write_attempted:
  description: Whether a write may have reached the switch.
  type: bool
  returned: structured apply failure
readback:
  description: Verification snapshot, or recovery snapshot when verification produced
    none; null if unavailable.
  type: dict
  returned: structured apply failure
readback_error:
  description: Recovery read error type/message, or null.
  type: dict
  returned: structured apply failure
remaining_diff:
  description: Residual differences from verification.
  type: dict
  returned: verification mismatch
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
