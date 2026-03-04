# 03 -- LuCI Integration (not yet implemented)

> Last reviewed against: v0.4.0

## Goal

Make Salt-staged UCI changes visible in LuCI's "Unsaved Changes" view,
so operators using humanreviewed mode can review and apply Salt-proposed
changes through the web interface they already know.

## Status

Not started. The humanreviewed agent mode exists -- `managed()` stages
changes without applying -- but the staged changes are invisible to LuCI
because each rpcd session gets an isolated staging directory
(`/var/run/rpcd/uci-<session_id>/`).

## Problem

Salt's rpcd JSON-RPC session and LuCI's rpcd session are separate.
Neither can see the other's pending changes. An operator in humanreviewed
mode has no way to inspect what Salt staged without using the CLI.

## TODO

- [ ] Investigate whether Salt can stage into LuCI's rpcd session
      directory (e.g., authenticate with an existing LuCI session token)
- [ ] Alternatively, explore writing directly to LuCI's staging path
      via SSH, bypassing rpcd session isolation
- [ ] Check if rpcd supports any shared/global staging mechanism
      outside per-session directories
- [ ] Prototype: after `managed()` stages changes, copy the delta files
      into a location LuCI can pick up on next page load

## Design Notes

- This is specifically for humanreviewed mode; oneshot and autoverified
  apply changes immediately and do not need LuCI visibility
- The operator clicks "Save & Apply" in LuCI to finalize, completing
  the human review loop
- Salt remains the source of truth for desired state; LuCI is only the
  review/apply interface
- Drift detection (comparing live config against pillar) is a separate
  concern handled by the execution module, not a LuCI feature
