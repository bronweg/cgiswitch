"""Unit tests for cgiswitch.utils.port_diff.plan_port_changes."""

from __future__ import annotations

from cgiswitch.model.port import PortConfig, PortSettings
from cgiswitch.utils.port_diff import plan_port_changes

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_settings(
    port_id: int,
    admin_up: bool = True,
    speed_duplex: str | None = "Auto",
    flow_control: bool | None = True,
) -> PortSettings:
    return PortSettings(
        port_id=port_id,
        name=f"Port {port_id}",
        admin_up=admin_up,
        speed_duplex=speed_duplex,
        flow_control=flow_control,
    )


def make_cfg(
    port_id: int,
    admin_up: bool | None = None,
    speed_duplex: str | None = None,
    flow_control: bool | None = None,
) -> PortConfig:
    return PortConfig(
        port_id=port_id,
        admin_up=admin_up,
        speed_duplex=speed_duplex,
        flow_control=flow_control,
    )


# ---------------------------------------------------------------------------
# No-change scenarios
# ---------------------------------------------------------------------------

class TestNoChange:
    def test_empty_desired_returns_empty_changeset(self) -> None:
        current = [make_settings(1), make_settings(2)]
        cs = plan_port_changes(current, [])
        assert cs.update == []

    def test_all_none_desired_fields_returns_no_update(self) -> None:
        current = [make_settings(1, admin_up=True, speed_duplex="Auto")]
        desired = [make_cfg(1)]  # all None — no change
        cs = plan_port_changes(current, desired)
        assert cs.update == []

    def test_matching_values_return_no_update(self) -> None:
        current = [make_settings(1, admin_up=True, speed_duplex="Auto", flow_control=True)]
        desired = [make_cfg(1, admin_up=True, speed_duplex="Auto", flow_control=True)]
        cs = plan_port_changes(current, desired)
        assert cs.update == []

    def test_unknown_port_id_silently_ignored(self) -> None:
        current = [make_settings(1)]
        desired = [make_cfg(99, admin_up=False)]  # port 99 does not exist
        cs = plan_port_changes(current, desired)
        assert cs.update == []


# ---------------------------------------------------------------------------
# admin_up changes
# ---------------------------------------------------------------------------

class TestAdminUpChange:
    def test_disable_port(self) -> None:
        current = [make_settings(1, admin_up=True)]
        desired = [make_cfg(1, admin_up=False)]
        cs = plan_port_changes(current, desired)
        assert len(cs.update) == 1
        assert cs.update[0].port_id == 1
        assert cs.update[0].admin_up is False

    def test_enable_port(self) -> None:
        current = [make_settings(2, admin_up=False)]
        desired = [make_cfg(2, admin_up=True)]
        cs = plan_port_changes(current, desired)
        assert len(cs.update) == 1
        assert cs.update[0].admin_up is True

    def test_no_change_when_already_disabled(self) -> None:
        current = [make_settings(1, admin_up=False)]
        desired = [make_cfg(1, admin_up=False)]
        cs = plan_port_changes(current, desired)
        assert cs.update == []


# ---------------------------------------------------------------------------
# speed_duplex changes
# ---------------------------------------------------------------------------

class TestSpeedDuplexChange:
    def test_change_speed(self) -> None:
        current = [make_settings(1, speed_duplex="Auto")]
        desired = [make_cfg(1, speed_duplex="1000M/Full")]
        cs = plan_port_changes(current, desired)
        assert len(cs.update) == 1
        assert cs.update[0].speed_duplex == "1000M/Full"

    def test_no_change_when_speed_matches(self) -> None:
        current = [make_settings(1, speed_duplex="1000M/Full")]
        desired = [make_cfg(1, speed_duplex="1000M/Full")]
        cs = plan_port_changes(current, desired)
        assert cs.update == []


# ---------------------------------------------------------------------------
# flow_control changes
# ---------------------------------------------------------------------------

class TestFlowControlChange:
    def test_disable_flow_control(self) -> None:
        current = [make_settings(1, flow_control=True)]
        desired = [make_cfg(1, flow_control=False)]
        cs = plan_port_changes(current, desired)
        assert len(cs.update) == 1
        assert cs.update[0].flow_control is False

    def test_no_change_when_flow_matches(self) -> None:
        current = [make_settings(1, flow_control=False)]
        desired = [make_cfg(1, flow_control=False)]
        cs = plan_port_changes(current, desired)
        assert cs.update == []


# ---------------------------------------------------------------------------
# Ordering and multiple ports
# ---------------------------------------------------------------------------

class TestOrdering:
    def test_updates_sorted_ascending_by_port_id(self) -> None:
        current = [make_settings(1), make_settings(2), make_settings(3)]
        desired = [
            make_cfg(3, admin_up=False),
            make_cfg(1, admin_up=False),
        ]
        cs = plan_port_changes(current, desired)
        assert [c.port_id for c in cs.update] == [1, 3]

    def test_multiple_fields_changed_on_same_port(self) -> None:
        current = [make_settings(1, admin_up=True, speed_duplex="Auto", flow_control=True)]
        desired = [make_cfg(1, admin_up=False, speed_duplex="1000M/Full", flow_control=False)]
        cs = plan_port_changes(current, desired)
        assert len(cs.update) == 1
        cfg = cs.update[0]
        assert cfg.admin_up is False
        assert cfg.speed_duplex == "1000M/Full"
        assert cfg.flow_control is False

    def test_only_changed_ports_included(self) -> None:
        current = [make_settings(1), make_settings(2), make_settings(3)]
        desired = [
            make_cfg(1),                 # no change
            make_cfg(2, admin_up=False), # change
            make_cfg(3),                 # no change
        ]
        cs = plan_port_changes(current, desired)
        assert [c.port_id for c in cs.update] == [2]
