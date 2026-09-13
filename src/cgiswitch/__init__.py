"""Standalone client for JTCom CGI-based Ethernet switches."""

from cgiswitch.client.errors import JTComApplyError, JTComPolicyError
from cgiswitch.model.options import ApplyPolicy, JTComConnectionOptions
from cgiswitch.switch import JTComSwitch

__all__ = [
    "ApplyPolicy",
    "JTComApplyError",
    "JTComConnectionOptions",
    "JTComPolicyError",
    "JTComSwitch",
]
__version__ = "0.1.0"
