"""
Salt execution module for OpenWrt UCI configuration via ubus JSON-RPC.

Requires the saltext_uci proxy module to be configured and running.

UCI metadata fields are returned with underscore prefixes to avoid
collision with UCI option names:
  .type -> _type, .name -> _name, .anonymous -> _anonymous, .index -> _index
"""

import logging

log = logging.getLogger(__name__)

__virtualname__ = "saltext_uci"
__proxyenabled__ = ["saltext_uci_ubus"]

__func_alias__ = {
    "set_": "set",
    "apply_": "apply",
}


def __virtual__():
    if "proxy" not in __opts__:
        return False, "Not a proxy minion"
    if __opts__.get("proxy", {}).get("proxytype") != "saltext_uci_ubus":
        return False, "proxytype is not saltext_uci_ubus"
    return __virtualname__


def _call(ubus_object, ubus_method, params=None):
    """Forward a ubus call through the proxy module."""
    return __proxy__["saltext_uci_ubus.call"](ubus_object, ubus_method, params)


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
    Read UCI configuration.

    Returns the full config, a single section, or a single option value.
    UCI metadata fields (.type, .name, .anonymous, .index) are returned
    with underscore prefixes (_type, _name, _anonymous, _index).

    CLI Example:

    .. code-block:: bash

        salt austru saltext_uci.get network
        salt austru saltext_uci.get network lan
        salt austru saltext_uci.get network lan proto
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
        # ubus wraps single-section results in "values" too
        data = result.get("values", result)
        return _transform_section(data)

    # Full config: transform each section
    values = result.get("values", {})
    return {name: _transform_section(data) for name, data in values.items()}


def configs():
    """
    List available UCI configuration packages.

    CLI Example:

    .. code-block:: bash

        salt austru saltext_uci.configs
    """
    result = _call("uci", "configs")
    return result.get("configs", [])


def changes(config):
    """
    Show uncommitted changes for a UCI package.

    Returns a list of pending change tuples, or an empty list if no
    changes are staged.

    CLI Example:

    .. code-block:: bash

        salt austru saltext_uci.changes network
    """
    result = _call("uci", "changes", {"config": config})
    return result.get("changes", [])


# --- Write operations ---


def set_(config, section, values):
    """
    Set UCI option values on an existing section.

    Args:
        config: UCI package name (e.g., 'network').
        section: Section name (e.g., 'lan').
        values: Dict of option names to values.

    CLI Example:

    .. code-block:: bash

        salt austru saltext_uci.set network lan '{"proto": "static"}'
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

    Args:
        config: UCI package name.
        type_: UCI section type (e.g., 'interface').
        name: Optional section name. If omitted, creates anonymous section.
        values: Optional dict of initial option values.

    CLI Example:

    .. code-block:: bash

        salt austru saltext_uci.add network interface name=wan2
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

        salt austru saltext_uci.delete network wan2
        salt austru saltext_uci.delete network lan dns
    """
    params = {"config": config, "section": section}
    if option is not None:
        params["option"] = option
    return _call("uci", "delete", params)


# --- Apply operations ---


def apply_(rollback=90):  # pylint: disable=redefined-outer-name
    """
    Commit and apply UCI changes with rollback safety.

    Changes are committed to /etc/config and daemons are reloaded.
    If confirm() is not called within the rollback timeout, changes
    are automatically reverted.

    Args:
        rollback: Rollback timeout in seconds (default 90).

    CLI Example:

    .. code-block:: bash

        salt austru saltext_uci.apply
        salt austru saltext_uci.apply rollback=120
    """
    return _call("uci", "apply", {"rollback": True, "timeout": rollback})


def confirm():
    """
    Confirm a pending apply, locking in the changes.

    Must be called after apply() within the rollback timeout,
    otherwise changes are automatically reverted.

    CLI Example:

    .. code-block:: bash

        salt austru saltext_uci.confirm
    """
    return _call("uci", "confirm", {})


def rollback():
    """
    Manually trigger a rollback of the last apply.

    CLI Example:

    .. code-block:: bash

        salt austru saltext_uci.rollback
    """
    return _call("uci", "rollback", {})


def revert(config):
    """
    Discard staged (uncommitted) changes for a UCI package.

    CLI Example:

    .. code-block:: bash

        salt austru saltext_uci.revert network
    """
    return _call("uci", "revert", {"config": config})


def commit(config):
    """
    Commit staged changes to /etc/config without reloading daemons.

    Use this to persist changes without triggering a service reload.
    For commit + reload with rollback safety, use ``apply`` instead.

    Args:
        config: UCI package name (e.g., 'network').

    CLI Example:

    .. code-block:: bash

        salt austru saltext_uci.commit network
    """
    return _call("uci", "commit", {"config": config})


def state(config, section=None):
    """
    Return runtime-merged UCI state (defaults + config + overrides).

    Unlike ``get`` which reads /tmp/.uci (staged) or /etc/config (saved),
    ``state`` returns the merged view that running daemons see.

    Args:
        config: UCI package name (e.g., 'network').
        section: Optional section name to narrow the query.

    CLI Example:

    .. code-block:: bash

        salt austru saltext_uci.state network
        salt austru saltext_uci.state network lan
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

        salt austru saltext_uci.system_board
    """
    return _call("system", "board")


def system_info():
    """
    Return system info (memory, uptime, load).

    CLI Example:

    .. code-block:: bash

        salt austru saltext_uci.system_info
    """
    return _call("system", "info")


def network_dump():
    """
    Return network interface state.

    CLI Example:

    .. code-block:: bash

        salt austru saltext_uci.network_dump
    """
    return _call("network.interface", "dump")
