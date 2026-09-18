"""Diff renderer for device plans."""

from __future__ import annotations

from typing import Any

from cgiswitch.model.config import DeviceConfig
from cgiswitch.model.vlan import VlanConfig
from cgiswitch.utils.device_diff import DevicePlan, build_device_plan
from cgiswitch.utils.vlan_membership import VlanMembershipPlan


def render_diff(plan: DevicePlan) -> dict[str, Any]:
    """Serialize *plan* to a JSON-serializable dict.

    Returns:
        A dict with keys:

        - ``"summary"`` — count of each change kind.
        - ``"total_changes"`` — total number of changes.
        - ``"changes"`` — list of change dicts (``kind``, ``key``, ``details``).
    """
    return {
        "summary": dict(plan.summary),
        "total_changes": len(plan.changes),
        "changes": [
            {"kind": c.kind, "key": c.key, "details": c.details}
            for c in plan.changes
        ],
    }


def render_effective_diff(
    current: DeviceConfig,
    desired: DeviceConfig,
    membership_plan: VlanMembershipPlan,
) -> dict[str, Any]:
    """Render the diff for the effective canonical membership target.

    The membership policy may resolve an incremental request to a different
    canonical target, for example by mapping an empty port to VLAN 1.  Build
    the device plan from that resolved target so the rendered diff describes
    the state that will actually be compiled and applied.  Scalar port intent,
    VLAN names, and VLAN state intent are retained from *desired*.

    The input configurations and membership plan are never modified.
    """
    # Include every explicit VLAN intent so an effective no-op cannot retain
    # an intermediate membership operation in the rendered diff. Membership
    # changes also include implicit source/target VLANs such as fallback VLAN 1.
    affected_vlans = set(membership_plan.changed_vlans) | set(desired.vlans)
    effective_vlans: dict[int, VlanConfig] = {
        vlan_id: cfg for vlan_id, cfg in desired.vlans.items()
    }

    for vlan_id in sorted(affected_vlans):
        desired_cfg = desired.vlans.get(vlan_id)
        current_cfg = current.vlans.get(vlan_id)
        if desired_cfg is None and current_cfg is None:
            # A membership plan should only reference VLANs represented by
            # current or desired state. Keep the renderer defensive here.
            continue
        source = desired_cfg or current_cfg
        assert source is not None
        tagged_ports: list[int] = []
        untagged_ports: list[int] = []
        for port_id, state in sorted(membership_plan.desired_per_port.items()):
            tagged_vlans = state["tagged_vlans"]
            if isinstance(tagged_vlans, set) and vlan_id in tagged_vlans:
                tagged_ports.append(port_id)
            if state["untagged_vlan"] == vlan_id:
                untagged_ports.append(port_id)
        effective_vlans[vlan_id] = VlanConfig(
            vlan_id=vlan_id,
            name=source.name,
            state=source.state,
            tagged_set=tagged_ports,
            untagged_set=untagged_ports,
        )

    effective = DeviceConfig(
        vlans=effective_vlans,
        ports=dict(desired.ports),
        metadata=dict(desired.metadata),
    )
    return render_diff(build_device_plan(current, effective))
