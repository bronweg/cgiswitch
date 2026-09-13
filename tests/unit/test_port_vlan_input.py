"""Unit tests for port-centric VLAN membership input."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from cgiswitch.model.config import DeviceConfig
from cgiswitch.model.options import ApplyPolicy
from cgiswitch.model.port import PortConfig, PortSettings
from cgiswitch.model.vlan import VlanConfig, VlanEntry
from cgiswitch.switch import JTComSwitch
from cgiswitch.utils.port_vlan_input import (
    DualSyntaxConflictError,
    merge_port_vlan_membership_inputs,
)
from cgiswitch.utils.vlan_membership import make_port_state


def test_port_config_validates_vlan_ids() -> None:
    PortConfig(
        port_id=5,
        access_vlan=10,
        native_vlan=20,
        trunk_add_vlans=[30],
        trunk_remove_vlans=[40],
    )

    with pytest.raises(ValueError, match="access_vlan"):
        PortConfig(port_id=5, access_vlan=0)
    with pytest.raises(ValueError, match="native_vlan"):
        PortConfig(port_id=5, native_vlan=4095)
    with pytest.raises(ValueError, match="trunk_add_vlans"):
        PortConfig(port_id=5, trunk_add_vlans=[10, 4095])
    with pytest.raises(ValueError, match="trunk_set_vlans cannot be combined"):
        PortConfig(port_id=5, trunk_set_vlans=[10], trunk_add_vlans=[20])


def test_access_and_native_vlan_can_coexist_with_trunk_lists() -> None:
    cfg = PortConfig(
        port_id=5,
        access_vlan=10,
        native_vlan=10,
        trunk_add_vlans=[20],
        trunk_remove_vlans=[30],
    )
    assert cfg.access_vlan == 10
    assert cfg.trunk_add_vlans == [20]


def test_port_only_input_translates_to_vlan_ops() -> None:
    merged = merge_port_vlan_membership_inputs(
        {5: make_port_state()},
        {},
        {
            5: PortConfig(
                port_id=5,
                access_vlan=10,
                trunk_add_vlans=[20],
                trunk_remove_vlans=[30],
            )
        },
    )

    assert merged[10].untagged_add == [5]
    assert merged[20].tagged_add == [5]
    assert merged[30].tagged_remove == [5]


def test_trunk_set_uses_current_tagged_membership() -> None:
    merged = merge_port_vlan_membership_inputs(
        {5: make_port_state(tagged_vlans={10, 20, 30})},
        {},
        {5: PortConfig(port_id=5, trunk_set_vlans=[20, 40])},
    )

    assert merged[10].tagged_remove == [5]
    assert 20 not in merged
    assert merged[30].tagged_remove == [5]
    assert merged[40].tagged_add == [5]


def test_vlan_only_input_is_unchanged() -> None:
    desired = {20: VlanConfig(vlan_id=20, tagged_add=[5])}
    merged = merge_port_vlan_membership_inputs({5: make_port_state()}, desired, {})

    assert merged[20].tagged_add == [5]
    assert desired[20].tagged_add == [5]


def test_compatible_vlan_and_port_inputs_are_merged() -> None:
    merged = merge_port_vlan_membership_inputs(
        {5: make_port_state()},
        {20: VlanConfig(vlan_id=20, tagged_add=[5])},
        {5: PortConfig(port_id=5, native_vlan=10, trunk_add_vlans=[30])},
    )

    assert merged[10].untagged_add == [5]
    assert merged[20].tagged_add == [5]
    assert merged[30].tagged_add == [5]


def test_untagged_dual_syntax_conflict_fails() -> None:
    with pytest.raises(DualSyntaxConflictError, match="Conflicting untagged VLANs"):
        merge_port_vlan_membership_inputs(
            {5: make_port_state()},
            {10: VlanConfig(vlan_id=10, untagged_add=[5])},
            {5: PortConfig(port_id=5, access_vlan=20)},
        )


def test_tagged_dual_syntax_add_remove_conflict_fails() -> None:
    with pytest.raises(DualSyntaxConflictError, match="Conflicting tagged add/remove"):
        merge_port_vlan_membership_inputs(
            {5: make_port_state(tagged_vlans={20})},
            {20: VlanConfig(vlan_id=20, tagged_add=[5])},
            {5: PortConfig(port_id=5, trunk_remove_vlans=[20])},
        )


def test_untagged_dual_syntax_add_remove_conflict_fails() -> None:
    with pytest.raises(DualSyntaxConflictError, match="Conflicting untagged add/remove"):
        merge_port_vlan_membership_inputs(
            {5: make_port_state(untagged_vlan=10)},
            {10: VlanConfig(vlan_id=10, untagged_remove=[5])},
            {5: PortConfig(port_id=5, access_vlan=10)},
        )


def test_trunk_set_conflicts_with_vlan_centric_tagged_ops_for_same_port() -> None:
    with pytest.raises(DualSyntaxConflictError, match="trunk_set_vlans"):
        merge_port_vlan_membership_inputs(
            {5: make_port_state(tagged_vlans={20})},
            {30: VlanConfig(vlan_id=30, tagged_add=[5])},
            {5: PortConfig(port_id=5, trunk_set_vlans=[20, 40])},
        )


def test_switch_check_mode_accepts_port_centric_vlan_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    switch = JTComSwitch("192.0.2.1", "admin", "admin")
    switch._session = MagicMock()
    current_vlans = {10: VlanEntry(vlan_id=10, name="v10")}
    current_ports = [PortSettings(
        port_id=5, name="Port 5", admin_up=True, speed_duplex="Auto", flow_control=False,
    )]
    monkeypatch.setattr(
        switch,
        "_read_current_state",
        lambda _session: (current_vlans, current_ports),
    )

    result = switch.apply(
        DeviceConfig(
            ports={
                5: PortConfig(
                    port_id=5,
                    admin_up=False,
                    native_vlan=10,
                    trunk_add_vlans=[20],
                )
            }
        ),
        check_mode=True,
    )

    assert result["changed"] is True
    assert result["changed_ports"] == [5]
    assert result["changed_vlans"] == [10, 20]
    assert result["diff"]["summary"]["port_update"] == 1
    assert result["diff"]["vlan_membership"]["after"][5] == {
        "untagged_vlan": 10,
        "tagged_vlans": [20],
    }


def test_switch_leaves_vlan_centric_input_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    switch = JTComSwitch("192.0.2.1", "admin", "admin")
    switch._session = MagicMock()
    current_vlans = {
        20: VlanEntry(vlan_id=20, name="v20"),
    }
    current_ports = [PortSettings(port_id=5, name="Port 5", admin_up=True)]
    monkeypatch.setattr(
        switch,
        "_read_current_state",
        lambda _session: (current_vlans, current_ports),
    )

    result = switch.apply(
        DeviceConfig(vlans={20: VlanConfig(vlan_id=20, tagged_add=[5])}),
        check_mode=True,
    )

    assert result["changed_ports"] == [5]
    assert result["changed_vlans"] == [20]
    assert result["diff"]["vlan_membership"]["after"][5]["tagged_vlans"] == [20]


def test_switch_dual_syntax_conflict_fails_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    switch = JTComSwitch("192.0.2.1", "admin", "admin")
    session = MagicMock()
    switch._session = session
    current_vlans = {
        10: VlanEntry(vlan_id=10, name="v10"),
        20: VlanEntry(vlan_id=20, name="v20"),
    }
    current_ports = [PortSettings(port_id=5, name="Port 5", admin_up=True)]
    monkeypatch.setattr(
        switch,
        "_read_current_state",
        lambda _session: (current_vlans, current_ports),
    )

    with pytest.raises(DualSyntaxConflictError):
        switch.apply(
            DeviceConfig(
                vlans={10: VlanConfig(vlan_id=10, untagged_add=[5])},
                ports={5: PortConfig(port_id=5, access_vlan=20)},
            )
        )

    session.post.assert_not_called()
    session.download_config_backup.assert_not_called()


def test_port_centric_untagged_move_fails_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    switch = JTComSwitch("192.0.2.1", "admin", "admin")
    switch._session = MagicMock()
    current_vlans = {
        20: VlanEntry(vlan_id=20, name="v20", untagged_ports=["Port 5"]),
        30: VlanEntry(vlan_id=30, name="v30"),
    }
    current_ports = [PortSettings(port_id=5, name="Port 5", admin_up=True)]
    monkeypatch.setattr(
        switch,
        "_read_current_state",
        lambda _session: (current_vlans, current_ports),
    )

    with pytest.raises(ValueError, match="Untagged/native VLAN move blocked"):
        switch.apply(
            DeviceConfig(ports={5: PortConfig(port_id=5, access_vlan=30)})
        )


def test_port_centric_untagged_move_allowed_with_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    switch = JTComSwitch(
        "192.0.2.1",
        "admin",
        "admin",
        policy=ApplyPolicy(allow_untagged_move=True),
    )
    switch._session = MagicMock()
    current_vlans = {
        20: VlanEntry(vlan_id=20, name="v20", untagged_ports=["Port 5"]),
        30: VlanEntry(vlan_id=30, name="v30"),
    }
    current_ports = [PortSettings(port_id=5, name="Port 5", admin_up=True)]
    monkeypatch.setattr(
        switch,
        "_read_current_state",
        lambda _session: (current_vlans, current_ports),
    )

    result = switch.apply(
        DeviceConfig(ports={5: PortConfig(port_id=5, access_vlan=30)}),
        check_mode=True,
    )

    assert result["changed_ports"] == [5]
    assert result["warnings"][0]["type"] == "untagged_move"
    assert result["after"][5]["untagged_vlan"] == 30


def test_allow_vlan_delete_in_use_does_not_suppress_dual_syntax_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    switch = JTComSwitch(
        "192.0.2.1",
        "admin",
        "admin",
        policy=ApplyPolicy(allow_vlan_delete_in_use=True),
    )
    switch._session = MagicMock()
    current_vlans = {20: VlanEntry(vlan_id=20, name="v20")}
    current_ports = [PortSettings(port_id=5, name="Port 5", admin_up=True)]
    monkeypatch.setattr(
        switch,
        "_read_current_state",
        lambda _session: (current_vlans, current_ports),
    )

    with pytest.raises(DualSyntaxConflictError):
        switch.apply(
            DeviceConfig(
                vlans={20: VlanConfig(vlan_id=20, state="absent")},
                ports={5: PortConfig(port_id=5, trunk_add_vlans=[20])},
            )
        )


def test_allow_untagged_move_does_not_suppress_dual_syntax_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    switch = JTComSwitch(
        "192.0.2.1",
        "admin",
        "admin",
        policy=ApplyPolicy(allow_untagged_move=True),
    )
    switch._session = MagicMock()
    current_vlans = {10: VlanEntry(vlan_id=10, name="v10"), 20: VlanEntry(vlan_id=20, name="v20")}
    current_ports = [PortSettings(port_id=5, name="Port 5", admin_up=True)]
    monkeypatch.setattr(
        switch,
        "_read_current_state",
        lambda _session: (current_vlans, current_ports),
    )

    with pytest.raises(DualSyntaxConflictError):
        switch.apply(
            DeviceConfig(
                vlans={10: VlanConfig(vlan_id=10, untagged_add=[5])},
                ports={5: PortConfig(port_id=5, access_vlan=20)},
            )
        )
