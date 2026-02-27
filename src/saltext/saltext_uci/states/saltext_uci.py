"""
Salt state module for OpenWrt UCI configuration management.

Ensures named UCI sections match a desired state using partial
semantics: only options present in pillar are managed, unmanaged
options are left untouched. Matches LuCI's option-by-option model.

Anonymous section management is deferred to v0.3, with one exception:
singleton anonymous sections (exactly one section of a given type in
a package) can be addressed by ``_<type>`` pillar key with a ``_type``
field.
"""

import logging

log = logging.getLogger(__name__)

__virtualname__ = "saltext_uci"
__proxyenabled__ = ["saltext_uci_ubus", "saltext_uci_ssh"]


def __virtual__():
    if "saltext_uci.get" not in __salt__:
        return False, "The 'saltext_uci' execution module is not available"
    return __virtualname__


def managed(name, config, sections, apply_rollback=90, revert_pending=False):
    """
    Ensure named UCI sections match desired state.

    Only options listed in ``sections`` are managed. Unmanaged options
    are left untouched (partial semantics).

    Args:
        name: State ID.
        config: UCI package name (e.g., 'network').
        sections: Dict of ``{section_name: {option: value, ...}}``.
            Keys starting with ``_`` trigger singleton anonymous section
            lookup by the ``_type`` field.
        apply_rollback: Rollback timeout in seconds. ``None`` = stage
            changes only (do not commit or reload). Default ``90`` =
            commit + reload with 90s rollback safety net.
        revert_pending: If ``True``, silently revert uncommitted deltas
            before proceeding. If ``False`` (default), fail when pending
            deltas exist to prevent discarding someone else's staged
            changes.

    Example:

    .. code-block:: yaml

        network_config:
          saltext_uci.managed:
            - config: network
            - sections:
                lan:
                  _type: interface
                  proto: static
                  ipaddr: 10.35.24.1
    """
    ret = {"name": name, "changes": {}, "result": True, "comment": ""}

    # 1. Check for pending deltas
    pending = _check_pending(ret, config, revert_pending)
    if ret["result"] is False:
        return ret

    # 2. Read current state and resolve sections
    current, resolved = _read_and_resolve(ret, config, sections)
    if ret["result"] is False:
        return ret

    # 3. Diff: compare desired against current (partial)
    all_changes = {}
    for section_name, desired in resolved.items():
        current_section = current.get(section_name, {})

        # Type mismatch guard: catch it before any changes are staged
        if current_section:
            desired_type = desired.get("_type")
            current_type = current_section.get("_type")
            if desired_type and current_type and desired_type != current_type:
                ret["result"] = False
                ret["comment"] = (
                    f"Type mismatch on {config}.{section_name}: "
                    f"desired _type '{desired_type}' != "
                    f"current _type '{current_type}'"
                )
                return ret

        section_changes = _diff_section(desired, current_section)
        if section_changes:
            all_changes[section_name] = section_changes

    if not all_changes:
        ret["comment"] = f"{config}: already in desired state"
        return ret

    # 4. Test mode
    if __opts__["test"]:
        ret["result"] = None
        ret["changes"] = all_changes
        parts = []
        if pending and revert_pending:
            parts.append(f"would revert pending changes: {pending}")
        parts.append(f"{len(all_changes)} section(s) would be updated")
        ret["comment"] = f"{config}: {'; '.join(parts)}"
        return ret

    # 5. Stage uci.set calls
    _stage_changes(ret, config, all_changes, resolved, current)
    if ret["result"] is False:
        return ret

    # 6. Apply, verify, confirm
    if apply_rollback is not None:
        _apply_and_confirm(ret, config, all_changes, apply_rollback)
        if ret["result"] is False:
            return ret

    ret["changes"] = all_changes
    if apply_rollback is None:
        ret["comment"] = (
            f"{config}: {len(all_changes)} section(s) updated (staged only, not applied)"
        )
    else:
        ret["comment"] = f"{config}: {len(all_changes)} section(s) updated, applied, and confirmed"
    return ret


def _check_pending(ret, config, revert_pending):
    """Check for pending deltas, optionally reverting them."""
    try:
        pending = __salt__["saltext_uci.changes"](config)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        ret["result"] = False
        ret["comment"] = f"Failed to check pending changes for {config}: {exc}"
        return None

    if pending:
        if not revert_pending:
            ret["result"] = False
            ret["comment"] = (
                f"Uncommitted changes exist for {config}. "
                f"Set revert_pending=True to discard them, or "
                f"revert manually with saltext_uci.revert. "
                f"Pending: {pending}"
            )
            return pending
        if not __opts__["test"]:
            __salt__["saltext_uci.revert"](config)
    return pending


def _read_and_resolve(ret, config, sections):
    """Read current config and resolve singleton anonymous sections."""
    try:
        current = __salt__["saltext_uci.get"](config)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        ret["result"] = False
        ret["comment"] = f"Failed to read {config}: {exc}"
        return {}, {}

    try:
        resolved = _resolve_sections(config, sections, current)
    except ValueError as exc:
        ret["result"] = False
        ret["comment"] = str(exc)
        return {}, {}

    return current, resolved


def _stage_changes(ret, config, all_changes, resolved, current):
    """Issue uci.add and uci.set calls for changed sections."""
    try:
        for section_name, section_changes in all_changes.items():
            if section_name not in current:
                desired = resolved[section_name]
                type_ = desired.get("_type")
                if not type_:
                    ret["result"] = False
                    ret["comment"] = (
                        f"Section '{section_name}' does not exist in {config} "
                        f"and no _type specified for creation"
                    )
                    return
                __salt__["saltext_uci.add"](config, type_, name=section_name)

            values = {opt: change["new"] for opt, change in section_changes.items()}
            __salt__["saltext_uci.set"](config, section_name, values)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        ret["result"] = False
        ret["comment"] = f"Failed to set values on {config}: {exc}"


def _apply_and_confirm(ret, config, all_changes, apply_rollback):
    """Apply changes, verify, and confirm."""
    try:
        __salt__["saltext_uci.apply"](rollback=apply_rollback)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        ret["result"] = False
        ret["comment"] = f"Failed to apply {config}: {exc}"
        return

    try:
        new_state = __salt__["saltext_uci.get"](config)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        ret["result"] = False
        ret["comment"] = (
            f"Failed to verify {config} after apply: {exc}. "
            f"Rollback will revert in {apply_rollback}s."
        )
        return

    for section_name, section_changes in all_changes.items():
        new_section = new_state.get(section_name, {})
        for option, change in section_changes.items():
            actual = new_section.get(option)
            if actual != change["new"]:
                ret["result"] = False
                ret["comment"] = (
                    f"Verification failed: {config}.{section_name}.{option} "
                    f"expected {change['new']!r}, got {actual!r}. "
                    f"Rollback will revert in {apply_rollback}s."
                )
                return

    try:
        __salt__["saltext_uci.confirm"]()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        ret["result"] = False
        ret["comment"] = (
            f"Failed to confirm {config}: {exc}. " f"Rollback will revert in {apply_rollback}s."
        )


def _resolve_sections(config, sections, current):
    """
    Resolve pillar section names to actual UCI section names.

    A pillar key starting with ``_`` with a ``_type`` field triggers
    singleton anonymous section lookup: find the one anonymous section
    of that type in the current config. Fails if zero or more than one
    match.
    """
    resolved = {}
    for pillar_name, desired in sections.items():
        if pillar_name.startswith("_") and "_type" in desired:
            target_type = desired["_type"]
            matches = [
                name
                for name, data in current.items()
                if data.get("_anonymous") and data.get("_type") == target_type
            ]
            if len(matches) == 0:
                raise ValueError(
                    f"No anonymous section of type '{target_type}' " f"found in {config}"
                )
            if len(matches) > 1:
                raise ValueError(
                    f"Multiple anonymous sections of type '{target_type}' "
                    f"found in {config}: {matches}. "
                    f"Singleton lookup requires exactly one. "
                    f"Full anonymous section support is planned for v0.3."
                )
            resolved[matches[0]] = desired
        else:
            resolved[pillar_name] = desired
    return resolved


def _diff_section(desired, current):
    """
    Compare desired options against current section, return changes.

    Only checks options listed in desired (partial semantics).
    Keys starting with ``_`` are metadata and skipped.
    """
    changes = {}
    for option, desired_value in desired.items():
        if option.startswith("_"):
            continue
        current_value = current.get(option)
        if current_value != desired_value:
            changes[option] = {"old": current_value, "new": desired_value}
    return changes
