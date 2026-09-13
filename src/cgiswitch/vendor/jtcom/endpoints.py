"""JTCom CGI endpoint URL paths.

Each constant is a URL path segment relative to the switch base URL.
Extend this module as new pages are reverse-engineered.
"""

from __future__ import annotations

# Authentication
LOGIN: str = "/login.cgi"

SYSCMD: str = "/syscmd.cgi"
# JTCom logout is performed via syscmd.cgi
LOGOUT: str = SYSCMD

# Device / system
DEVICE_INFO: str = "/info.cgi"

# Port management
PORT_SETTINGS: str = "/port.cgi"
PORT_STATS: str = "/port.cgi"  # use ?page=stats query param

# VLAN management
VLAN_STATIC: str = "/vlan.cgi"
VLAN_PORT_BASED: str = "/vlan.cgi"

# Trunk / LAG
TRUNK_GROUP: str = "/trunk.cgi"
TRUNK_LACP: str = "/trunk.cgi"

# VLAN write operations (confirmed from real switch)
VLAN_CREATE_DELETE: str = "/staticvlan.cgi"  # POST: create (cmd=add) or delete (cmd=del)
VLAN_PORT_SET: str = "/vlanport.cgi"          # POST: per-port VLAN membership

# Configuration backup
CONFIG_BACKUP: str = "/config.cgi"            # GET ?cmd=conf_backup → raw binary

