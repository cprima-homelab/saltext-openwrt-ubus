"""
Salt state module for OpenWrt configuration management via ubus.

Ensures UCI sections match a desired state using partial semantics:
only options present in pillar are managed, unmanaged options are
left untouched. Supports named sections, singleton anonymous
sections (``_type`` match), and multi-instance anonymous sections
(``_match``/``_items`` with order enforcement and ``_prune``).
The ``_absent`` sentinel deletes options or entire sections.
"""

import logging
import time

from saltext.openwrt_ubus.utils import scope
from saltext.openwrt_ubus.utils.ubus_ops import diff_section as _diff_section
from saltext.openwrt_ubus.utils.ubus_ops import resolve_sections as _resolve_sections

log = logging.getLogger(__name__)

POLL_INTERVAL = 3  # seconds between service polls
SAFETY_MARGIN_FRACTION = 4  # use rollback // 4 as margin, min 10s

__virtualname__ = "openwrt_ubus"
__proxyenabled__ = ["openwrt_ubus_jsonrpc", "openwrt_ubus_ssh"]


def __virtual__():
    if "openwrt_ubus.get" not in __salt__:
        return False, "The 'openwrt_ubus' execution module is not available"
    return __virtualname__


def managed(  # pylint: disable=too-many-return-statements
    name, config, sections, apply_rollback=None, revert_pending=False, allow_experimental=None
):
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
        apply_rollback: Rollback timeout in seconds. ``None`` (default)
            = resolve from device ``rollback_timeout`` config in oneshot
            mode, or stage only in autoverified/humanreviewed mode.
        revert_pending: If ``True``, silently revert uncommitted deltas
            before proceeding. If ``False`` (default), fail when pending
            deltas exist to prevent discarding someone else's staged
            changes.
        allow_experimental: Controls access to experimental-tier packages.
            ``True`` = allow, ``False`` = deny (overrides pillar),
            ``None`` (default) = check pillar
            ``openwrt:allow_experimental``.

    Example:

    .. code-block:: yaml

        network_config:
          openwrt_ubus.managed:
            - config: network
            - sections:
                lan:
                  _type: interface
                  proto: static
                  ipaddr: 10.35.24.1
    """
    ret = {"name": name, "changes": {}, "result": True, "comment": ""}

    # 1. Check agent mode
    enabled, mode, rollback_timeout = _get_agent_mode()
    if not enabled:
        ret["comment"] = f"{config}: salt-openwrt disabled on device, skipping"
        return ret

    # 2. Check package scope
    _check_scope(ret, config, allow_experimental)
    if ret["result"] is False:
        return ret

    # 3. Check for pending deltas
    pending = _check_pending(ret, config, revert_pending)
    if ret["result"] is False:
        return ret

    # 4. Read current state and resolve sections
    current, resolved, prune_targets = _read_and_resolve(ret, config, sections)
    if ret["result"] is False:
        return ret

    # 5. Diff: compare desired against current (partial)
    all_changes = {}
    for section_name, desired in resolved.items():
        # Whole-section absence: mark for deletion
        if desired == "_absent":
            if section_name in current:
                all_changes[section_name] = {"_action": "delete"}
            continue

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

    # 5b. Mark pruned sections for deletion
    for section_name in prune_targets:
        all_changes[section_name] = {"_action": "delete"}

    if not all_changes:
        if mode == "audit":
            ret["comment"] = f"{config}: audit mode -- no drift detected"
        else:
            ret["comment"] = f"{config}: already in desired state"
        return ret

    # 6. Audit mode -- report drift, never write
    if mode == "audit":
        ret["changes"] = all_changes
        ret["comment"] = (
            f"{config}: audit mode -- {len(all_changes)} section(s) drifted, " f"no changes applied"
        )
        return ret

    # 7. Autoverified / humanreviewed mode -- stage only, do not apply
    if mode in ("autoverified", "humanreviewed"):
        apply_rollback = None

    # 8. Resolve apply_rollback default for oneshot mode
    if apply_rollback is None and mode == "oneshot":
        apply_rollback = rollback_timeout

    # 9. Test mode
    if __opts__["test"]:
        ret["result"] = None
        ret["changes"] = all_changes
        parts = []
        if pending and revert_pending:
            parts.append(f"would revert pending changes: {pending}")
        parts.append(f"{len(all_changes)} section(s) would be updated")
        ret["comment"] = f"{config}: {'; '.join(parts)}"
        return ret

    # 10. Stage uci.set calls
    _stage_changes(ret, config, all_changes, resolved, current)
    if ret["result"] is False:
        return ret

    # 11. Commit or apply
    _commit_or_apply(ret, config, all_changes, apply_rollback)
    if ret["result"] is False:
        return ret

    ret["changes"] = all_changes
    return ret


def applied(name, config=None, rollback=None):
    """
    Apply staged UCI changes with rollback protection and service
    health verification.

    Use after ``managed()`` in autoverified mode to safely activate
    changes that have been staged. In oneshot mode, ``managed()``
    handles apply and confirm internally -- this state is not needed.

    The rpcd confirmed-commit cycle:

    1. ``uci apply`` snapshots ``/etc/config/*``, commits staged
       changes, reloads services, and arms a rollback timer.
    2. This state polls ``service list`` until all previously-running
       services show ``running=true`` again.
    3. ``uci confirm`` cancels the timer -- changes are permanent.
    4. If services crash or fail to restart, confirm is NOT called
       and rpcd auto-reverts when the timer expires.

    Args:
        name: State ID.
        config: UCI package name. Optional, used only for labeling.
        rollback: Rollback timeout in seconds. Default ``None`` =
            resolved from device ``rollback_timeout`` config.
    """
    ret = {"name": name, "changes": {}, "result": True, "comment": ""}
    label = config or "all"

    # 1. Check agent enabled
    enabled, _, rollback_timeout = _get_agent_mode()
    if not enabled:
        ret["comment"] = f"{label}: salt-openwrt disabled on device, skipping"
        return ret

    # Resolve rollback default from device config
    if rollback is None:
        rollback = rollback_timeout

    # 2. Test mode
    if __opts__["test"]:
        ret["result"] = None
        ret["comment"] = f"{label}: would apply staged changes with {rollback}s rollback"
        return ret

    # 3. Snapshot running services before apply
    snapshot = _snapshot_services()

    # 4. Apply with rollback timer
    try:
        __salt__["openwrt_ubus.apply"](rollback=rollback)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        # ubus status 5 = "No data" means nothing to apply
        if "status 5" in str(exc) or "No data" in str(exc):
            ret["comment"] = f"{label}: nothing to apply"
            return ret
        ret["result"] = False
        ret["comment"] = f"Failed to apply {label}: {exc}"
        return ret

    # 5. Poll services until all previously-running are back
    all_ok, down = _wait_for_services(snapshot, rollback)
    if not all_ok:
        ret["result"] = False
        ret["comment"] = (
            f"{label}: services not recovered after apply, "
            f"NOT confirming (rollback will revert in {rollback}s). "
            f"Down: {', '.join(down)}"
        )
        return ret

    # 6. Confirm -- cancel rollback timer, changes permanent
    try:
        __salt__["openwrt_ubus.confirm"]()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        ret["result"] = False
        ret["comment"] = (
            f"Failed to confirm {label}: {exc}. " f"Rollback will revert in {rollback}s."
        )
        return ret

    svc_note = ""
    if snapshot:
        svc_note = f" ({len(snapshot)} service(s) verified running)"
    ret["comment"] = f"{label}: applied and confirmed{svc_note}"
    return ret


def _get_agent_mode():
    """Read salt-openwrt config from the device. Returns (enabled, mode, rollback_timeout)."""
    try:
        agent = __salt__["openwrt_ubus.get"]("salt-openwrt", "global")
    except Exception:  # pylint: disable=broad-exception-caught
        log.debug("salt-openwrt config not found, defaulting to oneshot mode")
        return True, "oneshot", 120
    enabled = agent.get("enabled", "1") == "1"
    mode = agent.get("mode", "oneshot")
    try:
        rollback_timeout = int(agent.get("rollback_timeout", "120"))
    except (ValueError, TypeError):
        rollback_timeout = 120
    return enabled, mode, rollback_timeout


def _check_scope(ret, config, allow_experimental):
    """Check if the package is within the supported scope. Modifies ret in place."""
    pkg_tier = scope.tier(config)
    if pkg_tier is None:
        ret["result"] = False
        ret["comment"] = (
            f"{config}: not in saltext-openwrt-ubus scope. "
            f"Supported packages: {', '.join(scope.supported())}"
        )
        return
    if pkg_tier == "experimental":
        if allow_experimental is None:
            allow_experimental = __salt__["pillar.get"]("openwrt:allow_experimental", False)
        if not allow_experimental:
            ret["result"] = False
            ret["comment"] = (
                f"{config}: experimental support. "
                f"Pass allow_experimental=True or set "
                f"pillar openwrt:allow_experimental to proceed."
            )


def _is_json_rpc():
    """Check if the current transport is JSON-RPC (session-scoped staging)."""
    return __opts__.get("proxy", {}).get("proxytype") == "openwrt_ubus_jsonrpc"


def _check_pending(ret, config, revert_pending):
    """Check for pending deltas, optionally reverting them."""
    try:
        pending = __salt__["openwrt_ubus.changes"](config)
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
                f"revert manually with openwrt_ubus.revert. "
                f"Pending: {pending}"
            )
            return pending
        if not __opts__["test"]:
            __salt__["openwrt_ubus.revert"](config)
    return pending


def _read_and_resolve(ret, config, sections):
    """Read current config and resolve anonymous sections."""
    try:
        current = __salt__["openwrt_ubus.get"](config)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        ret["result"] = False
        ret["comment"] = f"Failed to read {config}: {exc}"
        return {}, {}, []

    try:
        resolved, prune_targets = _resolve_sections(config, sections, current)
    except ValueError as exc:
        ret["result"] = False
        ret["comment"] = str(exc)
        return {}, {}, []

    return current, resolved, prune_targets


def _stage_changes(ret, config, all_changes, resolved, current):
    """Issue uci.add, uci.set, and uci.delete calls for changed sections.

    Processes deletions before additions to avoid section count limits
    during reorder operations. Handles:

    - Section deletion (``_action: delete`` from prune or ``_absent``)
    - Anonymous section creation (``_anonymous_new`` flag in resolved)
    - Named section creation (existing behavior)
    - Option-level ``_absent`` (delete individual options)
    - Normal option updates (uci.set)
    """
    try:
        # Split into deletes and updates; process deletes first
        deletes = {
            k: v
            for k, v in all_changes.items()
            if isinstance(v, dict) and v.get("_action") == "delete"
        }
        updates = {
            k: v
            for k, v in all_changes.items()
            if not (isinstance(v, dict) and v.get("_action") == "delete")
        }

        # 1. Deletions (prune, _absent whole-section, reorder tear-down)
        for section_name in deletes:
            __salt__["openwrt_ubus.delete"](config, section_name)

        # 2. Creates and updates
        for section_name, section_changes in updates.items():
            # Separate normal values from _absent options
            values = {}
            absent_opts = []
            for opt, change in section_changes.items():
                if change["new"] == "_absent":
                    absent_opts.append(opt)
                else:
                    values[opt] = change["new"]

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

                if desired.get("_anonymous_new"):
                    # Anonymous: add without name, get generated name back
                    result = __salt__["openwrt_ubus.add"](config, type_)
                    generated = result if isinstance(result, str) else result.get("section", result)
                    if values:
                        __salt__["openwrt_ubus.set"](config, generated, values)
                    for opt in absent_opts:
                        __salt__["openwrt_ubus.delete"](config, generated, opt)
                else:
                    # Named: add with name
                    __salt__["openwrt_ubus.add"](config, type_, name=section_name)
                    if values:
                        __salt__["openwrt_ubus.set"](config, section_name, values)
                    for opt in absent_opts:
                        __salt__["openwrt_ubus.delete"](config, section_name, opt)
            else:
                # Existing section: set changed values, delete absent options
                if values:
                    __salt__["openwrt_ubus.set"](config, section_name, values)
                for opt in absent_opts:
                    __salt__["openwrt_ubus.delete"](config, section_name, opt)

    except Exception as exc:  # pylint: disable=broad-exception-caught
        ret["result"] = False
        ret["comment"] = f"Failed to stage changes on {config}: {exc}"


def _commit_or_apply(ret, config, all_changes, apply_rollback):
    """Commit or apply depending on rollback setting and transport type."""
    if apply_rollback is None:
        # Autoverified / humanreviewed mode: leave changes staged for
        # applied() to commit+reload with rollback protection.  SSH stages
        # to /tmp/.uci/ (reviewable via 'uci changes'), JSON-RPC stages in
        # the rpcd session (kept alive by the proxy minion).
        if _is_json_rpc():
            ret["comment"] = (
                f"{config}: {len(all_changes)} section(s) staged in rpcd session "
                f"(apply with openwrt_ubus.applied)"
            )
        else:
            ret["comment"] = (
                f"{config}: {len(all_changes)} section(s) staged "
                f"(review with 'uci changes {config}', "
                f"then apply with openwrt_ubus.applied)"
            )
    else:
        _apply_and_confirm(ret, config, all_changes, apply_rollback)
        if ret["result"] is False:
            return
        ret["comment"] = f"{config}: {len(all_changes)} section(s) updated, applied, and confirmed"


def _apply_and_confirm(ret, config, all_changes, apply_rollback):
    """Apply changes, verify UCI values, check services, and confirm."""
    # Snapshot running services before apply
    snapshot = _snapshot_services()

    try:
        __salt__["openwrt_ubus.apply"](rollback=apply_rollback)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        ret["result"] = False
        ret["comment"] = f"Failed to apply {config}: {exc}"
        return

    # Verify UCI values were written correctly
    try:
        new_state = __salt__["openwrt_ubus.get"](config)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        ret["result"] = False
        ret["comment"] = (
            f"Failed to verify {config} after apply: {exc}. "
            f"Rollback will revert in {apply_rollback}s."
        )
        return

    for section_name, section_changes in all_changes.items():
        # Deleted sections should be gone
        if isinstance(section_changes, dict) and section_changes.get("_action") == "delete":
            if section_name in new_state:
                ret["result"] = False
                ret["comment"] = (
                    f"Verification failed: {config}.{section_name} "
                    f"expected deleted, still exists. "
                    f"Rollback will revert in {apply_rollback}s."
                )
                return
            continue

        new_section = new_state.get(section_name, {})
        for option, change in section_changes.items():
            if change["new"] == "_absent":
                # Option should be gone
                if option in new_section:
                    ret["result"] = False
                    ret["comment"] = (
                        f"Verification failed: {config}.{section_name}.{option} "
                        f"expected absent, still exists. "
                        f"Rollback will revert in {apply_rollback}s."
                    )
                    return
            else:
                actual = new_section.get(option)
                if actual != change["new"]:
                    ret["result"] = False
                    ret["comment"] = (
                        f"Verification failed: {config}.{section_name}.{option} "
                        f"expected {change['new']!r}, got {actual!r}. "
                        f"Rollback will revert in {apply_rollback}s."
                    )
                    return

    # Check that services recovered after apply
    all_ok, down = _wait_for_services(snapshot, apply_rollback)
    if not all_ok:
        ret["result"] = False
        ret["comment"] = (
            f"{config}: services not recovered after apply, "
            f"NOT confirming (rollback will revert in {apply_rollback}s). "
            f"Down: {', '.join(down)}"
        )
        return

    try:
        __salt__["openwrt_ubus.confirm"]()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        ret["result"] = False
        ret["comment"] = (
            f"Failed to confirm {config}: {exc}. " f"Rollback will revert in {apply_rollback}s."
        )


def _snapshot_services():
    """
    Snapshot currently running services via ``service list``.

    Returns dict of ``{service_name: {instance_name: pid}}`` for running
    instances only. Services with no running instances are skipped.
    """
    try:
        services = __salt__["openwrt_ubus.service_list"]()
    except Exception:  # pylint: disable=broad-exception-caught
        log.debug("Could not snapshot services, skipping health check")
        return {}

    if not services:
        return {}

    snapshot = {}
    for svc_name, svc_data in services.items():
        instances = svc_data.get("instances", {})
        running = {}
        for inst_name, inst_data in instances.items():
            if inst_data.get("running"):
                running[inst_name] = inst_data.get("pid")
        if running:
            snapshot[svc_name] = running
    return snapshot


def _wait_for_services(snapshot, rollback):
    """
    Poll ``service list`` until all previously-running services are back.

    Returns ``(all_ok, down)`` where ``down`` is a list of
    ``"service/instance"`` strings for services still not running.
    Stops polling with a safety margin before the rollback deadline.
    """
    if not snapshot:
        return True, []

    safety_margin = max(10, rollback // SAFETY_MARGIN_FRACTION)
    deadline = time.monotonic() + rollback - safety_margin

    while True:
        time.sleep(POLL_INTERVAL)

        try:
            services = __salt__["openwrt_ubus.service_list"]()
        except Exception:  # pylint: disable=broad-exception-caught
            log.debug("service_list poll failed, will retry")
            if time.monotonic() >= deadline:
                # Can't verify -- treat as failure
                down = [f"{svc}/{inst}" for svc, insts in snapshot.items() for inst in insts]
                return False, down
            continue

        down = []
        for svc_name, instances in snapshot.items():
            svc_data = (services or {}).get(svc_name, {})
            svc_instances = svc_data.get("instances", {})
            for inst_name in instances:
                inst_data = svc_instances.get(inst_name, {})
                if not inst_data.get("running"):
                    down.append(f"{svc_name}/{inst_name}")

        if not down:
            return True, []

        if time.monotonic() >= deadline:
            return False, down
