# 06 -- OpenWrt Device Packages

> Last reviewed against: v0.4.0

The device-side half of the extension: opkg packages that prepare an
OpenWrt router for Salt management.

Source: `packages/` in the `cprima-homelab/openwrt-packages` repo (migrated
out of this repo; no longer vendored here).

## Package inventory

| Package | Version | Purpose |
|---------|---------|---------|
| `salt-agent-ubus` | 0.3.0-1 | rpcd user, ACL, JSON-RPC access |
| `salt-openwrt` | 0.1.1-1 | Agent mode UCI config |
| `salt-agent-ssh` | 0.1.0-1 | SSH access (stub, not yet implemented) |
| `luci-app-salt-openwrt` | 0.1.1-1 | LuCI web UI for agent config |

## salt-agent-ubus

Creates the rpcd credentials and ACL that the JSON-RPC proxy uses to
authenticate.

### What it installs

| File | Purpose |
|------|---------|
| `/usr/share/rpcd/acl.d/salt-agent-ubus.json` | rpcd access group definition |

### postinst: user creation

The post-install script creates a system user for rpcd authentication:

```sh
# packages/salt-agent-ubus/Makefile (cprima-homelab/openwrt-packages)
# Find next free system uid (scan 999 down to 100)
uid=999
while [ "$uid" -ge 100 ]; do
    if ! grep -q "^[^:]*:[^:]*:${uid}:" /etc/passwd; then
        NEW_UID=$uid
        break
    fi
    uid=$((uid - 1))
done
echo "salt-agent:x:${NEW_UID}:${NEW_UID}:salt-agent:/home/salt-agent:/bin/false" >> /etc/passwd
echo "salt-agent:!:0:0:99999:7:::" >> /etc/shadow
```

- Dynamic uid allocation in 100-999 range (Debian service account convention)
- Shell `/bin/false` -- no interactive login
- Password locked (`!` in shadow) until operator runs `passwd salt-agent`

### postinst: rpcd login entry

```sh
uci add rpcd login
uci set "rpcd.@login[-1].username=salt-agent"
uci set "rpcd.@login[-1].password=$(printf '$p$salt-agent')"
uci add_list "rpcd.@login[-1].read=saltext-uci"
uci add_list "rpcd.@login[-1].write=saltext-uci"
uci commit rpcd
/etc/init.d/rpcd restart
```

- `$p$salt-agent` tells rpcd to verify against `/etc/shadow`
- `read` and `write` reference the ACL group `saltext-uci`

### postrm: cleanup

Removes the rpcd login entry but intentionally keeps the system user
and home directory to preserve file ownership.

### ACL: `salt-agent-ubus.json`

Access group name: **`saltext-uci`**

#### Read grants

| ubus object | Methods |
|-------------|---------|
| `session` | `access`, `login` |
| `system` | `board`, `info` |
| `service` | `list` |
| `network` | `get_proto_handlers` |
| `network.device` | `status` |
| `network.interface` | `dump` |
| `network.interface.*` | `status`, `dump` |
| `luci-rpc` | `getBoardJSON`, `getNetworkDevices`, `getDHCPLeases`, `getHostHints`, `getWirelessDevices` |
| `uci` | `configs`, `get`, `state`, `changes` |
| UCI packages | `*` (all) |

#### Write grants

| ubus object | Methods |
|-------------|---------|
| `uci` | `add`, `set`, `delete`, `rename`, `order`, `commit`, `revert`, `apply`, `confirm`, `rollback`, `reload_config` |
| UCI packages | `*` (all) |

#### ACL scope

UCI package scope is intentionally broad (`*`) during development.
Planned for tightening to specific packages (network, wireless, dhcp,
firewall, system, openvpn) in a future version. See plan/07.

## salt-openwrt

Ships the UCI config file that controls agent behavior. The state module
reads this config from the device at runtime.

### What it installs

| File | Purpose |
|------|---------|
| `/etc/config/salt-openwrt` | Agent mode configuration |

Marked as `conffile` -- survives package upgrades when locally modified.

### UCI config

```
config salt-openwrt 'global'
    option enabled '1'
    option mode 'audit'
    option rollback_timeout '120'
    option last_run ''
    option last_drift ''
```

| Option | Values | Purpose |
|--------|--------|---------|
| `enabled` | `1` / `0` | Enable/disable Salt management |
| `mode` | `audit`, `oneshot`, `autoverified`, `humanreviewed` | Agent behavior mode |
| `rollback_timeout` | seconds | Default rollback timer for `uci apply` |
| `last_run` | timestamp | Populated by state module |
| `last_drift` | timestamp | Populated by state module |

Default mode is `audit` (read-only). The operator upgrades to `oneshot`
or `autoverified` when ready for Salt to make changes.

### How the state module reads this

```python
# states/saltext_ubus.py:241-254
def _get_agent_mode():
    try:
        agent = __salt__["openwrt_ubus.get"]("salt-openwrt", "global")
    except Exception:
        return True, "oneshot", 120      # package not installed → default
    enabled = agent.get("enabled", "1") == "1"
    mode = agent.get("mode", "oneshot")
    rollback_timeout = int(agent.get("rollback_timeout", "120"))
    return enabled, mode, rollback_timeout
```

If the `salt-openwrt` package is not installed, the state defaults to
oneshot mode (full apply+confirm on every run).

## luci-app-salt-openwrt

LuCI web interface for viewing and configuring the agent mode.

### What it installs

| File | Purpose |
|------|---------|
| `/usr/share/luci/menu.d/luci-app-salt-openwrt.json` | Menu entry (Services > Salt Agent) |
| `/usr/share/rpcd/acl.d/luci-app-salt-openwrt.json` | rpcd ACL for LuCI access |
| `/usr/share/ucitrack/luci-app-salt-openwrt.json` | UCI change tracking |
| `/www/luci-static/resources/view/salt-openwrt.js` | Web UI form (JavaScript) |

The LuCI ACL is scoped to `salt-openwrt` UCI package only -- it cannot
read or write other packages.

## Dual-sided architecture

The extension works across two sides:

```
Salt master (WSL / Linux)              OpenWrt device (austru)
─────────────────────────              ─────────────────────────
saltext-openwrt-ubus (pip/uv)                 salt-agent-ubus (opkg)
  modules/ubus_jsonrpc.py  ──HTTPS──>   rpcd + salt-agent user
  states/saltext_ubus.py                 salt-agent-ubus.json ACL
  proxy/ubus_jsonrpc.py                salt-openwrt (opkg)
  utils/rpc.py                           /etc/config/salt-openwrt
  utils/ubus_ops.py                    luci-app-salt-openwrt (opkg)
                                         LuCI web UI
```

The Salt extension (Python, runs on master) and the OpenWrt packages
(shell scripts, runs on device) are versioned in the same repo. The
ACL file defines the device-side boundary of what Salt can access.
The agent mode config defines the device-side boundary of what Salt
is allowed to do.
