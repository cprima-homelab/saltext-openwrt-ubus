# 03 -- LuCI Integration

## Status: Future

This document is forward-looking. Implementation depends on completing [01 Salt Module Development](01-salt-module-development.md) and [02 CLI Config Reader](02-cli-config-reader.md) first.

## Problem

OpenWrt users expect a web interface (LuCI) for configuration. When Salt manages a router's config, there is no visibility into what Salt changed, when, or why. LuCI shows current state but has no history. There is no bridge between Salt-managed declarative config and the LuCI web interface.

## Goals

1. **Snapshot history**: maintain a rolling history of UCI configuration states
2. **Change logbook**: record what changed, when, and by which mechanism
3. **Drift detection**: alert when config diverges from the Salt-declared state
4. **Read-only dashboard** (future): LuCI page showing Salt management status

## Snapshot History

### Data Collection

Periodic snapshots via cron or Salt schedule:

```
salt-ssh '*' -r 'uci show' > snapshots/austru/2026-02-25T03:00:00.txt
```

Or stored as git commits in a dedicated branch/repo:

```
snapshots/
  austru/
    2026-02-25T03:00:00.txt
    2026-02-25T04:00:00.txt
    ...
```

### Storage Options

| Option | Pros | Cons |
|--------|------|------|
| Git repo (flat files) | Natural diffing, history, merge | Grows linearly |
| SQLite on salt-master | Queryable, compact | No built-in diff |
| Salt mine | Native Salt integration | Ephemeral, no history |

Recommended: **Git repo with flat files**. Use `git diff` for comparison. Prune old snapshots with retention policy.

### Sensitive Data

`uci show` output contains secrets: Wi-Fi PSKs, PPPoE credentials, VPN keys, DDNS tokens. Raw snapshots must not be stored in plain text in a shared or public repository.

| Mitigation | Approach | Trade-off |
|------------|----------|-----------|
| **Private repo** (minimum) | Snapshot repo is private, access-controlled | Secrets at rest in plain text; depends on hosting ACLs |
| **Scrubbing** | Strip known sensitive keys before storage | Loses data fidelity; must maintain a scrub-list per package |
| **git-crypt / SOPS** | Encrypt snapshot files transparently | Adds tooling dependency; complicates `git diff` |
| **Pillar-only diff** | Only store the subset of keys declared in pillar, ignore others | No secrets stored that aren't already in pillar; limited visibility |

**Decision**: Start with a **private repo + scrubbing** of known secret keys (`*.key`, `*.password`, `*.psk`, `*.secret`, `*.token`). The scrub step replaces values with `<REDACTED>` before commit. A future iteration can add git-crypt for full-fidelity encrypted storage if needed.

### Diff Format

Reuse the diff engine from the CLI config reader (02):

```
[2026-02-25 03:00 -> 04:00]
  network.wan.ipaddr: 192.168.16.99 -> 192.168.16.100
  + firewall.@rule[new]: Allow-HTTPS
```

## Change Logbook

### Event Sources

| Source | Trigger | Metadata |
|--------|---------|----------|
| Salt state run | State apply completes | State name, changes dict, user, timestamp |
| Manual SSH command | Snapshot diff detects change | Before/after snapshot, timestamp |
| LuCI web change | Snapshot diff detects change | Before/after snapshot, timestamp |
| Scheduled snapshot | Cron/schedule | Automatic |

### Log Format

```yaml
- timestamp: 2026-02-25T03:15:00Z
  source: salt-state
  user: root
  target: austru
  changes:
    - key: network.wan.dns
      old: [1.1.1.1, 1.0.0.1]
      new: [8.8.8.8, 8.8.4.4]
  comment: "Update DNS servers per pillar change"
```

### Salt Integration Points

The logbook needs structured change data from Salt. Without explicit integration, it can only detect changes reactively via snapshot diffs. The following mechanisms feed the logbook:

| Mechanism | How it works | When available |
|-----------|-------------|----------------|
| **Salt returner** | Custom returner writes job results (changes dict, timestamp, user) to the logbook file/repo | After execution module (01) is working; requires a returner module |
| **Reactor + event bus** | Salt reactor listens for `salt/job/*/ret/*` events and appends to logbook | Requires a running Salt master (not applicable to masterless salt-ssh) |
| **Post-state hook** | Shell script or Salt orchestration step that runs after `salt-ssh state.apply`, captures the JSON return, and appends to logbook | Works with salt-ssh; simplest to implement first |
| **Snapshot diff** (fallback) | Cron compares consecutive snapshots and infers changes | Always works; no Salt integration needed; loses "who" metadata |

**Decision**: Implement the **post-state hook** first since this project uses salt-ssh without a master. The hook parses `salt-ssh --out=json` output and writes structured log entries. A returner module is a future enhancement for environments that run a Salt master.

### Storage

Append-only log file per router, rotated monthly. Or a structured log in the snapshot git repo.

## Drift Detection

Compare latest snapshot against declared pillar state:

```
Desired (pillar):  network.wan.dns = [8.8.8.8, 8.8.4.4]
Actual (snapshot): network.wan.dns = [1.1.1.1, 1.0.0.1]
Status: DRIFTED
```

Can be implemented as:
- Salt runner that compares pillar vs live config
- Cron job on salt-master that alerts on drift
- GitHub Action that runs on pillar changes

## Future LuCI App

### Scope

A **read-only** LuCI page that shows:
- Current Salt management status (managed/unmanaged)
- Last state run timestamp and result
- Change history (last N changes from logbook)
- Drift status (in-sync / drifted)

### Architecture

```
LuCI (browser) -> uhttpd -> rpcd -> ubus -> script reads logbook
```

The LuCI app would be a separate opkg package (`luci-app-saltext-uci`) that:
- Reads a JSON status file written by Salt or cron
- Displays it in a LuCI page
- Does NOT write config (Salt is the source of truth)

### Dependencies

- Execution module (01) for reading config
- Config reader (02) for parsing and diffing
- Snapshot infrastructure (this doc) for history
- Separate repo for the LuCI app package

## Implementation Phases

1. **Snapshots**: cron job + git storage (can start now, independent of Salt module)
2. **Diff engine**: part of the config reader (02)
3. **Change logbook**: after Salt module (01) is working
4. **Drift detection**: after pillar structure is defined
5. **LuCI app**: last priority, after everything else is stable
