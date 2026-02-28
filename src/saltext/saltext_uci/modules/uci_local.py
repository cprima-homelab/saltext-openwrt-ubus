"""
Salt execution module for OpenWrt UCI configuration via local ubus.

For devices with Python3 and ubusd running, managed via salt-ssh.
Calls ``ubus call`` directly via subprocess -- no proxy module needed.

The JSON output is identical to what the JSON-RPC and SSH adapters
return, so the state module works unchanged.

UCI metadata fields are returned with underscore prefixes to avoid
collision with UCI option names::

    .type -> _type, .name -> _name, .anonymous -> _anonymous, .index -> _index
"""

import json
import logging
import subprocess

import salt.utils.path
from salt.exceptions import CommandExecutionError

log = logging.getLogger(__name__)

__virtualname__ = "saltext_uci"

__func_alias__ = {
    "set_": "set",
    "apply_": "apply",
}


def __virtual__():
    if __opts__.get("proxy"):
        return False, "Running as proxy minion -- use the proxy execution module instead"
    if not salt.utils.path.which("ubus"):
        return False, "ubus binary not found"
    return __virtualname__


def _call(ubus_object, ubus_method, params=None):
    """Execute a local ubus call and return parsed JSON."""
    args = ["ubus", "call", ubus_object, ubus_method]
    if params is not None:
        args.append(json.dumps(params))

    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    if result.returncode != 0:
        raise CommandExecutionError(
            f"ubus call {ubus_object} {ubus_method} failed "
            f"(rc={result.returncode}): {result.stderr.strip()}"
        )

    output = result.stdout.strip()
    if not output:
        return None
    return json.loads(output)


def _transform_section(data):
    """Transform UCI dot-prefixed metadata to underscore-prefixed."""
    result = {}
    for key, value in data.items():
        if key.startswith("."):
            result["_" + key[1:]] = value
        else:
            result[key] = value
    return result


# --- Read operations ---


def get(config, section=None, option=None):
    """
    Read UCI configuration via local ``ubus call uci get``.

    Returns the full config, a single section, or a single option value.
    UCI metadata fields (.type, .name, .anonymous, .index) are returned
    with underscore prefixes (_type, _name, _anonymous, _index).

    CLI Example:

    .. code-block:: bash

        salt device saltext_uci.get network
        salt device saltext_uci.get network lan
        salt device saltext_uci.get network lan proto
    """
    params = {"config": config}
    if section is not None:
        params["section"] = section
    if option is not None:
        params["option"] = option

    result = _call("uci", "get", params)

    if option is not None:
        return result.get("value")

    if section is not None:
        data = result.get("values", result)
        return _transform_section(data)

    values = result.get("values", {})
    return {name: _transform_section(data) for name, data in values.items()}


def configs():
    """
    List available UCI configuration packages.

    CLI Example:

    .. code-block:: bash

        salt device saltext_uci.configs
    """
    result = _call("uci", "configs")
    return result.get("configs", [])


def changes(config):
    """
    Show uncommitted changes for a UCI package.

    CLI Example:

    .. code-block:: bash

        salt device saltext_uci.changes network
    """
    result = _call("uci", "changes", {"config": config})
    return result.get("changes", [])


# --- Write operations ---


def set_(config, section, values):
    """
    Set UCI option values on an existing section.

    CLI Example:

    .. code-block:: bash

        salt device saltext_uci.set network lan '{"proto": "static"}'
    """
    return _call(
        "uci",
        "set",
        {
            "config": config,
            "section": section,
            "values": values,
        },
    )


def add(config, type_, name=None, values=None):
    """
    Add a new UCI section.

    CLI Example:

    .. code-block:: bash

        salt device saltext_uci.add network interface name=wan2
    """
    params = {"config": config, "type": type_}
    if name is not None:
        params["name"] = name
    if values is not None:
        params["values"] = values
    return _call("uci", "add", params)


def delete(config, section, option=None):
    """
    Delete a UCI section or option.

    CLI Example:

    .. code-block:: bash

        salt device saltext_uci.delete network wan2
        salt device saltext_uci.delete network lan dns
    """
    params = {"config": config, "section": section}
    if option is not None:
        params["option"] = option
    return _call("uci", "delete", params)


# --- Apply operations ---


def apply_(rollback=90):  # pylint: disable=redefined-outer-name
    """
    Commit and apply UCI changes with rollback safety.

    CLI Example:

    .. code-block:: bash

        salt device saltext_uci.apply
        salt device saltext_uci.apply rollback=120
    """
    return _call("uci", "apply", {"rollback": True, "timeout": rollback})


def confirm():
    """
    Confirm a pending apply, locking in the changes.

    CLI Example:

    .. code-block:: bash

        salt device saltext_uci.confirm
    """
    return _call("uci", "confirm", {})


def rollback():
    """
    Manually trigger a rollback of the last apply.

    CLI Example:

    .. code-block:: bash

        salt device saltext_uci.rollback
    """
    return _call("uci", "rollback", {})


def revert(config):
    """
    Discard staged (uncommitted) changes for a UCI package.

    CLI Example:

    .. code-block:: bash

        salt device saltext_uci.revert network
    """
    return _call("uci", "revert", {"config": config})


def commit(config):
    """
    Commit staged changes to /etc/config without reloading daemons.

    CLI Example:

    .. code-block:: bash

        salt device saltext_uci.commit network
    """
    return _call("uci", "commit", {"config": config})


def state(config, section=None):
    """
    Return runtime-merged UCI state (defaults + config + overrides).

    CLI Example:

    .. code-block:: bash

        salt device saltext_uci.state network
        salt device saltext_uci.state network lan
    """
    params = {"config": config}
    if section is not None:
        params["section"] = section
    result = _call("uci", "state", params)

    if section is not None:
        data = result.get("values", result)
        return _transform_section(data)

    values = result.get("values", {})
    return {name: _transform_section(data) for name, data in values.items()}


# --- System info ---


def system_board():
    """
    Return system board information.

    CLI Example:

    .. code-block:: bash

        salt device saltext_uci.system_board
    """
    return _call("system", "board")


def system_info():
    """
    Return system info (memory, uptime, load).

    CLI Example:

    .. code-block:: bash

        salt device saltext_uci.system_info
    """
    return _call("system", "info")


def network_dump():
    """
    Return network interface state.

    CLI Example:

    .. code-block:: bash

        salt device saltext_uci.network_dump
    """
    return _call("network.interface", "dump")
