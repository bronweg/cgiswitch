"""Bootstrap state matrix, identity failures, and persistence barriers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from cgiswitch import BootstrapConfig, ManagementNetworkConfig, bootstrap_switch
from cgiswitch.bootstrap import discovery, orchestrator
from cgiswitch.bootstrap.credentials import CredentialTransitionResult
from cgiswitch.bootstrap.discovery import Candidate
from cgiswitch.bootstrap.identity import DeviceIdentity
from cgiswitch.bootstrap.network import NetworkTransitionResult
from cgiswitch.client.errors import JTComAuthError, JTComRequestError
from cgiswitch.client.session import JTComCredentials
from cgiswitch.model.device import DeviceInfo
from cgiswitch.model.management import ManagementNetworkState

FACTORY = "http://192.0.2.1"
TARGET = "http://192.0.2.10"
IDENTITY = DeviceIdentity("02:00:00:00:00:01", "fixture-serial")
DEVICE = DeviceInfo(IDENTITY.mac_address, serial_number=IDENTITY.serial_number)
DESIRED = ManagementNetworkConfig("192.0.2.10", 24, "192.0.2.1")
CURRENT = ManagementNetworkConfig("192.0.2.1", 24, "192.0.2.1").as_state()
ORDER = [(TARGET, True), (FACTORY, True), (TARGET, False), (FACTORY, False)]
CREDENTIAL_OP = {"key": "credentials:update"}
NETWORK_OP = {"key": "management_network:update"}
STATE_MATRIX = [
    (FACTORY, False, CURRENT, [CREDENTIAL_OP, NETWORK_OP]),
    (FACTORY, True, CURRENT, [NETWORK_OP]),
    (TARGET, False, DESIRED.as_state(), [CREDENTIAL_OP]),
    (TARGET, True, DESIRED.as_state(), []),
]


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


@pytest.mark.parametrize(
    "changes",
    [
        {"factory_url": "http://not-an-ip"},
        {"target_url": "http://192.0.2.11"},
        {"expected_mac": "00:00:00:00:00:00"},
        {"username": None},
        {"factory_password": None},
        {"target_password": None},
        {"verify_tls": 1},
        {"timeout_s": True},
        {"poll_interval_s": 0},
        {"management": None},
        {"expected_mac": None, "expected_serial": None},
    ],
)
def test_model_rejects_invalid_inputs(changes: dict) -> None:
    with pytest.raises(ValueError):
        make_config(**changes)


def test_management_is_required_and_publicly_importable() -> None:
    assert ManagementNetworkConfig is type(DESIRED)
    with pytest.raises(TypeError, match="management"):
        BootstrapConfig(FACTORY, TARGET, "admin", "OldFixture1!", "NewFixture2!")


def test_model_repr_does_not_contain_secrets() -> None:
    assert "OldFixture1!" not in repr(make_config())
    assert "NewFixture2!" not in repr(make_config())


def rejected_candidates() -> dict:
    return {key: JTComAuthError("rejected") for key in ORDER}


def setup_discovery(monkeypatch: pytest.MonkeyPatch, outcomes: dict) -> list:
    calls = []

    def factory(endpoint: str, credentials: JTComCredentials, **_: object) -> MagicMock:
        key = (endpoint, credentials.password == "NewFixture2!")
        calls.append(key)
        session = MagicMock()
        outcome = outcomes[key]
        if isinstance(outcome, Exception):
            session.login.side_effect = outcome
        else:
            session.get.return_value, session.network = outcome
        return session

    monkeypatch.setattr(discovery, "JTComSession", factory)
    monkeypatch.setattr(discovery, "parse_device_info", lambda page: page)
    monkeypatch.setattr(discovery, "read_management_network", lambda session: session.network)
    return calls


@pytest.mark.parametrize("endpoint,target_credentials,state,operations", STATE_MATRIX)
def test_discovery_four_reachable_states_probes_all_candidates(
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
    target_credentials: bool,
    state: ManagementNetworkState,
    operations: list,
) -> None:
    outcomes = rejected_candidates()
    for address, credential in ORDER:
        if address != endpoint:
            outcomes[(address, credential)] = JTComRequestError(address, TimeoutError())
    outcomes[(endpoint, target_credentials)] = (DEVICE, state)
    calls = setup_discovery(monkeypatch, outcomes)
    result = discovery.discover(make_config())
    assert result == Candidate(endpoint, target_credentials, IDENTITY, state)
    assert calls == ORDER


def test_discovery_same_device_aliases_prefer_target(monkeypatch: pytest.MonkeyPatch) -> None:
    outcomes = rejected_candidates()
    outcomes[(TARGET, True)] = outcomes[(FACTORY, True)] = (DEVICE, DESIRED.as_state())
    setup_discovery(monkeypatch, outcomes)
    assert discovery.discover(make_config()).endpoint == TARGET


@pytest.mark.parametrize("endpoint", [TARGET, FACTORY])
def test_wrong_expected_identity_fails_before_any_mutation(
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
) -> None:
    outcomes = rejected_candidates()
    outcomes[(endpoint, True)] = (DeviceInfo("02:00:00:00:00:02"), CURRENT)
    setup_discovery(monkeypatch, outcomes)
    credential = MagicMock()
    network = MagicMock()
    save = MagicMock()
    monkeypatch.setattr(orchestrator, "transition_credentials", credential)
    monkeypatch.setattr(orchestrator, "transition_management_network", network)
    monkeypatch.setattr(orchestrator, "save_config", save)
    with pytest.raises(orchestrator.JTComBootstrapError) as caught:
        bootstrap_switch(make_config())
    assert not caught.value.as_result()["changed"]
    credential.assert_not_called()
    network.assert_not_called()
    save.assert_not_called()


def test_different_physical_devices_even_if_serial_matches_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcomes = rejected_candidates()
    outcomes[(TARGET, True)] = (DEVICE, CURRENT)
    outcomes[(FACTORY, True)] = (
        DeviceInfo("02:00:00:00:00:02", serial_number=IDENTITY.serial_number),
        CURRENT,
    )
    setup_discovery(monkeypatch, outcomes)
    with pytest.raises(ValueError, match="Different physical"):
        discovery.discover(make_config(expected_mac=None))


@pytest.mark.parametrize("fault", ["no_candidate", "both_credentials", "changing_state"])
def test_distinct_ambiguous_discovery_failures(
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    outcomes = rejected_candidates()
    message = "No candidate"
    if fault == "both_credentials":
        outcomes[(TARGET, True)] = outcomes[(TARGET, False)] = (DEVICE, DESIRED.as_state())
        message = "Both credentials"
    elif fault == "changing_state":
        outcomes[(TARGET, True)] = (DEVICE, DESIRED.as_state())
        outcomes[(FACTORY, True)] = (DEVICE, CURRENT)
        message = "inconsistent"
    setup_discovery(monkeypatch, outcomes)
    with pytest.raises(ValueError, match=message):
        discovery.discover(make_config())


def setup_orchestration(monkeypatch: pytest.MonkeyPatch, candidate: Candidate) -> dict:
    monkeypatch.setattr(orchestrator, "discover", lambda _: candidate)
    events = []
    credential = MagicMock(
        side_effect=lambda *args, **kwargs: (
            events.append("credentials")
            or CredentialTransitionResult(True, candidate.endpoint, IDENTITY)
        )
    )
    network = MagicMock(
        side_effect=lambda *args, **kwargs: (
            events.append("network") or NetworkTransitionResult(True, TARGET, IDENTITY)
        )
    )
    session = MagicMock()
    factory = MagicMock(return_value=session)
    read_identity = MagicMock(side_effect=lambda _: events.append("identity") or DEVICE)
    read_network = MagicMock(side_effect=lambda _: events.append("state") or DESIRED.as_state())
    save = MagicMock(side_effect=lambda _: events.append("save"))
    for name, value in {
        "transition_credentials": credential,
        "transition_management_network": network,
        "JTComSession": factory,
        "parse_device_info": read_identity,
        "read_management_network": read_network,
        "save_config": save,
    }.items():
        monkeypatch.setattr(orchestrator, name, value)
    return dict(
        credential=credential,
        network=network,
        factory=factory,
        session=session,
        read_identity=read_identity,
        read_network=read_network,
        save=save,
        events=events,
    )


@pytest.mark.parametrize("endpoint,target_credentials,state,operations", STATE_MATRIX)
@pytest.mark.parametrize("check_mode", [False, True])
def test_operation_matrix_and_persistence_barrier(
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
    target_credentials: bool,
    state: ManagementNetworkState,
    operations: list,
    check_mode: bool,
) -> None:
    mocks = setup_orchestration(
        monkeypatch, Candidate(endpoint, target_credentials, IDENTITY, state)
    )
    result = bootstrap_switch(make_config(), check_mode=check_mode)
    assert result["operations"] == operations
    assert result["changed"] == bool(operations)
    if check_mode:
        assert result["persistence"] == "save_required"
        assert result["completed_operations"] == []
        for key in ("credential", "network", "factory", "save"):
            mocks[key].assert_not_called()
    else:
        assert mocks["credential"].call_count == (CREDENTIAL_OP in operations)
        assert mocks["network"].call_count == (NETWORK_OP in operations)
        if NETWORK_OP in operations:
            assert mocks["network"].call_args.kwargs["expected_identity"] == IDENTITY
        expected_events = []
        if CREDENTIAL_OP in operations:
            expected_events.append("credentials")
        if NETWORK_OP in operations:
            expected_events.append("network")
        assert mocks["events"] == expected_events + ["identity", "state", "save"]
        mocks["save"].assert_called_once_with(mocks["session"])
        mocks["session"]._discard.assert_called_once()
        assert result["persistence"] == "saved"
        assert result["completed_operations"] == operations


@pytest.mark.parametrize("fault", ["identity", "state", "save"])
def test_unchanged_rerun_barrier_failure_is_not_a_logical_change(
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    mocks = setup_orchestration(monkeypatch, Candidate(TARGET, True, IDENTITY, DESIRED.as_state()))
    if fault == "identity":
        mocks["read_identity"].side_effect = None
        mocks["read_identity"].return_value = DeviceInfo("02:00:00:00:00:02")
    elif fault == "state":
        mocks["read_network"].side_effect = None
        mocks["read_network"].return_value = CURRENT
    else:
        mocks["save"].side_effect = JTComRequestError(TARGET, TimeoutError("lost save response"))
    with pytest.raises(orchestrator.JTComBootstrapError) as caught:
        bootstrap_switch(make_config())
    result = caught.value.as_result()
    assert result["changed"] is False
    assert result["write_attempted"] is (fault == "save")
    assert result["failed_operation"] == (
        {"key": "configuration:save"} if fault == "save" else None
    )
    assert result["stage"] == ("persistence" if fault == "save" else "persistence_preflight")
    assert result["completed_operations"] == []
    assert mocks["save"].call_count == (fault == "save")
    mocks["credential"].assert_not_called()
    mocks["network"].assert_not_called()


def test_partial_failure_reports_completed_credential_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocks = setup_orchestration(monkeypatch, Candidate(FACTORY, False, IDENTITY, CURRENT))
    mocks["network"].side_effect = RuntimeError("private failure")
    with pytest.raises(orchestrator.JTComBootstrapError) as caught:
        bootstrap_switch(make_config())
    result = caught.value.as_result()
    assert result["stage"] == "management_network"
    assert result["changed"] is True and result["write_attempted"] is True
    assert result["completed_operations"] == [CREDENTIAL_OP]
    assert result["failed_operation"] == NETWORK_OP
    mocks["save"].assert_not_called()
