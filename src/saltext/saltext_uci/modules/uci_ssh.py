"""
Salt execution module for OpenWrt UCI configuration via SSH.

Alternative to the ubus JSON-RPC execution module for devices that
have Python installed. Executes ``uci`` CLI commands over SSH and
parses the text output into the same dict structure as the JSON-RPC
adapter.

NOT YET IMPLEMENTED. This module exists as a stub to define the
adapter interface. All functions raise ``NotImplementedError``.

The output format must match the JSON-RPC adapter so the state module
(``states/saltext_uci_mod.py``) works unchanged:

- Section metadata: ``_type``, ``_name``, ``_anonymous``
- List options: Python lists
- Scalar options: Python strings
"""

import logging

log = logging.getLogger(__name__)

__virtualname__ = "saltext_uci"
__proxyenabled__ = ["saltext_uci_ssh"]

__func_alias__ = {
    "set_": "set",
    "apply_": "apply",
}


def __virtual__():
    if "proxy" not in __opts__:
        return False, "Not a proxy minion"
    if __opts__.get("proxy", {}).get("proxytype") != "saltext_uci_ssh":
        return False, "proxytype is not saltext_uci_ssh"
    return __virtualname__


# --- Read operations ---


def get(config, section=None, option=None):
    """
    Read UCI configuration via ``uci show`` / ``uci get`` over SSH.

    Must return the same dict structure as the JSON-RPC adapter:
    underscore-prefixed metadata (``_type``, ``_name``, ``_anonymous``)
    alongside UCI option values.

    CLI Example:

    .. code-block:: bash

        salt router saltext_uci.get network
        salt router saltext_uci.get network lan
        salt router saltext_uci.get network lan proto
    """
    raise NotImplementedError("SSH execution module is not yet implemented.")


def configs():
    """
    List available UCI configuration packages via ``uci show`` over SSH.

    CLI Example:

    .. code-block:: bash

        salt router saltext_uci.configs
    """
    raise NotImplementedError("SSH execution module is not yet implemented.")


def changes(config):
    """
    Show uncommitted changes via ``uci changes`` over SSH.

    CLI Example:

    .. code-block:: bash

        salt router saltext_uci.changes network
    """
    raise NotImplementedError("SSH execution module is not yet implemented.")


# --- Write operations ---


def set_(config, section, values):
    """
    Set UCI option values via ``uci set`` over SSH.

    CLI Example:

    .. code-block:: bash

        salt router saltext_uci.set network lan '{"proto": "static"}'
    """
    raise NotImplementedError("SSH execution module is not yet implemented.")


def add(config, type_, name=None, values=None):
    """
    Add a new UCI section via ``uci add`` / ``uci rename`` over SSH.

    CLI Example:

    .. code-block:: bash

        salt router saltext_uci.add network interface name=wan2
    """
    raise NotImplementedError("SSH execution module is not yet implemented.")


def delete(config, section, option=None):
    """
    Delete a UCI section or option via ``uci delete`` over SSH.

    CLI Example:

    .. code-block:: bash

        salt router saltext_uci.delete network wan2
    """
    raise NotImplementedError("SSH execution module is not yet implemented.")


# --- Apply operations ---


def apply_(rollback=90):  # pylint: disable=redefined-outer-name
    """
    Commit and apply UCI changes via ``uci commit`` + service reload.

    Note: the SSH adapter cannot use ubus apply/confirm rollback.
    Rollback safety must be implemented differently (e.g., scheduled
    revert via ``at`` or ``sleep && uci revert`` background job).

    CLI Example:

    .. code-block:: bash

        salt router saltext_uci.apply
    """
    raise NotImplementedError("SSH execution module is not yet implemented.")


def confirm():
    """
    Confirm a pending apply.

    CLI Example:

    .. code-block:: bash

        salt router saltext_uci.confirm
    """
    raise NotImplementedError("SSH execution module is not yet implemented.")


def rollback():
    """
    Manually trigger a rollback.

    CLI Example:

    .. code-block:: bash

        salt router saltext_uci.rollback
    """
    raise NotImplementedError("SSH execution module is not yet implemented.")


def revert(config):
    """
    Discard staged changes via ``uci revert`` over SSH.

    CLI Example:

    .. code-block:: bash

        salt router saltext_uci.revert network
    """
    raise NotImplementedError("SSH execution module is not yet implemented.")


# --- System info ---


def system_board():
    """
    Return system board information via ``/etc/board.json`` or ``ubus call``.

    CLI Example:

    .. code-block:: bash

        salt router saltext_uci.system_board
    """
    raise NotImplementedError("SSH execution module is not yet implemented.")


def system_info():
    """
    Return system info via ``/proc/meminfo``, ``/proc/uptime``, etc.

    CLI Example:

    .. code-block:: bash

        salt router saltext_uci.system_info
    """
    raise NotImplementedError("SSH execution module is not yet implemented.")


def network_dump():
    """
    Return network interface state via ``ubus call network.interface dump``.

    CLI Example:

    .. code-block:: bash

        salt router saltext_uci.network_dump
    """
    raise NotImplementedError("SSH execution module is not yet implemented.")
