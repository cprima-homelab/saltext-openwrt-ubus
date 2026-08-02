"""
Shorthand alias for the ``uci`` execution module.

Provides ``openwrt.<function>`` as a convenience alias so operators
can type either ``openwrt.get`` or ``uci.get``.
"""

__virtualname__ = "openwrt"

__func_alias__ = {
    "set_": "set",
    "apply_": "apply",
}


def __virtual__():
    if "uci.get" not in __salt__:
        return False, "uci module not available"
    return __virtualname__


# --- Read operations ---


def get(config, section=None, option=None):
    """
    Read UCI configuration. Alias for ``uci.get``.

    CLI Example:

    .. code-block:: bash

        salt austru openwrt.get network
        salt austru openwrt.get network lan
        salt austru openwrt.get network lan proto
    """
    return __salt__["uci.get"](config, section, option)


def configs():
    """
    List available UCI configuration packages. Alias for ``uci.configs``.

    CLI Example:

    .. code-block:: bash

        salt austru openwrt.configs
    """
    return __salt__["uci.configs"]()


def changes(config):
    """
    Show uncommitted changes for a UCI package. Alias for ``uci.changes``.

    CLI Example:

    .. code-block:: bash

        salt austru openwrt.changes network
    """
    return __salt__["uci.changes"](config)


def config_export(config, format="json"):  # pylint: disable=redefined-builtin
    """
    Export live UCI config as a grouped sections dict.
    Alias for ``uci.config_export``.

    CLI Example:

    .. code-block:: bash

        salt austru openwrt.config_export network
        salt austru openwrt.config_export network format=pillar
    """
    return __salt__["uci.config_export"](config, format=format)


def config_export_all(format="json"):  # pylint: disable=redefined-builtin
    """
    Export all UCI config packages as a grouped dict.
    Alias for ``uci.config_export_all``.

    CLI Example:

    .. code-block:: bash

        salt austru openwrt.config_export_all
        salt austru openwrt.config_export_all format=pillar
    """
    return __salt__["uci.config_export_all"](format=format)


def config_diff(config, sections):
    """
    Compare live UCI config against declared sections and return drift.
    Alias for ``uci.config_diff``.

    CLI Example:

    .. code-block:: bash

        salt austru openwrt.config_diff network sections='{"lan": {"ipaddr": "10.0.0.2"}}'
    """
    return __salt__["uci.config_diff"](config, sections)


# --- Write operations ---


def set_(config, section, values):
    """
    Set UCI option values on an existing section. Alias for ``uci.set``.

    CLI Example:

    .. code-block:: bash

        salt austru openwrt.set network lan '{"proto": "static"}'
    """
    return __salt__["uci.set"](config, section, values)


def add(config, type_, name=None, values=None):
    """
    Add a new UCI section. Alias for ``uci.add``.

    CLI Example:

    .. code-block:: bash

        salt austru openwrt.add network interface name=wan2
    """
    return __salt__["uci.add"](config, type_, name, values)


def delete(config, section, option=None):
    """
    Delete a UCI section or option. Alias for ``uci.delete``.

    CLI Example:

    .. code-block:: bash

        salt austru openwrt.delete network wan2
    """
    return __salt__["uci.delete"](config, section, option)


# --- Apply operations ---


def apply_(rollback=90):  # pylint: disable=redefined-outer-name
    """
    Commit and apply UCI changes with rollback safety. Alias for ``uci.apply``.

    CLI Example:

    .. code-block:: bash

        salt austru openwrt.apply
        salt austru openwrt.apply rollback=120
    """
    return __salt__["uci.apply"](rollback=rollback)


def confirm():
    """
    Confirm a pending apply. Alias for ``uci.confirm``.

    CLI Example:

    .. code-block:: bash

        salt austru openwrt.confirm
    """
    return __salt__["uci.confirm"]()


def rollback():
    """
    Manually trigger a rollback. Alias for ``uci.rollback``.

    CLI Example:

    .. code-block:: bash

        salt austru openwrt.rollback
    """
    return __salt__["uci.rollback"]()


def revert(config):
    """
    Discard staged changes for a UCI package. Alias for ``uci.revert``.

    CLI Example:

    .. code-block:: bash

        salt austru openwrt.revert network
    """
    return __salt__["uci.revert"](config)


def commit(config):
    """
    Commit staged changes without reloading daemons. Alias for ``uci.commit``.

    CLI Example:

    .. code-block:: bash

        salt austru openwrt.commit network
    """
    return __salt__["uci.commit"](config)


def state(config, section=None):
    """
    Return runtime-merged UCI state. Alias for ``uci.state``.

    CLI Example:

    .. code-block:: bash

        salt austru openwrt.state network
        salt austru openwrt.state network lan
    """
    return __salt__["uci.state"](config, section)


# --- System info ---


def system_board():
    """
    Return system board information. Alias for ``uci.system_board``.

    CLI Example:

    .. code-block:: bash

        salt austru openwrt.system_board
    """
    return __salt__["uci.system_board"]()


def system_info():
    """
    Return system info (memory, uptime, load). Alias for ``uci.system_info``.

    CLI Example:

    .. code-block:: bash

        salt austru openwrt.system_info
    """
    return __salt__["uci.system_info"]()


def network_dump():
    """
    Return network interface state. Alias for ``uci.network_dump``.

    CLI Example:

    .. code-block:: bash

        salt austru openwrt.network_dump
    """
    return __salt__["uci.network_dump"]()


# --- Service info ---


def service_list(verbose=False):
    """
    Return procd service list. Alias for ``uci.service_list``.

    CLI Example:

    .. code-block:: bash

        salt austru openwrt.service_list
        salt austru openwrt.service_list verbose=True
    """
    return __salt__["uci.service_list"](verbose=verbose)
