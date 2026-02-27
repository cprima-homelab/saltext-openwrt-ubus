"""
Salt proxy module for OpenWrt devices via SSH.

Alternative to the ubus JSON-RPC proxy for devices that have Python
installed and enough RAM to support SSH-based management. Uses
``uci`` CLI commands over SSH instead of the ubus JSON-RPC API.

NOT YET IMPLEMENTED. This module exists as a stub to define the
adapter interface. All functions raise ``NotImplementedError``.

.. code-block:: yaml

    # /srv/salt/pillar/router.sls
    proxy:
      proxytype: saltext_uci_ssh
      host: 10.35.24.1
      username: root
      port: 22
"""

import logging

log = logging.getLogger(__name__)

__virtualname__ = "saltext_uci_ssh"
__proxyenabled__ = ["saltext_uci_ssh"]

DETAILS = {}


def __virtual__():
    return __virtualname__


def init(opts):
    """Establish SSH connection from proxy pillar config."""
    raise NotImplementedError(
        "SSH proxy adapter is not yet implemented. Use proxytype: saltext_uci (JSON-RPC) instead."
    )


def alive(opts):  # pylint: disable=unused-argument
    """Return True if the SSH connection is active."""
    raise NotImplementedError("SSH proxy adapter is not yet implemented.")


def ping():
    """Return True if the device responds to a UCI command over SSH."""
    raise NotImplementedError("SSH proxy adapter is not yet implemented.")


def shutdown(opts):  # pylint: disable=unused-argument
    """Close the SSH connection and clean up."""
    raise NotImplementedError("SSH proxy adapter is not yet implemented.")


def grains():
    """Return cached device grains."""
    raise NotImplementedError("SSH proxy adapter is not yet implemented.")


def grains_refresh():
    """Re-fetch grains from the device via SSH."""
    raise NotImplementedError("SSH proxy adapter is not yet implemented.")


def call(uci_cmd, *args):
    """Execute a UCI CLI command over SSH and return parsed output."""
    raise NotImplementedError("SSH proxy adapter is not yet implemented.")
