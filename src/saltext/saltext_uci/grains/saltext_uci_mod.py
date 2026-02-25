"""
OpenWrt device grains via saltext_uci proxy.

Bridges the Salt grains framework to the proxy module's
``get_grains()`` function, which collects device facts over SSH.

Overrides core grains that would otherwise reflect the proxy host
rather than the managed OpenWrt device.  Salt's built-in grains
modules (``core.py``, ``extra.py``) use ``__proxyenabled__ = ["*"]``
and run inside the proxy process, collecting information about the
machine running the proxy.  Every key returned here takes precedence.

Grains that cannot be reliably collected from the device are set to
empty values rather than left to leak from the proxy host.

.. note::

    Salt's ``extra.py`` overrides the ``shell`` grain after extension
    grains are merged.  To correct it, add a static grain in the
    proxy config (``/etc/salt/proxy.d/<id>/grains``)::

        shell: /bin/ash

Only loads when the proxy type is ``saltext_uci``.

.. versionadded:: 0.2.0
"""

import logging

log = logging.getLogger(__name__)

__virtualname__ = "saltext_uci"
__proxyenabled__ = ["saltext_uci"]

GRAINS_CACHE = {}


def __virtual__():
    try:
        if __opts__.get("proxy", {}).get("proxytype") != "saltext_uci":
            return (False, "Not a saltext_uci proxy")
    except Exception:  # pylint: disable=broad-except
        return (False, "Could not determine proxy type")
    return __virtualname__


def _device_grains(proxy=None):
    """Fetch device grains from the proxy, with module-level caching."""
    global GRAINS_CACHE  # pylint: disable=global-statement
    if GRAINS_CACHE:
        return GRAINS_CACHE
    if proxy is None or "saltext_uci.get_grains" not in proxy:
        return {}
    try:
        GRAINS_CACHE = proxy["saltext_uci.get_grains"]()
    except Exception:  # pylint: disable=broad-except
        log.error("Failed to collect saltext_uci proxy grains", exc_info=True)
    return GRAINS_CACHE


def proxy_functions(proxy=None):
    """
    Collect grains from the OpenWrt device via the proxy module
    and override core grains that would otherwise leak proxy-host
    information.

    Only values actually collected from the device are populated.
    Everything else is set to empty to prevent host contamination.
    """
    device = _device_grains(proxy)
    if not device:
        return {}

    version = device.get("os_version", "")
    sys_path = device.get("systempath", [])

    grains = {
        # ---- device grains collected over SSH ----
        "os": device.get("os", "OpenWrt"),
        "os_version": version,
        "os_revision": device.get("os_revision", ""),
        "os_target": device.get("os_target", ""),
        "os_arch": device.get("os_arch", ""),
        "model": device.get("model", ""),
        "board_name": device.get("board_name", ""),
        "hostname": device.get("hostname", ""),
        "mem_total_kb": device.get("mem_total_kb", 0),
        "mem_total": device.get("mem_total_kb", 0) // 1024,
        "flash_total_kb": device.get("flash_total_kb", 0),
        "flash_used_kb": device.get("flash_used_kb", 0),
        "kernelrelease": device.get("kernelrelease", ""),
        "kernelversion": device.get("kernelrelease", ""),
        "cpuarch": device.get("cpuarch", device.get("os_arch", "")),
        "systempath": sys_path,
        "path": ":".join(sys_path),
        # ---- derived from device data ----
        "os_family": device.get("os", "OpenWrt"),
        "osfullname": device.get("os", "OpenWrt"),
        "osrelease": version,
        "osrelease_info": tuple(int(p) for p in version.split(".") if p.isdigit()),
        "osfinger": f"{device.get('os', 'OpenWrt')}-{version}",
        "osarch": device.get("os_arch", device.get("cpuarch", "")),
        "nodename": device.get("hostname", ""),
        "kernel": "Linux",
        # ---- emptied: not from device, must not show host values ----
        "oscodename": "",
        "kernelparams": [],
        "cwd": "/",
        "locale_info": {},
        "machine_id": "",
        "virtual": "",
        "virtual_subtype": "",
        "num_cpus": 0,
        "num_gpus": 0,
        "gpus": [],
        "ps": "",
        "transactional": False,
        "efi": False,
        "efi-secure-boot": False,
        "dns": {},
        "fqdns": [],
        "hwaddr_interfaces": {},
        "ip4_gw": False,
        "ip6_gw": False,
        "ip_gw": False,
        "ip4_interfaces": {},
        "ip6_interfaces": {},
        "ipv4": [],
        "ipv6": [],
    }

    return grains


def shell(proxy=None):  # pylint: disable=unused-argument
    """
    Override extra.py shell() which returns the proxy host's shell.

    .. note::

        Salt's built-in ``extra.py`` may override this after extension
        grains are merged.  If ``shell`` still shows the host value,
        use a static grain file instead.
    """
    return {"shell": "/bin/ash"}
