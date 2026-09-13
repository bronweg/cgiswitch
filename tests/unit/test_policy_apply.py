"""Policy decisions are identical in preview and apply, before any mutation."""

from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from cgiswitch import ApplyPolicy, JTComPolicyError, JTComSwitch
from cgiswitch.model.config import DeviceConfig
from cgiswitch.model.port import PortConfig, PortSettings
from cgiswitch.model.vlan import VlanConfig, VlanEntry


def switch_with_state(
    monkeypatch: pytest.MonkeyPatch,
    vlans: dict[int, VlanEntry],
    policy: ApplyPolicy | None = None,
) -> JTComSwitch:
    switch = JTComSwitch("192.0.2.1", "admin", "secret", policy=policy)
    switch._session = MagicMock()
    ports = [PortSettings(pid, f"Port {pid}", True, "Auto", False) for pid in [1, 6]]
    monkeypatch.setattr(switch, "_read_current_state", lambda _: (vlans, ports))
    monkeypatch.setattr(switch, "_save_backup", MagicMock())
    return switch


def scenario(name: str) -> tuple[dict[int, VlanEntry], DeviceConfig, ApplyPolicy]:
    current = {
        1: VlanEntry(1, name="v1", untagged_ports=["Port 1", "Port 6"]),
        20: VlanEntry(20, name="v20"),
    }
    desired = DeviceConfig(vlans={99: VlanConfig(99, name="unrelated")})
    if name == "safety_port_shutdown":
        desired.ports[6] = PortConfig(6, admin_up=False)
        override = ApplyPolicy(safety_port_id=5)
    elif name == "port_mode_change":
        desired.vlans[20] = VlanConfig(20, tagged_add=[1])
        override = ApplyPolicy(allow_port_mode_change=True)
    elif name == "untagged_move":
        desired.vlans[20] = VlanConfig(20, untagged_add=[1])
        override = ApplyPolicy(allow_untagged_move=True)
    elif name == "vlan_delete_in_use":
        current[20].tagged_ports = ["Port 1"]
        current[30] = VlanEntry(30, name="v30", tagged_ports=["Port 1"])
        desired.vlans[20] = VlanConfig(20, state="absent")
        override = ApplyPolicy(allow_vlan_delete_in_use=True)
    else:
        current[20].tagged_ports = ["Port 1"]
        desired.vlans[1] = VlanConfig(1, untagged_remove=[1])
        override = ApplyPolicy(
            allow_port_mode_change=True, allow_untagged_move=True, allow_vlan_delete_in_use=True
        )
    return current, desired, override


@pytest.mark.parametrize(
    "kind",
    [
        "safety_port_shutdown",
        "port_mode_change",
        "untagged_move",
        "vlan_delete_in_use",
        "unsupported_vlan_port_mode",
    ],
)
def test_blocked_check_and_apply_share_violations_without_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    current, desired, override = scenario(kind)
    original = deepcopy(desired)
    switch = switch_with_state(monkeypatch, current)
    preview = switch.apply(desired, check_mode=True)
    assert preview["changed"] is True
    assert preview["blocked"] is True
    assert kind in [item["type"] for item in preview["violations"]]
    assert kind not in [item["type"] for item in preview["warnings"]]
    assert preview["backup_file"] == ""
    assert preview["applied"] == []
    if kind == "safety_port_shutdown":
        change = next(c for c in preview["diff"]["changes"] if c["key"] == "port:6")
        assert change["details"]["admin_up"] == {"from": True, "to": False}
    with pytest.raises(JTComPolicyError) as exc:
        switch.apply(desired)
    assert exc.value.violations == preview["violations"]
    assert exc.value.blocked is True
    switch._save_backup.assert_not_called()
    switch._session.post.assert_not_called()
    switch._session.download_config_backup.assert_not_called()
    assert desired == original

    allowed_switch = switch_with_state(monkeypatch, current, override)
    allowed = allowed_switch.apply(desired, check_mode=True)
    assert allowed["blocked"] is (kind == "unsupported_vlan_port_mode")
    if kind != "unsupported_vlan_port_mode":
        assert allowed["violations"] == []
    allowed_switch._save_backup.assert_not_called()
    allowed_switch._session.post.assert_not_called()


@pytest.mark.parametrize(
    "field", ["access_vlan", "native_vlan", "trunk_add_vlans", "trunk_set_vlans"]
)
@pytest.mark.parametrize("check_mode", [True, False])
def test_unknown_port_vlan_default_fails_without_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    check_mode: bool,
) -> None:
    switch = switch_with_state(monkeypatch, {1: VlanEntry(1, name="v1", untagged_ports=["Port 1"])})
    value = [20] if field.startswith("trunk") else 20
    desired = DeviceConfig(ports={1: PortConfig(1, **{field: value})})
    with pytest.raises(ValueError, match="20"):
        switch.apply(desired, check_mode=check_mode)
    switch._save_backup.assert_not_called()
    switch._session.post.assert_not_called()
    switch._session.download_config_backup.assert_not_called()


@pytest.mark.parametrize("explicit", [False, True])
def test_referenced_vlan_creation_is_explicit_or_opted_in(
    monkeypatch: pytest.MonkeyPatch,
    explicit: bool,
) -> None:
    current = {1: VlanEntry(1, name="v1", untagged_ports=["Port 1", "Port 6"])}
    switch = switch_with_state(
        monkeypatch,
        current,
        ApplyPolicy(
            auto_create_referenced_vlans=not explicit,
            allow_port_mode_change=True,
            backup_before_change=False,
        ),
    )
    desired = DeviceConfig(
        ports={1: PortConfig(1, trunk_add_vlans=[20])},
        vlans={20: VlanConfig(20)} if explicit else {},
    )
    preview = switch.apply(desired, check_mode=True)
    assert preview["blocked"] is False
    assert any(
        c["kind"] == "vlan_create" and c["key"] == "vlan:20" for c in preview["diff"]["changes"]
    )
    post = {**current, 20: VlanEntry(20, name="v20", tagged_ports=["Port 1"])}
    ports = [PortSettings(pid, f"Port {pid}", True, "Auto", False) for pid in [1, 6]]
    monkeypatch.setattr(
        switch, "_read_current_state", MagicMock(side_effect=[(current, ports), (post, ports)])
    )
    monkeypatch.setattr(switch, "_verify_vlan_membership", MagicMock())
    result = switch.apply(desired)
    assert result["blocked"] is False
    assert "vlan:20" in result["applied"]
    assert switch._session.post.call_count == 2


@pytest.mark.parametrize(
    "field", ["access_vlan", "native_vlan", "trunk_add_vlans", "trunk_set_vlans"]
)
@pytest.mark.parametrize("existing", [False, True])
def test_port_references_use_existing_or_auto_created_vlan(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    existing: bool,
) -> None:
    current = {1: VlanEntry(1, "default", untagged_ports=["Port 1", "Port 6"])}
    if existing:
        current[20] = VlanEntry(20, "existing")
    switch = switch_with_state(
        monkeypatch,
        current,
        ApplyPolicy(
            auto_create_referenced_vlans=not existing,
            allow_port_mode_change=True,
            allow_untagged_move=True,
        ),
    )
    desired = DeviceConfig(
        ports={
            1: PortConfig(
                1,
                **{
                    field: [20] if field.startswith("trunk") else 20,
                },
            )
        }
    )
    original = deepcopy(desired)
    result = switch.apply(desired, check_mode=True)
    assert result["blocked"] is False
    creates = [c for c in result["diff"]["changes"] if c["kind"] == "vlan_create"]
    assert [c["key"] for c in creates] == ([] if existing else ["vlan:20"])
    assert desired == original
    switch._save_backup.assert_not_called()
    switch._session.post.assert_not_called()


@pytest.mark.parametrize(
    "field",
    ["access_vlan", "native_vlan", "trunk_add_vlans", "trunk_set_vlans", "trunk_remove_vlans"],
)
@pytest.mark.parametrize("check_mode", [False, True])
@pytest.mark.parametrize("auto_create", [False, True])
def test_absent_reference_conflict_is_always_preflight_error(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    check_mode: bool,
    auto_create: bool,
) -> None:
    switch = switch_with_state(
        monkeypatch,
        {20: VlanEntry(20, "existing")},
        ApplyPolicy(
            auto_create_referenced_vlans=auto_create,
        ),
    )
    desired = DeviceConfig(
        vlans={20: VlanConfig(20, state="absent")},
        ports={
            1: PortConfig(1, **{field: [20] if field.startswith("trunk") else 20}),
        },
    )
    with pytest.raises(ValueError, match="absent"):
        switch.apply(desired, check_mode=check_mode)
    switch._save_backup.assert_not_called()
    switch._session.post.assert_not_called()
    switch._session.download_config_backup.assert_not_called()


@pytest.mark.parametrize("check_mode", [False, True])
@pytest.mark.parametrize("auto_create", [False, True])
def test_unknown_remove_target_is_error_before_backup_or_write(
    monkeypatch: pytest.MonkeyPatch,
    check_mode: bool,
    auto_create: bool,
) -> None:
    switch = switch_with_state(
        monkeypatch,
        {},
        ApplyPolicy(
            auto_create_referenced_vlans=auto_create,
        ),
    )
    with pytest.raises(ValueError, match="unknown VLAN 20"):
        switch.apply(
            DeviceConfig(ports={1: PortConfig(1, trunk_remove_vlans=[20])}), check_mode=check_mode
        )
    switch._save_backup.assert_not_called()
    switch._session.post.assert_not_called()
    switch._session.download_config_backup.assert_not_called()


@pytest.mark.parametrize("allow", [False, True])
def test_access_intent_clears_trunk_tags_and_requires_mode_override(
    monkeypatch: pytest.MonkeyPatch,
    allow: bool,
) -> None:
    current = {
        1: VlanEntry(1, "default", untagged_ports=["Port 1", "Port 6"]),
        20: VlanEntry(20, "voice", tagged_ports=["Port 1"]),
        30: VlanEntry(30, "data", tagged_ports=["Port 1"]),
    }
    switch = switch_with_state(
        monkeypatch,
        current,
        ApplyPolicy(
            allow_port_mode_change=allow,
            backup_before_change=False,
        ),
    )
    desired = DeviceConfig(ports={1: PortConfig(1, access_vlan=1)})
    result = switch.apply(desired, check_mode=True)
    assert result["changed"] is True
    assert result["blocked"] is (not allow)
    assert result["after"][1] == {"untagged_vlan": 1, "tagged_vlans": []}
    switch._session.post.assert_not_called()
    switch._save_backup.assert_not_called()
    if not allow:
        assert [v["type"] for v in result["violations"]] == ["port_mode_change"]
        assert result["violations"][0]["current_mode"] == "trunk"
        assert result["violations"][0]["desired_mode"] == "access"
        with pytest.raises(JTComPolicyError) as exc:
            switch.apply(desired)
        assert exc.value.violations == result["violations"]
        switch._session.post.assert_not_called()
        switch._save_backup.assert_not_called()
        switch._session.download_config_backup.assert_not_called()
    else:
        post = {1: current[1], 20: VlanEntry(20, "voice"), 30: VlanEntry(30, "data")}
        ports = [PortSettings(pid, f"Port {pid}", True, "Auto", False) for pid in [1, 6]]
        monkeypatch.setattr(
            switch, "_read_current_state", MagicMock(side_effect=[(current, ports), (post, ports)])
        )
        monkeypatch.setattr(switch, "_verify_vlan_membership", MagicMock())
        applied = switch.apply(desired)
        assert applied["blocked"] is False
        assert switch._session.post.call_count == 1
        assert switch._session.post.call_args.kwargs["data"]["VlanType"] == "0"
