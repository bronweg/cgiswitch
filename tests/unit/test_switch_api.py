"""Focused tests for the standalone JTComSwitch API."""

from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cgiswitch.model.config import DeviceConfig
from cgiswitch.model.device import DeviceInfo
from cgiswitch.model.options import ApplyPolicy, JTComConnectionOptions
from cgiswitch.model.port import PortOperStatus, PortSettings
from cgiswitch.model.vlan import VlanConfig, VlanEntry
from cgiswitch.switch import JTComSwitch
from cgiswitch.utils.device_diff import build_device_plan


def test_connection_and_policy_options_are_typed_and_frozen() -> None:
    connection = JTComConnectionOptions(verify_tls=True, port=8443, timeout=12)
    policy = ApplyPolicy(backup_dir="/tmp/backups", allow_untagged_move=True)
    switch = JTComSwitch("switch.example", "admin", "secret", connection=connection, policy=policy)

    assert switch.connection == connection
    assert switch.policy == policy
    assert switch._build_base_url() == "https://switch.example:8443"
    with pytest.raises(FrozenInstanceError):
        connection.port = 9443  # type: ignore[misc]


def test_is_connected_reflects_authenticated_session() -> None:
    switch = JTComSwitch("192.0.2.1", "admin", "secret")
    assert switch.is_connected() is False
    session = MagicMock()
    session.logged_in = True
    switch._session = session
    assert switch.is_connected() is True


def test_open_closes_session_when_login_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    closed = []

    class FailingSession:
        logged_in = False

        def __init__(self, **_kwargs: object) -> None:
            pass

        def login(self) -> None:
            raise RuntimeError("login failed")

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr("cgiswitch.switch.JTComSession", FailingSession)
    switch = JTComSwitch("192.0.2.1", "admin", "secret")

    with pytest.raises(RuntimeError, match="login failed"):
        switch.open()

    assert closed == [True]
    assert switch.is_connected() is False


def test_typed_read_helpers_return_parser_models(monkeypatch: pytest.MonkeyPatch) -> None:
    switch = JTComSwitch("192.0.2.1", "admin", "secret")
    session = MagicMock()
    switch._session = session
    info = DeviceInfo(mac_address="00:11:22:33:44:55")
    settings = [PortSettings(port_id=1, name="Port 1", admin_up=True)]
    oper = [PortOperStatus(port_id=1, link_up=True)]
    vlans = {1: VlanEntry(vlan_id=1, name="default")}
    monkeypatch.setattr("cgiswitch.switch.parse_device_info", lambda _html: info)
    monkeypatch.setattr("cgiswitch.switch.parse_port_page", lambda _html: (settings, oper))
    monkeypatch.setattr(switch, "_fetch_vlan_state", lambda _session: vlans)

    assert switch.read_device_info() is info
    assert switch.read_ports() == (settings, oper)
    assert switch.read_vlans() == vlans


def test_apply_uses_constructor_policy_for_membership_planning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = ApplyPolicy(
        safety_port_id=7,
        allow_port_mode_change=True,
        allow_untagged_move=True,
        allow_vlan_delete_in_use=True,
    )
    switch = JTComSwitch("192.0.2.1", "admin", "secret", policy=policy)
    switch._session = MagicMock()
    monkeypatch.setattr(switch, "_read_current_state", lambda _session: ({}, []))
    seen: list[ApplyPolicy] = []
    build_plan = MagicMock(wraps=build_device_plan)
    monkeypatch.setattr("cgiswitch.switch.build_device_plan", build_plan)

    def plan(*_args: object, **kwargs: object) -> MagicMock:
        policy_arg = kwargs["policy"]
        assert isinstance(policy_arg, ApplyPolicy)
        seen.append(policy_arg)
        return MagicMock(changed_ports=[], warnings=[])

    monkeypatch.setattr(switch, "_plan_vlan_membership", plan)
    result = switch.apply(DeviceConfig(), check_mode=True)

    assert result["changed"] is False
    assert switch.policy is policy
    assert seen == [policy]
    assert build_plan.call_args.kwargs["safety_port_id"] == 7


def test_apply_rejects_policy_keyword_before_reads_or_writes() -> None:
    switch = JTComSwitch("192.0.2.1", "admin", "secret")
    session = MagicMock()
    switch._session = session

    with pytest.raises(TypeError, match="unexpected keyword argument 'policy'"):
        switch.apply(DeviceConfig(), policy=ApplyPolicy())  # type: ignore[call-arg]

    session.assert_not_called()
    session.get.assert_not_called()
    session.post.assert_not_called()
    session.download_config_backup.assert_not_called()


def test_apply_uses_constructor_backup_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    enabled_dir = tmp_path / "enabled-backups"
    switch = JTComSwitch(
        "192.0.2.1",
        "admin",
        "secret",
        policy=ApplyPolicy(
            safety_port_id=9,
            backup_before_change=True,
            backup_dir=enabled_dir,
            allow_port_mode_change=True,
            allow_untagged_move=True,
            allow_vlan_delete_in_use=True,
        ),
    )
    session = MagicMock()
    switch._session = session
    current: tuple[dict[int, VlanEntry], list[PortSettings]] = ({}, [])
    post: tuple[dict[int, VlanEntry], list[PortSettings]] = (
        {10: VlanEntry(vlan_id=10, name="v10")},
        [],
    )
    monkeypatch.setattr(switch, "_read_current_state", MagicMock(side_effect=[current, post]))
    monkeypatch.setattr("cgiswitch.switch.vlan_create", MagicMock())
    session.download_config_backup.return_value = b"backup"
    desired = DeviceConfig(vlans={10: VlanConfig(vlan_id=10, name="v10")})

    first = switch.apply(desired)
    backup_path = first["backup_file"]
    assert backup_path
    assert backup_path.startswith(str(enabled_dir))
    assert (enabled_dir / backup_path.rsplit("/", 1)[-1]).read_bytes() == b"backup"
    assert switch.policy.safety_port_id == 9

    disabled = JTComSwitch(
        "192.0.2.1",
        "admin",
        "secret",
        policy=ApplyPolicy(backup_before_change=False),
    )
    disabled._session = session
    monkeypatch.setattr(disabled, "_read_current_state", MagicMock(side_effect=[current, post]))
    second = disabled.apply(desired)
    assert second["backup_file"] == ""
    assert session.download_config_backup.call_count == 1


def test_context_manager_closes_and_propagates_body_exception() -> None:
    switch = JTComSwitch("192.0.2.1", "admin", "secret")
    switch.open = MagicMock()  # type: ignore[method-assign]
    switch.close = MagicMock()  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="body failure"), switch:
        raise RuntimeError("body failure")

    switch.open.assert_called_once()
    switch.close.assert_called_once()
