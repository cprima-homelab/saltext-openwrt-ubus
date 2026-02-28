# ADR-001: Device-controlled agent mode via UCI config

- **Status**: Accepted
- **Date**: 2026-02-28
- **Context**: saltext-ubus v0.2.2 change management design

## Context

Salt extensions traditionally operate under the assumption that the Salt
master has full authority over managed devices. The master decides what
to read, what to write, and when to apply. The managed device has no
say in the matter.

For production OpenWrt routers this model is unacceptable:

1. **Unattended writes are dangerous** -- a misconfigured firewall rule
   or interface change can brick a remote device that is only reachable
   over the network it manages.
2. **Onboarding requires a read-only phase** -- when a device is first
   enrolled, the operator needs to observe what Salt *would* change
   before granting write access.
3. **Change management workflows** -- some environments require human
   approval before configuration changes take effect.

The question is: who controls the extension's behavior?

## Decision

**The managed device controls Salt's behavior through a UCI config file
(`/etc/config/salt-openwrt`), not the Salt master.**

```
config salt-openwrt 'global'
    option enabled '1'
    option mode 'audit'
    option require_commit '0'
```

The state module reads this config via `saltext_ubus.get("salt-openwrt",
"global")` at the start of every `managed()` call and enforces the mode
before any write operations.

### Mode semantics

| Mode     | Reads config | Computes drift | Stages writes | Applies | Confirms |
|----------|-------------|----------------|---------------|---------|----------|
| `audit`  | yes         | yes            | no            | no      | no       |
| `manual` | yes         | yes            | yes           | no      | no       |
| `auto`   | yes         | yes            | yes           | yes     | yes      |

- **audit** -- Salt reports what is different between desired and actual
  state. No UCI writes occur. Safe default for newly enrolled devices.
- **manual** -- Salt stages UCI changes (calls `uci set`) but does not
  call `uci apply` or `uci confirm`. The staging behavior is
  transport-aware:
  - *SSH*: changes stage to `/tmp/.uci/`, visible to `uci changes`.
    The operator reviews and activates with `uci commit && uci apply`.
  - *JSON-RPC*: changes are session-scoped (`/var/run/rpcd/uci-<sid>/`)
    and would be lost when the session expires. Salt calls `uci commit`
    to persist to `/etc/config/`. The operator activates with `uci apply`.
- **auto** -- Salt applies changes with rollback safety (existing
  behavior). Full automation.

Setting `enabled` to `0` causes Salt to skip the device entirely.

### Backward compatibility

When `/etc/config/salt-openwrt` does not exist (package not installed),
`_get_agent_mode()` catches the exception and returns `(True, "auto")`.
Existing devices continue to work without any changes.

## Rationale

### Inversion of control

The conventional approach would be to control the mode from pillar data
on the Salt master:

```yaml
# Conventional: master controls device
proxy:
  proxytype: saltext_ubus_jsonrpc
  mode: audit
```

This was rejected because:

- **The master can override device intent.** A pillar change on the
  master can silently re-enable writes on a device the operator locked
  down.
- **The device cannot protect itself.** If the master is compromised or
  misconfigured, the device has no defense.
- **Visibility is split.** The device operator must check two places
  (device config + master pillar) to understand behavior.

With the device-side config:

- **The device is self-governing.** A sysadmin sets `mode audit` on the
  router and knows Salt cannot write, regardless of what the master
  sends.
- **Configuration is visible in LuCI.** No SSH or Salt knowledge needed
  to check or change the mode.
- **Standard UCI tooling applies.** `uci set`, `uci commit`, backup/
  restore, sysupgrade config preservation all work normally.

### UCI as the config format

The agent config uses UCI (not a Salt-specific file format) because:

- It is the native config format on OpenWrt -- `uci show`, `uci set`,
  LuCI, and backup/restore all work out of the box.
- The Salt extension already reads UCI via `saltext_ubus.get()` -- no
  new parsing code is needed.
- The `conffiles` mechanism in opkg preserves user edits across package
  upgrades.

### Default to audit

New installs default to `mode audit` rather than `mode auto` because:

- Enrolling a device should be a read-only operation until the operator
  explicitly opts in to writes.
- Audit mode lets the operator observe drift reports and verify that
  pillar data is correct before granting write access.
- Switching from audit to auto is a single `uci set` command -- low
  friction when the operator is ready.

## Consequences

- A new opkg package `salt-openwrt` ships the default config file.
  It has no dependencies and can be installed alongside either
  `salt-agent-ubus` (JSON-RPC) or `salt-agent-ssh`.
- The state module's `managed()` function has three new code paths
  (disabled, audit, manual) in addition to the existing auto path.
- Drift reporting in audit mode uses the same diff logic as the normal
  path -- no separate code is needed.
- Manual mode reuses the existing `apply_rollback=None` code path.
  It is transport-aware: SSH skips commit (true staging), JSON-RPC
  commits to persist past the ephemeral rpcd session.
- The mode check adds one extra `uci get` call per `managed()` run.
  On a 128 MB device over JSON-RPC this is sub-millisecond overhead.

## Alternatives considered

### Pillar-controlled mode

Control the mode from Salt pillar data on the master. Simpler to
implement (no opkg package needed) but the device cannot protect
itself from the master. Rejected: violates the inversion-of-control
principle.

### Grain-based mode

Cache the agent config in grains during proxy init. Faster (no extra
`uci get` per run) but stale until `grains_refresh`. Mode changes
would require proxy restart. Rejected: live reads are simple and
the overhead is negligible.

### Separate config file outside UCI

Use a plain file like `/etc/salt-agent.conf` instead of UCI. Would
work but loses LuCI visibility, `uci` tooling, and opkg conffile
protection. Rejected: UCI is the right abstraction on OpenWrt.
