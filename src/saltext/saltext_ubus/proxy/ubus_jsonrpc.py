"""
Salt proxy module for OpenWrt devices via ubus JSON-RPC.

Connects to the device's uhttpd JSON-RPC endpoint and provides
OpenWrt configuration management through the ubus API.

.. code-block:: yaml

    # /srv/salt/pillar/router.sls
    proxy:
      proxytype: saltext_ubus_jsonrpc
      host: 10.35.24.1
      password: secret
      # username: salt-agent   (default)
      # port: 443              (default)
      # verify_ssl: false      (default)
      # timeout: 30            (default)
"""

import logging
import urllib.error

from saltext.saltext_ubus.utils.rpc import UbusRpcClient

log = logging.getLogger(__name__)

__virtualname__ = "saltext_ubus_jsonrpc"
__proxyenabled__ = ["saltext_ubus_jsonrpc"]

DETAILS = {}

# rpcd's compiled-in default is 300s. Sessions shorter than this cause
# staged UCI changes to be lost between state runs.
MIN_SESSION_TIMEOUT = 300


def __virtual__():
    return __virtualname__


def init(opts):
    """Create JSON-RPC client from proxy pillar and authenticate."""
    DETAILS.clear()
    proxy_conf = opts["proxy"]
    for key in ("host", "password"):
        if key not in proxy_conf:
            raise ValueError(f"saltext_ubus_jsonrpc: required pillar key '{key}' is missing")
    client = UbusRpcClient(
        host=proxy_conf["host"],
        username=proxy_conf.get("username", "salt-agent"),
        password=proxy_conf["password"],
        port=proxy_conf.get("port", 443),
        verify_ssl=proxy_conf.get("verify_ssl", False),
        timeout=proxy_conf.get("timeout", 30),
        session_timeout=MIN_SESSION_TIMEOUT,
    )
    client.login()
    if client.session_timeout < MIN_SESSION_TIMEOUT:
        log.warning(
            "rpcd granted session timeout of %ds (requested %ds). "
            "Staged UCI changes may be lost between state runs.",
            client.session_timeout,
            MIN_SESSION_TIMEOUT,
        )
    DETAILS["client"] = client
    DETAILS["grains_cache"] = _fetch_grains(client)
    DETAILS["initialized"] = True
    log.info("saltext_ubus_jsonrpc proxy initialized for %s", proxy_conf["host"])


def alive(opts):  # pylint: disable=unused-argument
    """Return True if the proxy was initialized and no transport error has occurred.

    This is a flag-based check (no network I/O). Transport errors in
    ``call()`` or ``ping()`` flip ``initialized`` to False so that Salt
    triggers ``init()`` on the next cycle.
    """
    return DETAILS.get("initialized", False)


def ping():
    """Return True if the device responds to a system.board call."""
    try:
        DETAILS["client"].call("system", "board")
        return True
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.warning("Transport error during ping: %s", exc)
        DETAILS["initialized"] = False
        return False
    except Exception:  # pylint: disable=broad-exception-caught
        return False


def shutdown(opts):  # pylint: disable=unused-argument
    """Clean up proxy state."""
    DETAILS.clear()
    log.info("saltext_ubus_jsonrpc proxy shut down")


def grains():
    """Return cached device grains."""
    return DETAILS.get("grains_cache", {})


def grains_refresh():
    """Re-fetch grains from the device."""
    if "client" in DETAILS:
        DETAILS["grains_cache"] = _fetch_grains(DETAILS["client"])
    return grains()


def call(ubus_object, ubus_method, params=None):
    """Forward a ubus call through the proxy's RPC client."""
    try:
        return DETAILS["client"].call(ubus_object, ubus_method, params)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.warning("Transport error during ubus call %s.%s: %s", ubus_object, ubus_method, exc)
        DETAILS["initialized"] = False
        raise


def _fetch_grains(client):
    """Build grains dict from system.board and system.info responses."""
    grains_data = {}

    try:
        board = client.call("system", "board")
        if board:
            release = board.get("release", {})
            grains_data["os"] = release.get("distribution", "OpenWrt")
            grains_data["os_family"] = "OpenWrt"
            grains_data["osrelease"] = release.get("version", "")
            grains_data["oscodename"] = release.get("revision", "")
            grains_data["osfullname"] = release.get("description", "")
            grains_data["kernel"] = board.get("kernel", "")
            grains_data["kernelrelease"] = board.get("kernel", "")
            grains_data["model"] = board.get("model", "")
            grains_data["board_name"] = board.get("board_name", "")
            if board.get("system"):
                grains_data["cpuarch"] = board["system"]
            hostname = board.get("hostname", "")
            if hostname:
                grains_data["host"] = hostname
                grains_data["nodename"] = hostname
                grains_data["fqdn"] = hostname
                if "." in hostname:
                    parts = hostname.split(".", 1)
                    grains_data["domain"] = parts[1]
    except Exception as exc:  # pylint: disable=broad-exception-caught
        log.warning("Failed to fetch system.board grains: %s", exc)

    try:
        info = client.call("system", "info")
        if info:
            grains_data["mem_total"] = info.get("memory", {}).get("total", 0) // 1024
            grains_data["uptime"] = info.get("uptime", 0)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        log.warning("Failed to fetch system.info grains: %s", exc)

    return grains_data
