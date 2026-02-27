"""
Schema for the ``netifd`` opkg package (UCI package: ``network``).

netifd owns ``/etc/config/network``. This module declares which sections
are named vs anonymous and which options are lists, allowing the parser
to disambiguate ``uci show`` output.

Source: ``opkg info netifd`` on austru, ``uci show network``.

.. versionadded:: 0.1.0
"""

UCI_PACKAGE = "network"
OPKG = "netifd"

# Named section types with stable UCI paths (e.g. network.lan)
NAMED_SECTION_TYPES = {
    "interface",
    "globals",
}

# Anonymous section types addressed as @type[N] -- deferred from v0.1
ANONYMOUS_SECTION_TYPES = {
    "device",
    "switch",
    "switch_vlan",
    "switch_port",
}

# Options known to be lists (needed to disambiguate uci show output
# where 'val1' 'val2' could be a multi-word scalar or a list).
# Keyed by section type.
LIST_OPTIONS = {
    "interface": {"dns"},
}
