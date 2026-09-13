"""Tests for structured apply failure context."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from cgiswitch.client.errors import JTComApplyError, JTComVerificationError

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
        spec = importlib.util.spec_from_file_location("test_apply_error_action", ACTION_PATH)
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


def _action(module: types.ModuleType) -> object:
    instance = module.ActionModule()
    instance._task = types.SimpleNamespace(
        args={"host": "192.0.2.1", "username": "admin", "password": "secret"}
    )
    instance._play_context = types.SimpleNamespace(check_mode=False)
    return instance


def test_apply_error_serializes_partial_failure() -> None:
    cause = ValueError("write rejected")
    error = JTComApplyError(
        backup_file="/tmp/backup.cfg",
        completed_operations=[{"key": "vlan_create:10", "kind": "vlan_create"}],
        failed_operation={"key": "port_update:3", "kind": "port_update"},
        original_exception=cause,
        write_attempted=True,
        readback={"ports": {"3": {"admin_up": True}}},
    )

    assert error.original_exception is cause
    assert error.applied == ["vlan_create:10"]
    assert error.as_result() == {
        "failed": True,
        "msg": "Apply failed during port_update:3: write rejected",
        "changed": True,
        "backup_file": "/tmp/backup.cfg",
        "applied": ["vlan_create:10"],
        "completed_operations": [{"key": "vlan_create:10", "kind": "vlan_create"}],
        "failed_operation": {"key": "port_update:3", "kind": "port_update"},
        "original_exception": {"type": "ValueError", "message": "write rejected"},
        "readback": {"ports": {"3": {"admin_up": True}}},
        "readback_error": None,
        "write_attempted": True,
    }


def test_verification_error_includes_remaining_diff() -> None:
    error = JTComApplyError(
        backup_file="",
        completed_operations=[],
        failed_operation={"key": "verify", "kind": "verification"},
        original_exception=JTComVerificationError({"total_changes": 1}),
        write_attempted=True,
        readback_error=TimeoutError("readback timed out"),
    )

    result = error.as_result()
    assert result["remaining_diff"] == {"total_changes": 1}
    assert result["readback_error"] == {
        "type": "TimeoutError",
        "message": "readback timed out",
    }


def test_action_forwards_apply_error_result(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_action()
    failure = JTComApplyError(
        backup_file="/tmp/backup.cfg",
        completed_operations=[{"key": "vlan_create:10", "kind": "vlan_create"}],
        failed_operation={"key": "port_update:3", "kind": "port_update"},
        original_exception=ConnectionError("connection lost"),
        write_attempted=True,
    )

    class FakeSwitch:
        def __init__(self, **kwargs: object) -> None:
            pass

        def open(self) -> None:
            pass

        def close(self) -> None:
            pass

        def apply(self, desired: object, *, check_mode: bool) -> dict[str, object]:
            raise failure

    monkeypatch.setattr("cgiswitch.switch.JTComSwitch", FakeSwitch)
    result = _action(module).run()

    assert result == failure.as_result()
