"""
Salt execution module for OpenWrt UCI configuration.

Provides idempotent read/write access to UCI options on OpenWrt targets.
Supports two modes:

- **Direct mode**: via salt-ssh thin client, uses ``cmd.run_all``
  (requires Python on the target).
- **Proxy mode**: via the saltext_uci proxy minion, uses ``__proxy__``
  to SSH from the master (no Python needed on the target).

.. versionadded:: 0.1.0
"""

import logging
import shlex

import salt.exceptions
import salt.utils.path

from saltext.saltext_uci.utils.uci_parser import _unquote

log = logging.getLogger(__name__)

__virtualname__ = "saltext_uci"
__func_alias__ = {"set_": "set"}


def __virtual__():
    """
    Load unconditionally when running under a proxy minion.
    Otherwise, only load if the ``uci`` binary is available on the target.
    """
    if "proxy" in __opts__ and __opts__.get("proxy", {}).get("proxytype") == "saltext_uci":
        return __virtualname__
    if salt.utils.path.which("uci") is None:
        return (False, "The 'uci' binary was not found on the target")
    return __virtualname__


def _run(cmd, ignore_retcode=True):
    """
    Run a UCI command and return a ``cmd.run_all``-style dict.

    Routes through the proxy module when running under a proxy minion,
    otherwise uses ``cmd.run_all`` directly on the target.
    """
    if "__proxy__" in globals() and "saltext_uci.cmd" in __proxy__:
        return __proxy__["saltext_uci.cmd"](cmd)
    return __salt__["cmd.run_all"](cmd, ignore_retcode=ignore_retcode)


def get(key):
    """
    Get a single UCI option value.

    Returns the value as a string, or ``None`` if the key does not exist.
    For list options, returns a list of strings.

    Args:
        key: UCI path (e.g., ``network.lan.ipaddr``)

    CLI Example:

    .. code-block:: bash

        salt-ssh '*' saltext_uci.get network.lan.ipaddr
    """
    ret = _run(f"uci get {shlex.quote(key)}")
    if ret["retcode"] != 0:
        return None
    stdout = ret["stdout"].strip()
    if not stdout:
        return ""
    # uci get returns list values space-separated on one line.
    # We cannot distinguish a multi-word scalar from a list here;
    # callers who know the schema can split if needed.
    return stdout


def get_all(package, section):
    """
    Get all options for a named UCI section as a dict.

    Args:
        package: UCI package name (e.g., ``network``)
        section: UCI section name (e.g., ``lan``)

    Returns:
        Dict of option names to values (scalars as strings, lists as
        space-separated strings matching ``uci show`` output), with an
        additional ``_type`` key for the section type. Returns ``None``
        if the section does not exist.

    CLI Example:

    .. code-block:: bash

        salt-ssh '*' saltext_uci.get_all network lan
    """
    ret = _run(f"uci show {shlex.quote(package + '.' + section)}")
    if ret["retcode"] != 0:
        return None
    return _parse_show_output(ret["stdout"], f"{package}.{section}")


def _parse_show_output(text, prefix):
    """Parse ``uci show <package>.<section>`` output into a dict."""
    result = {}
    for line in text.strip().splitlines():
        if "=" not in line:
            continue
        path, _, raw_value = line.partition("=")
        if path == prefix:
            # Section type declaration: network.lan=interface
            result["_type"] = raw_value
        elif path.startswith(prefix + "."):
            option = path[len(prefix) + 1 :]
            result[option] = _unquote(raw_value)
    return result


def show(package=None):
    """
    Return raw ``uci show`` output for a package or all packages.

    Args:
        package: UCI package name, or ``None`` for all packages.

    CLI Example:

    .. code-block:: bash

        salt-ssh '*' saltext_uci.show network
    """
    cmd = "uci show"
    if package:
        cmd += f" {shlex.quote(package)}"
    ret = _run(cmd)
    if ret["retcode"] != 0:
        return None
    return ret["stdout"]


def set_(key, value):
    """
    Set a UCI option. Idempotent: returns ``False`` if already set.

    Args:
        key: UCI path (e.g., ``network.lan.ipaddr``)
        value: Value to set

    Returns:
        ``True`` if the value was changed, ``False`` if already set.

    CLI Example:

    .. code-block:: bash

        salt-ssh '*' saltext_uci.set network.lan.ipaddr 10.35.24.1
    """
    current = get(key)
    if current == str(value):
        return False
    ret = _run(f"uci set {shlex.quote(key + '=' + str(value))}")
    if ret["retcode"] != 0:
        raise salt.exceptions.CommandExecutionError(f"uci set failed: {ret['stderr'].strip()}")
    return True


def delete(key):
    """
    Delete a UCI option or section. Idempotent via ``-q`` flag.

    Args:
        key: UCI path (e.g., ``network.wan6``)

    Returns:
        ``True`` (always succeeds due to ``-q``).

    CLI Example:

    .. code-block:: bash

        salt-ssh '*' saltext_uci.delete network.wan6
    """
    _run(f"uci -q delete {shlex.quote(key)}")
    return True


def add_list(key, value):
    """
    Add a value to a UCI list option if not already present.

    Args:
        key: UCI path (e.g., ``network.wan.dns``)
        value: Value to add

    Returns:
        ``True`` if added, ``False`` if already present.

    CLI Example:

    .. code-block:: bash

        salt-ssh '*' saltext_uci.add_list network.wan.dns 1.1.1.1
    """
    current = get(key)
    if current is not None:
        current_values = current.split() if current else []
        if str(value) in current_values:
            return False
    ret = _run(f"uci add_list {shlex.quote(key + '=' + str(value))}")
    if ret["retcode"] != 0:
        raise salt.exceptions.CommandExecutionError(f"uci add_list failed: {ret['stderr'].strip()}")
    return True


def set_list(key, values):
    """
    Replace an entire UCI list option. Idempotent: no-op if identical.

    Args:
        key: UCI path (e.g., ``network.wan.dns``)
        values: List of values

    Returns:
        ``True`` if changed, ``False`` if already identical.

    CLI Example:

    .. code-block:: bash

        salt-ssh '*' saltext_uci.set_list network.wan.dns '["1.1.1.1", "1.0.0.1"]'
    """
    current = get(key)
    current_values = current.split() if current else []
    desired = [str(v) for v in values]
    if current_values == desired:
        return False
    _run(f"uci -q delete {shlex.quote(key)}")
    for val in desired:
        ret = _run(f"uci add_list {shlex.quote(key + '=' + val)}")
        if ret["retcode"] != 0:
            raise salt.exceptions.CommandExecutionError(
                f"uci add_list failed: {ret['stderr'].strip()}"
            )
    return True


def commit(package=None):
    """
    Commit staged UCI changes for a package (or all packages).

    Args:
        package: UCI package name, or ``None`` for all.

    Returns:
        ``True`` on success.

    CLI Example:

    .. code-block:: bash

        salt-ssh '*' saltext_uci.commit network
    """
    cmd = "uci commit"
    if package:
        cmd += f" {shlex.quote(package)}"
    ret = _run(cmd, ignore_retcode=False)
    if ret["retcode"] != 0:
        raise salt.exceptions.CommandExecutionError(f"uci commit failed: {ret['stderr'].strip()}")
    return True
