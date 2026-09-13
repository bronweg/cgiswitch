"""JTCom field name mappings from HTML labels to model attributes.

Maps raw HTML text labels (as they appear in the switch web UI) to
the typed model attribute names used by the core.
"""

from __future__ import annotations

# Maps port speed strings displayed in the UI to integer Mbps values.
SPEED_MAP: dict[str, int] = {
    "10M": 10,
    "100M": 100,
    "1000M": 1000,
    "1G": 1000,
    "10G": 10000,
}

# Maps duplex strings from the UI to normalised values.
DUPLEX_MAP: dict[str, str] = {
    "Full": "full",
    "Half": "half",
    "Auto": "auto",
}


# Canonical speed/duplex tokens — must match keys in client.port_ops.SPEED_TOKEN_TO_CODE.
SPEED_DUPLEX_CANONICAL: frozenset[str] = frozenset(
    {
        "Auto",
        "10M/Half",
        "10M/Full",
        "100M/Half",
        "100M/Full",
        "1000M/Full",
        "2500M/Full",
        "10G/Full",
    }
)

# Maps lower-cased alternative representations to their canonical token.
SPEED_DUPLEX_ALIASES: dict[str, str] = {
    "auto": "Auto",
    "10m/half": "10M/Half",
    "10m/full": "10M/Full",
    "100m/half": "100M/Half",
    "100m/full": "100M/Full",
    "1000m/full": "1000M/Full",
    "1g/full": "1000M/Full",
    "2500m/full": "2500M/Full",
    "10g/full": "10G/Full",
    "10mhalf": "10M/Half",
    "10mfull": "10M/Full",
    "100mhalf": "100M/Half",
    "100mfull": "100M/Full",
    "1000mfull": "1000M/Full",
    "1gfull": "1000M/Full",
}
