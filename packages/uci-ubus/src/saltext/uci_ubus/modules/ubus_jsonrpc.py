"""
Salt execution module for OpenWrt configuration via ubus JSON-RPC.

Requires the uci proxy module to be configured and running.

UCI metadata fields are returned with underscore prefixes to avoid
collision with UCI option names::

    .type -> _type, .name -> _name, .anonymous -> _anonymous, .index -> _index
"""

import logging

from saltext.uci._internal import ubus_ops

log = logging.getLogger(__name__)

__virtualname__ = "uci"
__proxyenabled__ = ["uci_ubus_jsonrpc"]

__func_alias__ = {
    "set_": "set",
    "apply_": "apply",
}


def __virtual__():
    if "proxy" not in __opts__:
        return False, "Not a proxy minion"
    if __opts__.get("proxy", {}).get("proxytype") != "uci_ubus_jsonrpc":
        return False, "proxytype is not uci_ubus_jsonrpc"
    return __virtualname__


def _call(ubus_object, ubus_method, params=None):
    """Forward a ubus call through the proxy module."""
    return __proxy__["uci_ubus_jsonrpc.call"](ubus_object, ubus_method, params)


# --- Read operations ---


def get(config, section=None, option=None):
    """
    Read UCI configuration.

    Returns the full config, a single section, or a single option value.
    UCI metadata fields (.type, .name, .anonymous, .index) are returned
    with underscore prefixes (_type, _name, _anonymous, _index).

    CLI Example:

    .. code-block:: bash

        salt austru uci.get network
        salt austru uci.get network lan
        salt austru uci.get network lan proto
    """
    return ubus_ops.get(_call, config, section, option)


def configs():
    """
    List available UCI configuration packages.

    CLI Example:

    .. code-block:: bash

        salt austru uci.configs
    """
    return ubus_ops.configs(_call)


def changes(config):
    """
    Show uncommitted changes for a UCI package.

    CLI Example:

    .. code-block:: bash

        salt austru uci.changes network
    """
    return ubus_ops.changes(_call, config)


def config_evidence(config):
    """
    Return the configured UCI state for ``config`` wrapped in a provenance envelope.

    Calls :func:`config_export` for the payload and adds metadata describing
    *what* was collected, *from where*, *when*, and *how*.

    No storage side effect — the caller (runner, CLI, orchestration layer)
    decides where to persist the record.

    CLI Example:

    .. code-block:: bash

        salt austru uci.config_evidence network
        salt austru uci.config_evidence dhcp
    """
    try:
        import importlib.metadata as _meta  # pylint: disable=import-outside-toplevel

        collector_version = _meta.version("saltext-uci-ubus")
    except Exception:  # pylint: disable=broad-exception-caught
        collector_version = "unknown"

    return ubus_ops.config_evidence(
        _call,
        config,
        source_device=__opts__.get("id", ""),
        collector="saltext-uci-ubus",
        transport="ubus-jsonrpc",
        collector_version=collector_version,
    )


def runtime_evidence(domain):
    """
    Return observed runtime state for ``domain`` wrapped in a provenance envelope.

    Valid domains:

    * ``network``  — interface operational state (``network_dump()``)
    * ``system``   — board identity + uptime/memory (``system_board()`` + ``system_info()``)
    * ``services`` — procd service state (``service_list(verbose=True)``)

    No storage side effect — the caller decides where to persist the record.

    CLI Example:

    .. code-block:: bash

        salt bora uci.runtime_evidence network
        salt bora uci.runtime_evidence system
        salt bora uci.runtime_evidence services
    """
    try:
        import importlib.metadata as _meta  # pylint: disable=import-outside-toplevel

        collector_version = _meta.version("saltext-uci-ubus")
    except Exception:  # pylint: disable=broad-exception-caught
        collector_version = "unknown"

    return ubus_ops.runtime_evidence(
        _call,
        domain,
        source_device=__opts__.get("id", ""),
        collector="saltext-uci-ubus",
        transport="ubus-jsonrpc",
        collector_version=collector_version,
    )


def config_export(config, format="json"):  # pylint: disable=redefined-builtin
    """
    Export live UCI config as a grouped sections dict.

    Transforms the device config into the format consumed by
    ``uci.managed()``. Anonymous sections are emitted as
    singleton (``_<type>``) or multi-instance (``_<type>s`` with
    ``_match`` and ``_items``).

    Use ``format=pillar`` to redact sensitive values with Jinja2
    pillar references, or ``format=json`` (default) for plaintext.

    CLI Example:

    .. code-block:: bash

        salt austru uci.config_export network
        salt austru uci.config_export network format=pillar
    """
    return ubus_ops.config_export(_call, config, format=format)


def config_export_all(format="json"):  # pylint: disable=redefined-builtin
    """
    Export all UCI config packages as a grouped dict.

    CLI Example:

    .. code-block:: bash

        salt austru uci.config_export_all
        salt austru uci.config_export_all format=pillar
    """
    return ubus_ops.config_export_all(_call, format=format)


def config_diff(config, sections):
    """
    Compare live UCI config against declared sections and return drift.

    Read-only -- no writes are issued. Returns a categorized dict with
    ``changed``, ``new``, ``removed``, ``reordered``, and ``summary``.

    CLI Example:

    .. code-block:: bash

        salt austru uci.config_diff network sections='{"lan": {"ipaddr": "10.0.0.2"}}'
    """
    return ubus_ops.config_diff(_call, config, sections)


# --- Write operations ---


def set_(config, section, values):
    """
    Set UCI option values on an existing section.

    CLI Example:

    .. code-block:: bash

        salt austru uci.set network lan '{"proto": "static"}'
    """
    return ubus_ops.set_(_call, config, section, values)


def add(config, type_, name=None, values=None):
    """
    Add a new UCI section.

    CLI Example:

    .. code-block:: bash

        salt austru uci.add network interface name=wan2
    """
    return ubus_ops.add(_call, config, type_, name, values)


def delete(config, section, option=None):
    """
    Delete a UCI section or option.

    CLI Example:

    .. code-block:: bash

        salt austru uci.delete network wan2
        salt austru uci.delete network lan dns
    """
    return ubus_ops.delete(_call, config, section, option)


# --- Apply operations ---


def apply_(rollback=90):  # pylint: disable=redefined-outer-name
    """
    Commit and apply UCI changes with rollback safety.

    CLI Example:

    .. code-block:: bash

        salt austru uci.apply
        salt austru uci.apply rollback=120
    """
    return ubus_ops.apply_(_call, rollback)


def confirm():
    """
    Confirm a pending apply, locking in the changes.

    CLI Example:

    .. code-block:: bash

        salt austru uci.confirm
    """
    return ubus_ops.confirm(_call)


def rollback():
    """
    Manually trigger a rollback of the last apply.

    CLI Example:

    .. code-block:: bash

        salt austru uci.rollback
    """
    return ubus_ops.rollback(_call)


def revert(config):
    """
    Discard staged (uncommitted) changes for a UCI package.

    CLI Example:

    .. code-block:: bash

        salt austru uci.revert network
    """
    return ubus_ops.revert(_call, config)


def commit(config):
    """
    Commit staged changes to /etc/config without reloading daemons.

    CLI Example:

    .. code-block:: bash

        salt austru uci.commit network
    """
    return ubus_ops.commit(_call, config)


def state(config, section=None):
    """
    Return runtime-merged UCI state (defaults + config + overrides).

    CLI Example:

    .. code-block:: bash

        salt austru uci.state network
        salt austru uci.state network lan
    """
    return ubus_ops.state(_call, config, section)


# --- System info ---


def system_board():
    """
    Return system board information.

    CLI Example:

    .. code-block:: bash

        salt austru uci.system_board
    """
    return ubus_ops.system_board(_call)


def system_info():
    """
    Return system info (memory, uptime, load).

    CLI Example:

    .. code-block:: bash

        salt austru uci.system_info
    """
    return ubus_ops.system_info(_call)


def network_dump():
    """
    Return network interface state.

    CLI Example:

    .. code-block:: bash

        salt austru uci.network_dump
    """
    return ubus_ops.network_dump(_call)


# --- Service info ---


def service_list(verbose=False):
    """
    Return procd service list.

    CLI Example:

    .. code-block:: bash

        salt austru uci.service_list
        salt austru uci.service_list verbose=True
    """
    return ubus_ops.service_list(_call, verbose)
