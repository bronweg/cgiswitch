"""Unit tests for port POST payload formation in cgiswitch.client.port_ops.

Verifies that the correct form fields are built and sent to the switch,
without requiring a real device.  Uses the ``responses`` library to
intercept HTTP calls.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
import responses as responses_lib

from cgiswitch.client.port_ops import (
    SPEED_TOKEN_TO_CODE,
    _build_port_payload,
    apply_port_changes,
)
from cgiswitch.model.port import PortChangeSet, PortConfig, PortSettings

_BASE = "http://192.168.1.1"
_OK = json.dumps({"code": 0, "data": ""})
_ERR = json.dumps({"code": 1, "data": "param error"})


def _mock_session(base_url: str = _BASE) -> MagicMock:
    from cgiswitch.client.session import JTComCredentials, JTComSession
    session = JTComSession(
        base_url=base_url,
        credentials=JTComCredentials("admin", "admin"),
    )
    session._logged_in = True  # skip login
    return session


def make_settings(
    port_id: int,
    admin_up: bool = True,
    speed_duplex: str = "Auto",
    flow_control: bool = True,
) -> PortSettings:
    return PortSettings(
        port_id=port_id,
        name=f"Port {port_id}",
        admin_up=admin_up,
        speed_duplex=speed_duplex,
        flow_control=flow_control,
    )


# ---------------------------------------------------------------------------
# SPEED_TOKEN_TO_CODE completeness
# ---------------------------------------------------------------------------

class TestSpeedTokenToCode:
    def test_all_tokens_present(self) -> None:
        expected = {"Auto", "10M/Half", "10M/Full", "100M/Half",
                    "100M/Full", "1000M/Full", "2500M/Full", "10G/Full"}
        assert set(SPEED_TOKEN_TO_CODE.keys()) == expected

    def test_auto_maps_to_zero(self) -> None:
        assert SPEED_TOKEN_TO_CODE["Auto"] == "0"

    def test_10g_maps_to_seven(self) -> None:
        assert SPEED_TOKEN_TO_CODE["10G/Full"] == "7"

    def test_codes_are_sequential(self) -> None:
        codes = sorted(int(v) for v in SPEED_TOKEN_TO_CODE.values())
        assert codes == list(range(8))


# ---------------------------------------------------------------------------
# _build_port_payload
# ---------------------------------------------------------------------------

class TestBuildPortPayload:
    def test_disable_port_1(self) -> None:
        cfg = PortConfig(port_id=1, admin_up=False)
        current = make_settings(1, admin_up=True, speed_duplex="Auto", flow_control=True)
        payload = _build_port_payload(cfg, current)
        assert payload["portid"] == "0"      # 1-based → 0-based
        assert payload["state"] == "0"       # disabled
        assert payload["speed_duplex"] == "0"  # Auto
        assert payload["flow"] == "1"        # On (from current)

    def test_enable_port_2(self) -> None:
        cfg = PortConfig(port_id=2, admin_up=True)
        current = make_settings(2, admin_up=False, speed_duplex="1000M/Full", flow_control=False)
        payload = _build_port_payload(cfg, current)
        assert payload["portid"] == "1"      # 2 - 1 = 1
        assert payload["state"] == "1"       # enabled
        assert payload["speed_duplex"] == "5"  # 1000M/Full
        assert payload["flow"] == "0"        # Off (from current)

    def test_change_speed_duplex_only(self) -> None:
        cfg = PortConfig(port_id=3, speed_duplex="100M/Full")
        current = make_settings(3, admin_up=True, speed_duplex="Auto", flow_control=True)
        payload = _build_port_payload(cfg, current)
        assert payload["state"] == "1"         # unchanged from current
        assert payload["speed_duplex"] == "4"  # 100M/Full code
        assert payload["flow"] == "1"

    def test_change_flow_control_only(self) -> None:
        cfg = PortConfig(port_id=4, flow_control=False)
        current = make_settings(4, admin_up=True, speed_duplex="Auto", flow_control=True)
        payload = _build_port_payload(cfg, current)
        assert payload["state"] == "1"
        assert payload["speed_duplex"] == "0"
        assert payload["flow"] == "0"

    def test_port_6_0based_index_is_5(self) -> None:
        cfg = PortConfig(port_id=6, admin_up=True)
        current = make_settings(6, speed_duplex="10G/Full")
        payload = _build_port_payload(cfg, current)
        assert payload["portid"] == "5"        # 6 - 1 = 5
        assert payload["speed_duplex"] == "7"  # 10G/Full

    def test_unknown_speed_token_raises(self) -> None:
        # admin_up must be non-None so we reach the speed_duplex resolution
        cfg = PortConfig(port_id=1, admin_up=True, speed_duplex="BadToken")
        with pytest.raises(ValueError, match="unknown speed/duplex token"):
            _build_port_payload(cfg, None)

    def test_all_none_with_no_current_raises(self) -> None:
        cfg = PortConfig(port_id=1)  # all None
        with pytest.raises(ValueError, match="admin_up is None"):
            _build_port_payload(cfg, None)

    def test_all_fields_from_desired_when_current_is_none(self) -> None:
        cfg = PortConfig(port_id=1, admin_up=True, speed_duplex="Auto", flow_control=False)
        payload = _build_port_payload(cfg, None)
        assert payload["portid"] == "0"
        assert payload["state"] == "1"
        assert payload["speed_duplex"] == "0"
        assert payload["flow"] == "0"


# ---------------------------------------------------------------------------
# apply_port_changes integration (HTTP mocked)
# ---------------------------------------------------------------------------

class TestApplyPortChanges:
    @responses_lib.activate
    def test_no_call_when_changeset_empty(self) -> None:
        session = _mock_session()
        apply_port_changes(session, [], PortChangeSet(update=[]))
        assert len(responses_lib.calls) == 0

    @responses_lib.activate
    def test_single_port_posts_correct_payload(self) -> None:
        responses_lib.add(
            responses_lib.POST,
            f"{_BASE}/port.cgi",
            body=_OK,
            content_type="application/json",
        )
        session = _mock_session()
        current = [make_settings(1, admin_up=True, speed_duplex="Auto", flow_control=True)]
        change_set = PortChangeSet(update=[PortConfig(port_id=1, admin_up=False)])
        apply_port_changes(session, current, change_set)

        assert len(responses_lib.calls) == 1
        body = responses_lib.calls[0].request.body or ""
        assert "portid=0" in body
        assert "state=0" in body
        assert "speed_duplex=0" in body
        assert "flow=1" in body
        assert "page=inside" in body

    @responses_lib.activate
    def test_multiple_ports_issue_separate_posts(self) -> None:
        for _ in range(2):
            responses_lib.add(
                responses_lib.POST,
                f"{_BASE}/port.cgi",
                body=_OK,
                content_type="application/json",
            )
        session = _mock_session()
        current = [
            make_settings(1, admin_up=True),
            make_settings(2, admin_up=True),
        ]
        change_set = PortChangeSet(update=[
            PortConfig(port_id=1, admin_up=False),
            PortConfig(port_id=2, admin_up=False),
        ])
        apply_port_changes(session, current, change_set)
        assert len(responses_lib.calls) == 2

    @responses_lib.activate
    def test_switch_error_raises(self) -> None:
        responses_lib.add(
            responses_lib.POST,
            f"{_BASE}/port.cgi",
            body=_ERR,
            content_type="application/json",
        )
        from cgiswitch.client.errors import JTComSwitchError
        session = _mock_session()
        current = [make_settings(1)]
        change_set = PortChangeSet(update=[PortConfig(port_id=1, admin_up=False)])
        with pytest.raises(JTComSwitchError):
            apply_port_changes(session, current, change_set)


@pytest.mark.parametrize("field", ["admin_up", "flow_control", "speed_duplex"])
def test_unknown_preserved_fields_never_become_defaults(field: str) -> None:
    current = make_settings(3)
    setattr(current, field, None)
    desired = PortConfig(3, speed_duplex="100M/Full")
    if field == "speed_duplex":
        desired = PortConfig(3, admin_up=False)
    with pytest.raises(ValueError, match=field):
        _build_port_payload(desired, current)


def test_explicit_flow_resolves_unknown_without_changing_other_fields() -> None:
    current = PortSettings(3, "Port 3", False, "1000M/Full", None)
    assert _build_port_payload(PortConfig(3, flow_control=True), current) == {
        "portid": "2", "state": "0", "speed_duplex": "5", "flow": "1",
    }


def test_entire_port_batch_is_compiled_before_any_post() -> None:
    session = MagicMock()
    current = [make_settings(1), PortSettings(2, "Port 2", True, "Auto", None)]
    changes = PortChangeSet(update=[PortConfig(1, admin_up=False),
                                    PortConfig(2, speed_duplex="100M/Full")])
    with pytest.raises(ValueError, match="flow_control"):
        apply_port_changes(session, current, changes)
    session.post.assert_not_called()
