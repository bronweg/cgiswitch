"""Regression tests for the strict bootstrap Ansible action boundary."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

import pytest

ACTION_PATH = Path("galaxy/bronweg/cgiswitch/plugins/action/jtcom_bootstrap.py")
INPUT_PATH = Path("galaxy/bronweg/cgiswitch/plugins/module_utils/bootstrap_input.py")


def _load_action() -> types.ModuleType:
    class ActionBase:
        def run(
            self, tmp: str | None = None, task_vars: dict[str, Any] | None = None
        ) -> dict[str, Any]:
            return {}

    ansible = types.ModuleType("ansible")
    plugins = types.ModuleType("ansible.plugins")
    action = types.ModuleType("ansible.plugins.action")
    action.ActionBase = ActionBase
    names = ("ansible", "ansible.plugins", "ansible.plugins.action")
    old = {name: sys.modules.get(name) for name in names}
    sys.modules.update(
        {"ansible": ansible, "ansible.plugins": plugins, "ansible.plugins.action": action}
    )
    try:
        spec = importlib.util.spec_from_file_location("test_bootstrap_action_plugin", ACTION_PATH)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, value in old.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


def _action(module: types.ModuleType, args: dict[str, Any], check_mode: bool = False) -> object:
    instance = module.ActionModule()
    instance._task = types.SimpleNamespace(args=args)
    instance._play_context = types.SimpleNamespace(check_mode=check_mode)
    return instance


def _valid_args() -> dict[str, Any]:
    return {
        "factory_url": "http://192.0.2.1",
        "target_url": "http://198.51.100.10",
        "username": "admin",
        "factory_password": "factory-secret",
        "password": "secret",
        "management": {"address": "198.51.100.10", "prefix_length": 24, "gateway": "198.51.100.1"},
        "expected_mac": "00:11:22:33:44:55",
    }


@pytest.mark.parametrize(
    "bad",
    [
        {"extra": 1},
        {"management": None},
        {"management": {"address": "198.51.100.10"}},
        {"verify_tls": 1},
        {"username": 4},
    ],
)
def test_invalid_bootstrap_input_fails_before_api(
    monkeypatch: pytest.MonkeyPatch, bad: dict[str, Any]
) -> None:
    module = _load_action()
    args = _valid_args()
    args.update(bad)
    called = False

    def fake_bootstrap(*args: object, **kwargs: object) -> dict[str, object]:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr("cgiswitch.bootstrap_switch", fake_bootstrap)
    result = _action(module, args).run()
    assert result["failed"] is True
    assert result["changed"] is False
    assert result["_ansible_no_log"] is True
    assert called is False


def test_action_maps_separate_passwords_and_hides_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_action()
    seen: list[object] = []

    def fake_bootstrap(config: object, *, check_mode: bool) -> dict[str, object]:
        seen.append(config)
        return {"changed": False, "operations": [], "completed_operations": []}

    monkeypatch.setattr("cgiswitch.bootstrap_switch", fake_bootstrap)
    result = _action(module, _valid_args(), check_mode=True).run()
    config = seen[0]
    assert config.factory_password == "factory-secret"
    assert config.target_password == "secret"
    assert result["changed"] is False
    assert result["_ansible_no_log"] is True
    assert "secret" not in repr(result)


def test_bootstrap_error_is_returned_as_safe_structured_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_action()

    def fail(*args: object, **kwargs: object) -> object:
        raise RuntimeError("safe failure")

    monkeypatch.setattr("cgiswitch.bootstrap_switch", fail)
    result = _action(module, _valid_args()).run()
    assert result["failed"] is True
    assert result["_ansible_no_log"] is True
