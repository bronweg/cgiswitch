"""Unit tests for management form payload contracts."""

from __future__ import annotations

import pytest

from cgiswitch.client.management_contracts import (
    build_management_network_payload,
    build_system_payload,
    build_user_account_payload,
)


def test_management_network_payload_matches_ip_form() -> None:
    assert build_management_network_payload(
        "192.0.2.10", "255.255.255.0", "192.0.2.1",
    ) == {
        "dhcp_state": "0", "ip": "192.0.2.10", "netmask": "255.255.255.0",
        "gateway": "192.0.2.1", "cmd": "ip", "page": "inside",
    }


@pytest.mark.parametrize("value", ["192.0.2.999", "192.0.2", "192.0.2.1.1"])
def test_management_network_rejects_invalid_ipv4(value: str) -> None:
    with pytest.raises(ValueError):
        build_management_network_payload(value, "255.255.255.0", "192.0.2.1")


def test_management_network_rejects_noncontiguous_netmask() -> None:
    with pytest.raises(ValueError, match="contiguous"):
        build_management_network_payload("192.0.2.10", "255.0.255.0", "192.0.2.1")


def test_user_account_payload_repeats_password() -> None:
    payload = build_user_account_payload("admin", "Synthet1c!")
    assert payload == {
        "mname": "admin", "mpass": "Synthet1c!", "mpass2": "Synthet1c!", "page": "inside",
    }


@pytest.mark.parametrize("username", ["adm", "bad-name", "a" * 17])
def test_user_account_rejects_invalid_username(username: str) -> None:
    with pytest.raises(ValueError):
        build_user_account_payload(username, "Synthet1c!")


@pytest.mark.parametrize("password", ["short", "a" * 17, "bad space"])
def test_user_account_rejects_invalid_password_without_echoing_it(password: str) -> None:
    with pytest.raises(ValueError) as caught:
        build_user_account_payload("admin", password)
    assert password not in str(caught.value)


@pytest.mark.parametrize("command", ["saveconfig", "reboot"])
def test_system_payload_allows_supported_commands(command: str) -> None:
    assert build_system_payload(command) == {"cmd": command, "page": "inside"}


@pytest.mark.parametrize("command", ["restore", "logout", "anything"])
def test_system_payload_rejects_unsupported_commands(command: str) -> None:
    with pytest.raises(ValueError):
        build_system_payload(command)


def test_payload_fields_match_captured_named_controls() -> None:
    from pathlib import Path

    from bs4 import BeautifulSoup

    fixtures = Path(__file__).parents[1] / 'fixtures'
    cases = [
        ('management_ip.html', build_management_network_payload(
            '192.0.2.10', '255.255.255.0', '192.0.2.254',
        )),
        ('user_account.html', build_user_account_payload('admin', 'Synthet1c!')),
    ]
    for filename, payload in cases:
        soup = BeautifulSoup((fixtures / filename).read_text(), 'html.parser')
        names = {control['name'] for control in soup.select('input[name], select[name]')}
        assert set(payload) == names | {'page'}
    helpers = (fixtures / 'management_form_helpers.js').read_text()
    assert "data=params+'&page=inside'" in helpers
    assert 'encodeURIComponent(values[i])' in helpers


def test_management_gateway_must_match_observed_ui_subnet_rule() -> None:
    with pytest.raises(ValueError, match='subnet'):
        build_management_network_payload('192.0.2.10', '255.255.255.0', '198.51.100.1')
