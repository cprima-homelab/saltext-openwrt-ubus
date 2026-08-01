"""
Shorthand alias for the ``uci_ubus`` state module.

Provides ``openwrt.managed`` and ``openwrt.applied`` as convenience
aliases so operators can use either name in state files.
"""

__virtualname__ = "openwrt"


def __virtual__():
    if "uci_ubus.get" not in __salt__:
        return False, "uci_ubus module not available"
    return __virtualname__


def managed(name, config, sections, apply_rollback=None, revert_pending=False):
    """
    Ensure named UCI sections match desired state. Alias for ``uci_ubus.managed``.

    Example:

    .. code-block:: yaml

        network_config:
          openwrt.managed:
            - config: network
            - sections:
                lan:
                  _type: interface
                  proto: static
                  ipaddr: 10.35.24.1
    """
    return __states__["uci_ubus.managed"](
        name, config, sections, apply_rollback=apply_rollback, revert_pending=revert_pending
    )


def applied(name, config=None, rollback=None):
    """
    Apply staged UCI changes with rollback protection. Alias for ``uci_ubus.applied``.

    Example:

    .. code-block:: yaml

        apply_staged:
          openwrt.applied: []
    """
    return __states__["uci_ubus.applied"](name, config=config, rollback=rollback)
