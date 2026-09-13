"""Pure compilation of a device plan into deterministic write operations."""

from __future__ import annotations

from dataclasses import dataclass

from cgiswitch.client.port_ops import compile_port_changes
from cgiswitch.client.vlan_ops import (
    build_vlan_create_payload,
    build_vlan_delete_payload,
    build_vlan_port_payload,
)
from cgiswitch.model.config import DeviceConfig
from cgiswitch.model.port import PortChangeSet, PortSettings
from cgiswitch.utils.device_diff import DevicePlan
from cgiswitch.utils.vlan_membership import (
    VlanMembershipPlan,
    canonical_to_jtcom_port_vlan_state,
    copy_port_state,
)
from cgiswitch.vendor.jtcom.endpoints import (
    PORT_SETTINGS,
    VLAN_CREATE_DELETE,
    VLAN_PORT_SET,
)


@dataclass(frozen=True)
class WriteOperation:
    """One fully compiled backend write, with no transport side effects."""

    key: str
    kind: str
    endpoint: str
    data: dict[str, str] | list[tuple[str, str]]

    def describe(self) -> dict[str, str]:
        """Return the stable, transport-independent operation description."""
        return {"key": self.key, "kind": self.kind, "endpoint": self.endpoint}


def compile_apply_operations(
    plan: DevicePlan,
    desired: DeviceConfig,
    current_ports: list[PortSettings],
    membership_plan: VlanMembershipPlan,
) -> list[WriteOperation]:
    """Compile every planned write before any backup or transport operation.

    VLAN creation, rename, membership, port setting, and deletion operations
    are returned in the fixed order required by the JTCom backend. All payload
    conversion, including canonical membership conversion, occurs in this
    function so a conversion error leaves the caller with no writes to make.
    """
    creates: list[WriteOperation] = []
    renames: list[WriteOperation] = []
    memberships: list[WriteOperation] = []
    port_updates: list[WriteOperation] = []
    deletes: list[WriteOperation] = []

    for change in plan.changes:
        if change.kind == "vlan_create":
            vlan_id = int(change.details["vlan_id"])
            vlan_config = desired.vlans[vlan_id]
            creates.append(WriteOperation(
                key=f"vlan:{vlan_id}", kind="vlan_create", endpoint=VLAN_CREATE_DELETE,
                data=build_vlan_create_payload(vlan_config.vlan_id, vlan_config.name),
            ))
        elif change.kind == "vlan_update" and "name" in change.details:
            vlan_id = int(change.details["vlan_id"])
            vlan_config = desired.vlans[vlan_id]
            renames.append(WriteOperation(
                key=f"vlan:{vlan_id}", kind="vlan_rename", endpoint=VLAN_CREATE_DELETE,
                data=build_vlan_create_payload(vlan_config.vlan_id, vlan_config.name),
            ))
        elif change.kind == "vlan_delete":
            vlan_id = int(change.details["vlan_id"])
            deletes.append(WriteOperation(
                key=f"vlan:{vlan_id}", kind="vlan_delete", endpoint=VLAN_CREATE_DELETE,
                data=build_vlan_delete_payload([vlan_id]),
            ))

    memberships = compile_membership_operations(membership_plan)

    desired_port_changes = PortChangeSet(update=[
        desired.ports[int(change.details["port_id"])]
        for change in plan.changes if change.kind == "port_update"
    ])
    for port_config, payload in zip(
        sorted(desired_port_changes.update, key=lambda item: item.port_id),
        compile_port_changes(current_ports, desired_port_changes),
        strict=True,
    ):
        port_updates.append(WriteOperation(
            key=f"port:{port_config.port_id}", kind="port_update", endpoint=PORT_SETTINGS,
            data=payload,
        ))

    creates.sort(key=lambda operation: int(operation.key.split(":", 1)[1]))
    renames.sort(key=lambda operation: int(operation.key.split(":", 1)[1]))
    deletes.sort(key=lambda operation: int(operation.key.split(":", 1)[1]), reverse=True)
    return creates + renames + memberships + port_updates + deletes


def compile_membership_operations(
    membership_plan: VlanMembershipPlan,
) -> list[WriteOperation]:
    """Compile all changed canonical port membership states into writes."""
    operations: list[WriteOperation] = []
    for port_id in sorted(membership_plan.changed_ports):
        state = membership_plan.desired_per_port[port_id]
        try:
            backend = canonical_to_jtcom_port_vlan_state(copy_port_state(state))
        except ValueError as exc:
            raise ValueError(
                f"Port {port_id} canonical state cannot be compiled to JTCom backend: {exc}"
            ) from exc
        operations.append(WriteOperation(
            key=f"vlan_membership:port:{port_id}", kind="vlan_membership", endpoint=VLAN_PORT_SET,
            data=build_vlan_port_payload(
                [port_id], backend["mode"], backend["access_vlan"],
                backend["native_vlan"], list(backend["permit_vlans"]),
            ),
        ))
    return operations
