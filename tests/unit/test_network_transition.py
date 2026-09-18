"""Disruptive transitions reconcile observations without repeating their write."""

import json
from unittest.mock import MagicMock

import pytest

from cgiswitch.bootstrap import network
from cgiswitch.bootstrap.errors import JTComTransitionError
from cgiswitch.bootstrap.identity import DeviceIdentity
from cgiswitch.client.errors import JTComAuthError, JTComRequestError
from cgiswitch.client.session import JTComCredentials
from cgiswitch.model.device import DeviceInfo
from cgiswitch.model.management import ManagementNetworkConfig

OLD = "http://192.0.2.1"
TARGET = "http://192.0.2.10"
DESIRED = ManagementNetworkConfig("192.0.2.10", 24, "192.0.2.254")
BEFORE = ManagementNetworkConfig("192.0.2.1", 24, "192.0.2.254").as_state()
IDENTITY = DeviceInfo("02:00:00:00:00:01", serial_number="fixture-serial")
EXPECTED_IDENTITY = DeviceIdentity.from_device(IDENTITY)
CREDENTIALS = JTComCredentials("fixture-user", "fixture-private-value")


def unavailable() -> JTComRequestError:
    return JTComRequestError(TARGET, TimeoutError("unreachable"))


@pytest.fixture
def setup(monkeypatch: pytest.MonkeyPatch) -> dict:
    current, preflight, target = MagicMock(), MagicMock(), MagicMock()
    preflight.login.side_effect = unavailable()
    factory = MagicMock(side_effect=[current, preflight, target])
    monkeypatch.setattr(network, "JTComSession", factory)
    identity = MagicMock(return_value=IDENTITY)
    monkeypatch.setattr(network, "parse_device_info", identity)
    reads = MagicMock(side_effect=[BEFORE, DESIRED.as_state()])
    monkeypatch.setattr(network, "read_management_network", reads)
    write = MagicMock()
    monkeypatch.setattr(network, "set_management_network_once", write)
    return dict(
        current=current,
        preflight=preflight,
        target=target,
        factory=factory,
        identity=identity,
        reads=reads,
        write=write,
    )


def test_success_and_response_loss_reconcile_once(setup: dict) -> None:
    result = network.transition_management_network(
        OLD, TARGET, CREDENTIALS, DESIRED, expected_identity=EXPECTED_IDENTITY
    )
    assert result.changed and result.endpoint == TARGET
    setup["write"].assert_called_once_with(setup["current"], DESIRED)
    setup["current"]._discard.assert_called_once()
    setup["target"]._discard.assert_called_once()


def test_ambiguous_write_success(setup: dict) -> None:
    setup["write"].side_effect = unavailable()
    result = network.transition_management_network(
        OLD, TARGET, CREDENTIALS, DESIRED, expected_identity=EXPECTED_IDENTITY
    )
    assert result.changed
    assert setup["write"].call_count == 1


def test_already_desired_has_no_post(setup: dict) -> None:
    setup["reads"].side_effect = [DESIRED.as_state()]
    result = network.transition_management_network(
        TARGET, TARGET, CREDENTIALS, DESIRED, expected_identity=EXPECTED_IDENTITY
    )
    assert not result.changed
    setup["write"].assert_not_called()


@pytest.mark.parametrize(
    "field,value", [("mac_address", "02:00:00:00:00:02"), ("serial_number", "other-serial")]
)
def test_target_identity_mismatch_fails(setup: dict, field: str, value: str) -> None:
    other = DeviceInfo(IDENTITY.mac_address, serial_number=IDENTITY.serial_number)
    setattr(other, field, value)
    setup["identity"].side_effect = [IDENTITY, IDENTITY, other]
    with pytest.raises(JTComTransitionError) as caught:
        network.transition_management_network(
            OLD, TARGET, CREDENTIALS, DESIRED, expected_identity=EXPECTED_IDENTITY
        )
    assert caught.value.stage == "verify_identity"
    assert caught.value.write_attempted
    assert setup["write"].call_count == 1


def test_preexisting_foreign_target_blocks_write(setup: dict) -> None:
    setup["preflight"].login.side_effect = None
    setup["identity"].side_effect = [IDENTITY, DeviceInfo("02:00:00:00:00:02")]
    with pytest.raises(JTComTransitionError) as caught:
        network.transition_management_network(
            OLD, TARGET, CREDENTIALS, DESIRED, expected_identity=EXPECTED_IDENTITY
        )
    assert not caught.value.write_attempted
    setup["write"].assert_not_called()


def test_target_wrong_network_fails_verification(setup: dict) -> None:
    setup["reads"].side_effect = [BEFORE, BEFORE]
    with pytest.raises(JTComTransitionError) as caught:
        network.transition_management_network(
            OLD, TARGET, CREDENTIALS, DESIRED, expected_identity=EXPECTED_IDENTITY
        )
    assert caught.value.stage == "verify_network"
    assert caught.value.target_reached
    assert not caught.value.verification_completed


def test_auth_failure_precedes_write_and_never_echoes_secret(setup: dict) -> None:
    setup["current"].login.side_effect = JTComAuthError(CREDENTIALS.password)
    with pytest.raises(JTComTransitionError) as caught:
        network.transition_management_network(
            OLD, TARGET, CREDENTIALS, DESIRED, expected_identity=EXPECTED_IDENTITY
        )
    assert not caught.value.write_attempted
    assert CREDENTIALS.password not in str(caught.value)
    assert CREDENTIALS.password not in json.dumps(caught.value.as_result())
    setup["write"].assert_not_called()


def test_target_deadline_after_ambiguous_write_no_retry(
    setup: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup["write"].side_effect = unavailable()
    setup["target"].login.side_effect = unavailable()
    monkeypatch.setattr(network.time, "monotonic", MagicMock(side_effect=[0, 0, 2, 2]))
    monkeypatch.setattr(network.time, "sleep", MagicMock())
    with pytest.raises(JTComTransitionError) as caught:
        network.transition_management_network(
            OLD,
            TARGET,
            CREDENTIALS,
            DESIRED,
            expected_identity=EXPECTED_IDENTITY,
            transition_timeout_s=1,
        )
    assert caught.value.write_attempted and not caught.value.target_reached
    assert setup["write"].call_count == 1


@pytest.mark.parametrize(
    "url",
    [
        "192.0.2.10",
        "http://secret@192.0.2.10",
        "http://192.0.2.10/path",
        "http://192.0.2.11",
        "http://192.0.2.10?secret=value",
    ],
)
def test_bad_target_rejected_before_connect(setup: dict, url: str) -> None:
    with pytest.raises(ValueError):
        network.transition_management_network(
            OLD, url, CREDENTIALS, DESIRED, expected_identity=EXPECTED_IDENTITY
        )
    setup["factory"].assert_not_called()


def test_discard_does_not_contact_device() -> None:
    from cgiswitch.client.session import JTComSession

    session = JTComSession(OLD, CREDENTIALS)
    session._http = MagicMock()
    session._logged_in = True
    session._discard()
    assert not session.logged_in
    session._http.close.assert_called_once()
    session._http.post_form.assert_not_called()


@pytest.mark.parametrize("stage", ["initial", "before_write"])
@pytest.mark.parametrize(
    "field,value", [("mac_address", "02:00:00:00:00:02"), ("serial_number", "replacement-device")]
)
def test_external_identity_mismatch_never_writes_ip(
    setup: dict,
    stage: str,
    field: str,
    value: str,
) -> None:
    replacement = DeviceInfo(IDENTITY.mac_address, serial_number=IDENTITY.serial_number)
    setattr(replacement, field, value)
    setup["identity"].side_effect = [replacement] if stage == "initial" else [IDENTITY, replacement]
    with pytest.raises(JTComTransitionError) as caught:
        network.transition_management_network(
            OLD,
            TARGET,
            CREDENTIALS,
            DESIRED,
            expected_identity=EXPECTED_IDENTITY,
        )
    assert not caught.value.write_attempted
    assert caught.value.stage == (
        "read_identity" if stage == "initial" else "verify_source_identity"
    )
    setup["write"].assert_not_called()


def test_external_identity_is_mandatory_before_connection(setup: dict) -> None:
    with pytest.raises(TypeError, match="expected_identity"):
        network.transition_management_network(OLD, TARGET, CREDENTIALS, DESIRED)
    with pytest.raises(ValueError, match="expected identity"):
        network.transition_management_network(
            OLD,
            TARGET,
            CREDENTIALS,
            DESIRED,
            expected_identity=None,
        )
    setup["factory"].assert_not_called()
    setup["write"].assert_not_called()


@pytest.mark.parametrize(
    "fault,reached,verified_endpoint",
    [
        ("identity", True, OLD),
        ("network", True, TARGET),
        ("unreachable", False, OLD),
    ],
)
def test_bootstrap_preserves_network_transition_observations(
    setup: dict,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
    reached: bool,
    verified_endpoint: str,
) -> None:
    from cgiswitch.bootstrap import orchestrator
    from cgiswitch.bootstrap.discovery import Candidate
    from cgiswitch.bootstrap.model import BootstrapConfig

    config = BootstrapConfig(
        factory_url=OLD, target_url=TARGET, username="admin",
        factory_password="fixtureOld1", target_password="fixtureNew2",
        management=DESIRED, expected_mac=IDENTITY.mac_address,
        transition_timeout_s=1,
    )
    monkeypatch.setattr(
        orchestrator, "discover",
        lambda _: Candidate(OLD, True, EXPECTED_IDENTITY, BEFORE),
    )
    save = MagicMock()
    monkeypatch.setattr(orchestrator, "save_config", save)
    if fault == "identity":
        setup["identity"].side_effect = [
            IDENTITY, IDENTITY, DeviceInfo("02:00:00:00:00:02"),
        ]
    elif fault == "network":
        setup["reads"].side_effect = [BEFORE, BEFORE]
    else:
        setup["target"].login.side_effect = unavailable()
        monkeypatch.setattr(network.time, "monotonic", MagicMock(side_effect=[0, 0, 2, 2]))
        monkeypatch.setattr(network.time, "sleep", MagicMock())
    with pytest.raises(orchestrator.JTComBootstrapError) as caught:
        orchestrator.bootstrap_switch(config)
    result = caught.value.as_result()
    assert result["target_reached"] is reached
    assert result["last_verified_endpoint"] == verified_endpoint
    assert result["stage"] == "management_network"
    assert result["failed_operation"] == {"key": "management_network:update"}
    assert result["changed"] and result["write_attempted"]
    assert result["completed_operations"] == []
    setup["write"].assert_called_once()
    save.assert_not_called()
