"""Resolve collection imports against the source checkout in unit tests."""

from __future__ import annotations

import sys
import types
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def collection_namespace() -> Iterator[None]:
    """Expose the local Galaxy layout under Ansible's collection namespace."""
    namespace = types.ModuleType("ansible_collections")
    namespace.__path__ = [str(Path(__file__).resolve().parents[1] / "galaxy")]
    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(sys.modules, "ansible_collections", namespace)
        yield
