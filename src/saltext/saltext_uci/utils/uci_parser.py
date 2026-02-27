"""
Parser for ``uci show`` output.

Converts raw ``uci show`` text into structured Python dicts suitable
for Salt pillar data or programmatic analysis.

.. versionadded:: 0.1.0
"""

import re
import shlex

_ANON_RE = re.compile(r"^@(\w+)\[(\d+)\]$")


def parse_show(text):
    """
    Parse ``uci show`` output into a nested dict.

    Args:
        text: Raw output from ``uci show`` or ``uci show <package>``

    Returns:
        Dict keyed by package name. Each package contains named sections
        as dict keys and anonymous sections collected under ``_anonymous``.

    Example::

        >>> parse_show("network.lan=interface\\nnetwork.lan.proto='static'")
        {'network': {'lan': {'_type': 'interface', 'proto': 'static'}}}
    """
    result = {}
    for line in text.strip().splitlines():
        if "=" not in line:
            continue
        path, _, raw_value = line.partition("=")
        parts = path.split(".")

        if len(parts) == 2:
            # Section type declaration: network.lan=interface
            package, section = parts
            _ensure_package(result, package)
            match = _ANON_RE.match(section)
            if match:
                sec_type, index = match.group(1), int(match.group(2))
                anon = _ensure_anonymous(result[package], sec_type, index)
                anon["_type"] = raw_value
            else:
                if section not in result[package]:
                    result[package][section] = {}
                result[package][section]["_type"] = raw_value

        elif len(parts) == 3:
            # Option: network.lan.device='br-lan'
            package, section, option = parts
            _ensure_package(result, package)
            match = _ANON_RE.match(section)
            if match:
                sec_type, index = match.group(1), int(match.group(2))
                anon = _ensure_anonymous(result[package], sec_type, index)
                anon[option] = _unquote(raw_value)
            else:
                if section not in result[package]:
                    result[package][section] = {}
                result[package][section][option] = _unquote(raw_value)

    return result


def to_pillar(config):
    """
    Convert parsed config to pillar-ready structure.

    Args:
        config: Dict from :func:`parse_show`

    Returns:
        Dict with ``uci`` top-level key wrapping the config.
    """
    return {"uci": config}


def _ensure_package(result, package):
    if package not in result:
        result[package] = {}


def _ensure_anonymous(package_dict, sec_type, index):
    """Return or create an anonymous section entry in ``_anonymous``."""
    if "_anonymous" not in package_dict:
        package_dict["_anonymous"] = []
    anon_list = package_dict["_anonymous"]
    # Find existing entry with matching type and index
    for entry in anon_list:
        if entry.get("_type_key") == sec_type and entry.get("_index") == index:
            return entry
    # Create new entry
    entry = {"_type_key": sec_type, "_index": index}
    anon_list.append(entry)
    return entry


def _unquote(value):
    """Strip single quotes from a ``uci show`` value.

    ``uci show`` wraps values in single quotes: ``'static'``.
    List values are space-separated quoted strings: ``'1.1.1.1' '1.0.0.1'``.
    """
    try:
        parts = shlex.split(value)
    except ValueError:
        return value.strip("'")
    if len(parts) == 1:
        return parts[0]
    return parts
