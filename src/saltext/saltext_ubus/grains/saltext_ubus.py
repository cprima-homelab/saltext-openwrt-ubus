"""
Grains module for OpenWrt devices managed via openwrt_ubus proxies.

Overrides grains that would otherwise leak from the salt-master host
with actual device values from the proxy module's grains cache.

Supports both ``openwrt_ubus_jsonrpc`` and ``openwrt_ubus_ssh`` proxy types.

Salt passes the proxy LazyLoader as a function parameter (not via
``__proxy__``), because grains load before the dunder is injected.
"""

import logging

log = logging.getLogger(__name__)

__proxyenabled__ = ["openwrt_ubus_jsonrpc", "openwrt_ubus_ssh"]
__virtualname__ = "openwrt_ubus"

_SUPPORTED_PROXYTYPES = frozenset({"openwrt_ubus_jsonrpc", "openwrt_ubus_ssh"})


def __virtual__():
    if "proxy" not in __opts__:
        return False, "Not a proxy minion"
    if __opts__.get("proxy", {}).get("proxytype") not in _SUPPORTED_PROXYTYPES:
        return False, "proxytype is not openwrt_ubus_jsonrpc or openwrt_ubus_ssh"
    return __virtualname__


def openwrt_ubus(proxy=None):
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
