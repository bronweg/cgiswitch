"""Bounded tests for the public bootstrap model, discovery, and orchestrator."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from cgiswitch import BootstrapConfig, bootstrap_switch
from cgiswitch.bootstrap import discovery, orchestrator
from cgiswitch.bootstrap.discovery import Candidate
from cgiswitch.bootstrap.identity import DeviceIdentity
from cgiswitch.bootstrap.network import NetworkTransitionResult
from cgiswitch.client.errors import JTComAuthError
from cgiswitch.client.session import JTComCredentials
from cgiswitch.model.device import DeviceInfo
from cgiswitch.model.management import ManagementNetworkConfig, ManagementNetworkState

FACTORY = "http://192.0.2.1"
TARGET = "http://192.0.2.10"
IDENTITY = DeviceIdentity("02:00:00:00:00:01", "fixture-serial")
DEVICE = DeviceInfo(IDENTITY.mac_address, serial_number=IDENTITY.serial_number)
DESIRED = ManagementNetworkConfig("192.0.2.10", 24, "192.0.2.1")
CURRENT = ManagementNetworkConfig("192.0.2.1", 24, "192.0.2.1").as_state()


def make_config(**changes: object) -> BootstrapConfig:
    values: dict[str, object] = {
        "factory_url": FACTORY,
        "target_url": TARGET,
        "username": "admin",
        "factory_password": "OldFixture1!",
        "target_password": "NewFixture2!",
        "management": DESIRED,
        "expected_mac": IDENTITY.mac_address,
        "expected_serial": IDENTITY.serial_number,
    }
    values.update(changes)
    return BootstrapConfig(**values)  # type: ignore[arg-type]


def test_model_rejects_invalid_url_ip_and_empty_mac() -> None:
    with pytest.raises(ValueError):
        make_config(factory_url="http://not-an-ip")
    with pytest.raises(ValueError):
        make_config(target_url="http://192.0.2.11")
    with pytest.raises(ValueError):
        make_config(expected_mac="00:00:00:00:00:00")


@pytest.mark.parametrize(
    ("field", "value"),
    [("username", None), ("factory_password", None), ("target_password", None),
     ("verify_tls", 1), ("timeout_s", True), ("poll_interval_s", 0)],
)
def test_model_rejects_invalid_types_and_values(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        make_config(**{field: value})


def test_model_repr_does_not_contain_secrets() -> None:
    config = make_config()
    rendered = repr(config)
    assert "OldFixture1!" not in rendered
    assert "NewFixture2!" not in rendered


def _discovery_session_factory(
    monkeypatch: pytest.MonkeyPatch,
    outcomes: dict[tuple[str, bool], tuple[DeviceInfo, ManagementNetworkState] | Exception],
) -> list[tuple[str, bool]]:
    calls: list[tuple[str, bool]] = []

    def factory(endpoint: str, credentials: JTComCredentials, **_: object) -> MagicMock:
        key = (endpoint, credentials.password == "NewFixture2!")
        calls.append(key)
        session = MagicMock()
        outcome = outcomes[key]
        if isinstance(outcome, Exception):
            session.login.side_effect = outcome
        else:
            device, network = outcome
            session.get.return_value = device
            session._network = network
        return session

    monkeypatch.setattr(discovery, "JTComSession", factory)
    monkeypatch.setattr(discovery, "parse_device_info", lambda page: page)
    monkeypatch.setattr(discovery, "read_management_network", lambda session: session._network)
    return calls


@pytest.mark.parametrize("state", [CURRENT, DESIRED.as_state()])
def test_discovery_probes_all_candidates_and_selects_deterministically(
    monkeypatch: pytest.MonkeyPatch, state: ManagementNetworkState,
) -> None:
    outcomes = {(endpoint, target_creds): (DEVICE, state)
                for endpoint in (TARGET, FACTORY) for target_creds in (True, False)}
    calls = _discovery_session_factory(monkeypatch, outcomes)
    result = discovery.discover(make_config())
    assert result.endpoint == TARGET
    assert calls == [(TARGET, True), (FACTORY, True), (TARGET, False), (FACTORY, False)]


@pytest.mark.parametrize(
    "mutator",
    [
        lambda outcomes: outcomes.__setitem__((TARGET, True), (DeviceInfo("02:00:00:00:00:02"), CURRENT)),
        lambda outcomes: outcomes.__setitem__((FACTORY, True), (DEVICE, DESIRED.as_state())),
        lambda outcomes: outcomes.__setitem__((FACTORY, True), JTComAuthError("rejected")),
    ],
)
def test_discovery_rejects_wrong_identity_changed_state_or_no_candidate(
    monkeypatch: pytest.MonkeyPatch, mutator: object,
) -> None:
    outcomes = {(endpoint, target_creds): (DEVICE, CURRENT)
                for endpoint in (TARGET, FACTORY) for target_creds in (True, False)}
    mutator(outcomes)  # type: ignore[operator]
    _discovery_session_factory(monkeypatch, outcomes)
    with pytest.raises(ValueError):
        discovery.discover(make_config())


def test_discovery_rejects_different_devices_and_both_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    outcomes = {(endpoint, target_creds): (DEVICE, CURRENT)
                for endpoint in (TARGET, FACTORY) for target_creds in (True, False)}
    outcomes[(FACTORY, True)] = (DeviceInfo("02:00:00:00:00:02"), CURRENT)
    _discovery_session_factory(monkeypatch, outcomes)
    with pytest.raises(ValueError, match="Different physical"):
        discovery.discover(make_config())

    outcomes = {(TARGET, True): (DEVICE, CURRENT), (FACTORY, True): (DEVICE, CURRENT),
                (TARGET, False): JTComAuthError("rejected"), (FACTORY, False): JTComAuthError("rejected")}
    _discovery_session_factory(monkeypatch, outcomes)
    assert discovery.discover(make_config()).target_credentials is True


def test_discovery_rejects_both_credentials_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    outcomes = {(endpoint, target_creds): (DEVICE, CURRENT)
                for endpoint in (TARGET, FACTORY) for target_creds in (True, False)}
    _discovery_session_factory(monkeypatch, outcomes)
    with pytest.raises(ValueError, match="Both credentials"):
        discovery.discover(make_config())


def _candidate(config: BootstrapConfig, *, target_credentials: bool = False,
               network: ManagementNetworkState = CURRENT) -> Candidate:
    return Candidate(config.factory_url, target_credentials, IDENTITY, network)


def test_orchestrator_check_mode_plans_two_operations_without_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config()
    monkeypatch.setattr(orchestrator, "discover", lambda _: _candidate(config))
    credential = MagicMock(changed=True, endpoint=FACTORY, identity=IDENTITY)
    network = MagicMock(changed=True, endpoint=TARGET, identity=IDENTITY)
    monkeypatch.setattr(orchestrator, "transition_credentials", MagicMock(return_value=credential))
    monkeypatch.setattr(orchestrator, "transition_management_network", MagicMock(return_value=network))
    save = MagicMock()
    monkeypatch.setattr(orchestrator, "save_config", save)
    result = bootstrap_switch(config, check_mode=True)
    assert result["operations"] == [{"key": "credentials:update"}, {"key": "management_network:update"}]
    orchestrator.transition_credentials.assert_not_called()  # type: ignore[attr-defined]
    orchestrator.transition_management_network.assert_not_called()  # type: ignore[attr-defined]
    save.assert_not_called()


@pytest.mark.parametrize(
    ("target_credentials", "network", "expected"),
    [(True, CURRENT, []), (False, DESIRED.as_state(), [{"key": "credentials:update"}]),
     (True, DESIRED.as_state(), [{"key": "management_network:update"}])],
)
def test_orchestrator_operation_matrix_and_noop(
    monkeypatch: pytest.MonkeyPatch, target_credentials: bool,
    network: ManagementNetworkState, expected: list[dict[str, str]],
) -> None:
    config = make_config()
    monkeypatch.setattr(orchestrator, "discover", lambda _: _candidate(config, target_credentials=target_credentials, network=network))
    result = bootstrap_switch(config, check_mode=True)
    assert result["operations"] == expected


def test_orchestrator_applies_in_order_saves_and_passes_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config()
    monkeypatch.setattr(orchestrator, "discover", lambda _: _candidate(config))
    events: list[str] = []
    monkeypatch.setattr(orchestrator, "transition_credentials", lambda *args, **kwargs: (events.append("credentials") or MagicMock(changed=True, endpoint=FACTORY, identity=IDENTITY)))
    network = MagicMock(changed=True, endpoint=TARGET, identity=IDENTITY)
    def transition(*args: object, **kwargs: object) -> NetworkTransitionResult:
        events.append("network")
        assert kwargs["expected_identity"] is IDENTITY
        return network
    monkeypatch.setattr(orchestrator, "transition_management_network", transition)
    session = MagicMock()
    monkeypatch.setattr(orchestrator, "JTComSession", MagicMock(return_value=session))
    monkeypatch.setattr(orchestrator, "parse_device_info", lambda _: DEVICE)
    monkeypatch.setattr(orchestrator, "read_management_network", lambda _: DESIRED.as_state())
    monkeypatch.setattr(orchestrator, "save_config", lambda _: events.append("save"))
    result = bootstrap_switch(config)
    assert events == ["credentials", "network", "save"]
    assert result["persistence"] == "saved"


def test_orchestrator_failure_reports_partial_context_and_no_config_write(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config()
    monkeypatch.setattr(orchestrator, "discover", lambda _: _candidate(config))
    monkeypatch.setattr(orchestrator, "transition_credentials", lambda *args, **kwargs: MagicMock(changed=True, endpoint=FACTORY, identity=IDENTITY))
    monkeypatch.setattr(orchestrator, "transition_management_network", MagicMock(side_effect=RuntimeError("private failure")))
    save = MagicMock()
    monkeypatch.setattr(orchestrator, "save_config", save)
    with pytest.raises(orchestrator.JTComBootstrapError) as caught:
        bootstrap_switch(config)
    result = caught.value.as_result()
    assert result["stage"] == "management_network"
    assert result["write_attempted"] is True
    assert result["completed_operations"] == [{"key": "credentials:update"}]
    assert result["failed_operation"] == {"key": "management_network:update"}
    save.assert_not_called()
