"""Regression tests for management network read and one-shot write operations."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qsl

import pytest
import requests
import responses

from cgiswitch.client.errors import JTComAuthError, JTComRequestError
from cgiswitch.client.ip_ops import read_management_network, set_management_network_once
from cgiswitch.client.session import JTComCredentials, JTComSession
from cgiswitch.model.management import ManagementNetworkConfig, ManagementNetworkState
from cgiswitch.vendor.jtcom.endpoints import LOGIN, MANAGEMENT_NETWORK

BASE_URL = "http://192.0.2.1"
FIXTURE = Path(__file__).parents[1] / "fixtures" / "management_ip.html"


def _session() -> JTComSession:
    session = JTComSession(BASE_URL, JTComCredentials("fixture-user", "secret"))
    session._logged_in = True
    return session


def _login() -> None:
    responses.add(
        responses.POST, f"{BASE_URL}{LOGIN}",
        json={"code": 0, "data": ""}, content_type="application/json",
    )


def test_read_management_network_uses_real_session() -> None:
    with responses.RequestsMock() as mock:
        mock.add(responses.GET, f"{BASE_URL}{MANAGEMENT_NETWORK}", body=FIXTURE.read_text())
        state = read_management_network(_session())

    assert state == ManagementNetworkState(False, "192.0.2.10", "255.255.255.0", "192.0.2.254")


def test_set_management_network_success_has_exact_form_fields() -> None:
    with responses.RequestsMock() as mock:
        mock.add(
            responses.POST, f"{BASE_URL}{MANAGEMENT_NETWORK}",
            json={"code": 0, "data": ""}, content_type="application/json",
        )
        set_management_network_once(
            _session(), ManagementNetworkConfig("192.0.2.10", 24, "192.0.2.1")
        )

        request = mock.calls[0].request
    assert dict(parse_qsl(request.body)) == {
        "page": "inside", "dhcp_state": "0", "ip": "192.0.2.10",
        "netmask": "255.255.255.0", "gateway": "192.0.2.1", "cmd": "ip",
    }


@pytest.mark.parametrize("response", [
    {"status": 401, "body": ""},
    {"status": 200, "body": '{"code":11,"data":""}'},
])
def test_set_management_network_auth_failure_is_never_retried(response: dict[str, object]) -> None:
    with responses.RequestsMock() as mock:
        mock.add(
            responses.POST, f"{BASE_URL}{MANAGEMENT_NETWORK}",
            status=int(response["status"]), body=str(response["body"]),
            content_type="application/json",
        )
        with pytest.raises(JTComAuthError):
            set_management_network_once(
                _session(), ManagementNetworkConfig("192.0.2.10", 24, "192.0.2.1")
            )

        assert len(mock.calls) == 1


def test_set_management_network_transport_timeout_is_never_retried() -> None:
    with responses.RequestsMock() as mock:
        mock.add(
            responses.POST, f"{BASE_URL}{MANAGEMENT_NETWORK}",
            body=requests.exceptions.Timeout("timed out"),
        )
        with pytest.raises(JTComRequestError):
            set_management_network_once(
                _session(), ManagementNetworkConfig("192.0.2.10", 24, "192.0.2.1")
            )

        assert len(mock.calls) == 1
