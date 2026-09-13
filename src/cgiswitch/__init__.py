"""Standalone client for JTCom CGI-based Ethernet switches."""

from cgiswitch.model.options import ApplyPolicy, JTComConnectionOptions
from cgiswitch.switch import JTComSwitch

__all__ = ["ApplyPolicy", "JTComConnectionOptions", "JTComSwitch"]
__version__ = "0.1.0"
