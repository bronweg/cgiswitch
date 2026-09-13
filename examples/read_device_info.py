#!/usr/bin/env python3
"""Read and print device information from a JTCom switch."""

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
        os.getenv("JTCOM_PASSWORD", "admin"),
        connection=connection,
    ) as switch:
        print(json.dumps(asdict(switch.read_device_info()), indent=2))


if __name__ == "__main__":
    main()
