# 06 -- OpenWrt Configuration Layers

> Last reviewed against: v0.4.0

## Overview

OpenWrt's configuration system is a stack of daemons and libraries,
each adding a layer of abstraction. Understanding this stack is essential
for debugging Salt state runs and reasoning about change propagation.

```
 Operator / Salt
      |
  uhttpd (HTTPS :443, endpoint /ubus)
      |
  rpcd (session + ACL + per-session staging)
      |
  ubusd (system message bus, /var/run/ubus.sock)
      |
  libuci (staging, commit, apply/confirm/rollback)
      |
  /etc/config/* (persistent UCI files)
      |
  procd (service reload on config change)
      |
  netifd / dnsmasq / firewall4 / hostapd / ...
```

## Layer 1: UCI -- Config Hierarchy

### Package > Section > Option

```
package (file in /etc/config/)
  section (named or anonymous, has a type)
    option (scalar string value)
    list   (multi-value option, repeated keyword)
```

### Presentation Formats

The same configuration has multiple representations, optimized for
different consumers. This is a key source of confusion.

**Human-friendly format** -- config files (`/etc/config/*`) and
`uci export`:

```
config interface 'lan'
    option device 'br-lan'
    option proto 'static'
    option ipaddr '10.35.24.1'
    list dns '1.1.1.1'
    list dns '1.0.0.1'

config device
    option name 'br-lan'
    option type 'bridge'
    list ports 'eth0'
```

Keywords `config`, `option`, `list` define the structure. Anonymous
sections have no name after the type. Comments (`#`) are supported.
Quotes are required only when values contain spaces or tabs.

**Programmable format** -- `uci show`:

```
network.lan=interface
network.lan.device='br-lan'
network.lan.proto='static'
network.lan.ipaddr='10.35.24.1'
network.lan.dns='1.1.1.1' '1.0.0.1'
network.@device[0]=device
network.@device[0].name='br-lan'
network.@device[0].type='bridge'
network.@device[0].ports='eth0'
```

Dot-notation paths, single-quoted values. Anonymous sections use
`@type[index]` notation (unstable -- indices shift on add/remove).
List values are space-separated on one line.

**Single-value retrieval** -- `uci get`:

```
$ uci get network.lan.proto
static
$ uci get network.lan.dns
1.1.1.1 1.0.0.1
```

Raw value only, no quoting. Lists are space-separated, **indistinguishable
from multi-word scalars** (e.g., `ports='0 1 2 3 5'` -- is this a string
or five items?). This ambiguity is unsolvable without schema knowledge.

**ubus JSON** -- `ubus call uci get`:

```json
{
  "lan": {
    ".type": "interface",
    ".name": "lan",
    ".anonymous": false,
    "proto": "static",
    "ipaddr": "10.35.24.1",
    "dns": ["1.1.1.1", "1.0.0.1"]
  },
  "cfg040f15": {
    ".type": "device",
    ".name": "cfg040f15",
    ".anonymous": true,
    "name": "br-lan",
    "type": "bridge",
    "ports": ["eth0"]
  }
}
```

Lists are native JSON arrays (unambiguous). Anonymous sections get
stable auto-generated IDs (`cfg040f15`) with explicit metadata.
**This is the only representation that resolves all ambiguities**,
which is why the extension uses ubus exclusively (ADR-000).

| Format | Lists | Anonymous sections | Metadata | Ambiguity |
|--------|-------|--------------------|----------|-----------|
| Config file / `uci export` | Repeated `list` lines | No name after type | Keywords | None (structured) |
| `uci show` | Space-separated on one line | `@type[index]` | Dot-notation | Scalar vs list |
| `uci get` | Space-separated, unquoted | `@type[index]` | None | Scalar vs list |
| ubus JSON | Native arrays | Stable internal IDs | Dot-prefixed keys | None |

### Named vs Anonymous Sections

| Kind | Example | Path | Stable? |
|------|---------|------|---------|
| Named | `config interface 'lan'` | `network.lan` | Yes |
| Anonymous | `config rule` | `firewall.@rule[3]` (CLI) | No -- index shifts on add/remove |

ubus returns anonymous sections with stable internal IDs (`cfg09b3c1`)
and explicit metadata, avoiding the index instability of the CLI.

### UCI Staging Semantics

Changes go through a staging area before reaching `/etc/config/`:

| Operation | Effect |
|-----------|--------|
| `uci set` | Writes to staging directory |
| `uci add` | Creates new section in staging |
| `uci delete` | Marks deletion in staging |
| `uci changes` | Shows uncommitted deltas |
| `uci revert` | Discards staged changes |
| `uci commit` | Persists staging to `/etc/config/` (no service reload) |
| `uci apply` | Commits + reloads services (optionally with rollback timer) |
| `uci confirm` | Cancels rollback timer, changes become permanent |
| `uci rollback` | Restores pre-apply snapshot |

Staging location depends on transport:

| Transport | Staging Directory |
|-----------|-------------------|
| CLI / SSH / local | `/tmp/.uci/` (global, shared) |
| rpcd JSON-RPC | `/var/run/rpcd/uci-<session_id>/` (per-session, isolated) |

The per-session isolation means Salt's JSON-RPC session and LuCI's
session cannot see each other's uncommitted changes.

## Layer 2: ubusd -- System Message Bus

`ubusd` is OpenWrt's lightweight IPC daemon. All daemons register
objects and methods on the bus. UCI operations, service management,
network queries, and system info all flow through ubus.

Socket: `/var/run/ubus.sock` (Unix domain, local access only)

### Access Paths to ubus

| Path | Auth | ACL | Used By |
|------|------|-----|---------|
| Local socket (`ubus call ...`) | root | None | CLI, SSH adapter |
| rpcd over HTTPS (`POST /ubus`) | Session token | rpcd ACL files | JSON-RPC adapter |
| SSH remote (`ssh host 'ubus call ...'`) | SSH key | None (runs as root) | SSH adapter |
| Local subprocess | Process user | None | Local adapter |

### ubus Response Format

All calls return the same JSON regardless of transport:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": [
    0,
    {
      "values": {
        "lan": {
          ".type": "interface",
          ".name": "lan",
          ".anonymous": false,
          ".index": 5,
          "proto": "static",
          "ipaddr": "10.35.24.1",
          "dns": ["1.1.1.1", "1.0.0.1"]
        }
      }
    }
  ]
}
```

- `result[0]`: ubus status code (0 = OK, 6 = permission denied)
- `result[1]["values"]`: section data
- Dot-prefixed keys (`.type`, `.name`, `.anonymous`, `.index`) are
  metadata, transformed to underscore-prefix (`_type`, etc.) by
  `ubus_ops.transform_section()`
- Lists are native JSON arrays (no ambiguity)

### Key ubus Objects

#### uci -- Configuration Management

| Method | Purpose |
|--------|---------|
| `get` | Read config/section/option with metadata |
| `set` | Stage option changes |
| `add` | Create new section |
| `delete` | Delete section or option |
| `changes` | Show uncommitted deltas |
| `revert` | Discard staged changes |
| `commit` | Persist to `/etc/config/` without reload |
| `apply` | Commit + reload, optional rollback timer |
| `confirm` | Cancel rollback timer |
| `rollback` | Trigger manual rollback |
| `configs` | List available packages |
| `state` | Runtime-merged state (defaults + config + overrides) |

#### system -- Device Information

| Method | Returns |
|--------|---------|
| `board` | Kernel, hostname, model, board_name, release (version, target, revision) |
| `info` | Uptime, load, memory (total, free, shared, buffered, cached), disk (root, tmp) |

#### network.interface -- L3 Interfaces

| Method | Returns |
|--------|---------|
| `dump` | All interfaces: name, device, proto, IP, gateway, DNS, up/running state |

Per-interface objects (`network.interface.lan`, `.wan`, etc.) are
created dynamically by netifd from UCI config.

#### service -- Process Supervision (procd)

| Method | Returns |
|--------|---------|
| `list` | All services with instances: `{name: {instances: {inst: {running, pid}}}}` |

Used by Salt's `applied()` state to verify service health after
`uci apply`.

#### luci-rpc -- LuCI Helpers

| Method | Returns |
|--------|---------|
| `getNetworkDevices` | L2 device details (IPs, stats, carrier, MAC) |
| `getDHCPLeases` | Active DHCP leases |
| `getHostHints` | DHCP/ARP hostname mappings |
| `getWirelessDevices` | WiFi associations and signal |
| `getBoardJSON` | `/etc/board.json` contents |

## Layer 3: rpcd -- RPC Daemon

rpcd sits between uhttpd and ubusd, adding session management and
access control. It is the gatekeeper for all remote ubus access.

### Session Management

1. Client calls `session login` with username + password
2. rpcd returns a 32-char hex session token (default TTL: 300s)
3. Client includes token in all subsequent JSON-RPC calls
4. Each successful call resets the TTL countdown
5. On expiry, rpcd destroys the session and its staging directory

Session state is in-memory only -- lost on rpcd restart.

### ACL Files

Location: `/usr/share/rpcd/acl.d/*.json`

```json
{
  "salt-agent-ubus": {
    "description": "Salt agent full UCI access",
    "read": {
      "ubus": {
        "uci": ["*"],
        "system": ["board", "info"],
        "network.interface": ["dump"],
        "service": ["list"]
      },
      "uci": ["*"]
    },
    "write": {
      "ubus": {
        "uci": ["*"]
      },
      "uci": ["*"]
    }
  }
}
```

ACL grants are scoped per ubus object + method, and per UCI package.
The `uci` key in the ACL controls which config packages are accessible.

### User Configuration

```
# /etc/config/rpcd
config login
    option username 'salt-agent'
    option password '$p$salt-agent'    # lookup hash from /etc/shadow
    list read 'salt-agent-ubus'
    list write 'salt-agent-ubus'
```

### Three Timeout Mechanisms

| Timeout | Default | Controlled By | Purpose |
|---------|---------|---------------|---------|
| HTTP timeout | 30s | Pillar `timeout` | How long urllib waits for uhttpd to respond |
| Session timeout | 300s | Pillar `session_timeout` | How long the rpcd login session lives |
| Invoke timeout | 30s | UCI `rpcd.@rpcd[0].timeout` | How long rpcd waits for a ubus call to complete |

For slow MIPS routers, all three must be tuned. The proxy module
auto-bumps the invoke timeout if it's below the pillar value.

## Layer 4: uhttpd -- HTTP Server

uhttpd is OpenWrt's lightweight web server. The `uhttpd-mod-ubus`
plugin exposes the JSON-RPC endpoint.

- Endpoint: `https://<device>/ubus`
- TLS: self-signed certificate (`/etc/uhttpd.crt`, `/etc/uhttpd.key`)
- Config: UCI package `uhttpd`, section `main`
- `ubus_prefix` option sets the endpoint path (default `/ubus`)

## Layer 5: procd -- Init and Service Supervision

procd is OpenWrt's PID 1. It supervises all system services and
handles service reload when configuration changes.

### Reload Chain

```
uci apply
  -> rpcd commits /etc/config/*
  -> rpcd emits ubus event config.change.<package>
  -> procd detects event
  -> procd calls /etc/init.d/<service> reload
  -> daemon re-reads /etc/config/<package>
```

### Service Health Verification

Salt's `applied()` state uses this chain:

1. Snapshot running service PIDs via `service list`
2. Call `uci apply` with rollback timeout
3. Poll `service list` until all previously-running services return
   with `running: true`
4. If healthy: call `uci confirm` (changes permanent)
5. If services fail to restart: skip confirm, rpcd auto-rollback
   restores the previous config

## Layer 6: Network and Service Daemons

### netifd (Network Interface Daemon)

Owns the `network` UCI package. Creates dynamic ubus objects per
interface (`network.interface.lan`, `.wan`, etc.).

Protocol handlers in `/lib/netifd/proto/*.sh` (ash scripts):
`static`, `dhcp`, `dhcpv6`, `ppp`, `pppoe`, `none`

### firewall4 (nftables-based Firewall)

Owns the `firewall` UCI package. Translates UCI zones/rules/forwards
into nftables rulesets. Heavy use of anonymous sections (rules, zones,
forwardings).

### dnsmasq (DNS/DHCP)

Owns portions of the `dhcp` UCI package (shared with odhcpd).
Provides DNS forwarding and DHCP lease management.

### hostapd (WiFi AP)

Manages wireless interfaces. Creates per-radio ubus objects
(`hostapd.phy0-ap0`). Configuration from `wireless` UCI package.

## File System Reference

### Persistent Configuration

```
/etc/config/
    network         netifd: interfaces, devices, routes, switches
    firewall        firewall4: zones, rules, forwards, NAT
    dhcp            dnsmasq + odhcpd: DHCP, DNS, static leases
    wireless        hostapd: radios, SSIDs, encryption
    system          base-files: hostname, timezone, NTP, LEDs
    dropbear        dropbear: SSH server config
    uhttpd          uhttpd: web server, TLS, ubus endpoint
    rpcd            rpcd: users, ACL group assignments, timeout
    luci            luci: UI preferences
    salt-openwrt    salt agent: mode (audit/oneshot/autoverified)
```

### Runtime State

```
/tmp/.uci/                          Default staging (CLI/SSH/local)
/var/run/rpcd/uci-<session_id>/     Per-session staging (JSON-RPC)
/var/run/rpcd/snapshot-files/       Rollback snapshots during apply
/var/run/ubus.sock                  ubusd Unix socket
/tmp/dhcp.leases                    Active DHCP leases
/etc/shadow                         Password hashes ($p$ references)
```

### Binaries

```
/sbin/ubusd         Message bus daemon
/sbin/rpcd          RPC daemon (session + ACL)
/sbin/procd         Init / service supervisor
/sbin/netifd        Network interface daemon
/usr/sbin/uhttpd    Web server
/usr/bin/ubus       CLI for ubus calls
/usr/bin/uci        CLI for UCI (not used by this extension)
/bin/ash            BusyBox shell
```

### ACL Files

```
/usr/share/rpcd/acl.d/
    luci-base.json              Core: uci get/set, system board/info
    luci-mod-network.json       Network packages
    luci-mod-system.json        System packages
    saltext-ubus.json           Salt agent access (custom)
```

## Hardware Constraints (WNDR3800 Reference)

| Resource | Value | Implication |
|----------|-------|-------------|
| RAM | 128 MB | ~40 MB free after boot; no Python runtime |
| Flash | 16 MB | squashfs root; overlay for `/etc/config/` writes |
| CPU | MIPS (AR7161) | Slow service reloads; needs generous timeouts |
| Shell | ash (BusyBox) | No bash; limited coreutils |
| Python | Not available | Must use proxy minion pattern |

## Internet References

### Official OpenWrt Documentation

- [UCI system](https://openwrt.org/docs/guide-user/base-system/uci) --
  config file syntax, CLI usage, package/section/option model
- [ubus (technical reference)](https://openwrt.org/docs/techref/ubus) --
  ubusd architecture, object registration, call semantics
- [rpcd](https://openwrt.org/docs/techref/rpcd) --
  ACL system, session management, JSON-RPC bridge
- [procd](https://openwrt.org/docs/techref/procd) --
  init system, service supervision, reload triggers
- [netifd](https://openwrt.org/docs/techref/netifd) --
  network daemon, protocol handlers, interface lifecycle
- [uhttpd](https://openwrt.org/docs/guide-user/services/webserver/uhttpd) --
  web server config, ubus plugin, TLS setup

### OpenWrt Source Code (key files)

- [rpcd/session.c](https://git.openwrt.org/?p=project/rpcd.git;a=blob;f=session.c) --
  session create/destroy, `RPC_DEFAULT_SESSION_TIMEOUT` (300s)
- [rpcd/uci.c](https://git.openwrt.org/?p=project/rpcd.git;a=blob;f=uci.c) --
  per-session savedir (`/var/run/rpcd/uci-<sid>/`), purge on session destroy
- [rpcd/include/rpcd/session.h](https://git.openwrt.org/?p=project/rpcd.git;a=blob;f=include/rpcd/session.h) --
  `RPC_DEFAULT_SESSION_TIMEOUT` compile-time constant
- [libuci (uci.h)](https://git.openwrt.org/?p=project/uci.git;a=blob;f=uci.h) --
  staging, delta files, commit semantics
- [netifd/proto-shell.c](https://git.openwrt.org/?p=project/netifd.git;a=blob;f=proto-shell.c) --
  protocol handler lifecycle

### Community and Forum Resources

- [OpenWrt forum](https://forum.openwrt.org/) --
  device-specific issues, config examples, troubleshooting
- [OpenWrt wiki: Table of Hardware](https://openwrt.org/toh/start) --
  device specs, flash/RAM, supported builds
- [OpenWrt wiki: Firewall](https://openwrt.org/docs/guide-user/firewall/firewall_configuration) --
  zone/rule/forward config patterns, anonymous section conventions
- [OpenWrt wiki: Network configuration](https://openwrt.org/docs/guide-user/network/network_configuration) --
  interface types, protocol options, VLAN setup

### Related Projects

- [Salt Extension: saltext-ubus](https://github.com/cprima-homelab/saltext-ubus) --
  this project; manages OpenWrt via ubus
- [JSON-RPC spec](https://www.jsonrpc.org/specification) --
  protocol used by uhttpd's ubus endpoint
- [nftables wiki](https://wiki.nftables.org/) --
  firewall4's backend; useful for understanding rule semantics
