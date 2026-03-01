"""
Shared ubus operations for all execution module adapters.

Each adapter (JSON-RPC, SSH, local) provides its own ``_call()`` function
that handles transport. The functions here implement the common
post-processing logic that is identical regardless of transport.
"""


def transform_section(data):
    """Transform UCI dot-prefixed metadata to underscore-prefixed."""
    result = {}
    for key, value in data.items():
        if key.startswith("."):
            result["_" + key[1:]] = value
        else:
            result[key] = value
    return result


# --- Read operations ---


def get(call, config, section=None, option=None):
    """Read UCI configuration via ubus."""
    params = {"config": config}
    if section is not None:
        params["section"] = section
    if option is not None:
        params["option"] = option

    result = call("uci", "get", params)

    if option is not None:
        return result.get("value")

    if section is not None:
        data = result.get("values", result)
        return transform_section(data)

    values = result.get("values", {})
    return {name: transform_section(data) for name, data in values.items()}


def configs(call):
    """List available UCI configuration packages."""
    result = call("uci", "configs")
    return result.get("configs", [])


def changes(call, config):
    """Show uncommitted changes for a UCI package."""
    result = call("uci", "changes", {"config": config})
    return result.get("changes", [])


# --- Write operations ---


def set_(call, config, section, values):
    """Set UCI option values on an existing section."""
    return call(
        "uci",
        "set",
        {
            "config": config,
            "section": section,
            "values": values,
        },
    )


def add(call, config, type_, name=None, values=None):
    """Add a new UCI section."""
    params = {"config": config, "type": type_}
    if name is not None:
        params["name"] = name
    if values is not None:
        params["values"] = values
    return call("uci", "add", params)


def delete(call, config, section, option=None):
    """Delete a UCI section or option."""
    params = {"config": config, "section": section}
    if option is not None:
        params["option"] = option
    return call("uci", "delete", params)


# --- Apply operations ---


def apply_(call, timeout=90):
    """Commit and apply UCI changes with rollback safety."""
    return call("uci", "apply", {"rollback": True, "timeout": timeout})


def confirm(call):
    """Confirm a pending apply, locking in the changes."""
    return call("uci", "confirm", {})


def rollback(call):
    """Manually trigger a rollback of the last apply."""
    return call("uci", "rollback", {})


def revert(call, config):
    """Discard staged (uncommitted) changes for a UCI package."""
    return call("uci", "revert", {"config": config})


def commit(call, config):
    """Commit staged changes to /etc/config without reloading daemons."""
    return call("uci", "commit", {"config": config})


def state(call, config, section=None):
    """Return runtime-merged UCI state (defaults + config + overrides)."""
    params = {"config": config}
    if section is not None:
        params["section"] = section
    result = call("uci", "state", params)

    if section is not None:
        data = result.get("values", result)
        return transform_section(data)

    values = result.get("values", {})
    return {name: transform_section(data) for name, data in values.items()}


# --- System info ---


def system_board(call):
    """Return system board information."""
    return call("system", "board")


def system_info(call):
    """Return system info (memory, uptime, load)."""
    return call("system", "info")


def network_dump(call):
    """Return network interface state."""
    return call("network.interface", "dump")


# --- Service info ---


def service_list(call, verbose=False):
    """Return procd service list. Use verbose=True to include triggers."""
    params = {"verbose": True} if verbose else None
    return call("service", "list", params)
