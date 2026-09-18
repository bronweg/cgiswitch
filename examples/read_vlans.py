#!/usr/bin/env python3
"""Read and print VLAN state."""

from __future__ import annotations

import json
import os
from dataclasses import asdict

from cgiswitch import JTComConnectionOptions, JTComSwitch


def main() -> None:
    connection = JTComConnectionOptions(
        verify_tls=os.getenv("JTCOM_VERIFY_TLS", "false").lower() not in {"0", "false", "no", "off"}
    )
    with JTComSwitch(
        os.environ["JTCOM_HOST"],
        os.getenv("JTCOM_USERNAME", "admin"),
        os.environ["JTCOM_PASSWORD"],
        connection=connection,
    ) as switch:
        vlans = switch.read_vlans()
    print(json.dumps({str(vlan_id): asdict(entry) for vlan_id, entry in vlans.items()}, indent=2))


if __name__ == "__main__":
    main()
