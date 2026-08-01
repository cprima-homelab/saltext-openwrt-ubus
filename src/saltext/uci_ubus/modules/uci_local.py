"""
Salt execution module for OpenWrt configuration via local ubus.

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

from saltext.uci_ubus._internal import ubus_ops

log = logging.getLogger(__name__)

__virtualname__ = "uci_ubus"

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
            f"ubus call {ubus_object} {ubus_method} failed (rc={result.returncode}): {result.stderr.strip()}"
        )

    output = result.stdout.strip()
    if not output:
        return None
    return json.loads(output)


# --- Read operations ---


def get(config, section=None, option=None):
    """
    Read UCI configuration via local ``ubus call uci get``.

    Returns the full config, a single section, or a single option value.
    UCI metadata fields (.type, .name, .anonymous, .index) are returned
    with underscore prefixes (_type, _name, _anonymous, _index).

    CLI Example:

    .. code-block:: bash

        salt device uci_ubus.get network
        salt device uci_ubus.get network lan
        salt device uci_ubus.get network lan proto
    """
    return ubus_ops.get(_call, config, section, option)


def configs():
    """
    List available UCI configuration packages.

    CLI Example:

    .. code-block:: bash

        salt device uci_ubus.configs
    """
    return ubus_ops.configs(_call)


def changes(config):
    """
    Show uncommitted changes for a UCI package.

    CLI Example:

    .. code-block:: bash

        salt device uci_ubus.changes network
    """
    return ubus_ops.changes(_call, config)


def config_export(config, format="json"):  # pylint: disable=redefined-builtin
    """
    Export live UCI config as a grouped sections dict.

    Transforms the device config into the format consumed by
    ``uci_ubus.managed()``. Anonymous sections are emitted as
    singleton (``_<type>``) or multi-instance (``_<type>s`` with
    ``_match`` and ``_items``).

    Use ``format=pillar`` to redact sensitive values with Jinja2
    pillar references, or ``format=json`` (default) for plaintext.

    CLI Example:

    .. code-block:: bash

        salt device uci_ubus.config_export network
        salt device uci_ubus.config_export network format=pillar
    """
    return ubus_ops.config_export(_call, config, format=format)


def config_export_all(format="json"):  # pylint: disable=redefined-builtin
    """
    Export all UCI config packages as a grouped dict.

    CLI Example:

    .. code-block:: bash

        salt device uci_ubus.config_export_all
        salt device uci_ubus.config_export_all format=pillar
    """
    return ubus_ops.config_export_all(_call, format=format)


def config_diff(config, sections):
    """
    Compare live UCI config against declared sections and return drift.

    Read-only -- no writes are issued. Returns a categorized dict with
    ``changed``, ``new``, ``removed``, ``reordered``, and ``summary``.

    CLI Example:

    .. code-block:: bash

        salt device uci_ubus.config_diff network sections='{"lan": {"ipaddr": "10.0.0.2"}}'
    """
    return ubus_ops.config_diff(_call, config, sections)


# --- Write operations ---


def set_(config, section, values):
    """
    Set UCI option values on an existing section.

    CLI Example:

    .. code-block:: bash

        salt device uci_ubus.set network lan '{"proto": "static"}'
    """
    return ubus_ops.set_(_call, config, section, values)


def add(config, type_, name=None, values=None):
    """
    Add a new UCI section.

    CLI Example:

    .. code-block:: bash

        salt device uci_ubus.add network interface name=wan2
    """
    return ubus_ops.add(_call, config, type_, name, values)


def delete(config, section, option=None):
    """
    Delete a UCI section or option.

    CLI Example:

    .. code-block:: bash

        salt device uci_ubus.delete network wan2
        salt device uci_ubus.delete network lan dns
    """
    return ubus_ops.delete(_call, config, section, option)


# --- Apply operations ---


def apply_(rollback=90):  # pylint: disable=redefined-outer-name
    """
    Commit and apply UCI changes with rollback safety.

    CLI Example:

    .. code-block:: bash

        salt device uci_ubus.apply
        salt device uci_ubus.apply rollback=120
    """
    return ubus_ops.apply_(_call, rollback)


def confirm():
    """
    Confirm a pending apply, locking in the changes.

    CLI Example:

    .. code-block:: bash

        salt device uci_ubus.confirm
    """
    return ubus_ops.confirm(_call)


def rollback():
    """
    Manually trigger a rollback of the last apply.

    CLI Example:

    .. code-block:: bash

        salt device uci_ubus.rollback
    """
    return ubus_ops.rollback(_call)


def revert(config):
    """
    Discard staged (uncommitted) changes for a UCI package.

    CLI Example:

    .. code-block:: bash

        salt device uci_ubus.revert network
    """
    return ubus_ops.revert(_call, config)


def commit(config):
    """
    Commit staged changes to /etc/config without reloading daemons.

    CLI Example:

    .. code-block:: bash

        salt device uci_ubus.commit network
    """
    return ubus_ops.commit(_call, config)


def state(config, section=None):
    """
    Return runtime-merged UCI state (defaults + config + overrides).

    CLI Example:

    .. code-block:: bash

        salt device uci_ubus.state network
        salt device uci_ubus.state network lan
    """
    return ubus_ops.state(_call, config, section)


# --- System info ---


def system_board():
    """
    Return system board information.

    CLI Example:

    .. code-block:: bash

        salt device uci_ubus.system_board
    """
    return ubus_ops.system_board(_call)


def system_info():
    """
    Return system info (memory, uptime, load).

    CLI Example:

    .. code-block:: bash

        salt device uci_ubus.system_info
    """
    return ubus_ops.system_info(_call)


def network_dump():
    """
    Return network interface state.

    CLI Example:

    .. code-block:: bash

        salt device uci_ubus.network_dump
    """
    return ubus_ops.network_dump(_call)


# --- Service info ---


def service_list(verbose=False):
    """
    Return procd service list.

    CLI Example:

    .. code-block:: bash

        salt device uci_ubus.service_list
        salt device uci_ubus.service_list verbose=True
    """
    return ubus_ops.service_list(_call, verbose)
