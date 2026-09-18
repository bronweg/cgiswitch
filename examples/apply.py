#!/usr/bin/env python3
"""Plan or apply an incremental JTCom switch configuration."""

from __future__ import annotations

import os
import pprint

from cgiswitch import ApplyPolicy, JTComConnectionOptions, JTComSwitch
from cgiswitch.model.config import DeviceConfig
from cgiswitch.model.vlan import VlanConfig


def main() -> None:
    host = os.getenv("JTCOM_HOST", "192.0.2.1")
    apply_changes = os.getenv("APPLY", "0") == "1"
    desired = DeviceConfig(
        vlans={100: VlanConfig(vlan_id=100, name="example", state="present")},
        ports={},
    )
    connection = JTComConnectionOptions(verify_tls=False, timeout=10)
    policy = ApplyPolicy(backup_before_change=apply_changes)

    with JTComSwitch(
        host,
        os.getenv("JTCOM_USERNAME", "admin"),
        os.environ["JTCOM_PASSWORD"],
        connection=connection,
        policy=policy,
    ) as switch:
        result = switch.apply(desired, check_mode=not apply_changes)
    print(f"{'LIVE APPLY' if apply_changes else 'DRY RUN'}")
    pprint.pprint(result)


if __name__ == "__main__":
    main()
