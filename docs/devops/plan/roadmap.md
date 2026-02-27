# Roadmap

## Resolved in v0.1

- **Templating for UCI commands**: All user-provided values are now
  escaped via `shlex.quote()` to prevent shell injection.
- **Inspecting `uci` opkg**: The `uci` package (opkg `uci`, depends on
  `libuci`) provides the CLI binary. Both are in the `base` section.
- **salt-ssh vs proxy**: Solved via proxy minion pattern. The proxy runs
  on the salt-master and SSHes into the router. No Python needed on
  the target. salt-ssh raw mode is not used.

## Post-v0.1 Technical Debt

### SSH Connection Efficiency

Each proxy `cmd()` call opens a fresh SSH connection via `subprocess.run`.
A function like `set_list` with 5 values triggers 7 SSH connections
(1 get + 1 delete + 5 add_list).

Improvement: Use SSH ControlMaster multiplexing. Open a persistent
control socket in `init()`, reuse it in `cmd()`, close in `shutdown()`.

### Scalar vs List Ambiguity in `uci show`

A multi-word scalar (`ports='0 1 2 3 5'`) is indistinguishable from a
list (`dns='1.1.1.1' '1.0.0.1'`) in `uci show` output.

Improvement: Use the schema declarations in `utils/packages/*.py`
(`LIST_OPTIONS`) to disambiguate during parsing.

### Grains Support (NAPALM parity)

NAPALM proxy implements `get_grains()` and `grains_refresh()` to expose
device facts (vendor, model, OS version, serial, interfaces) as Salt
grains. This enables targeting by device characteristics:
`salt -G 'os:OpenWrt' saltext_uci.show network`.

OpenWrt grains could include:

| Grain | Source command |
|-------|---------------|
| `openwrt_version` | `cat /etc/openwrt_release` |
| `model` | `cat /tmp/sysinfo/model` |
| `board_name` | `cat /tmp/sysinfo/board_name` |
| `hostname` | `uci get system.@system[0].hostname` |
| `installed_packages` | `opkg list-installed` |
| `total_ram` | `cat /proc/meminfo` (MemTotal) |
| `flash_size` | `df /overlay` |

### `force_reconnect` (NAPALM parity)

NAPALM supports `force_reconnect=True` to use alternate connection
parameters per-call (different user, different port). Not needed while
we use per-call SSH (no persistent connection), but would matter if
SSH ControlMaster is added.

### `alive()` Real Check (NAPALM parity)

NAPALM's `alive()` calls `is_alive()` on the device driver to verify
the connection is still open. Our proxy always returns True since there
is no persistent connection. If ControlMaster is added, `alive()` should
check the control socket.

### Multiprocessing Flag (NAPALM parity)

NAPALM sets `multiprocessing: False` for SSH-based proxy minions to
avoid concurrent SSH sessions stomping on each other. Our proxy uses
per-call subprocess SSH so this is not currently an issue, but should
be considered if connection pooling is added.

### State Module

`states/saltext_uci_mod.py` is a stub. Next step: implement `managed`
state for named sections (Tier 1), using the existing execution module
functions.

### Anonymous Section Support (Tier 2/3)

Named sections have stable paths (`network.lan`). Anonymous sections
(`firewall.@rule[N]`) require walk+match logic: find the section by
matching on field values, not by index. Needed for `firewall`, `dhcp`
static leases, and `system`.

### `uci export` Parser

`utils/uci_parser.py` only implements `parse_show()`. Plan 02 also calls
for `parse_export()` for round-trip config backup/restore.

### CLI Entry Point

Plan 02 describes a standalone CLI (`uci-reader`) that reads config
without requiring Salt. Deferred from v0.1.
