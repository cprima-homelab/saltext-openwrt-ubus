# 01 -- Salt Module Development

## Problem

OpenWrt's UCI system has commands that are not idempotent. Running `uci add` or `uci add_list` twice creates duplicates. Salt has no built-in UCI module. This extension must provide idempotent UCI management that works over both salt-ssh module mode and raw mode.
Most OpenWrt router architectures do not run a Salt minion at all because stock firmware lacks Python and has very limited flash/RAM, so salt-ssh (either module mode or raw scripts) is the default transport this project must optimize for.

## Assumptions

- **SSH key authentication** is the expected access method. The roster file references key paths; password-based SSH (`passwd:`, `sshpass`) is considered out of scope for now.
- **Dropbear** on the target needs an authorized key deployed before salt-ssh can manage it.

These assumptions may be revisited as the project matures.

## Package Scope

The project needs a way to limit which UCI packages it covers. One option is a whitelist based on the standard OpenWrt build profile.

### Standard Build Packages

The following packages ship in the current target build:

```
base-files ca-bundle dnsmasq dropbear firewall4 fstools
kmod-ath9k kmod-gpio-button-hotplug kmod-nft-offload
libc libgcc libustream-mbedtls logd mtd netifd nftables
odhcp6c odhcpd-ipv6only opkg ppp ppp-mod-pppoe procd-ujail
swconfig uboot-envtools uci uclient-fetch urandom-seed urngd
wpad-basic-mbedtls kmod-usb-ohci kmod-usb2 kmod-usb-ledtrig-usbport
kmod-leds-reset kmod-owl-loader kmod-switch-rtl8366s luci
```

Not all of these produce UCI config (kernel modules, libraries). The UCI-relevant subset, with a tentative priority ranking:

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

### Open Questions

- Should the whitelist be hardcoded, or configurable per deployment?
- How should additional packages (e.g., VPN, advanced routing) be added later -- extend the table, or a separate config file?
- Is the priority ranking above correct, or should some packages move between tiers?

## Execution Module Functions

Module name: `saltext_uci` (called as `salt-ssh '*' saltext_uci.<function>`)

### Common Plumbing

All execution module functions follow shared conventions:

**Standard return payload**: Every function returns a dict with consistent structure:
```python
{
    "result": True,       # bool: success or failure
    "comment": "",        # str: human-readable summary
    "changes": {},        # dict: what changed (empty if no-op)
    "value": ...,         # any: the requested data (read ops) or None (write ops)
}
```

**Error surfacing**: UCI errors (non-zero return codes, stderr output) are captured via `cmd.run_all` and surfaced in the `comment` field with the raw UCI error message. Functions never silently swallow errors.

**`__virtual__` failure handling**: The module refuses to load (returns a reason string) if `uci` is not found on the target. The check uses `salt.utils.path.which("uci")`.

**Batching round-trips** (post-v0.1): For operations that require multiple UCI calls (e.g., `add` with match check, `set_list`), a future optimization can read state once via a single `uci show <package>` call and parse in Python, rather than issuing separate `uci get` calls per option. In v0.1, each function issues its own UCI calls for simplicity.

**Shell command API**: All functions use `__salt__["cmd.run_all"]` (not `cmd.run`) to capture return codes and stderr. This is mandatory for salt-ssh compatibility.

### Read Operations

| Function | UCI Command | Returns |
|----------|------------|---------|
| `show(package=None)` | `uci show [package]` | Parsed dict of all config or one package |
| `get(key)` | `uci get <key>` | Single value or list |
| `export(package=None)` | `uci export [package]` | Raw UCI export text |
| `changes(package=None)` | `uci changes [package]` | List of uncommitted changes |

### Write Operations

| Function | UCI Command | Idempotent | Strategy |
|----------|------------|-----------|----------|
| `set(key, value)` | `uci set` | Yes | Direct call |
| `delete(key)` | `uci -q delete` | Yes | Direct call with `-q` |
| `add(package, type, values, match_on)` | `uci add` | **Made safe** | Parse `uci show` output via shared parser, match on `match_on` fields, skip if found |
| `add_list(key, value)` | `uci add_list` | **Made safe** | Read current list, skip if value already present |
| `del_list(key, value)` | `uci del_list` | Yes | Direct call |
| `set_list(key, values)` | delete + add_list | **Made safe** | Delete list, add all desired values |
| `commit(package=None)` | `uci commit` | Yes | Direct call |
| `revert(package=None)` | `uci revert` | Yes | Direct call |

### Compound Operations

| Function | Purpose |
|----------|---------|
| `section_exists(package, type, match_on)` | Check if a section matching criteria exists |
| `ensure_section(package, type, name, values)` | Create named section if absent, set all values |
| `diff(package=None)` | Compare running config vs committed config |

## Idempotency Strategy

### Anonymous Sections (`uci add`)

UCI anonymous sections are referenced by index (`firewall.@rule[3]`). The index changes when sections are added or removed. To make `add` idempotent:

```
1. Read package state: call uci show <package> once
2. Parse output using the shared uci_parser library (see 02-cli-config-reader.md, Phase 1)
3. Filter sections by target type in Python
4. For each existing section, compare values in match_on fields
5. If a match is found, return the existing section path (no change)
6. If no match, call uci add and set values
```

The parsing is done in Python, not via shell `grep`, to avoid BusyBox incompatibilities in raw mode and to reuse the same parser as the CLI config reader (02).

The `match_on` parameter defines which fields constitute identity. Example:
- Firewall rule: `match_on=["name"]` or `match_on=["src", "dest", "dest_port"]`
- DHCP host: `match_on=["name"]` or `match_on=["mac"]`

### List Options (`uci add_list`)

```
1. Read current list: uci get <key> (returns space-separated or error if unset)
2. If desired value already in list, return (no change)
3. If not present, call uci add_list
```

For `set_list` (replace entire list):
```
1. Read current list
2. If current == desired, return (no change)
3. Delete list: uci delete <key>
4. Add each desired value: uci add_list <key>=<value>
```

## State Module Functions

Module name: `saltext_uci` (called in state files as `saltext_uci.<state>`)

| State | Purpose | Example |
|-------|---------|---------|
| `option_present` | Ensure a UCI option has a specific value | `network.lan.ipaddr: 10.35.24.1` |
| `option_absent` | Ensure a UCI option does not exist | Remove `network.wan6` |
| `section_present` | Ensure a section exists with given values | Firewall zone with specific settings |
| `section_absent` | Ensure a section does not exist | Remove a firewall rule by match |
| `list_present` | Ensure a list option contains specific values | DNS servers in `network.wan.dns` |
| `list_absent` | Ensure a list option does not contain specific values | Remove a DNS server |
| `committed` | Ensure all changes for a package are committed | `uci commit network` |
| `managed` | Declare full desired state for a package | Converge entire package config |

Each state function returns the standard Salt state dict:
```python
{"name": ..., "changes": {...}, "result": True/False/None, "comment": "..."}
```

`result=None` in test mode (dry run).

## Dual-Mode Operation

### Mode Selection

Not all targets can run module mode. Use this decision gate:

| Criterion | Module mode | Raw mode |
|-----------|:-----------:|:--------:|
| Python 3.10+ available on target | Required | Not needed |
| RAM >= 256 MB | Required (thin tarball + Python) | Works on 128 MB |
| Flash >= 16 MB free | Required (thin tarball storage) | Minimal footprint |
| Target OS | OpenWrt with Python opkg | Any OpenWrt (stock or minimal) |

**Default to raw mode** for stock OpenWrt routers. Module mode is viable only when the target has been explicitly provisioned with Python packages (e.g., via opkg install python3-light).

### Module Mode (salt-ssh with Python on target)

Standard approach: the execution module runs on the target via Salt's loader system. All functions use `__salt__["cmd.run_all"]("uci ...")` to call UCI commands.

Requirements:
- Python 3.10+ on target (opkg: `python3-light` + `python3-base`)
- Salt thin tarball deployed (~15 MB compressed)
- RAM >= 256 MB (thin tarball extraction + Python runtime)
- Flash >= 16 MB free

When these requirements are not met, salt-ssh will fail to deploy the thin tarball. The error surfaces as a transport-level failure. There is no graceful fallback; the operator must explicitly switch to raw mode.

### Raw Mode (salt-ssh -r)

For constrained devices (128 MB RAM, no Python). The execution module provides a helper to generate shell scripts:

```python
saltext_uci.render_script(desired_state) -> str
```

This produces a self-contained shell script that:
1. Reads current state via `uci show`
2. Computes diff against desired state
3. Applies only necessary changes
4. Commits affected packages

The script is sent via `salt-ssh '*' -r 'sh -s' < script.sh`.

## UCI Command Behavior Reference

| Command | Idempotent | Notes |
|---------|-----------|-------|
| `uci show` | Read-only | Outputs `package.section.option=value` |
| `uci get` | Read-only | Returns single value; error if missing |
| `uci export` | Read-only | Outputs full config in UCI syntax |
| `uci set` | Yes | Creates or overwrites; safe to repeat |
| `uci delete` | Yes (with `-q`) | `-q` suppresses error if missing |
| `uci add` | **No** | Always creates new anonymous section |
| `uci add_list` | **No** | Always appends, even if duplicate |
| `uci del_list` | Yes | No error if value not in list |
| `uci commit` | Yes | Writes staging to disk; no-op if clean |
| `uci revert` | Yes | Discards staging; no-op if clean |
| `uci changes` | Read-only | Lists uncommitted changes |

## Testing Strategy

### Unit Tests
- Mock `__salt__["cmd.run_all"]` to return known UCI output (retcode, stdout, stderr)
- Test each function's parsing and idempotency logic
- Test edge cases: empty config, missing sections, malformed output
- Test error paths: non-zero retcode, stderr messages, missing `uci` binary

### Functional Tests
- Use `pytest-salt-factories` loader fixtures
- Test module loading and `__virtual__` function
- Test state module with mock execution module

### Integration Tests
- Use SSH fixtures (already configured with `ssh_fixtures: true`)
- Test against a mock UCI environment or containerized OpenWrt
- Validate full salt-ssh round-trip

## File Locations

```
src/saltext/saltext_uci/
  modules/
    saltext_uci_mod.py    # Execution module
  states/
    saltext_uci_mod.py    # State module
tests/
  unit/modules/           # Unit tests for execution module
  unit/states/            # Unit tests for state module
  functional/modules/     # Functional tests
  functional/states/
  integration/modules/    # Integration tests with SSH
  integration/states/
```
