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


def config_export(call, config, format="json"):  # pylint: disable=redefined-builtin
    """Read a live UCI config and return a grouped sections dict.

    Both formats use the same grouped structure (metadata-stripped,
    anonymous sections grouped as singletons or multi-instance with
    ``_match``/``_items``). The ``pillar`` format redacts sensitive
    options with Jinja2 pillar references; ``json`` keeps plaintext.

    Args:
        call: Transport-specific ubus call function.
        config: UCI package name (e.g., ``network``).
        format: Output format -- ``"json"`` (default, plaintext values)
            or ``"pillar"`` (sensitive values replaced with Jinja2
            pillar references).

    Returns:
        dict: Sections dict consumable by the ``managed()`` state.

    CLI Example:

    .. code-block:: bash

        salt austru openwrt_ubus.config_export network
        salt austru openwrt_ubus.config_export network format=pillar
    """
    redact = format == "pillar"
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


def config_export_all(call, format="json"):  # pylint: disable=redefined-builtin
    """Export all UCI config packages as a grouped dict.

    Returns:
        dict: Maps config names to their sections dicts.

    CLI Example:

    .. code-block:: bash

        salt austru openwrt_ubus.config_export_all
        salt austru openwrt_ubus.config_export_all format=pillar
    """
    result = {}
    for config_name in configs(call):
        try:
            result[config_name] = config_export(call, config_name, format=format)
        except Exception:  # pylint: disable=broad-except
            result[config_name] = {"_error": f"Failed to read {config_name}"}
    return result


def config_diff(call, config, sections):
    """Compare live UCI config against declared sections and return drift.

    Read-only operation -- no writes are issued. Returns a categorized
    dict with ``changed``, ``new``, ``removed``, ``reordered``, and
    ``summary`` keys. On resolution or type-mismatch errors, returns
    ``{"error": "...message..."}``.

    Args:
        call: Transport-specific ubus call function.
        config: UCI package name (e.g., ``network``).
        sections: Pillar-style sections dict (same format as
            ``managed()`` accepts).

    Returns:
        dict: Categorized drift report.

    CLI Example:

    .. code-block:: bash

        salt austru openwrt_ubus.config_diff network sections='{"lan": {"ipaddr": "10.0.0.2"}}'
    """
    current = get(call, config)

    try:
        resolved, prune_targets = resolve_sections(config, sections, current)
    except ValueError as exc:
        return {"error": str(exc)}

    changed = {}
    new = {}
    removed = {}
    reordered = {}

    for section_name, desired in resolved.items():
        # Whole-section absence
        if desired == "_absent":
            if section_name in current:
                removed[section_name] = dict(current[section_name])
            continue

        current_section = current.get(section_name, {})

        # Type mismatch guard
        if current_section:
            desired_type = desired.get("_type")
            current_type = current_section.get("_type")
            if desired_type and current_type and desired_type != current_type:
                return {
                    "error": (
                        f"Type mismatch on {config}.{section_name}: "
                        f"desired _type '{desired_type}' != "
                        f"current _type '{current_type}'"
                    )
                }

        section_changes = diff_section(desired, current_section)
        if section_changes:
            if section_name not in current:
                new[section_name] = section_changes
            else:
                changed[section_name] = section_changes

    # Classify prune targets
    for section_name in prune_targets:
        # Check if this is a reorder (has _anonymous_new items of same _type)
        pruned_type = current.get(section_name, {}).get("_type")
        has_new_of_type = any(
            v.get("_anonymous_new") and v.get("_type") == pruned_type
            for v in resolved.values()
            if isinstance(v, dict)
        )
        if has_new_of_type:
            reordered[section_name] = dict(current.get(section_name, {}))
        else:
            removed[section_name] = dict(current.get(section_name, {}))

    n_changed = len(changed)
    n_new = len(new)
    n_removed = len(removed)
    n_reordered = len(reordered)
    total = n_changed + n_new + n_removed + n_reordered

    return {
        "changed": changed,
        "new": new,
        "removed": removed,
        "reordered": reordered,
        "summary": {
            "changed": n_changed,
            "new": n_new,
            "removed": n_removed,
            "reordered": n_reordered,
            "total": total,
            "in_sync": total == 0,
        },
    }


# --- Diff / resolve helpers ---


def diff_section(desired, current):
    """
    Compare desired options against current section, return changes.

    Only checks options listed in desired (partial semantics).
    Keys starting with ``_`` are metadata and skipped.
    The sentinel value ``"_absent"`` marks an option for deletion.
    """
    diffs = {}
    for option, desired_value in desired.items():
        if option.startswith("_"):
            continue
        if desired_value == "_absent":
            if option in current:
                diffs[option] = {"old": current[option], "new": "_absent"}
            continue
        current_value = current.get(option)
        if current_value != desired_value:
            diffs[option] = {"old": current_value, "new": desired_value}
    return diffs


def resolve_sections(config, sections, current):
    """
    Resolve pillar section names to actual UCI section names.

    Handles three cases for ``_``-prefixed pillar keys:

    1. **_absent**: Section should not exist. Passed through as the
       string ``"_absent"`` for the caller to handle deletion.
    2. **Multi-instance** (``_items`` present): Multiple anonymous
       sections matched by ``_match`` key. Delegates to
       ``_resolve_multi_instance()``.
    3. **Singleton**: One anonymous section of a given type.

    Returns ``(resolved, prune_targets)`` where ``prune_targets`` is a
    list of device section names to delete (from ``_prune: true``
    multi-instance specs or reorder operations).
    """
    resolved = {}
    prune_targets = []
    for pillar_name, desired in sections.items():
        # Whole-section absence
        if desired == "_absent":
            resolved[pillar_name] = "_absent"
            continue

        if pillar_name.startswith("_") and isinstance(desired, dict) and "_type" in desired:
            if "_items" in desired:
                # Multi-instance anonymous sections
                _resolve_multi_instance(
                    config, pillar_name, desired, current, resolved, prune_targets
                )
            else:
                # Singleton anonymous section lookup
                target_type = desired["_type"]
                matches = [
                    name
                    for name, data in current.items()
                    if data.get("_anonymous") and data.get("_type") == target_type
                ]
                if len(matches) == 0:
                    raise ValueError(
                        f"No anonymous section of type '{target_type}' found in {config}"
                    )
                if len(matches) > 1:
                    raise ValueError(
                        f"Multiple anonymous sections of type '{target_type}' "
                        f"found in {config}: {matches}. "
                        f"Singleton lookup requires exactly one. "
                        f"Use _items for multi-instance management."
                    )
                resolved[matches[0]] = desired
        else:
            resolved[pillar_name] = desired
    return resolved, prune_targets


def _resolve_multi_instance(_config, _pillar_name, spec, current, resolved, prune_targets):
    """
    Resolve a multi-instance anonymous section spec to device sections.

    Matches pillar items to device sections by ``_match`` key(s).
    Unmatched pillar items are flagged for anonymous creation.
    If ``_prune`` is true, unmatched device sections are added to
    ``prune_targets`` for deletion. If device order differs from
    pillar order, all matched sections are deleted and re-added.
    """
    type_ = spec["_type"]
    match_keys = spec["_match"]
    if isinstance(match_keys, str):
        match_keys = [match_keys]
    items = spec["_items"]
    prune = spec.get("_prune", False)

    # 1. Index device sections of this type by match key
    device_index = {}  # {match_tuple: section_name}
    device_sections = []  # [(section_name, data), ...]
    for name, data in current.items():
        if data.get("_type") == type_ and data.get("_anonymous"):
            key = tuple(data.get(k) for k in match_keys)
            device_index[key] = name
            device_sections.append((name, data))

    # 2. Resolve each pillar item to a device section or mark for creation
    matched_device_names = set()
    for idx, item in enumerate(items):
        key = tuple(item.get(k) for k in match_keys)
        device_name = device_index.get(key)
        if device_name:
            resolved[device_name] = {"_type": type_, **item}
            matched_device_names.add(device_name)
        else:
            placeholder = f"_new_{type_}_{idx}"
            resolved[placeholder] = {"_type": type_, "_anonymous_new": True, **item}

    # 3. Check order -- if device order differs from pillar, reorder
    if len(matched_device_names) > 1:
        ordered_device = sorted(
            [(n, d) for n, d in device_sections if n in matched_device_names],
            key=lambda nd: nd[1].get("_index", 0),
        )
        if not _check_order(items, match_keys, ordered_device):
            # Delete all existing, re-add all in pillar order
            for name in matched_device_names:
                prune_targets.append(name)
                if name in resolved:
                    del resolved[name]
            for idx, item in enumerate(items):
                placeholder = f"_new_{type_}_{idx}"
                if placeholder not in resolved:
                    resolved[placeholder] = {"_type": type_, "_anonymous_new": True, **item}

    # 4. Prune unmatched device sections of this type
    if prune:
        for name, _data in device_sections:
            if name not in matched_device_names:
                prune_targets.append(name)


def _check_order(items, match_keys, device_sections_ordered):
    """
    Compare pillar item order against device section order.

    Returns True if the relative order of matched items on the device
    matches the pillar list order.
    """
    device_order = []
    for _name, data in device_sections_ordered:
        key = tuple(data.get(k) for k in match_keys)
        device_order.append(key)

    pillar_order = []
    for item in items:
        key = tuple(item.get(k) for k in match_keys)
        pillar_order.append(key)

    # Filter both lists to only keys present in the other,
    # so new pillar items (not yet on device) don't cause a false mismatch.
    pillar_set = set(pillar_order)
    device_set = set(device_order)
    device_matched = [k for k in device_order if k in pillar_set]
    pillar_matched = [k for k in pillar_order if k in device_set]

    return device_matched == pillar_matched


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
