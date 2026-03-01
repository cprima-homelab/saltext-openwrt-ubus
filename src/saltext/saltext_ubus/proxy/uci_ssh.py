"""
Salt proxy module for OpenWrt devices via SSH.

Alternative to the ubus JSON-RPC proxy for devices where SSH is
available but uhttpd/rpcd may not be. Runs ``ubus call`` commands
over SSH and parses the JSON output -- the same structured data
as the JSON-RPC adapter.

.. code-block:: yaml

    # /srv/salt/pillar/router.sls
    proxy:
      proxytype: saltext_ubus_ssh
      host: 10.35.24.1
      # username: root                          (default)
      # port: 22                                (default)
      # timeout: 30                             (default)
      ssh_key: /root/.ssh/openwrt_ed25519
      # ssh_options:                            (defaults below)
      #   - StrictHostKeyChecking=no
      #   - UserKnownHostsFile=/dev/null
      #   - HostKeyAlgorithms=+ssh-rsa
      #   - PubkeyAcceptedAlgorithms=+ssh-rsa

When ``ssh_options`` is explicitly set in pillar, it fully replaces
the defaults (no merging). When ``ssh_key`` is set, an
``IdentityFile=<path>`` entry is prepended to the options list.
"""

import json
import logging
import shlex
import subprocess

from saltext.saltext_ubus.utils.ssh import SshCommandError
from saltext.saltext_ubus.utils.ssh import SshRunner

log = logging.getLogger(__name__)

_DEFAULT_SSH_OPTIONS = [
    "StrictHostKeyChecking=no",
    "UserKnownHostsFile=/dev/null",
    "HostKeyAlgorithms=+ssh-rsa",
    "PubkeyAcceptedAlgorithms=+ssh-rsa",
]

__virtualname__ = "saltext_ubus_ssh"
__proxyenabled__ = ["saltext_ubus_ssh"]

DETAILS = {}


def __virtual__():
    return __virtualname__


def init(opts):
    """Create SSH runner from proxy pillar and verify connectivity."""
    DETAILS.clear()
    proxy_conf = opts["proxy"]
    for key in ("host", "ssh_key"):
        if key not in proxy_conf:
            raise ValueError(f"saltext_ubus_ssh: required pillar key '{key}' is missing")
    ssh_options = proxy_conf.get("ssh_options", list(_DEFAULT_SSH_OPTIONS))
    ssh_key = proxy_conf["ssh_key"]
    ssh_options = [f"IdentityFile={ssh_key}"] + ssh_options
    runner = SshRunner(
        host=proxy_conf["host"],
        username=proxy_conf.get("username", "root"),
        port=proxy_conf.get("port", 22),
        ssh_options=ssh_options,
        timeout=proxy_conf.get("timeout", 30),
    )
    if not runner.test_connection():
        raise ConnectionError(f"Cannot connect to {proxy_conf['host']} via SSH")
    DETAILS["runner"] = runner
    DETAILS["grains_cache"] = _fetch_grains(runner)
    DETAILS["initialized"] = True
    log.info("saltext_ubus_ssh proxy initialized for %s", proxy_conf["host"])


def alive(opts):  # pylint: disable=unused-argument
    """Return True if the proxy was initialized and no transport error has occurred.

    This is a flag-based check (no network I/O). Transport errors in
    ``call()``, ``run_raw()``, or ``ping()`` flip ``initialized`` to
    False so that Salt triggers ``init()`` on the next cycle.
    """
    return DETAILS.get("initialized", False)


def ping():
    """Return True if the device responds to an echo over SSH."""
    try:
        runner = DETAILS["runner"]
        result = runner.test_connection()
        if not result:
            log.warning("SSH ping failed for %s", runner.host)
            DETAILS["initialized"] = False
        return result
    except Exception:  # pylint: disable=broad-exception-caught
        DETAILS["initialized"] = False
        return False


def shutdown(opts):  # pylint: disable=unused-argument
    """Clean up proxy state."""
    DETAILS.clear()
    log.info("saltext_ubus_ssh proxy shut down")


def grains():
    """Return cached device grains."""
    return DETAILS.get("grains_cache", {})


def grains_refresh():
    """Re-fetch grains from the device via SSH."""
    if "runner" in DETAILS:
        DETAILS["grains_cache"] = _fetch_grains(DETAILS["runner"])
    return grains()


def call(ubus_object, ubus_method, params=None):
    """Execute a ubus call over SSH and return parsed JSON.

    Args:
        ubus_object: ubus object path (e.g., ``"uci"``, ``"system"``).
        ubus_method: Method name (e.g., ``"get"``, ``"board"``).
        params: Dict of method parameters (default None).

    Returns:
        The parsed JSON response as a dict, or None if the command
        produces no output.

    Raises:
        SshCommandError: If the remote command exits non-zero.
    """
    cmd = f"ubus call {ubus_object} {ubus_method}"
    if params is not None:
        cmd += f" {shlex.quote(json.dumps(params))}"

    runner = DETAILS["runner"]
    try:
        output = runner.run(cmd)
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.warning("Transport error during SSH command '%s': %s", cmd, exc)
        DETAILS["initialized"] = False
        raise
    except SshCommandError as exc:
        if exc.returncode == 255:
            log.warning("SSH connection failure during '%s': %s", cmd, exc)
            DETAILS["initialized"] = False
        raise

    if not output:
        return None
    return json.loads(output)


def run_raw(command):
    """Execute an arbitrary command over SSH and return stdout.

    Useful for non-ubus commands like ``reload_config``.
    """
    runner = DETAILS["runner"]
    try:
        return runner.run(command)
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.warning("Transport error during SSH command '%s': %s", command, exc)
        DETAILS["initialized"] = False
        raise
    except SshCommandError as exc:
        if exc.returncode == 255:
            log.warning("SSH connection failure during '%s': %s", command, exc)
            DETAILS["initialized"] = False
        raise


def _fetch_grains(runner):
    """Build grains dict from system.board and system.info responses."""
    grains_data = {}

    try:
        board_output = runner.run("ubus call system board")
        board = json.loads(board_output) if board_output else None
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
        info_output = runner.run("ubus call system info")
        info = json.loads(info_output) if info_output else None
        if info:
            grains_data["mem_total"] = info.get("memory", {}).get("total", 0) // 1024
            grains_data["uptime"] = info.get("uptime", 0)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        log.warning("Failed to fetch system.info grains: %s", exc)

    return grains_data
