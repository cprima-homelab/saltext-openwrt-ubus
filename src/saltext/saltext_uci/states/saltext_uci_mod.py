"""
Salt state module for OpenWrt UCI configuration.

.. versionadded:: 0.1.0
"""

import logging

log = logging.getLogger(__name__)

__virtualname__ = "saltext_uci"


def __virtual__():
    if "saltext_uci.get" not in __salt__:
        return False, "The 'saltext_uci' execution module is not available"
    return __virtualname__
