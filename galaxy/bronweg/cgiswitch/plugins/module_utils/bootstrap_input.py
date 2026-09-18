"""Strict parsing of JTCom bootstrap Ansible input."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from cgiswitch import BootstrapConfig
from cgiswitch.model.management import ManagementNetworkConfig

_TOP_LEVEL = frozenset(
    {
        "factory_url",
        "target_url",
        "username",
        "factory_password",
        "password",
        "management",
        "expected_mac",
        "expected_serial",
        "timeout_s",
        "transition_timeout_s",
        "poll_interval_s",
        "verify_tls",
    }
)
_MANAGEMENT_KEYS = frozenset({"address", "prefix_length", "gateway"})


def parse_bootstrap_config(args: Mapping[str, object]) -> BootstrapConfig:
    """Parse raw action arguments without coercing values or opening a session."""
    if not isinstance(args, Mapping):
        raise ValueError("Task arguments must be a mapping")
    unknown = sorted(set(args) - _TOP_LEVEL, key=repr)
    if unknown:
        raise ValueError(f"Unknown task parameters: {unknown}")

    factory_url = _required_string(args, "factory_url")
    target_url = _required_string(args, "target_url")
    username = _required_string(args, "username")
    factory_password = _required_string(args, "factory_password")
    password = _required_string(args, "password")

    raw_management = args.get("management", _MISSING)
    if raw_management is _MISSING or not isinstance(raw_management, Mapping):
        raise ValueError("Parameter 'management' must be a mapping")
    if any(not isinstance(key, str) for key in raw_management):
        raise ValueError("Parameter 'management' keys must be strings")
    management_unknown = sorted(set(raw_management) - _MANAGEMENT_KEYS, key=repr)
    if management_unknown:
        raise ValueError(f"Unknown management keys: {management_unknown}")
    if set(raw_management) != _MANAGEMENT_KEYS:
        raise ValueError(
            "Parameter 'management' must contain exactly address, prefix_length, gateway"
        )
    address = _required_string(raw_management, "address", prefix="management.")
    gateway = _required_string(raw_management, "gateway", prefix="management.")
    prefix_length = raw_management["prefix_length"]
    if isinstance(prefix_length, bool) or not isinstance(prefix_length, int):
        raise ValueError("Parameter 'management.prefix_length' must be an integer")

    optional: dict[str, Any] = {}
    for key in ("expected_mac", "expected_serial"):
        if key in args:
            value = args[key]
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"Parameter '{key}' must be a non-empty string or null")
            optional[key] = value
    for key in ("timeout_s", "transition_timeout_s", "poll_interval_s"):
        if key in args:
            value = args[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"Parameter '{key}' must be a number")
            optional[key] = value
    if "verify_tls" in args and not isinstance(args["verify_tls"], bool):
        raise ValueError("Parameter 'verify_tls' must be a boolean")
    if "verify_tls" in args:
        optional["verify_tls"] = args["verify_tls"]

    return BootstrapConfig(
        factory_url=factory_url,
        target_url=target_url,
        username=username,
        factory_password=factory_password,
        target_password=password,
        management=ManagementNetworkConfig(
            address=address,
            prefix_length=prefix_length,
            gateway=gateway,
        ),
        **optional,
    )


_MISSING = object()


def _required_string(args: Mapping[str, object], key: str, *, prefix: str = "") -> str:
    value = args.get(key, _MISSING)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Parameter '{prefix}{key}' must be a non-empty string")
    return value
