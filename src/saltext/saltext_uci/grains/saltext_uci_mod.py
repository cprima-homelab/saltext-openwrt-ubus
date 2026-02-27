"""
Grains module for OpenWrt devices managed via saltext_uci proxy.

Overrides grains that would otherwise leak from the salt-master host
with actual device values from the JSON-RPC system.board response.

Salt passes the proxy LazyLoader as a function parameter (not via
``__proxy__``), because grains load before the dunder is injected.
"""

import logging

log = logging.getLogger(__name__)

__proxyenabled__ = ["saltext_uci"]
__virtualname__ = "saltext_uci"


def __virtual__():
    if "proxy" not in __opts__:
        return False, "Not a proxy minion"
    if __opts__.get("proxy", {}).get("proxytype") != "saltext_uci":
        return False, "proxytype is not saltext_uci"
    return __virtualname__


def saltext_uci(proxy=None):
    """Return device grains from the proxy module.

    The ``proxy`` parameter is injected by Salt's grains loader
    when the proxy LazyLoader is available.
    """
    if proxy is None:
        return {}
    if "saltext_uci.grains" not in proxy:
        return {}
    return proxy["saltext_uci.grains"]()
