"""
Salt execution module for OpenWrt configuration via ubus over SSH.

Requires the ``saltext_ubus_ssh`` proxy module to be configured and
running. Delegates all ubus calls through the proxy's ``call()``
function, which runs ``ubus call`` over SSH and returns parsed JSON --
the same structured data as the JSON-RPC adapter.

UCI metadata fields are returned with underscore prefixes to avoid
collision with UCI option names::

    .type -> _type, .name -> _name, .anonymous -> _anonymous, .index -> _index
"""

import logging

log = logging.getLogger(__name__)

__virtualname__ = "saltext_ubus"
__proxyenabled__ = ["saltext_ubus_ssh"]

__func_alias__ = {
    "set_": "set",
    "apply_": "apply",
}


def __virtual__():
    if "proxy" not in __opts__:
        return False, "Not a proxy minion"
    if __opts__.get("proxy", {}).get("proxytype") != "saltext_ubus_ssh":
        return False, "proxytype is not saltext_ubus_ssh"
    return __virtualname__


def _call(ubus_object, ubus_method, params=None):
    """Forward a ubus call through the proxy module."""
    return __proxy__["saltext_ubus_ssh.call"](ubus_object, ubus_method, params)


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
    Read UCI configuration via ``ubus call uci get`` over SSH.

    Returns the full config, a single section, or a single option value.
    UCI metadata fields (.type, .name, .anonymous, .index) are returned
    with underscore prefixes (_type, _name, _anonymous, _index).

    CLI Example:

    .. code-block:: bash

        salt router saltext_ubus.get network
        salt router saltext_ubus.get network lan
        salt router saltext_ubus.get network lan proto
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

        salt router saltext_ubus.configs
    """
    result = _call("uci", "configs")
    return result.get("configs", [])


def changes(config):
    """
    Show uncommitted changes for a UCI package.

    CLI Example:

    .. code-block:: bash

        salt router saltext_ubus.changes network
    """
    result = _call("uci", "changes", {"config": config})
    return result.get("changes", [])


# --- Write operations ---


def set_(config, section, values):
    """
    Set UCI option values on an existing section.

    CLI Example:

    .. code-block:: bash

        salt router saltext_ubus.set network lan '{"proto": "static"}'
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

        salt router saltext_ubus.add network interface name=wan2
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

        salt router saltext_ubus.delete network wan2
        salt router saltext_ubus.delete network lan dns
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

        salt router saltext_ubus.apply
        salt router saltext_ubus.apply rollback=120
    """
    return _call("uci", "apply", {"rollback": True, "timeout": rollback})


def confirm():
    """
    Confirm a pending apply, locking in the changes.

    CLI Example:

    .. code-block:: bash

        salt router saltext_ubus.confirm
    """
    return _call("uci", "confirm", {})


def rollback():
    """
    Manually trigger a rollback of the last apply.

    CLI Example:

    .. code-block:: bash

        salt router saltext_ubus.rollback
    """
    return _call("uci", "rollback", {})


def revert(config):
    """
    Discard staged (uncommitted) changes for a UCI package.

    CLI Example:

    .. code-block:: bash

        salt router saltext_ubus.revert network
    """
    return _call("uci", "revert", {"config": config})


def commit(config):
    """
    Commit staged changes to /etc/config without reloading daemons.

    CLI Example:

    .. code-block:: bash

        salt router saltext_ubus.commit network
    """
    return _call("uci", "commit", {"config": config})


def state(config, section=None):
    """
    Return runtime-merged UCI state (defaults + config + overrides).

    CLI Example:

    .. code-block:: bash

        salt router saltext_ubus.state network
        salt router saltext_ubus.state network lan
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

        salt router saltext_ubus.system_board
    """
    return _call("system", "board")


def system_info():
    """
    Return system info (memory, uptime, load).

    CLI Example:

    .. code-block:: bash

        salt router saltext_ubus.system_info
    """
    return _call("system", "info")


def network_dump():
    """
    Return network interface state.

    CLI Example:

    .. code-block:: bash

        salt router saltext_ubus.network_dump
    """
    return _call("network.interface", "dump")
