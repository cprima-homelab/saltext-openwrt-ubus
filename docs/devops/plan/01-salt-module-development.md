# 01 -- Salt Module Development

## Problem

OpenWrt's UCI system has commands that are not idempotent. Running `uci add` or `uci add_list` twice creates duplicates. Salt has no built-in UCI module.

Most OpenWrt routers cannot run a Salt minion at all: stock firmware lacks Python and has very limited flash (16 MB) and RAM (128 MB). The device must be managed remotely without executing Salt or Python on the target.

This extension uses the **ubus API** exclusively -- all UCI operations (and system/network/service queries) go through ubus, never the `uci` CLI. Three equally implemented transport adapters expose the same API surface: JSON-RPC over HTTPS, SSH, and local subprocess. A Salt proxy minion runs on the Salt master and talks to the device via the chosen transport -- no Salt or Python runs on the router.

The router side is configured by companion opkg packages (`salt-openwrt`, `salt-agent-ubus`) that set up the rpcd user, ACL rules, and agent mode config. While the Salt extension ships sane defaults, these packages give operators control over access scope and agent behavior directly on the device.

## Approaches Not Taken

- **UCI CLI over salt-ssh**: The original design used `cmd.run_all("uci ...")` over salt-ssh. Abandoned because parsing `uci show` output is fragile, each operation requires a separate SSH round-trip, and there is no confirmed-commit safety net.
- **Salt minion on device**: Running Python + Salt thin tarball on the router requires ~256 MB RAM and 16 MB free flash. The WNDR3800 has 128 MB RAM and 16 MB total flash -- not viable.
- **Raw mode / shell scripts**: A `render_script()` helper was planned to generate self-contained shell scripts for constrained devices. Never implemented; the ubus JSON-RPC proxy eliminates the need since no code runs on the device.
- **Package whitelist**: Early design proposed limiting managed packages to a hardcoded list. Dropped in favor of the device's rpcd ACL controlling access (`uci: ["*"]`).
- **Custom return payload**: A `{result, comment, changes, value}` wrapper dict was planned for execution module functions. Dropped; functions return raw ubus response dicts, and the state module handles result formatting.

## Architecture: Three Transport Adapters

All adapters call the same ubus API. No adapter uses the `uci` CLI.

| Adapter | Transport Path | Use Case |
|---------|---------------|----------|
| `ubus_jsonrpc.py` | HTTPS -> uhttpd -> rpcd -> ubus | Primary. Used for austru via proxy minion |
| `uci_ssh.py` | SSH -> `ubus call` CLI | Fallback / autan. Via salt-ssh proxy |
| `uci_local.py` | subprocess -> `ubus call` | On-device use (no proxy needed) |

### Shared Logic via Dependency Injection

All business logic lives in `utils/ubus_ops.py`. Each adapter only defines:

- `__virtual__()` -- decides whether this adapter should load
- `_call(ubus_object, ubus_method, params)` -- transport-specific ubus invocation

Every public function in the adapter delegates to `ubus_ops.<function>(call=_call, ...)`. This keeps the three adapters identical in behavior and avoids code duplication.

### Virtual Name Resolution

All three adapters register `__virtualname__ = "openwrt_ubus"`. Salt loads exactly one based on context:

- **JSON-RPC**: loads when `__opts__["proxy"]["proxytype"] == "openwrt_ubus_jsonrpc"`
- **SSH**: loads when `__opts__["proxy"]["proxytype"] == "openwrt_ubus_ssh"`
- **Local**: loads when not a proxy minion and the `ubus` binary exists on the system

## Package Scope

The following UCI-relevant packages ship in the current target build (WNDR3800, OpenWrt 24.10.x):

| Package | UCI Config File(s) | Priority |
|---------|-------------------|----------|
| `base-files` | `system` | Must have |
| `netifd` | `network` | Must have |
| `firewall4` | `firewall` | Must have |
| `dnsmasq` | `dhcp` | Must have |
| `dropbear` | `dropbear` | Must have |
| `odhcpd-ipv6only` | `dhcp` (shared) | Must have |
| `ppp` / `ppp-mod-pppoe` | `network` (wan sections) | Must have |
| `wpad-basic-mbedtls` | `wireless` | Must have |
| `luci` | `uhttpd`, `luci`, `rpcd` | Should have |
| `opkg` | `opkg` | Nice to have |
| `uboot-envtools` | `ubootenv` | Nice to have |

The module does not whitelist packages. The rpcd ACL on the device grants `uci: ["*"]`, so any UCI config package is manageable. The table above is informational -- it documents what ships on the target build.

## Execution Module API

Module name: `openwrt_ubus` (called as `salt 'austru' openwrt_ubus.<function>`, or shorthand `openwrt.<function>`)

All functions return raw ubus response dicts. There is no custom wrapper format.

### Read Operations

| Function | ubus Call | Returns |
|----------|----------|---------|
| `get(config, section=None, option=None)` | `uci get` | Full config dict, single section, or single option value |
| `configs()` | `uci configs` | List of available UCI config packages |
| `changes(config)` | `uci changes` | List of uncommitted changes |
| `state(config, section=None)` | `uci state` | Runtime-merged state (defaults + config + overrides) |

### Write Operations

| Function | ubus Call | Notes |
|----------|----------|-------|
| `set(config, section, values)` | `uci set` | Set one or more options on a section |
| `add(config, type, name=None, values=None)` | `uci add` | Create a section (named or anonymous) |
| `delete(config, section, option=None)` | `uci delete` | Delete a section or single option |

### Apply / Commit / Revert Operations

| Function | ubus Call | Notes |
|----------|----------|-------|
| `apply(timeout=90)` | `uci apply` | Apply with rollback safety (`rollback=True`) |
| `confirm()` | `uci confirm` | Lock in applied changes, cancel rollback timer |
| `rollback()` | `uci rollback` | Manually trigger rollback to pre-apply state |
| `commit(config)` | `uci commit` | Write staged changes to `/etc/config` without reloading services |
| `revert(config)` | `uci revert` | Discard staged (uncommitted) changes |

### System / Network / Service Queries

| Function | ubus Call | Returns |
|----------|----------|---------|
| `system_board()` | `system board` | Board info: kernel, hostname, model, release |
| `system_info()` | `system info` | Memory, uptime, load averages |
| `network_dump()` | `network.interface dump` | All network interfaces and their state |
| `service_list(verbose=False)` | `service list` | procd service list with instance info |

### Metadata Transform

ubus returns UCI metadata with dot-prefixed keys (`.type`, `.name`, `.anonymous`, `.index`). The helper `ubus_ops.transform_section()` converts these to underscore-prefixed (`_type`, `_name`, `_anonymous`, `_index`) for Python compatibility.

## State Module

Module name: `openwrt_ubus` (used in state files as `openwrt_ubus.managed`, or shorthand `openwrt.managed`)

### `managed(name, config, sections, apply_rollback=None, revert_pending=False)`

Declarative UCI configuration. Converges a config package to the desired state.

**Flow:**

1. Read agent mode from device config (`salt-openwrt.global` section)
2. Check for uncommitted changes (fail or revert based on `revert_pending`)
3. Read current config via `uci.get(config)`
4. Resolve sections: handle singleton anonymous section matching via `_resolve_sections()`
5. Diff each section: compare desired vs current via `_diff_section()`
6. Guard against type mismatches before staging any changes
7. Stage changes: `uci.add` for missing sections, `uci.set` for changed options
8. Apply or defer based on agent mode and `apply_rollback` parameter

### `applied(name, config=None, rollback=None)`

Applies staged changes and verifies service health. Used in autoverified/humanreviewed modes where `managed()` only stages and `applied()` commits.

**Flow:**

1. Read agent mode, resolve rollback timeout
2. Snapshot currently running services (PIDs)
3. Call `uci.apply(rollback=timeout)` to commit and reload
4. Poll `service.list` until all previously-running services are back
5. If healthy: call `uci.confirm()` to cancel rollback timer
6. If services down: skip confirm, let rpcd auto-rollback

### Agent Modes

| Mode | `managed()` Behavior | `applied()` Needed |
|------|----------------------|-------------------|
| `oneshot` | Stage + apply + confirm in one call | No |
| `autoverified` | Stage only | Yes -- applies, polls services, confirms |
| `humanreviewed` | Stage only | Yes -- operator reviews staged changes first |
| `audit` | Report drift, never write | No |

Each state function returns the standard Salt state dict: `{name, changes, result, comment}` with `result=None` in test mode.

## Idempotency Strategy

### Partial Semantics

Only options listed in the `sections` dict are managed. Other options on the same section are left untouched. This allows incremental management of shared config files.

### Config Diffing

`_diff_section(desired, current)` compares desired options against current state:

- Skips metadata fields (keys starting with `_`)
- Returns `{option: {old: current_value, new: desired_value}}` for each difference
- If no differences: state reports "already in desired state" (no-op)

### Anonymous Section Resolution

`_resolve_sections(config, sections, current)` returns a `(resolved, prune_targets)` tuple and handles three cases:

- **Singleton**: pillar key starts with `_` and has a `_type` field -- search for anonymous sections (`_anonymous=True`) matching that type. Exactly 1 match required.
- **Multi-instance**: `_match` + `_items` pillar syntax -- each item is matched against existing anonymous sections by the `_match` key. Unmatched items are created. `_prune: true` removes unmatched existing sections.
- **`_absent`**: pass-through for section deletion, no resolution needed.

### What Gets Staged

Only changed options are staged. The diff is computed in Python against the full config dict returned by `uci.get`. No shell-side parsing or `uci show` output processing.

## Apply / Confirm / Rollback

rpcd supports a confirmed-commit cycle via `uci.apply`:

1. `uci.apply(rollback=True, timeout=N)` -- apply changes and start a rollback timer
2. If the caller confirms within `timeout` seconds via `uci.confirm()`, changes are permanent
3. If no confirmation arrives (e.g., network broke, service crashed), rpcd automatically reverts

### Service Health Verification

The state module uses this cycle for safe applies:

1. **Snapshot**: record PIDs of all running services via `service.list` before apply
2. **Apply**: call `uci.apply` with rollback timeout
3. **Poll**: repeatedly call `service.list` until all previously-running services are back
4. **Confirm or let rollback**: if services recovered, call `uci.confirm()`; otherwise the rollback timer expires and rpcd reverts automatically

The polling deadline includes a safety margin (`rollback // 4`, minimum 10 seconds) before the rollback timeout to avoid racing the timer.

## rpcd Session and Timeouts

The JSON-RPC proxy maintains a persistent rpcd session. This is crucial for the autoverified workflow: `managed()` stages changes in one state run, `applied()` commits them in a subsequent run, and the staged changes persist because they share the same rpcd session through the proxy minion.

Three separate timeout mechanisms:

| Timeout | Default | Controlled By | Purpose |
|---------|---------|--------------|---------|
| Session timeout | 300s | pillar `session_timeout` | How long the rpcd login session lives |
| Invoke timeout | 300s | pillar `rpcd_timeout` (UCI `rpcd.@rpcd[0].timeout`) | How long rpcd waits for a ubus call to return |
| HTTP timeout | 30s | pillar `timeout` | urllib request timeout |

The proxy re-authenticates transparently via `_ensure_session()` when the session nears expiry (10-second margin).

## Testing Strategy

### Unit Tests

- **Execution module tests**: mock the proxy's `call()` function, verify each adapter delegates correctly to `ubus_ops`
- **State module tests**: mock execution module functions (`openwrt_ubus.get`, `openwrt_ubus.set`, etc.), test idempotency logic, agent modes, service health verification
- **Proxy tests**: mock `UbusRpcClient`, verify login, session management, grains fetching, timeout bumping
- **Utils tests**: test `ubus_ops.transform_section()`, `UbusRpcClient` request/response handling, `SshRunner` command building

### Functional Tests

- Use `pytest-salt-factories` loader fixtures
- Test module loading and `__virtual__` resolution
- Test state module with mock execution module through Salt's loader

### Integration Tests

- Containerized OpenWrt with rpcd planned but not yet implemented
- SSH integration fixtures configured (`sshd_server`, `known_hosts_file`, `salt_ssh_roster_file`)

## File Locations

```
src/saltext/openwrt_ubus/
  __init__.py
  version.py
  grains/
    saltext_ubus.py          # Device grains via proxy
  modules/
    ubus_jsonrpc.py           # Execution module: JSON-RPC adapter
    uci_ssh.py                # Execution module: SSH adapter
    uci_local.py              # Execution module: local subprocess adapter
    openwrt.py                # Shorthand alias -> openwrt_ubus via __salt__
  proxy/
    ubus_jsonrpc.py           # Proxy minion: JSON-RPC transport
    uci_ssh.py                # Proxy minion: SSH transport
  states/
    saltext_ubus.py           # State module: managed() and applied()
    openwrt.py                # Shorthand alias -> openwrt_ubus via __states__
  utils/
    ubus_ops.py               # Shared ubus logic (all 16 functions)
    rpc.py                    # UbusRpcClient (HTTPS JSON-RPC)
    ssh.py                    # SshRunner (SSH command execution)

tests/
  unit/
    grains/test_saltext_ubus.py
    modules/
      test_ubus_jsonrpc.py
      test_uci_ssh.py
      test_uci_local.py
    proxy/
      test_ubus_jsonrpc.py
      test_uci_ssh.py
    states/test_saltext_ubus.py
    utils/
      test_rpc.py
      test_ssh.py
      test_ubus_ops.py
```
