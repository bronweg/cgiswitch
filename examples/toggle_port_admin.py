#!/usr/bin/env python3
"""Toggle a port through the canonical apply API in check mode by default."""

from __future__ import annotations

import os
import pprint

from cgiswitch import ApplyPolicy, JTComConnectionOptions, JTComSwitch
from cgiswitch.model.config import DeviceConfig
from cgiswitch.model.port import PortConfig


def main() -> None:
    port_id = int(os.environ["TEST_PORT_ID"])
    apply_changes = os.getenv("APPLY", "0") == "1"
    connection = JTComConnectionOptions(
        verify_tls=os.getenv("JTCOM_VERIFY_TLS", "false").lower() in {"1", "true", "yes", "on"}
    )
    policy = ApplyPolicy(backup_before_change=apply_changes)
    with JTComSwitch(
        os.environ["JTCOM_HOST"],
        os.getenv("JTCOM_USERNAME", "admin"),
        os.getenv("JTCOM_PASSWORD", "admin"),
        connection=connection,
        policy=policy,
    ) as switch:
        settings, _ = switch.read_ports()
        current = next(item for item in settings if item.port_id == port_id)
        desired = DeviceConfig(
            ports={port_id: PortConfig(port_id=port_id, admin_up=not current.admin_up)}
        )
        result = switch.apply(desired, check_mode=not apply_changes)
        pprint.pprint(result)
        if apply_changes:
            restore = DeviceConfig(
                ports={port_id: PortConfig(port_id=port_id, admin_up=current.admin_up)}
            )
            switch.apply(restore)


if __name__ == "__main__":
    main()
