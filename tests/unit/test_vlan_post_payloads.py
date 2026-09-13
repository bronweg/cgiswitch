"""Unit tests for VLAN POST payload formation in cgiswitch.client.vlan_ops.

These tests verify that the correct form fields are built and sent to the
switch, without requiring a real device.  The :mod:`responses` library is
used to intercept HTTP calls.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
import responses as responses_lib

from cgiswitch.client.errors import JTComSwitchError
from cgiswitch.client.vlan_ops import vlan_create, vlan_delete, vlan_set_port

_BASE = "http://192.168.1.1"
_OK = json.dumps({"code": 0, "data": ""})
_ERR = json.dumps({"code": 1, "data": "param error"})


def _mock_session(base_url: str = _BASE) -> MagicMock:
    """Build a minimal mock session that delegates to a real JTComHTTP-like object."""
    from cgiswitch.client.session import JTComCredentials, JTComSession

    session = JTComSession(
        base_url=base_url,
        credentials=JTComCredentials("admin", "admin"),
    )
    session._logged_in = True  # skip login
    return session


# ---------------------------------------------------------------------------
# vlan_create
# ---------------------------------------------------------------------------

class TestVlanCreate:
    @responses_lib.activate
    def test_create_sends_correct_fields(self) -> None:
        responses_lib.add(
            responses_lib.POST,
            f"{_BASE}/staticvlan.cgi",
            body=_OK,
            content_type="application/json",
        )
        session = _mock_session()
        vlan_create(session, 222, "test222")

        req = responses_lib.calls[0].request
        body = req.body or ""
        assert "vlanid=222" in body
        assert "vlanname=test222" in body
        assert "cmd=add" in body
        assert "page=inside" in body

    @responses_lib.activate
    def test_create_without_name_sends_empty_vlanname(self) -> None:
        responses_lib.add(
            responses_lib.POST,
            f"{_BASE}/staticvlan.cgi",
            body=_OK,
            content_type="application/json",
        )
        session = _mock_session()
        vlan_create(session, 100)

        req = responses_lib.calls[0].request
        body = req.body or ""
        assert "vlanname=" in body
        assert "cmd=add" in body

    @responses_lib.activate
    def test_create_raises_on_switch_error(self) -> None:
        responses_lib.add(
            responses_lib.POST,
            f"{_BASE}/staticvlan.cgi",
            body=_ERR,
            content_type="application/json",
        )
        session = _mock_session()
        with pytest.raises(JTComSwitchError) as exc_info:
            vlan_create(session, 222, "test222")
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# vlan_delete
# ---------------------------------------------------------------------------

class TestVlanDelete:
    @responses_lib.activate
    def test_delete_single_vlan(self) -> None:
        responses_lib.add(
            responses_lib.POST,
            f"{_BASE}/staticvlan.cgi",
            body=_OK,
            content_type="application/json",
        )
        session = _mock_session()
        vlan_delete(session, [222])

        req = responses_lib.calls[0].request
        body = req.body or ""
        assert "del=222" in body
        assert "cmd=del" in body
        assert "page=inside" in body

    @responses_lib.activate
    def test_delete_multiple_vlans_sends_repeated_del_key(self) -> None:
        responses_lib.add(
            responses_lib.POST,
            f"{_BASE}/staticvlan.cgi",
            body=_OK,
            content_type="application/json",
        )
        session = _mock_session()
        vlan_delete(session, [10, 20, 30])

        req = responses_lib.calls[0].request
        body = req.body or ""
        assert body.count("del=") == 3
        assert "del=10" in body
        assert "del=20" in body
        assert "del=30" in body

    def test_delete_vlan1_raises_value_error(self) -> None:
        session = _mock_session()
        with pytest.raises(ValueError, match="deletable"):
            vlan_delete(session, [1])

    def test_delete_empty_list_raises_value_error(self) -> None:
        session = _mock_session()
        with pytest.raises(ValueError, match="deletable"):
            vlan_delete(session, [])

    def test_delete_filters_vlan1_from_mixed_list(self) -> None:
        # [1, 10] → only 10 should be sent; VLAN 1 silently skipped
        import responses as resp_mod

        with resp_mod.RequestsMock() as rsps:
            rsps.add(
                resp_mod.POST,
                f"{_BASE}/staticvlan.cgi",
                body=_OK,
                content_type="application/json",
            )
            session = _mock_session()
            vlan_delete(session, [1, 10])
            req = rsps.calls[0].request
            body = req.body or ""
            assert "del=10" in body
            assert "del=1&" not in body  # VLAN 1 not present


# ---------------------------------------------------------------------------
# vlan_set_port
# ---------------------------------------------------------------------------

class TestVlanSetPort:
    @responses_lib.activate
    def test_access_mode_fields(self) -> None:
        responses_lib.add(
            responses_lib.POST,
            f"{_BASE}/vlanport.cgi",
            body=_OK,
            content_type="application/json",
        )
        session = _mock_session()
        vlan_set_port(session, port_ids=[1], vlan_type="access",
                      access_vlan=10, native_vlan=None, permit_vlans=[])

        req = responses_lib.calls[0].request
        body = req.body or ""
        assert "PortId=0" in body
        assert "VlanType=0" in body
        assert "AccessVlan=10" in body
        assert "NativeVlan=1" in body
        assert "PermitVlan=" in body  # empty
        assert "page=inside" in body

    @responses_lib.activate
    def test_trunk_mode_fields(self) -> None:
        responses_lib.add(
            responses_lib.POST,
            f"{_BASE}/vlanport.cgi",
            body=_OK,
            content_type="application/json",
        )
        session = _mock_session()
        vlan_set_port(session, port_ids=[1, 2], vlan_type="trunk",
                      access_vlan=None, native_vlan=1, permit_vlans=[10])

        req = responses_lib.calls[0].request
        body = req.body or ""
        assert "PortId=0_1" in body
        assert "VlanType=1" in body
        assert "NativeVlan=1" in body
        assert "PermitVlan=10" in body

    @responses_lib.activate
    def test_trunk_multi_permit_vlans_joined_with_underscore(self) -> None:
        responses_lib.add(
            responses_lib.POST,
            f"{_BASE}/vlanport.cgi",
            body=_OK,
            content_type="application/json",
        )
        session = _mock_session()
        vlan_set_port(session, port_ids=[3], vlan_type="trunk",
                      access_vlan=None, native_vlan=1, permit_vlans=[10, 20, 30])

        req = responses_lib.calls[0].request
        body = req.body or ""
        assert "PermitVlan=10_20_30" in body

    def test_empty_port_ids_raises_value_error(self) -> None:
        session = _mock_session()
        with pytest.raises(ValueError, match="port_ids"):
            vlan_set_port(session, [], "access", 1, None, [])

    def test_invalid_vlan_type_raises_value_error(self) -> None:
        session = _mock_session()
        with pytest.raises(ValueError, match="vlan_type"):
            vlan_set_port(session, [1], "hybrid", 1, None, [])

    def test_port_zero_raises_value_error(self) -> None:
        session = _mock_session()
        with pytest.raises(ValueError, match="1-based positive integers"):
            vlan_set_port(session, [0], "access", 1, None, [])

    @responses_lib.activate
    def test_case_insensitive_vlan_type(self) -> None:
        responses_lib.add(
            responses_lib.POST,
            f"{_BASE}/vlanport.cgi",
            body=_OK,
            content_type="application/json",
        )
        session = _mock_session()
        # "TRUNK" should work same as "trunk"
        vlan_set_port(session, [1], "TRUNK", None, 1, [10])
        req = responses_lib.calls[0].request
        body = req.body or ""
        assert "VlanType=1" in body
