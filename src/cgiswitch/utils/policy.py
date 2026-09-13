"""Evaluate device policy without changing the requested plan."""

from __future__ import annotations

from typing import Any

from cgiswitch.model.options import ApplyPolicy
from cgiswitch.utils.device_diff import DevicePlan


def evaluate_device_policy(plan: DevicePlan, policy: ApplyPolicy) -> list[dict[str, Any]]:
    """Return safety-port violations while leaving every planned change intact."""
    violations: list[dict[str, Any]] = []
    for change in plan.changes:
        if (
            change.kind == "port_update"
            and change.details["port_id"] == policy.safety_port_id
            and change.details.get("admin_up", {}).get("to") is False
        ):
            violations.append(
                {
                    "type": "safety_port_shutdown",
                    "entity": "port",
                    "port_id": policy.safety_port_id,
                    "vlan_id": None,
                    "message": (
                        f"Port {policy.safety_port_id} is the safety port and cannot be disabled."
                    ),
                    "hint": (
                        "Select a different safety_port_id only after securing management access."
                    ),
                }
            )
    return violations
