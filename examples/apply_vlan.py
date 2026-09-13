#!/usr/bin/env python3
"""Apply an incremental VLAN change through the canonical switch API."""

from __future__ import annotations

import os
import pprint

from cgiswitch import ApplyPolicy, JTComConnectionOptions, JTComSwitch
from cgiswitch.model.config import DeviceConfig
from cgiswitch.model.vlan import VlanConfig


def main() -> None:
    host = os.environ["JTCOM_HOST"]
    apply_changes = os.getenv("APPLY", "0") == "1"
    desired = DeviceConfig(vlans={222: VlanConfig(vlan_id=222, name="test222")})
    connection = JTComConnectionOptions(
        verify_tls=os.getenv("JTCOM_VERIFY_TLS", "false").lower() == "true"
    )
    policy = ApplyPolicy(backup_before_change=apply_changes)
    with JTComSwitch(
        host,
        os.getenv("JTCOM_USERNAME", "admin"),
        os.getenv("JTCOM_PASSWORD", "admin"),
        connection=connection,
        policy=policy,
    ) as switch:
        result = switch.apply(desired, check_mode=not apply_changes)
    pprint.pprint(result)


if __name__ == "__main__":
    main()
