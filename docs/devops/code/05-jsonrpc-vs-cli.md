# JSON-RPC vs CLI: Interface Comparison

Comparing the two approaches for managing OpenWrt UCI configuration from Salt.

## v0.1 Approach: UCI CLI over SSH

```
Salt master -> SSH -> ash shell -> `uci show` / `uci set` -> stdout parsing
```

- Each operation spawns an SSH connection and runs a shell command
- Output is plain text requiring custom parsing
- List vs scalar ambiguity: `uci show` cannot distinguish `'0 1 2 3 5'`
  (scalar) from `'eth0' 'eth1'` (list) without schema knowledge
- No native transaction support (commit is fire-and-forget)
- Requires SSH key authentication
- Works on any OpenWrt device with dropbear

## v0.2 Approach: ubus JSON-RPC over HTTPS

```
Salt master -> HTTPS POST -> uhttpd -> rpcd -> ubus -> libubus
```

- Each operation is an HTTP POST with JSON payload
- Response is structured JSON: lists are arrays, metadata is inline
- No parsing ambiguity: UCI itself resolves list vs scalar before serialization
- Native transaction support: set -> commit -> apply(rollback) -> confirm
- Requires rpcd user + ACL configuration
- Requires uhttpd with `ubus_prefix` (standard on LuCI-enabled images)

## Feature Comparison

| Feature                    | CLI over SSH             | JSON-RPC over HTTPS       |
|----------------------------|--------------------------|---------------------------|
| **Transport**              | SSH (tcp/22)             | HTTPS (tcp/443)           |
| **Auth**                   | SSH key or password      | rpcd session token (300s) |
| **Output format**          | Plain text               | JSON                      |
| **List disambiguation**    | Requires schema/heuristic| Native (arrays vs strings)|
| **Batch read**             | One `uci show` call      | One `uci.get` call        |
| **Batch write**            | Multiple `uci set` calls | One `uci.set` with values object |
| **Safe apply + rollback**  | Via `ubus call uci apply` on local socket | `apply(rollback=true)` + `confirm` |
| **Staged changes inspect** | `uci changes` (text)     | `uci.changes` (JSON array)|
| **Device grains**          | Parse multiple files      | `system.board` + `system.info` |
| **Runtime network state**  | `ip addr`, `ifstatus`    | `network.interface dump`  |
| **DHCP leases**            | Parse `/tmp/dhcp.leases` | `luci-rpc.getDHCPLeases`  |
| **Network devices**        | `ip link`, `brctl show`  | `luci-rpc.getNetworkDevices` |
| **Python on target**       | Not needed (proxy mode)  | Not needed                |
| **Packages needed**        | dropbear (default)       | uhttpd-mod-ubus + rpcd (default with LuCI) |
| **ACL granularity**        | SSH = full root access   | Per-object, per-method    |
| **Connection overhead**    | SSH handshake per call   | Session token reuse       |

## Data Quality Comparison

### Reading a list option

**CLI** (`uci show network.wan.dns`):
```
network.wan.dns='1.1.1.1' '1.0.0.1'
```
Requires: quote-aware parsing, schema to know `dns` is a list.

**JSON-RPC** (`uci.get {config: "network", section: "wan", option: "dns"}`):
```json
{"value": ["1.1.1.1", "1.0.0.1"]}
```
Native array, no parsing needed.

### Reading a multi-word scalar

**CLI** (`uci show network.@switch_vlan[0].ports`):
```
network.@switch_vlan[0].ports='0 1 2 3 5'
```
Looks like it could be a list of 5 items. Only schema knowledge prevents misparse.

**JSON-RPC** (`uci.get {config: "network"}`):
```json
{"ports": "0 1 2 3 5"}
```
String, not array. Unambiguous.

### Anonymous section handling

**CLI**:
```
network.@device[0]=device
network.@device[0].name='br-lan'
```
Requires regex to parse `@type[index]` syntax.

**JSON-RPC**:
```json
{
  "cfg040f15": {
    ".anonymous": true,
    ".type": "device",
    ".name": "cfg040f15",
    ".index": 3,
    "name": "br-lan",
    "type": "bridge"
  }
}
```
Metadata is structured. Anonymous flag is explicit.

## Write Path Comparison

### CLI: set + commit (no rollback)

```sh
uci set network.lan.ipaddr='10.35.24.2'
uci commit network
reload_config
# If this breaks connectivity, manual recovery required
```

### CLI: set + apply with rollback (via local ubus socket)

```sh
uci set network.lan.ipaddr='10.35.24.2'
ubus call uci apply '{"rollback":true,"timeout":30}'
# Config is committed, services reloaded, 30s timer starts.
# rpcd handles the rollback -- the mechanism is the same as JSON-RPC.
ubus call uci confirm
# Timer cancelled, change is permanent.
# If confirm not sent: auto-revert after 30s.
```

The `ubus` CLI talks to rpcd via the local Unix socket. The confirmed
commit cycle (snapshot, apply, arm timer, confirm/rollback) is handled
entirely by rpcd, regardless of whether the request arrives over HTTPS
or the local socket. The only difference is staging location: CLI `uci
set` stages to `/tmp/.uci/`, JSON-RPC stages to the per-session
directory `/var/run/rpcd/uci-<session_id>/`.

### JSON-RPC: set + apply with rollback

```
1. uci.set {config: "network", section: "lan", values: {ipaddr: "10.35.24.2"}}
2. uci.apply {rollback: true, timeout: 30}
   -- commits staged changes, reloads services, 30s timer starts --
3. uci.confirm {}
   -- timer cancelled, change is permanent --
   -- if confirm not sent: auto-revert after 30s --
```

Note: `uci.apply` commits implicitly -- a separate `uci.commit` call
before `uci.apply` is not required. rpcd snapshots `/etc/config/*`,
commits from the staging directory, reloads services, and arms the
rollback timer in a single operation.

This is critical for remote management: a bad network change auto-reverts
instead of bricking the device.

## ACL Gaps Observed (austru, 2026-02-27)

Calls that returned "Access denied" even with `read: *, write: *`:

| Call                            | Reason                                   |
|---------------------------------|------------------------------------------|
| `network.device status`         | Not in any `/usr/share/rpcd/acl.d/` file |
| `network.interface.lan status`  | Not in any ACL file                      |
| `uci revert`                    | Not in luci-base write ACLs              |

These require either:
- Custom ACL file in `/usr/share/rpcd/acl.d/saltext-ubus.json`
- Or use the `luci-base` group which covers `uci.get`, `uci.set`,
  `uci.commit`, `uci.apply`, `uci.confirm`

## Recommendation for v0.2

Use JSON-RPC as the primary interface:

1. **Eliminates parsing**: no text parsing, no schema files, no ambiguity
2. **Safe writes**: `apply` + `confirm` pattern prevents lockout
3. **Richer data**: system.board, system.info, network.interface dump
   replace multi-command SSH grains collection
4. **ACL control**: salt user gets only what it needs (not full root shell)
5. **Session reuse**: one login per operation batch vs SSH handshake per call

Keep SSH as a fallback for:
- Devices without LuCI/uhttpd (minimal images)
- Operations not exposed via ubus (package install, sysupgrade)
- Bootstrapping the rpcd salt user itself
