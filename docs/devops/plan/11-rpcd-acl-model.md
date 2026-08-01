# 11 -- rpcd ACL Model

> **ACL tightened**: `uci: ["*"]` replaced with explicit package list
> matching the scope registry (network, system, dhcp, wireless,
> firewall, dropbear, salt-openwrt). Operators must reinstall the
> salt-agent-ubus ipk (v0.3.0) to pick up the change.

How OpenWrt controls access to the ubus JSON-RPC API.

## Architecture

```
curl (HTTPS) -> uhttpd -> rpcd -> ubus
                  |         |
                  |    session mgmt
                  |    ACL enforcement
                  |         |
                  |    /usr/share/rpcd/acl.d/*.json   (access group definitions)
                  |    /etc/config/rpcd               (user -> group mapping)
```

## Layers

### 1. uhttpd: HTTP endpoint

UCI config: `uhttpd.main.ubus_prefix='/ubus'`

uhttpd proxies JSON-RPC requests to rpcd via the ubus socket. Requires
`uhttpd-mod-ubus` package (installed by default with LuCI).

### 2. rpcd: Session and ACL

rpcd manages authentication and authorization.

#### User configuration (`/etc/config/rpcd`)

```
config login
    option username 'salt-agent'
    option password '$p$salt-agent'
    list read '*'
    list write '*'
```

- `$p$<username>` = look up system password from `/etc/shadow`
- `read` / `write` = list of access group names (or `*` for all groups)

#### Access group files (`/usr/share/rpcd/acl.d/`)

Each JSON file defines one or more named access groups. Groups specify
which ubus objects/methods, UCI packages, and files are accessible.

Example from `luci-base.json`:

```json
{
  "luci-base": {
    "description": "Grant access to basic LuCI procedures",
    "read": {
      "ubus": {
        "uci": ["changes", "get"],
        "file": ["list"]
      },
      "uci": ["system", "luci"]
    },
    "write": {
      "ubus": {
        "uci": ["add", "apply", "confirm", "delete", "order", "rename", "set"]
      },
      "uci": ["system", "luci"]
    }
  }
}
```

#### ACL sections

Each access group has `read` and `write` blocks containing:

| Section | Controls                              | Example                       |
|---------|---------------------------------------|-------------------------------|
| `ubus`  | Which ubus objects and methods        | `"uci": ["get", "set"]`      |
| `uci`   | Which UCI packages can be read/written| `["network", "firewall"]`    |
| `file`  | Which filesystem paths are accessible | `"/etc/config/*": ["read"]`  |
| `cgi-io`| CGI upload/download/exec permissions  | `["upload", "download"]`     |

### 3. ubus: Method dispatch

Once rpcd authorizes a call, it dispatches to the ubus daemon which routes
to the registered object handler (e.g., `rpcd-mod-ucode` for `uci.*`,
`netifd` for `network.*`).

## ACL Files on austru (OpenWrt 24.10.5 with LuCI)

```
/usr/share/rpcd/acl.d/
    luci-app-attendedsysupgrade.json
    luci-app-ddns.json
    luci-app-firewall.json
    luci-app-openvpn.json
    luci-app-package-manager.json
    luci-app-watchcat.json
    luci-base.json                     <-- core: uci.get/set, file, system
    luci-compat.json
    luci-mod-network.json              <-- network UCI + iwinfo
    luci-mod-status-index.json
    luci-mod-status.json
    luci-mod-system.json
    unauthenticated.json               <-- session.login (no auth needed)
```

## Network-Relevant ACL Grants

From `luci-base.json`:

| Group                        | Mode  | Scope                               |
|------------------------------|-------|-------------------------------------|
| `luci-base`                  | read  | `ubus: uci [changes, get]`         |
| `luci-base`                  | write | `ubus: uci [add, apply, confirm, delete, order, rename, set]` |
| `luci-base-network-status`   | read  | `ubus: network [get_proto_handlers], network.interface [dump]` |

From `luci-mod-network.json`:

| Group                        | Mode  | Scope                               |
|------------------------------|-------|-------------------------------------|
| `luci-mod-network-config`    | read  | `uci: [dhcp, firewall, network, wireless, system]` |
| `luci-mod-network-config`    | write | `uci: [dhcp, firewall, network, wireless]` |
| `luci-mod-network-dhcp`      | read  | `ubus: luci-rpc [getDHCPLeases, getDUIDHints, getHostHints]` |

## Missing ACLs (Gaps for Salt Use)

Calls that fail even with `read: *, write: *`:

| ubus call                      | Why it fails                              |
|--------------------------------|-------------------------------------------|
| `network.device status`        | No ACL file grants `network.device`       |
| `network.interface.<name> status` | No ACL grants per-interface methods    |
| `uci revert`                   | Not in luci-base write ubus ACLs          |
| `system.board`                 | In `luci-mod-system.json` read only       |
| `system.info`                  | In `luci-mod-system.json` read only       |

### Custom ACL for Salt

To grant full access for Salt operations, deploy a custom ACL file:

```json
// /usr/share/rpcd/acl.d/saltext-ubus.json
{
  "saltext-ubus": {
    "description": "Salt extension for UCI management",
    "read": {
      "ubus": {
        "session": ["access", "login"],
        "system": ["board", "info"],
        "service": ["list"],
        "network": ["get_proto_handlers"],
        "network.device": ["status"],
        "network.interface": ["dump"],
        "network.interface.*": ["status", "dump"],
        "luci-rpc": ["getNetworkDevices", "getDHCPLeases", "getHostHints"],
        "uci": ["configs", "get", "state", "changes"]
      },
      "uci": ["*"]
    },
    "write": {
      "ubus": {
        "uci": ["add", "set", "delete", "rename", "order",
                "commit", "revert", "apply", "confirm", "rollback",
                "reload_config"]
      },
      "uci": ["*"]
    }
  }
}
```

Then configure the salt rpcd login with `list read 'saltext-ubus'` and
`list write 'saltext-ubus'` instead of `*`.

## Session Lifecycle

1. **Login**: POST to `session.login` with null session -> receive token
2. **Use**: Include token in all subsequent calls (300s default TTL)
3. **Expire**: Token auto-expires after `timeout` seconds of inactivity
4. **Refresh**: Each successful call resets the expiry timer

There is no explicit logout. Sessions are stored in rpcd process memory
(not persisted to disk) and lost on rpcd restart.

### Per-Session UCI Staging

For the rpcd C source code that implements this mechanism, see
[../code/08-rpcd-session-staging-internals.md](../code/08-rpcd-session-staging-internals.md).

rpcd isolates uncommitted UCI changes by session. When a session-bearing
`uci.set` call arrives, rpcd directs libuci to write delta files to a
per-session directory:

```
/var/run/rpcd/uci-<session_id_hex>/
```

This means:

- Changes made in one rpcd session are invisible to other sessions until
  committed.
- CLI `uci set` commands (run as root on the device) stage to the default
  `/tmp/.uci/` directory, which is separate from any rpcd session.
- When a session expires, rpcd calls `rpc_uci_purge_savedir_cb` which
  deletes the entire per-session directory. All uncommitted changes for
  that session are silently discarded.

This is the first layer of safety: if a user starts changes in LuCI and
walks away (session times out after ~300s), the staged changes vanish.

### Apply / Confirm / Rollback

rpcd implements a confirmed-commit cycle via three `uci` methods:

| Method    | What it does |
|-----------|-------------|
| `apply`   | Snapshot `/etc/config/*` to `/var/run/rpcd/snapshot-files/`, commit staged changes, reload services via procd, arm a uloop rollback timer |
| `confirm` | Cancel the rollback timer, purge snapshots -- changes become permanent |
| `rollback`| Restore snapshots to `/etc/config/`, reload services -- device reverts to pre-apply state |

When `apply` is called with `{"rollback": true, "timeout": N}`:

1. rpcd copies current `/etc/config/*` files to `/var/run/rpcd/snapshot-files/`
2. Commits staged changes (from `/tmp/.uci/` or the session directory) to `/etc/config/`
3. Triggers procd service reloads via ubus events
4. Arms a timer for N seconds

If `confirm` arrives before the timer fires, the snapshots are purged and
changes are permanent. If the timer fires without confirmation, rpcd
restores the snapshots and reloads services -- the device reverts
automatically.

Only one rollback session can be active at a time. A second `apply` with
`rollback=true` while a timer is running returns `UBUS_STATUS_PERMISSION_DENIED`.

This mechanism works identically whether the request arrives over HTTPS
(JSON-RPC) or the local ubus socket (`ubus call` CLI over SSH).

## Timeout Configuration

rpcd has three independent timeout mechanisms that affect Salt operations.
The proxy module exposes all three as pillar settings.

### Overview

```
Salt Master (proxy minion)                    OpenWrt Device
  |                                              |
  |--- HTTPS POST /ubus ---- timeout ---------> |
  |    (HTTP request timeout)                    |
  |                                         rpcd |
  |                                              |--- ubus call ---> target daemon
  |                                              |    (rpcd invoke timeout)
  |                                              |<-- response ------
  |<-- JSON-RPC response ----------------------- |
  |                                              |
  |  session token valid for session_timeout     |
```

### The three timeouts

| Timeout | What it controls | Where configured | Default |
|---------|-----------------|------------------|---------|
| **HTTP request** | How long the Salt proxy waits for an HTTP response from uhttpd | Pillar `proxy.timeout` | 30s |
| **Session lifetime** | How long the rpcd login session lives; staged UCI changes are lost when it expires | Pillar `proxy.session_timeout`, passed to rpcd via `session login` ubus call | 300s |
| **rpcd invoke** | How long rpcd waits for a downstream ubus call to return before timing out | Pillar `proxy.rpcd_timeout`, enforced via `rpcd.@rpcd[0].timeout` UCI setting | 300s (OpenWrt ships 30s) |

### Pillar configuration

```yaml
proxy:
  proxytype: uci_ubus_jsonrpc
  host: 10.35.24.1
  password: secret
  timeout: 30            # HTTP request timeout (seconds)
  session_timeout: 300   # rpcd session lifetime (seconds)
  rpcd_timeout: 300      # rpcd ubus invoke timeout (seconds)
```

### How each timeout is applied

**HTTP request timeout** (`timeout`): Passed to Python's `urllib.request.urlopen`
as the socket timeout. If uhttpd or the network is slow, this fires first.

**Session lifetime** (`session_timeout`): Passed as the `timeout` parameter in
the `session login` ubus call. rpcd's `rpc_handle_login()` reads this from
the request and creates a session with that TTL (source: rpcd
[`include/rpcd/session.h:38`](https://git.openwrt.org/?p=project/rpcd.git;a=blob;f=include/rpcd/session.h),
[`session.c`](https://git.openwrt.org/?p=project/rpcd.git;a=blob;f=session.c)
line ~451). If the caller does not pass a timeout, rpcd uses the compiled-in
default of 300s (`RPC_DEFAULT_SESSION_TIMEOUT`). The proxy re-authenticates
automatically when the session nears expiry (`_ensure_session()`).

**rpcd invoke timeout** (`rpcd_timeout`): The `rpcd.@rpcd[0].timeout` UCI
setting controls how long rpcd waits for a ubus call to complete. This is
analogous to the `ubus -t` CLI flag. The OpenWrt default is 30s, which can
be too short for `uci apply` + service reloads on slow devices (128 MB MIPS
routers with many services). At proxy connect, `_ensure_rpcd_timeout()` reads
the current UCI value and bumps it if below the configured minimum. This
requires a `uci commit rpcd` + `reload_config` which restarts rpcd --
the proxy handles this by sleeping 2s and re-authenticating.

### Interaction between timeouts

For a `uci apply` call to succeed, all three timeouts must be long enough:

1. rpcd receives the call and dispatches to the uci handler
2. The uci handler commits changes, triggers `reload_config`, waits for
   procd to reload services
3. rpcd must not time out waiting for the uci handler (invoke timeout)
4. uhttpd must not time out waiting for rpcd (HTTP timeout is set on the
   client side, so the proxy controls this)
5. The session must still be valid when the response arrives

In practice: set `rpcd_timeout >= rollback_timeout` (so rpcd doesn't kill
the apply call before the rollback timer is armed) and `timeout` >= a few
seconds longer than `rpcd_timeout` (so the HTTP request doesn't timeout
before rpcd finishes).

## Security Notes

- rpcd sessions are in-memory only; restarting rpcd invalidates all
  sessions and discards all per-session staging directories
- `$p$<user>` reads the password hash from `/etc/shadow` (not `/etc/passwd`)
- The user must have an `/etc/shadow` entry for `$p$` to work
- ACL `*` for read/write grants all defined access groups but does NOT
  bypass the ACL file requirement: if no ACL file grants `network.device
  status`, even `*` cannot access it
- uhttpd redirects HTTP to HTTPS by default; self-signed cert
- Session tokens are transmitted in the JSON body, not cookies or headers
- The local ubus Unix socket bypasses rpcd session/ACL checks entirely;
  processes with socket access (typically root) have full ubus access
  including `uci apply`, `uci confirm`, and `uci rollback`
