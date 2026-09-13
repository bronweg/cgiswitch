"""Typed connection and apply options for JTCom switches."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class JTComConnectionOptions:
    """HTTP connection settings."""

    verify_tls: bool = False
    port: int | None = None
    timeout: int = 60


@dataclass(frozen=True)
class ApplyPolicy:
    """Safety and backup settings used by :meth:`JTComSwitch.apply`."""

    backup_before_change: bool = True
    backup_dir: str | Path = "./backups"
    safety_port_id: int = 6
    allow_port_mode_change: bool = False
    allow_untagged_move: bool = False
    allow_vlan_delete_in_use: bool = False
