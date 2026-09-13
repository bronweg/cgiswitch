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

        for key in ("host", "username", "password"):
            if not p.get(key):
                return dict(failed=True, msg=f"Parameter '{key}' is required.")

        try:
            from cgiswitch.client.errors import JTComError, JTComPolicyError
            from cgiswitch.model.config import DeviceConfig
            from cgiswitch.model.options import ApplyPolicy, JTComConnectionOptions
            from cgiswitch.model.port import PortConfig
            from cgiswitch.model.vlan import VlanConfig
            from cgiswitch.switch import JTComSwitch
        except ImportError as exc:
            return dict(failed=True, msg=f"cgiswitch is not installed: {exc}")

        vlans: dict[int, Any] = {}
        for key, entry in (p.get("vlans") or {}).items():
            vid = int(key)
            entry = entry or {}
            vlans[vid] = VlanConfig(
                vlan_id=vid,
                name=entry.get("name"),
                tagged_ports=_int_list_or_none(entry, "tagged_ports"),
                untagged_ports=_int_list_or_none(entry, "untagged_ports"),
                tagged_add=_int_list_or_none(entry, "tagged_add"),
                tagged_remove=_int_list_or_none(entry, "tagged_remove"),
                tagged_set=_int_list_or_none(entry, "tagged_set"),
                untagged_add=_int_list_or_none(entry, "untagged_add"),
                untagged_remove=_int_list_or_none(entry, "untagged_remove"),
                untagged_set=_int_list_or_none(entry, "untagged_set"),
                state=entry.get("state", "present"),
            )

        ports: dict[int, Any] = {}
        for key, entry in (p.get("ports") or {}).items():
            pid = int(key)
            entry = entry or {}
            ports[pid] = PortConfig(
                port_id=pid,
                admin_up=entry.get("admin_up"),
                speed_duplex=entry.get("speed"),
                flow_control=entry.get("flow_control"),
                access_vlan=_int_or_none(entry, "access_vlan"),
                native_vlan=_int_or_none(entry, "native_vlan"),
                trunk_add_vlans=_int_list_or_none(entry, "trunk_add_vlans"),
                trunk_remove_vlans=_int_list_or_none(entry, "trunk_remove_vlans"),
                trunk_set_vlans=_int_list_or_none(entry, "trunk_set_vlans"),
            )

        desired = DeviceConfig(vlans=vlans, ports=ports)

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
        )
        return result


def _int_list_or_none(entry: dict[str, Any], key: str) -> list[int] | None:
    if key not in entry or entry[key] is None:
        return None
    return [int(x) for x in entry[key]]


def _int_or_none(entry: dict[str, Any], key: str) -> int | None:
    if key not in entry or entry[key] is None:
        return None
    return int(entry[key])
