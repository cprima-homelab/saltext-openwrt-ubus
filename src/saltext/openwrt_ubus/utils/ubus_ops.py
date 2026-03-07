"""
Shared ubus operations for all execution module adapters.

Each adapter (JSON-RPC, SSH, local) provides its own ``_call()`` function
that handles transport. The functions here implement the common
post-processing logic that is identical regardless of transport.
"""


def transform_section(data):
    """Transform UCI dot-prefixed metadata to underscore-prefixed."""
    result = {}
    for key, value in data.items():
        if key.startswith("."):
            result["_" + key[1:]] = value
        else:
            result[key] = value
    return result


# --- Read operations ---


def get(call, config, section=None, option=None):
    """Read UCI configuration via ubus."""
    params = {"config": config}
    if section is not None:
        params["section"] = section
    if option is not None:
        params["option"] = option

    result = call("uci", "get", params)

    if option is not None:
        return result.get("value")

    if section is not None:
        data = result.get("values", result)
        return transform_section(data)

    values = result.get("values", {})
    return {name: transform_section(data) for name, data in values.items()}


def configs(call):
    """List available UCI configuration packages."""
    result = call("uci", "configs")
    return result.get("configs", [])


def changes(call, config):
    """Show uncommitted changes for a UCI package."""
    result = call("uci", "changes", {"config": config})
    return result.get("changes", [])


# --- Pillar generation ---

_METADATA_STRIP = frozenset({"_name", "_anonymous", "_index"})
_SENSITIVE_EXACT = frozenset({"password", "key", "psk", "secret", "token", "passphrase"})
_SENSITIVE_SUFFIXES = (
    "_password",
    "_key",
    "_psk",
    "_secret",
    "_token",
    "_passphrase",
    "_credential",
)


def _is_sensitive(option_name):
    """Check if an option name matches known sensitive patterns."""
    lower = option_name.lower()
    if lower in _SENSITIVE_EXACT:
        return True
    return any(lower.endswith(suffix) for suffix in _SENSITIVE_SUFFIXES)


def _strip_metadata(section_data):
    """Remove internal metadata, keep _type and user options."""
    return {k: v for k, v in section_data.items() if k not in _METADATA_STRIP}


def _detect_match_key(sections):
    """Auto-detect the best match key for a group of anonymous sections.

    Returns a single key name, a list of two key names (composite), or
    None if no viable match key is found.
    """
    if len(sections) < 2:
        return None

    # Find options present in ALL sections with scalar (non-list) values
    common = None
    for section in sections:
        scalars = {
            k for k, v in section.items() if not k.startswith("_") and not isinstance(v, list)
        }
        common = scalars if common is None else common & scalars
    if not common:
        return None

    # Check which common options have unique values across sections
    unique = []
    for key in sorted(common):
        values = [s[key] for s in sections]
        if len(values) == len(set(values)):
            unique.append(key)

    if "name" in unique:
        return "name"
    if unique:
        return unique[0]

    # Try composite keys of 2
    candidates = sorted(common)
    for i, k1 in enumerate(candidates):
        for k2 in candidates[i + 1 :]:
            composites = {(s[k1], s[k2]) for s in sections}
            if len(composites) == len(sections):
                return [k1, k2]

    return None


def _redact_value(config, section_name, option_name, match_key=None, match_value=None):
    """Build a Jinja2 pillar reference for a sensitive option."""
    if match_key and match_value:
        path = f"secrets:{config}:{section_name}:{match_value}:{option_name}"
    else:
        path = f"secrets:{config}:{section_name}:{option_name}"
    return "{{ salt['pillar.get']('" + path + "') }}"


def dump(call, config, redact=True):
    """Read a live UCI config and return a pillar-ready sections dict.

    Args:
        call: Transport-specific ubus call function.
        config: UCI package name (e.g., ``network``).
        redact: Replace sensitive option values with Jinja2 pillar
            references. Defaults to True.

    Returns:
        dict: Sections dict consumable by the ``managed()`` state.

    CLI Example:

    .. code-block:: bash

        salt austru openwrt_ubus.dump network
        salt austru openwrt_ubus.dump wireless redact=False
    """
    raw = get(call, config)
    if not raw:
        return {}

    named = {}
    anon_by_type = {}

    for section_name, section_data in raw.items():
        if section_data.get("_anonymous"):
            type_ = section_data.get("_type", "unknown")
            anon_by_type.setdefault(type_, []).append(section_data)
        else:
            named[section_name] = section_data

    result = {}

    # Named sections
    for section_name, section_data in named.items():
        cleaned = _strip_metadata(section_data)
        if redact:
            cleaned = {
                k: (
                    _redact_value(config, section_name, k)
                    if not k.startswith("_") and _is_sensitive(k)
                    else v
                )
                for k, v in cleaned.items()
            }
        result[section_name] = cleaned

    # Anonymous sections grouped by type
    for type_, sections_list in anon_by_type.items():
        sections_list.sort(key=lambda s: s.get("_index", 0))
        stripped = [_strip_metadata(s) for s in sections_list]

        if len(stripped) == 1:
            pillar_name = f"_{type_}"
            cleaned = stripped[0]
            if redact:
                cleaned = {
                    k: (
                        _redact_value(config, pillar_name, k)
                        if not k.startswith("_") and _is_sensitive(k)
                        else v
                    )
                    for k, v in cleaned.items()
                }
            result[pillar_name] = cleaned
        else:
            pillar_name = f"_{type_}s"
            match_key = _detect_match_key(stripped)

            entry = {"_type": type_}
            if match_key is not None:
                entry["_match"] = match_key
            else:
                entry["_comment"] = (
                    f"No unique match key detected for type '{type_}'. "
                    "Set _match manually before using this pillar."
                )

            items = []
            for section_data in stripped:
                item = {k: v for k, v in section_data.items() if k != "_type"}
                if redact:
                    # Determine match value for stable redaction path
                    if isinstance(match_key, str):
                        mv = item.get(match_key)
                    elif isinstance(match_key, list) and len(match_key) > 0:
                        mv = item.get(match_key[0])
                    else:
                        mv = None
                    item = {
                        k: (
                            _redact_value(
                                config, pillar_name, k, match_key=match_key, match_value=mv
                            )
                            if _is_sensitive(k)
                            else v
                        )
                        for k, v in item.items()
                    }
                items.append(item)

            entry["_items"] = items
            result[pillar_name] = entry

    return result


def dump_all(call, redact=True):
    """Dump all UCI config packages as a pillar-ready dict.

    Returns:
        dict: Maps config names to their sections dicts.

    CLI Example:

    .. code-block:: bash

        salt austru openwrt_ubus.dump_all
        salt austru openwrt_ubus.dump_all redact=False
    """
    result = {}
    for config_name in configs(call):
        try:
            result[config_name] = dump(call, config_name, redact=redact)
        except Exception:  # pylint: disable=broad-except
            result[config_name] = {"_error": f"Failed to read {config_name}"}
    return result


# --- Write operations ---


def set_(call, config, section, values):
    """Set UCI option values on an existing section."""
    return call(
        "uci",
        "set",
        {
            "config": config,
            "section": section,
            "values": values,
        },
    )


def add(call, config, type_, name=None, values=None):
    """Add a new UCI section."""
    params = {"config": config, "type": type_}
    if name is not None:
        params["name"] = name
    if values is not None:
        params["values"] = values
    return call("uci", "add", params)


def delete(call, config, section, option=None):
    """Delete a UCI section or option."""
    params = {"config": config, "section": section}
    if option is not None:
        params["option"] = option
    return call("uci", "delete", params)


# --- Apply operations ---


def apply_(call, timeout=90):
    """Commit and apply UCI changes with rollback safety."""
    return call("uci", "apply", {"rollback": True, "timeout": timeout})


def confirm(call):
    """Confirm a pending apply, locking in the changes."""
    return call("uci", "confirm", {})


def rollback(call):
    """Manually trigger a rollback of the last apply."""
    return call("uci", "rollback", {})


def revert(call, config):
    """Discard staged (uncommitted) changes for a UCI package."""
    return call("uci", "revert", {"config": config})


def commit(call, config):
    """Commit staged changes to /etc/config without reloading daemons."""
    return call("uci", "commit", {"config": config})


def state(call, config, section=None):
    """Return runtime-merged UCI state (defaults + config + overrides)."""
    params = {"config": config}
    if section is not None:
        params["section"] = section
    result = call("uci", "state", params)

    if section is not None:
        data = result.get("values", result)
        return transform_section(data)

    values = result.get("values", {})
    return {name: transform_section(data) for name, data in values.items()}


# --- System info ---


def system_board(call):
    """Return system board information."""
    return call("system", "board")


def system_info(call):
    """Return system info (memory, uptime, load)."""
    return call("system", "info")


def network_dump(call):
    """Return network interface state."""
    return call("network.interface", "dump")


# --- Service info ---


def service_list(call, verbose=False):
    """Return procd service list. Use verbose=True to include triggers."""
    params = {"verbose": True} if verbose else None
    return call("service", "list", params)
