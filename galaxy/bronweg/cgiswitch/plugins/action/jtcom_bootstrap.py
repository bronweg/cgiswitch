#!/usr/bin/python3
"""Ansible action plugin for JTCom switch bootstrap."""

from __future__ import annotations

from typing import Any

from ansible.plugins.action import ActionBase


class ActionModule(ActionBase):  # type: ignore[misc]
    """Bootstrap a switch through the cgiswitch controller-side API."""

    TRANSFERS_FILES = False

    def run(
        self,
        tmp: str | None = None,
        task_vars: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = super().run(tmp, task_vars)
        result["_ansible_no_log"] = True
        try:
            from ansible_collections.bronweg.cgiswitch.plugins.module_utils.bootstrap_input import (
                parse_bootstrap_config,
            )

            config = parse_bootstrap_config(self._task.args)
        except (ImportError, ValueError) as exc:
            return _failure(result, str(exc))

        try:
            from cgiswitch import JTComBootstrapError, bootstrap_switch

            outcome = bootstrap_switch(
                config,
                check_mode=bool(getattr(self._play_context, "check_mode", False)),
            )
        except JTComBootstrapError as exc:
            safe = exc.as_result()
            result.update(safe)
            return result
        except (ConnectionError, TimeoutError, ValueError, OSError) as exc:
            return _failure(result, str(exc))
        except ImportError as exc:
            return _failure(result, f"cgiswitch is not installed: {exc}")
        except Exception as exc:  # pragma: no cover - defensive controller boundary
            return _failure(result, str(exc))

        result.update(outcome)
        return result


def _failure(result: dict[str, Any], message: str) -> dict[str, Any]:
    result.update(failed=True, changed=False, msg=message, _ansible_no_log=True)
    return result
