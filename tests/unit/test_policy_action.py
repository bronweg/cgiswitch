"""Focused tests for Ansible policy plumbing."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from cgiswitch.client.errors import JTComPolicyError
from cgiswitch.model.options import ApplyPolicy

ACTION_PATH = Path("galaxy/bronweg/cgiswitch/plugins/action/jtcom_config.py")


def _load_action() -> types.ModuleType:
    class ActionBase:
        def run(
            self,
            tmp: str | None = None,
            task_vars: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            return {}

    ansible = types.ModuleType("ansible")
    plugins = types.ModuleType("ansible.plugins")
    action = types.ModuleType("ansible.plugins.action")
    action.ActionBase = ActionBase
    old = {
        name: sys.modules.get(name)
        for name in ("ansible", "ansible.plugins", "ansible.plugins.action")
    }
    sys.modules.update(
        {"ansible": ansible, "ansible.plugins": plugins, "ansible.plugins.action": action}
    )
    try:
        spec = importlib.util.spec_from_file_location("test_policy_action_plugin", ACTION_PATH)
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
    instance._task = types.SimpleNamespace(
        args={
            "host": "192.0.2.1",
            "username": "admin",
            "password": "secret",
            **args,
        }
    )
    instance._play_context = types.SimpleNamespace(check_mode=check_mode)
    return instance


def test_action_forwards_auto_create_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_action()
    seen: list[ApplyPolicy] = []

    class FakeSwitch:
        def __init__(self, **kwargs: object) -> None:
            policy = kwargs["policy"]
            assert isinstance(policy, ApplyPolicy)
            seen.append(policy)

        def open(self) -> None:
            pass

        def close(self) -> None:
            pass

        def apply(self, desired: object, *, check_mode: bool) -> dict[str, object]:
            return {
                "changed": False,
                "diff": {},
                "warnings": [],
                "violations": [],
                "blocked": False,
            }

    monkeypatch.setattr("cgiswitch.switch.JTComSwitch", FakeSwitch)
    _action(module, {}).run()
    _action(module, {"auto_create_referenced_vlans": True}).run()

    assert seen == [ApplyPolicy(), ApplyPolicy(auto_create_referenced_vlans=True)]


def test_action_returns_structured_blocked_check_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_action()
    violations = [{"type": "safety_port", "message": "Cannot disable safety port."}]

    class FakeSwitch:
        def __init__(self, **kwargs: object) -> None:
            pass

        def open(self) -> None:
            pass

        def close(self) -> None:
            pass

        def apply(self, desired: object, *, check_mode: bool) -> dict[str, object]:
            return {
                "changed": True,
                "diff": {"total_changes": 1},
                "blocked": True,
                "violations": violations,
                "backup_file": "",
                "applied": [],
                "warnings": [],
            }

    monkeypatch.setattr("cgiswitch.switch.JTComSwitch", FakeSwitch)
    result = _action(module, {}, check_mode=True).run()

    assert result["changed"] is True
    assert result["blocked"] is True
    assert result["violations"] == violations
    assert result["backup_file"] == ""
    assert result["applied"] == []


def test_action_maps_policy_exception_to_failed_structured_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_action()
    violations = [{"type": "untagged_move", "message": "Move is blocked."}]

    class FakeSwitch:
        def __init__(self, **kwargs: object) -> None:
            pass

        def open(self) -> None:
            pass

        def close(self) -> None:
            pass

        def apply(self, desired: object, *, check_mode: bool) -> dict[str, object]:
            raise JTComPolicyError(violations)

    monkeypatch.setattr("cgiswitch.switch.JTComSwitch", FakeSwitch)
    result = _action(module, {}).run()

    assert result["failed"] is True
    assert result["changed"] is False
    assert result["blocked"] is True
    assert result["violations"] == violations
    assert result["backup_file"] == ""
    assert result["applied"] == []
    assert result["warnings"] == []
