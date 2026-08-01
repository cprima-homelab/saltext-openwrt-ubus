# 09 -- ubus System Architecture

How OpenWrt's inter-process communication bus works, how objects get
registered, and where rpcd adds authentication and ACLs on top.

## What ubus is

ubus is OpenWrt's system IPC bus, analogous to D-Bus on desktop Linux.
A central broker daemon (`ubusd`) listens on a Unix domain socket.
Daemons register named objects with methods; clients call them by name.

```
          ┌──────────────────────────┐
          │         ubusd            │
          │  (Unix socket broker)    │
          └──┬────┬────┬────┬───────┘
             │    │    │    │
         netifd  procd rpcd dnsmasq  ...
         (network) (service) (session,uci) (dns)
```

ubusd itself performs no authentication and enforces no ACLs. Any
process with access to the Unix socket can call any registered object.

## The `ubus` CLI tool

The `ubus` command is the client interface to ubusd. It has exactly
7 commands:

| Command | Purpose |
|---------|---------|
| `list [<path>]` | List registered objects and their methods |
| `call <path> <method> [<message>]` | Call a method on an object |
| `subscribe <path>` | Subscribe to object notifications |
| `listen [<path>...]` | Listen for events |
| `send <type> [<message>]` | Send an event |
| `wait_for <object>...` | Wait for objects to appear |
| `monitor` | Monitor all ubus traffic |

The output of `ubus list` shows **registered objects**, not ubus
subcommands. For example, `container`, `uci`, and `system` are objects
registered by daemons. You interact with them via
`ubus call <object> <method>`.

Use `ubus -v list <object>` to see an object's method signatures:

```
# ubus -v list uci
'uci' @4fc2a775
    "configs":{}
    "get":{"config":"String","section":"String","option":"String",...}
    "set":{"config":"String","section":"String","values":"Table",...}
    ...
```

The hex value after `@` is the object's registration ID within ubusd.

## ubusd: the message broker

ubusd is started early by procd and manages the `/var/run/ubus/ubus.sock`
Unix socket. When a daemon registers an object, ubusd assigns it a
32-bit `objid` used for internal message routing. In `ubus monitor`
output this appears as e.g. `"objid":-1931865202` (the signed
representation of `0x8cda138e`).

ubusd routes calls from client to the process that owns the target
object. It does not inspect message contents, enforce permissions, or
filter methods. All access control is layered on top by rpcd.

## How objects get registered

### C daemons using libubus

A daemon links against `libubus`, connects to ubusd at startup, and
calls `ubus_add_object()` to register its methods. Each daemon is a
separate process with its own connection to ubusd.

| Daemon | Objects registered |
|--------|-------------------|
| `netifd` | `network`, `network.device`, `network.interface`, `network.interface.*`, `network.wireless`, `network.rrdns` |
| `procd` | `system`, `service`, `container`, `rc`, `hotplug.*` |
| `dnsmasq` | `dnsmasq`, `dnsmasq.dns` |
| `hostapd` | `hostapd`, `hostapd-auth`, `hostapd.phy0-ap0`, `hostapd.phy1-ap0` |
| `rpcd` | `session` (plus objects from its plugins, see below) |
| `logd` | `log` |
| `wpa_supplicant` | `wpa_supplicant` |

Note on `container`: this is procd's process/service container
management object, with the same method signatures as `service` (set,
add, list, delete, state). It is **not** LXC or Docker containers.

### rpcd plugins (shared libraries)

rpcd loads `.so` plugins from `/usr/lib/rpcd/`. Each plugin registers
ubus objects that run inside rpcd's process space:

| Plugin file | ubus object | Installed by |
|-------------|-------------|-------------|
| `uci.so` | `uci` | `rpcd` |
| `file.so` | `file` | `rpcd-mod-file` |
| `iwinfo.so` | `iwinfo` | `rpcd-mod-iwinfo` |
| `rpcsys.so` | `rpc-sys` | `rpcd` |
| `luci.so` | `luci`, `luci-rpc`, `luci.ddns` | `luci-base` |

This is why `uci` lives inside rpcd -- rpcd can intercept the session
ID from every UCI call and redirect the staging directory. See
[08-rpcd-session-staging-internals](08-rpcd-session-staging-internals.md)
for the C source code that does this.

### procd service registration

Services managed by procd automatically appear in `service list`.
procd also exposes event hooks as `hotplug.*` objects (dhcp, iface,
net, ntp, ieee80211, etc.) for system event notification.

## Dynamic objects

Some objects are created at runtime based on configuration:

- **`network.interface.<name>`** -- one per UCI network interface.
  austru has `lan`, `wan`, `loopback`, `vpn`, `autan`.
- **`hostapd.phy<N>-ap<N>`** -- one per wireless AP radio.
  austru has `phy0-ap0` (5 GHz) and `phy1-ap0` (2.4 GHz).

Installing a new package with ubus support adds new objects after
the service starts. Removing it removes them.

## Call paths

There are two ways to reach ubus objects, with fundamentally different
security properties:

### Local socket (SSH or direct shell)

```
ssh → "ubus call" CLI → ubusd → handler
```

- No authentication beyond Unix socket access (typically root)
- No ACLs -- every object and method is callable
- UCI staging writes to `/tmp/.uci/` (shared across all processes)

### JSON-RPC over HTTPS

```
HTTPS POST → uhttpd → rpcd → ubusd → handler
```

- Password-based session authentication (`session.login`)
- Per-method ACLs enforced by rpcd before dispatching
- UCI staging writes to `/var/run/rpcd/uci-<session>/` (isolated)

The key difference: rpcd sits in the JSON-RPC path and adds a session
+ ACL layer. Over the local socket, rpcd is not involved.

## The ACL layer

ACLs are **not** a ubus feature -- they are an rpcd feature layered
on top of ubus.

### How it works

1. **ACL files** in `/usr/share/rpcd/acl.d/*.json` define permission
   groups with read/write grants per ubus object and method.

2. **rpcd login entries** (`uci show rpcd`) bind system users to ACL
   groups.

3. **`session.login`** authenticates the user (password verified
   against `/etc/shadow`) and returns a session token. The token
   carries the expanded ACLs from all assigned groups.

4. **Every JSON-RPC call**: rpcd calls `session.access` to check
   whether the session's ACL permits the requested object + method
   before forwarding the call to ubusd.

### Custom ACL files

Any opkg package can ship its own ACL file. Drop a JSON file into
`/usr/share/rpcd/acl.d/` and restart rpcd. The ACL group name
(top-level key) must match what the rpcd login entry references.

See [06-openwrt-device-packages](06-openwrt-device-packages.md) for
the `salt-agent-ubus` package's ACL definition.

### Cost

rpcd's `session.login` only accepts username + password. There is no
way to authenticate with SSH keys through rpcd. To get ACLs, you need
a password set on the device.

## Implications for Salt

| | SSH proxy | JSON-RPC proxy |
|---|---|---|
| Transport | `ubus call` over SSH | JSON-RPC over HTTPS |
| Auth | SSH key | rpcd password + session token |
| ACLs | None (root access) | Per-object, per-method |
| UCI staging | Shared `/tmp/.uci/` | Isolated per-session |
| Required packages | dropbear or openssh (default) | uhttpd + rpcd + ACL file |

Both transports call the same ubus objects and get the same JSON
output. The Salt extension's adapter pattern
([01-adapter-pattern](01-adapter-pattern.md)) means the execution
modules work identically regardless of transport.

## See also

- [04-ubus-jsonrpc-api](04-ubus-jsonrpc-api.md) -- JSON-RPC protocol details
- [07-ubus-object-inventory](07-ubus-object-inventory.md) -- full object list from austru
- [08-rpcd-session-staging-internals](08-rpcd-session-staging-internals.md) -- rpcd C source analysis
- [../plan/10-jsonrpc-vs-cli](../plan/10-jsonrpc-vs-cli.md) -- transport comparison
