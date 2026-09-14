#!/usr/bin/python3
# Copyright: (c) 2024, cgiswitch contributors
# SPDX-License-Identifier: MIT
"""Ansible action plugin: bronweg.cgiswitch.jtcom_config.

Runs entirely in the Ansible controller Python process — cgiswitch is
imported directly with no subprocess or bootstrap tricks required.
"""
from __future__ import annotations

from typing import Any

from ansible.plugins.action import ActionBase


class ActionModule(ActionBase):  # type: ignore[misc]
    """Idempotent configuration of JTCom CGI switches via cgiswitch."""

    TRANSFERS_FILES = False

    def run(
        self,
        tmp: str | None = None,
        task_vars: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = super().run(tmp, task_vars)
        p: dict[str, Any] = self._task.args

        try:
            _validate_task_args(p)
        except ValueError as exc:
            return dict(failed=True, changed=False, msg=str(exc))

        try:
            from cgiswitch.client.errors import (
                JTComApplyError,
                JTComError,
                JTComPolicyError,
            )
            from cgiswitch.model.options import ApplyPolicy, JTComConnectionOptions
            from cgiswitch.switch import JTComSwitch
            from cgiswitch.utils.ansible_input import parse_desired_config
        except ImportError as exc:
            return dict(failed=True, msg=f"cgiswitch is not installed: {exc}")

        try:
            desired = parse_desired_config(p)
        except ValueError as exc:
            return dict(failed=True, changed=False, msg=str(exc))

        connection = JTComConnectionOptions(
            verify_tls=p.get("verify_tls", True),
        )
        policy = ApplyPolicy(
            backup_before_change=p.get("backup_before_change", True),
            safety_port_id=6,
            allow_port_mode_change=p.get("allow_port_mode_change", False),
            allow_untagged_move=p.get("allow_untagged_move", False),
            allow_vlan_delete_in_use=p.get("allow_vlan_delete_in_use", False),
            auto_create_referenced_vlans=p.get("auto_create_referenced_vlans", False),
        )

        try:
            switch = JTComSwitch(
                hostname=p["host"],
                username=p["username"],
                password=p["password"],
                connection=connection,
                policy=policy,
            )
            switch.open()
            try:
                cfg_result = switch.apply(
                    desired,
                    check_mode=self._play_context.check_mode,
                )
            finally:
                switch.close()
        except JTComApplyError as exc:
            return exc.as_result()
        except JTComPolicyError as exc:
            return dict(
                failed=True,
                msg=str(exc),
                changed=False,
                blocked=True,
                violations=exc.violations,
                backup_file="",
                applied=[],
                warnings=[],
            )
        except (JTComError, ValueError, ConnectionError) as exc:
            return dict(failed=True, msg=str(exc))

        result.update(
            changed=cfg_result["changed"],
            diff=cfg_result["diff"],
            backup_file=cfg_result.get("backup_file", ""),
            applied=cfg_result.get("applied", []),
            warnings=cfg_result.get("warnings", []),
            blocked=cfg_result.get("blocked", False),
            violations=cfg_result.get("violations", []),
            changed_ports=cfg_result.get("changed_ports", []),
            changed_vlans=cfg_result.get("changed_vlans", []),
            completed_operations=cfg_result.get("completed_operations", []),
            operations=cfg_result.get("operations", []),
        )
        return result


def _validate_task_args(args: object) -> None:
    """Validate raw task arguments without relying on the module stub."""
    if not isinstance(args, dict):
        raise ValueError("Task arguments must be a mapping")
    flags = {
        "verify_tls", "backup_before_change", "allow_port_mode_change",
        "allow_untagged_move", "allow_vlan_delete_in_use", "auto_create_referenced_vlans",
    }
    allowed = flags | {"host", "username", "password", "vlans", "ports"}
    for key in args:
        if not isinstance(key, str) or key not in allowed:
            raise ValueError(f"Unknown task parameter: {key!r}")
    for key in ("host", "username", "password"):
        value = args.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Parameter '{key}' must be a non-empty string")
    for key in sorted(flags):
        if key in args and not isinstance(args[key], bool):
            raise ValueError(f"Parameter '{key}' must be a boolean")
