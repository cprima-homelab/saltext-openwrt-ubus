# rpcd ACL Model

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
        "system": ["board", "info"],
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
