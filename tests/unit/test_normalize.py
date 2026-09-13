"""Unit tests for normalization helpers."""

from __future__ import annotations

from cgiswitch.model.config import DeviceConfig
from cgiswitch.model.port import PortConfig
from cgiswitch.model.vlan import VlanConfig
from cgiswitch.utils.normalize import (
    normalize_device_config,
    normalize_port_config,
    normalize_vlan_config,
)

# ---------------------------------------------------------------------------
# normalize_vlan_config
# ---------------------------------------------------------------------------


def test_normalize_vlan_sorts_tagged() -> None:
    cfg = VlanConfig(vlan_id=10, tagged_ports=[3, 1, 2])
    result = normalize_vlan_config(cfg)
    assert result.tagged_ports == [1, 2, 3]


def test_normalize_vlan_sorts_untagged() -> None:
    cfg = VlanConfig(vlan_id=10, untagged_ports=[5, 2, 1])
    result = normalize_vlan_config(cfg)
    assert result.untagged_ports == [1, 2, 5]


def test_normalize_vlan_deduplicates_tagged() -> None:
    cfg = VlanConfig(vlan_id=10, tagged_ports=[1, 1, 2, 2])
    result = normalize_vlan_config(cfg)
    assert result.tagged_ports == [1, 2]


def test_normalize_vlan_deduplicates_untagged() -> None:
    cfg = VlanConfig(vlan_id=10, untagged_ports=[3, 3, 5])
    result = normalize_vlan_config(cfg)
    assert result.untagged_ports == [3, 5]


def test_normalize_vlan_overlap_prefers_untagged() -> None:
    """Port in both tagged and untagged → removed from tagged."""
    cfg = VlanConfig(vlan_id=10, tagged_ports=[1, 2, 3], untagged_ports=[2, 4])
    result = normalize_vlan_config(cfg)
    assert result.tagged_ports == [1, 3]
    assert result.untagged_ports == [2, 4]


def test_normalize_vlan_all_overlap_clears_tagged() -> None:
    cfg = VlanConfig(vlan_id=10, tagged_ports=[1, 2], untagged_ports=[1, 2])
    result = normalize_vlan_config(cfg)
    assert result.tagged_ports == []
    assert result.untagged_ports == [1, 2]


def test_normalize_vlan_preserves_other_fields() -> None:
    cfg = VlanConfig(vlan_id=99, name="mgmt", tagged_ports=[3, 1], untagged_ports=[])
    result = normalize_vlan_config(cfg)
    assert result.vlan_id == 99
    assert result.name == "mgmt"


class TestNormalizeVlanConfigSemantics:
    def test_none_stays_none(self) -> None:
        cfg = VlanConfig(vlan_id=20, tagged_ports=None, untagged_ports=None)
        result = normalize_vlan_config(cfg)
        assert result.tagged_ports is None
        assert result.untagged_ports is None

    def test_empty_list_stays_empty_list(self) -> None:
        cfg = VlanConfig(vlan_id=20, tagged_ports=[], untagged_ports=[])
        result = normalize_vlan_config(cfg)
        assert result.tagged_ports == []
        assert result.untagged_ports == []

    def test_deduplication_works_for_explicit_lists(self) -> None:
        cfg = VlanConfig(vlan_id=20, tagged_ports=[1, 1, 2], untagged_ports=[3, 3])
        result = normalize_vlan_config(cfg)
        assert result.tagged_ports == [1, 2]
        assert result.untagged_ports == [3]

    def test_untagged_wins_on_overlap_for_lists(self) -> None:
        cfg = VlanConfig(vlan_id=20, tagged_ports=[1, 2], untagged_ports=[2, 3])
        result = normalize_vlan_config(cfg)
        assert result.tagged_ports == [1]
        assert result.untagged_ports == [2, 3]

    def test_tagged_none_with_untagged_list(self) -> None:
        cfg = VlanConfig(vlan_id=20, tagged_ports=None, untagged_ports=[2, 3])
        result = normalize_vlan_config(cfg)
        assert result.tagged_ports is None
        assert result.untagged_ports == [2, 3]

    def test_untagged_none_with_tagged_list(self) -> None:
        cfg = VlanConfig(vlan_id=20, tagged_ports=[1, 2], untagged_ports=None)
        result = normalize_vlan_config(cfg)
        assert result.tagged_ports == [1, 2]
        assert result.untagged_ports is None


# ---------------------------------------------------------------------------
# normalize_port_config
# ---------------------------------------------------------------------------


def test_normalize_port_canonical_unchanged() -> None:
    cfg = PortConfig(port_id=1, speed_duplex="1000M/Full")
    assert normalize_port_config(cfg) is cfg  # same object — already canonical


def test_normalize_port_alias_resolved() -> None:
    cfg = PortConfig(port_id=1, speed_duplex="1g/full")
    result = normalize_port_config(cfg)
    assert result.speed_duplex == "1000M/Full"


def test_normalize_port_alias_case_insensitive() -> None:
    cfg = PortConfig(port_id=1, speed_duplex="AUTO")
    result = normalize_port_config(cfg)
    assert result.speed_duplex == "Auto"


def test_normalize_port_alias_100m_half() -> None:
    cfg = PortConfig(port_id=2, speed_duplex="100mhalf")
    result = normalize_port_config(cfg)
    assert result.speed_duplex == "100M/Half"


def test_normalize_port_unknown_token_unchanged() -> None:
    cfg = PortConfig(port_id=3, speed_duplex="unknown_token")
    result = normalize_port_config(cfg)
    assert result.speed_duplex == "unknown_token"


def test_normalize_port_none_unchanged() -> None:
    cfg = PortConfig(port_id=4, speed_duplex=None)
    result = normalize_port_config(cfg)
    assert result.speed_duplex is None


def test_normalize_port_preserves_other_fields() -> None:
    cfg = PortConfig(port_id=5, admin_up=True, speed_duplex="auto", flow_control=False)
    result = normalize_port_config(cfg)
    assert result.admin_up is True
    assert result.flow_control is False
    assert result.speed_duplex == "Auto"


# ---------------------------------------------------------------------------
# normalize_device_config
# ---------------------------------------------------------------------------


def test_normalize_device_config_sorts_vlan_keys() -> None:
    cfg = DeviceConfig(
        vlans={
            30: VlanConfig(vlan_id=30),
            10: VlanConfig(vlan_id=10),
            20: VlanConfig(vlan_id=20),
        }
    )
    result = normalize_device_config(cfg)
    assert list(result.vlans.keys()) == [10, 20, 30]


def test_normalize_device_config_sorts_port_keys() -> None:
    cfg = DeviceConfig(
        ports={
            3: PortConfig(port_id=3),
            1: PortConfig(port_id=1),
            2: PortConfig(port_id=2),
        }
    )
    result = normalize_device_config(cfg)
    assert list(result.ports.keys()) == [1, 2, 3]


def test_normalize_device_config_normalizes_vlans() -> None:
    cfg = DeviceConfig(
        vlans={10: VlanConfig(vlan_id=10, tagged_ports=[3, 1], untagged_ports=[3])},
    )
    result = normalize_device_config(cfg)
    # port 3 in both tagged and untagged -> removed from tagged (prefer untagged)
    # port 1 only in tagged -> stays in tagged
    assert result.vlans[10].tagged_ports == [1]
    assert result.vlans[10].untagged_ports == [3]


def test_normalize_device_config_normalizes_ports() -> None:
    cfg = DeviceConfig(
        ports={1: PortConfig(port_id=1, speed_duplex="1g/full")},
    )
    result = normalize_device_config(cfg)
    assert result.ports[1].speed_duplex == "1000M/Full"


def test_normalize_device_config_copies_metadata() -> None:
    cfg = DeviceConfig(metadata={"source": "test"})
    result = normalize_device_config(cfg)
    assert result.metadata == {"source": "test"}
    assert result.metadata is not cfg.metadata  # independent copy
