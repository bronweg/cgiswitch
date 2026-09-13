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


def test_per_call_policy_does_not_mutate_stored_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    base = ApplyPolicy(allow_untagged_move=False)
    override = ApplyPolicy(allow_untagged_move=True)
    switch = JTComSwitch("192.0.2.1", "admin", "secret", policy=base)
    switch._session = MagicMock()
    monkeypatch.setattr(switch, "_read_current_state", lambda _session: ({}, []))
    seen: list[bool] = []

    def plan(*_args: object, **kwargs: object) -> MagicMock:
        seen.append(bool(kwargs["allow_untagged_move"]))
        return MagicMock(changed_ports=[], warnings=[])

    monkeypatch.setattr(switch, "_plan_vlan_membership", plan)
    result = switch.apply(DeviceConfig(), policy=override, check_mode=True)
    result_default = switch.apply(DeviceConfig(), check_mode=True)

    assert result["changed"] is False
    assert result_default["changed"] is False
    assert switch.policy is base
    assert seen == [True, False]


def test_apply_routes_per_call_backup_policy_without_mutating_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    switch = JTComSwitch(
        "192.0.2.1",
        "admin",
        "secret",
        policy=ApplyPolicy(backup_before_change=False),
    )
    session = MagicMock()
    switch._session = session
    current: tuple[dict[int, VlanEntry], list[PortSettings]] = ({}, [])
    post: tuple[dict[int, VlanEntry], list[PortSettings]] = (
        {10: VlanEntry(vlan_id=10, name="v10")},
        [],
    )
    monkeypatch.setattr(
        switch,
        "_read_current_state",
        MagicMock(side_effect=[current, post, current, post]),
    )
    monkeypatch.setattr("cgiswitch.switch.vlan_create", MagicMock())
    session.download_config_backup.return_value = b"backup"
    desired = DeviceConfig(vlans={10: VlanConfig(vlan_id=10, name="v10")})

    override_dir = tmp_path / "override-backups"
    first = switch.apply(
        desired,
        policy=ApplyPolicy(backup_before_change=True, backup_dir=override_dir),
    )
    backup_path = first["backup_file"]
    assert backup_path
    assert backup_path.startswith(str(override_dir))
    assert (override_dir / backup_path.rsplit("/", 1)[-1]).read_bytes() == b"backup"
    assert switch.policy.backup_before_change is False

    second = switch.apply(desired, policy=ApplyPolicy(backup_before_change=False))
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
