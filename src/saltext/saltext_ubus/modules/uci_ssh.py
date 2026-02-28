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

from saltext.saltext_ubus.utils import ubus_ops

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
    return ubus_ops.get(_call, config, section, option)


def configs():
    """
    List available UCI configuration packages.

    CLI Example:

    .. code-block:: bash

        salt router saltext_ubus.configs
    """
    return ubus_ops.configs(_call)


def changes(config):
    """
    Show uncommitted changes for a UCI package.

    CLI Example:

    .. code-block:: bash

        salt router saltext_ubus.changes network
    """
    return ubus_ops.changes(_call, config)


# --- Write operations ---


def set_(config, section, values):
    """
    Set UCI option values on an existing section.

    CLI Example:

    .. code-block:: bash

        salt router saltext_ubus.set network lan '{"proto": "static"}'
    """
    return ubus_ops.set_(_call, config, section, values)


def add(config, type_, name=None, values=None):
    """
    Add a new UCI section.

    CLI Example:

    .. code-block:: bash

        salt router saltext_ubus.add network interface name=wan2
    """
    return ubus_ops.add(_call, config, type_, name, values)


def delete(config, section, option=None):
    """
    Delete a UCI section or option.

    CLI Example:

    .. code-block:: bash

        salt router saltext_ubus.delete network wan2
        salt router saltext_ubus.delete network lan dns
    """
    return ubus_ops.delete(_call, config, section, option)


# --- Apply operations ---


def apply_(rollback=90):  # pylint: disable=redefined-outer-name
    """
    Commit and apply UCI changes with rollback safety.

    CLI Example:

    .. code-block:: bash

        salt router saltext_ubus.apply
        salt router saltext_ubus.apply rollback=120
    """
    return ubus_ops.apply_(_call, rollback)


def confirm():
    """
    Confirm a pending apply, locking in the changes.

    CLI Example:

    .. code-block:: bash

        salt router saltext_ubus.confirm
    """
    return ubus_ops.confirm(_call)


def rollback():
    """
    Manually trigger a rollback of the last apply.

    CLI Example:

    .. code-block:: bash

        salt router saltext_ubus.rollback
    """
    return ubus_ops.rollback(_call)


def revert(config):
    """
    Discard staged (uncommitted) changes for a UCI package.

    CLI Example:

    .. code-block:: bash

        salt router saltext_ubus.revert network
    """
    return ubus_ops.revert(_call, config)


def commit(config):
    """
    Commit staged changes to /etc/config without reloading daemons.

    CLI Example:

    .. code-block:: bash

        salt router saltext_ubus.commit network
    """
    return ubus_ops.commit(_call, config)


def state(config, section=None):
    """
    Return runtime-merged UCI state (defaults + config + overrides).

    CLI Example:

    .. code-block:: bash

        salt router saltext_ubus.state network
        salt router saltext_ubus.state network lan
    """
    return ubus_ops.state(_call, config, section)


# --- System info ---


def system_board():
    """
    Return system board information.

    CLI Example:

    .. code-block:: bash

        salt router saltext_ubus.system_board
    """
    return ubus_ops.system_board(_call)


def system_info():
    """
    Return system info (memory, uptime, load).

    CLI Example:

    .. code-block:: bash

        salt router saltext_ubus.system_info
    """
    return ubus_ops.system_info(_call)


def network_dump():
    """
    Return network interface state.

    CLI Example:

    .. code-block:: bash

        salt router saltext_ubus.network_dump
    """
    return ubus_ops.network_dump(_call)
