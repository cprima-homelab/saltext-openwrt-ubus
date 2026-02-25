"""
Salt proxy module for OpenWrt UCI configuration over SSH.

Allows managing OpenWrt devices that cannot run Python or the Salt thin
client (e.g., 128 MB RAM routers). The proxy minion runs on the master
and SSHes into the device to execute UCI commands.

Follows the NAPALM proxy pattern: execution modules detect proxy mode
via ``__proxy__`` and route commands through this module instead of
``cmd.run_all``.

Pillar example:

.. code-block:: yaml

    proxy:
      proxytype: saltext_uci
      host: 10.35.24.1
      user: root
      port: 22
      ssh_priv: /root/.ssh/id_ed25519

.. versionadded:: 0.1.0
"""

import logging
import re
import subprocess

log = logging.getLogger(__name__)

__proxyenabled__ = ["saltext_uci"]
__virtualname__ = "saltext_uci"

# Salt injects __context__ at runtime; provide a default for testability.
__context__ = {}


def __virtual__():
    return __virtualname__


def init(opts):
    """
    Read proxy pillar config and store SSH connection details in context.
    """
    proxy_conf = opts.get("proxy", {})
    __context__["saltext_uci"] = {
        "host": proxy_conf["host"],
        "user": proxy_conf.get("user", "root"),
        "port": proxy_conf.get("port", 22),
        "ssh_priv": proxy_conf.get("ssh_priv"),
        "initialized": True,
    }
    log.info(
        "saltext_uci proxy initialized for %s@%s:%s",
        __context__["saltext_uci"]["user"],
        __context__["saltext_uci"]["host"],
        __context__["saltext_uci"]["port"],
    )
    return True


def initialized():
    """Return whether the proxy has been initialized."""
    return __context__.get("saltext_uci", {}).get("initialized", False)


def alive(opts):  # pylint: disable=unused-argument
    """
    Connection check. Always returns True since we use per-call SSH
    (no persistent connection to go stale).
    """
    return True


def ping():
    """
    Test SSH connectivity to the device.
    """
    try:
        ret = cmd("echo ok")
        return ret["retcode"] == 0 and ret["stdout"].strip() == "ok"
    except Exception:  # pylint: disable=broad-except
        return False


def shutdown(opts):  # pylint: disable=unused-argument
    """
    Clean up proxy context. No persistent connections to close.
    """
    __context__.pop("saltext_uci", None)
    return True


def cmd(command):
    """
    Execute a shell command on the remote device via SSH.

    Returns a dict matching the ``cmd.run_all`` format:
    ``{"retcode": int, "stdout": str, "stderr": str, "pid": int}``

    Args:
        command: Shell command to execute on the device.
    """
    conf = __context__["saltext_uci"]
    ssh_cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-p",
        str(conf["port"]),
    ]
    if conf.get("ssh_priv"):
        ssh_cmd += ["-i", conf["ssh_priv"]]
    ssh_cmd += [f"{conf['user']}@{conf['host']}", command]

    log.debug("saltext_uci proxy cmd: %s", " ".join(ssh_cmd))
    result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=30, check=False)
    return {
        "retcode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "pid": result.pid if hasattr(result, "pid") else 0,
    }


_GRAINS_CMD = (
    "cat /etc/openwrt_release 2>/dev/null; echo '---DELIM---'; "
    "cat /tmp/sysinfo/model 2>/dev/null; echo '---DELIM---'; "
    "cat /tmp/sysinfo/board_name 2>/dev/null; echo '---DELIM---'; "
    "uci get system.@system[0].hostname 2>/dev/null; echo '---DELIM---'; "
    "head -1 /proc/meminfo 2>/dev/null; echo '---DELIM---'; "
    "df /overlay 2>/dev/null; echo '---DELIM---'; "
    "uname -r -m 2>/dev/null; echo '---DELIM---'; "
    "echo $PATH 2>/dev/null"
)

_RELEASE_KEYS = {
    "DISTRIB_ID": "os",
    "DISTRIB_RELEASE": "os_version",
    "DISTRIB_REVISION": "os_revision",
    "DISTRIB_TARGET": "os_target",
    "DISTRIB_ARCH": "os_arch",
}


def _parse_grains(output):
    """
    Parse the compound SSH output into a grains dict.

    Each section is separated by ``---DELIM---``.
    """
    sections = output.split("---DELIM---")
    grains = {}

    # Section 0: /etc/openwrt_release
    if len(sections) > 0:
        for line in sections[0].strip().splitlines():
            for key, grain in _RELEASE_KEYS.items():
                if line.startswith(key + "="):
                    grains[grain] = line.split("=", 1)[1].strip().strip("'\"")

    # Section 1: /tmp/sysinfo/model
    if len(sections) > 1:
        val = sections[1].strip()
        if val:
            grains["model"] = val

    # Section 2: /tmp/sysinfo/board_name
    if len(sections) > 2:
        val = sections[2].strip()
        if val:
            grains["board_name"] = val

    # Section 3: hostname
    if len(sections) > 3:
        val = sections[3].strip()
        if val:
            grains["hostname"] = val

    # Section 4: MemTotal from /proc/meminfo
    if len(sections) > 4:
        match = re.search(r"MemTotal:\s+(\d+)\s+kB", sections[4])
        if match:
            grains["mem_total_kb"] = int(match.group(1))

    # Section 5: df /overlay
    if len(sections) > 5:
        lines = sections[5].strip().splitlines()
        if len(lines) >= 2:
            cols = lines[-1].split()
            if len(cols) >= 3:
                try:
                    grains["flash_total_kb"] = int(cols[1])
                    grains["flash_used_kb"] = int(cols[2])
                except (ValueError, IndexError):
                    pass

    # Section 6: uname -r -m  (e.g. "6.6.86 mips")
    if len(sections) > 6:
        parts = sections[6].strip().split()
        if parts:
            grains["kernelrelease"] = parts[0]
        if len(parts) > 1:
            grains["cpuarch"] = parts[1]

    # Section 7: $PATH
    if len(sections) > 7:
        val = sections[7].strip()
        if val:
            grains["systempath"] = val.split(":")

    return grains


def get_grains():
    """
    Collect device grains via a single SSH call.

    Returns a dict of grains. Results are cached in context to avoid
    repeated SSH calls.
    """
    cached = __context__.get("saltext_uci", {}).get("grains_cache")
    if cached is not None:
        return cached

    ret = cmd(_GRAINS_CMD)
    if ret["retcode"] != 0:
        log.warning("saltext_uci grains collection failed: %s", ret["stderr"])
        return {}

    grains = _parse_grains(ret["stdout"])
    __context__.setdefault("saltext_uci", {})["grains_cache"] = grains
    return grains


def grains_refresh():
    """Clear cached grains and re-collect from the device."""
    ctx = __context__.get("saltext_uci", {})
    ctx.pop("grains_cache", None)
    return get_grains()


def fns():
    """Required by Salt grains framework for proxy grains discovery."""
    return {"details": "OpenWrt device grains."}
