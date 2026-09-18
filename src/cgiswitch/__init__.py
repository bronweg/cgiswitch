"""Standalone client for JTCom CGI-based Ethernet switches."""

from cgiswitch.bootstrap import BootstrapConfig, JTComBootstrapError, bootstrap_switch
from cgiswitch.client.errors import JTComApplyError, JTComPolicyError
from cgiswitch.model.options import ApplyPolicy, JTComConnectionOptions
from cgiswitch.switch import JTComSwitch

__all__ = [
    "ApplyPolicy",
    "BootstrapConfig",
    "JTComBootstrapError",
    "bootstrap_switch",
    "JTComApplyError",
    "JTComConnectionOptions",
    "JTComPolicyError",
    "JTComSwitch",
]
__version__ = "0.1.0"
