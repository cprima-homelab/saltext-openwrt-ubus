"""
Grains module for OpenWrt devices managed via uci proxies.

Overrides grains that would otherwise leak from the salt-master host
with actual device values from the proxy module's grains cache.

Supports both ``uci_ubus_jsonrpc`` and ``uci_ssh`` proxy types.

Salt passes the proxy LazyLoader as a function parameter (not via
``__proxy__``), because grains load before the dunder is injected.
"""

import logging

log = logging.getLogger(__name__)

__proxyenabled__ = ["uci_ubus_jsonrpc", "uci_ssh"]
__virtualname__ = "uci"

_SUPPORTED_PROXYTYPES = frozenset({"uci_ubus_jsonrpc", "uci_ssh"})


def __virtual__():
    if "proxy" not in __opts__:
        return False, "Not a proxy minion"
    if __opts__.get("proxy", {}).get("proxytype") not in _SUPPORTED_PROXYTYPES:
        return False, "proxytype is not uci_ubus_jsonrpc or uci_ssh"
    return __virtualname__


def uci(proxy=None):
    """Return device grains from the proxy module.

    The ``proxy`` parameter is injected by Salt's grains loader
    when the proxy LazyLoader is available.
    """
    if proxy is None:
        return {}
    proxytype = __opts__.get("proxy", {}).get("proxytype", "")
    grains_fn = f"{proxytype}.grains"
    if grains_fn not in proxy:
        return {}
    return proxy[grains_fn]()
