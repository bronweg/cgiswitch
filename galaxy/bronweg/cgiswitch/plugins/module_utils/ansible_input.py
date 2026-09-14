"""Strict parsing of nested Ansible configuration input."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TypeVar

from cgiswitch.client.port_ops import SPEED_TOKEN_TO_CODE
from cgiswitch.model.config import DeviceConfig
from cgiswitch.model.port import PortConfig
from cgiswitch.model.vlan import VlanConfig
from cgiswitch.vendor.jtcom.mappings import SPEED_DUPLEX_ALIASES

_VLAN_KEYS = frozenset(
    {
        "name",
        "state",
        "tagged_ports",
        "untagged_ports",
        "tagged_add",
        "tagged_remove",
        "tagged_set",
        "untagged_add",
        "untagged_remove",
        "untagged_set",
    }
)
_PORT_KEYS = frozenset(
    {
        "admin_up",
        "speed",
        "flow_control",
        "access_vlan",
        "native_vlan",
        "trunk_add_vlans",
        "trunk_remove_vlans",
        "trunk_set_vlans",
    }
)


def parse_desired_config(args: Mapping[str, object]) -> DeviceConfig:
    """Parse and strictly validate the nested ``vlans`` and ``ports`` input.

    The parser deliberately does not validate top-level Ansible arguments.
    It must run before opening a switch session so malformed input cannot cause
    network access. VLAN and port map keys may be integers or digit strings;
    aliases such as ``1`` and ``"01"`` are rejected when used together.
    """
    vlans_value = args.get("vlans", _MISSING)
    ports_value = args.get("ports", _MISSING)
    vlans = _parse_map(vlans_value, "vlans", _parse_vlan_entry)
    ports = _parse_map(ports_value, "ports", _parse_port_entry)
    return DeviceConfig(vlans=vlans, ports=ports)


_MISSING = object()


def _parse_map(
    value: object,
    path: str,
    parse_entry: Callable[[object, str, int], _EntryT],
) -> dict[int, _EntryT]:
    if value is _MISSING:
        return {}
    if value is None:
        raise ValueError(f"{path}: expected a mapping, got null")
    if not isinstance(value, Mapping):
        raise ValueError(f"{path}: expected a mapping, got {type(value).__name__}")

    result: dict[int, _EntryT] = {}
    source_paths: dict[int, str] = {}
    for raw_key, raw_entry in value.items():
        key = _parse_map_key(raw_key, path)
        entry_path = f"{path}[{raw_key!r}]"
        if key in result:
            raise ValueError(
                f"{entry_path}: key aliases {source_paths[key]} after normalization"
            )
        result[key] = parse_entry(raw_entry, entry_path, key)
        source_paths[key] = entry_path
    return result


def _parse_map_key(value: object, path: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{path}: keys must be integers or ASCII digit strings")
    if isinstance(value, int):
        key = value
    elif isinstance(value, str) and value and value.isascii() and value.isdecimal():
        key = int(value)
    else:
        raise ValueError(f"{path}[{value!r}]: key must be an integer or ASCII digit string")
    if key < 1:
        raise ValueError(f"{path}[{value!r}]: key must be positive")
    return key


def _require_entry(value: object, path: str, allowed: frozenset[str]) -> Mapping[str, object]:
    if value is None or not isinstance(value, Mapping):
        got = "null" if value is None else type(value).__name__
        raise ValueError(f"{path}: expected a mapping, got {got}")
    invalid_key_types = [key for key in value if not isinstance(key, str)]
    if invalid_key_types:
        raise ValueError(f"{path}: nested keys must be strings: {invalid_key_types!r}")
    unknown = sorted(set(value) - allowed, key=repr)
    if unknown:
        raise ValueError(f"{path}: unknown keys: {unknown}")
    return value


_EntryT = TypeVar("_EntryT")


def _parse_vlan_entry(value: object, path: str, vlan_id: int) -> VlanConfig:
    if vlan_id > 4094:
        raise ValueError(f"{path}: VLAN ID must be in range 1..4094")
    entry = _require_entry(value, path, _VLAN_KEYS)
    name = entry.get("name")
    if name is not None and not isinstance(name, str):
        raise ValueError(f"{path}.name: expected string or null")
    state = entry.get("state", "present")
    if state not in ("present", "absent"):
        raise ValueError(f"{path}.state: expected 'present' or 'absent'")
    try:
        return VlanConfig(
            vlan_id=vlan_id,
            name=name,
            state=state,
            tagged_ports=_parse_id_list(entry.get("tagged_ports"), f"{path}.tagged_ports", "port"),
            untagged_ports=_parse_id_list(
                entry.get("untagged_ports"), f"{path}.untagged_ports", "port"
            ),
            tagged_add=_parse_id_list(entry.get("tagged_add"), f"{path}.tagged_add", "port"),
            tagged_remove=_parse_id_list(
                entry.get("tagged_remove"), f"{path}.tagged_remove", "port"
            ),
            tagged_set=_parse_id_list(entry.get("tagged_set"), f"{path}.tagged_set", "port"),
            untagged_add=_parse_id_list(
                entry.get("untagged_add"), f"{path}.untagged_add", "port"
            ),
            untagged_remove=_parse_id_list(
                entry.get("untagged_remove"), f"{path}.untagged_remove", "port"
            ),
            untagged_set=_parse_id_list(
                entry.get("untagged_set"), f"{path}.untagged_set", "port"
            ),
        )
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from exc


def _parse_port_entry(value: object, path: str, port_id: int) -> PortConfig:
    entry = _require_entry(value, path, _PORT_KEYS)
    admin_up = _parse_bool_or_none(entry.get("admin_up"), f"{path}.admin_up")
    flow_control = _parse_bool_or_none(entry.get("flow_control"), f"{path}.flow_control")
    speed = entry.get("speed")
    if speed is not None:
        if not isinstance(speed, str):
            raise ValueError(f"{path}.speed: expected string or null")
        speed = SPEED_DUPLEX_ALIASES.get(speed.lower(), speed)
        if speed not in SPEED_TOKEN_TO_CODE:
            raise ValueError(f"{path}.speed: unknown speed token {speed!r}")
    try:
        return PortConfig(
            port_id=port_id,
            admin_up=admin_up,
            speed_duplex=speed,
            flow_control=flow_control,
            access_vlan=_parse_vlan_id(entry.get("access_vlan"), f"{path}.access_vlan"),
            native_vlan=_parse_vlan_id(entry.get("native_vlan"), f"{path}.native_vlan"),
            trunk_add_vlans=_parse_id_list(
                entry.get("trunk_add_vlans"), f"{path}.trunk_add_vlans", "VLAN"
            ),
            trunk_remove_vlans=_parse_id_list(
                entry.get("trunk_remove_vlans"), f"{path}.trunk_remove_vlans", "VLAN"
            ),
            trunk_set_vlans=_parse_id_list(
                entry.get("trunk_set_vlans"), f"{path}.trunk_set_vlans", "VLAN"
            ),
        )
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from exc


def _parse_bool_or_none(value: object, path: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"{path}: expected boolean or null")
    return value


def _parse_vlan_id(value: object, path: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{path}: expected integer VLAN ID or null")
    if not 1 <= value <= 4094:
        raise ValueError(f"{path}: VLAN ID must be in range 1..4094")
    return value


def _parse_id_list(value: object, path: str, kind: str) -> list[int] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError(f"{path}: expected a list of integer {kind} IDs or null")
    result: list[int] = []
    for index, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, int):
            raise ValueError(f"{path}[{index}]: expected integer {kind} ID")
        if kind == "VLAN" and not 1 <= item <= 4094:
            raise ValueError(f"{path}[{index}]: VLAN ID must be in range 1..4094")
        if kind == "port" and item < 1:
            raise ValueError(f"{path}[{index}]: port ID must be positive")
        result.append(item)
    return result
