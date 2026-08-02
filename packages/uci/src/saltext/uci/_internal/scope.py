"""
Package support tiers for saltext-uci-ubus.

Packages not listed here cannot be managed by the managed() state.
Execution module functions (get, set, config_diff, etc.) remain
unrestricted for inspection and ad-hoc use.
"""

STABLE = {
    "network",
    "system",
    "dhcp",
}

EXPERIMENTAL = {
    "wireless",
    "firewall",
    "dropbear",
}


def tier(config_name):
    """Return 'stable', 'experimental', or None (unregistered)."""
    if config_name in STABLE:
        return "stable"
    if config_name in EXPERIMENTAL:
        return "experimental"
    return None


def is_supported(config_name):
    """Check if a package is in any tier."""
    return config_name in STABLE or config_name in EXPERIMENTAL


def supported():
    """Return sorted list of all supported package names."""
    return sorted(STABLE | EXPERIMENTAL)
