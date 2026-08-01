"""
Salt proxy module for OpenWrt devices via ubus JSON-RPC.

Connects to the device's uhttpd JSON-RPC endpoint and provides
OpenWrt configuration management through the ubus API.

.. code-block:: yaml

    # /srv/salt/pillar/router.sls
    proxy:
      proxytype: openwrt_ubus_jsonrpc
      host: 10.35.24.1
      password: secret
      # username: salt-agent      (default)
      # scheme: https             (auto-detected by default: tries plain
      # port: 443                  HTTP on 80 first, falls back to HTTPS on
      #                            443 — set both explicitly to skip probing,
      #                            e.g. for a device behind Caddy/ACME)
      # verify_ssl: false         (default)
      # timeout: 30               (default, HTTP request timeout)
      # session_timeout: 300      (default, rpcd session lifetime)
      # rpcd_timeout: 300         (default, rpcd ubus invoke timeout)
"""

import logging
import time
import urllib.error

from saltext.openwrt_ubus.utils.rpc import UbusRpcClient

log = logging.getLogger(__name__)

__virtualname__ = "openwrt_ubus_jsonrpc"
__proxyenabled__ = ["openwrt_ubus_jsonrpc"]

DETAILS = {}

# rpcd session timeout: how long the login session lives. Staged UCI
# changes are scoped to the session and are lost when it expires.
DEFAULT_SESSION_TIMEOUT = 300

# rpcd ubus invoke timeout: how long rpcd waits for a ubus call to
# return (rpcd.@rpcd[0].timeout UCI setting). Calls like uci apply
# trigger service reloads and can take a while on slow devices.
DEFAULT_RPCD_TIMEOUT = 300


def __virtual__():
    return __virtualname__


def init(opts):
    """Create JSON-RPC client from proxy pillar and authenticate."""
    DETAILS.clear()
    proxy_conf = opts["proxy"]
    for key in ("host", "password"):
        if key not in proxy_conf:
            raise ValueError(f"openwrt_ubus_jsonrpc: required pillar key '{key}' is missing")

    session_timeout = proxy_conf.get("session_timeout", DEFAULT_SESSION_TIMEOUT)
    rpcd_timeout = proxy_conf.get("rpcd_timeout", DEFAULT_RPCD_TIMEOUT)

    client = UbusRpcClient(
        host=proxy_conf["host"],
        username=proxy_conf.get("username", "salt-agent"),
        password=proxy_conf["password"],
        # scheme/port default to None (auto-detect: plain HTTP on 80 first,
        # falling back to HTTPS on 443 — see UbusRpcClient). Set both
        # explicitly in pillar only to skip probing for a nonstandard setup.
        port=proxy_conf.get("port"),
        scheme=proxy_conf.get("scheme"),
        verify_ssl=proxy_conf.get("verify_ssl", False),
        # Set when a reverse proxy in front of the device (e.g. Caddy with a
        # per-domain ACME cert) routes by a specific name that doesn't match
        # `host` — needed for both TLS SNI and the HTTP Host header.
        server_name=proxy_conf.get("server_name"),
        timeout=proxy_conf.get("timeout", 30),
        session_timeout=session_timeout,
    )
    client.login()
    if client.session_timeout < session_timeout:
        log.warning(
            "rpcd granted session timeout of %ds (requested %ds). "
            "Staged UCI changes may be lost between state runs.",
            client.session_timeout,
            session_timeout,
        )
    _ensure_rpcd_timeout(client, rpcd_timeout)
    DETAILS["client"] = client
    DETAILS["grains_cache"] = _fetch_grains(client)
    DETAILS["initialized"] = True
    log.info("openwrt_ubus_jsonrpc proxy initialized for %s", proxy_conf["host"])


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
    log.info("openwrt_ubus_jsonrpc proxy shut down")


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


def _ensure_rpcd_timeout(client, desired):
    """Ensure rpcd's ubus invoke timeout is at least ``desired`` seconds.

    The ``rpcd.@rpcd[0].timeout`` UCI setting controls how long rpcd
    waits for a ubus call to complete. Operations like ``uci apply``
    trigger service reloads that can exceed the default 30s on slow
    devices. This reads the current value and bumps it if needed,
    then reloads rpcd and re-authenticates.
    """
    try:
        rpcd_conf = client.call("uci", "get", {"config": "rpcd", "type": "rpcd"})
    except Exception:  # pylint: disable=broad-exception-caught
        log.debug("Could not read rpcd config, skipping invoke timeout check")
        return

    # Find the first rpcd-type section
    values = rpcd_conf.get("values", {})
    section_name = None
    current_timeout = None
    for name, data in values.items():
        if data.get(".type") == "rpcd":
            section_name = name
            try:
                current_timeout = int(data.get("timeout", 30))
            except (ValueError, TypeError):
                current_timeout = 30
            break

    if section_name is None or current_timeout is None:
        return

    if current_timeout >= desired:
        return

    log.info(
        "rpcd invoke timeout is %ds (need %ds), updating",
        current_timeout,
        desired,
    )
    try:
        client.call(
            "uci",
            "set",
            {
                "config": "rpcd",
                "section": section_name,
                "values": {"timeout": str(desired)},
            },
        )
        client.call("uci", "commit", {"config": "rpcd"})
        client.call("uci", "reload_config")
    except Exception:  # pylint: disable=broad-exception-caught
        # reload_config restarts rpcd, which kills our connection
        pass
    time.sleep(2)
    client.login()
    log.info("rpcd invoke timeout updated to %ds", desired)


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
