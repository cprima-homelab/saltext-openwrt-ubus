# 05 -- Proxy Lifecycle

> Last reviewed against: v0.4.0

How the two proxy modules manage connections, sessions, and the
relationship between proxy and state module.

## Source files

| File | Lines | Transport |
|------|-------|-----------|
| `proxy/ubus_jsonrpc.py` | 233 | HTTPS JSON-RPC |
| `proxy/uci_ssh.py` | 221 | SSH |
| `utils/rpc.py` | 192 | Pure Python JSON-RPC client |
| `utils/ssh.py` | 112 | Pure Python SSH runner |

All paths relative to `src/saltext/openwrt_ubus/`.

## Proxy interface

Both proxy modules implement the same Salt proxy interface:

| Function | JSON-RPC | SSH |
|----------|----------|-----|
| `init(opts)` | Create `UbusRpcClient`, login, bump rpcd timeout, cache grains | Create `SshRunner`, test connection, cache grains |
| `alive(opts)` | Flag check (`DETAILS["initialized"]`) | Flag check |
| `ping()` | `system.board` call | `echo` over SSH |
| `call(obj, method, params)` | Forward to `UbusRpcClient.call()` | Run `ubus call` over SSH |
| `grains()` | Return cached dict | Return cached dict |
| `grains_refresh()` | Re-fetch and cache | Re-fetch and cache |
| `shutdown(opts)` | `DETAILS.clear()` | `DETAILS.clear()` |

The SSH proxy also provides `run_raw(command)` for non-ubus operations
like `reload_config`.

## Session persistence (JSON-RPC)

The JSON-RPC proxy keeps the rpcd session alive across multiple Salt
state runs. This is critical for **autoverified mode**: `managed()`
stages changes in one state, `applied()` commits them in a later state,
both sharing the same rpcd session.

### How it works

The `UbusRpcClient` tracks session expiration:

```python
# utils/rpc.py:114-140
def login(self):
    result = self._raw_request("call", [NULL_SESSION, "session", "login", login_params])
    data = result["result"][1]
    self._session = data["ubus_rpc_session"]
    self._session_timeout = data.get("timeout", 300)
    self._session_expires = time.monotonic() + self._session_timeout - 10  # safety margin
```

Before every call, the client checks if the session will expire soon:

```python
# utils/rpc.py:147-150
def _ensure_session(self):
    if self._session is None or time.monotonic() >= self._session_expires:
        self.login()
```

The **10-second safety margin** prevents a race condition: the client
re-logs in before the device closes the session, so there is never a
gap where the token is expired but the client thinks it's valid.

### Per-session staging

For the rpcd C source code that implements this mechanism, see
[08-rpcd-session-staging-internals.md](08-rpcd-session-staging-internals.md).

UCI changes made via JSON-RPC are staged in a per-session directory:

```
/var/run/rpcd/uci-<session_id_hex>/
```

These changes are invisible to other rpcd sessions, SSH, and the UCI
CLI. They persist as long as the session lives. When the session
expires, rpcd deletes the directory and all uncommitted changes are
silently discarded.

The proxy's `_ensure_session()` re-login keeps the session alive
indefinitely (as long as the proxy minion is running). This means
staged changes survive between state runs.

### SSH difference

SSH has no session concept. Changes stage to the device's filesystem:

```
/tmp/.uci/
```

These are visible to all processes on the device (SSH, LuCI, local CLI).
They persist until committed, reverted, or the device reboots.

## Flag-based dead connection detection

Both proxy modules use a pessimistic approach: any transport error
flips a flag, and Salt's next `alive()` check triggers reconnection.

```python
# proxy/ubus_jsonrpc.py:84-91,125-132
def alive(opts):
    return DETAILS.get("initialized", False)       # no I/O

def call(ubus_object, ubus_method, params=None):
    try:
        return DETAILS["client"].call(ubus_object, ubus_method, params)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        DETAILS["initialized"] = False             # flag dead
        raise
```

The SSH proxy has the same pattern, plus special handling for rc=255
(SSH connection failure vs command failure):

```python
# proxy/uci_ssh.py:150-154
except SshCommandError as exc:
    if exc.returncode == 255:               # SSH connection failure
        DETAILS["initialized"] = False
    raise                                    # command errors don't kill the proxy
```

## Preemptive rpcd timeout adjustment

At init, the JSON-RPC proxy checks if rpcd's invoke timeout is
sufficient. The default is 30s, which is too short for `uci apply`
with service reloads on slow routers (128 MB MIPS):

```python
# proxy/ubus_jsonrpc.py:135-191
def _ensure_rpcd_timeout(client, desired):
    rpcd_conf = client.call("uci", "get", {"config": "rpcd", "type": "rpcd"})
    # Find rpcd section and read current timeout ...
    if current_timeout >= desired:
        return                                     # already sufficient
    # Otherwise bump it
    client.call("uci", "set", {"config": "rpcd", "section": section_name,
                                "values": {"timeout": str(desired)}})
    client.call("uci", "commit", {"config": "rpcd"})
    client.call("uci", "reload_config")
    time.sleep(2)                                  # wait for rpcd restart
    client.login()                                 # re-authenticate
```

This is a one-time operation: subsequent proxy inits find the timeout
already bumped and skip the update.

## Session timeout validation

At login, the proxy checks whether rpcd granted the requested session
timeout:

```python
# proxy/ubus_jsonrpc.py:69-76
client.login()
if client.session_timeout < session_timeout:
    log.warning(
        "rpcd granted session timeout of %ds (requested %ds). "
        "Staged UCI changes may be lost between state runs.",
        client.session_timeout,
        session_timeout,
    )
```

This catches cases where rpcd's compiled-in maximum is lower than the
requested value.

## Grains caching

Both proxies cache grains at init time from `system.board` and
`system.info`:

| Grain | Source |
|-------|--------|
| `os`, `os_family` | `system.board` → `release.distribution` |
| `osrelease` | `system.board` → `release.version` |
| `model`, `board_name` | `system.board` |
| `kernel`, `cpuarch` | `system.board` |
| `host`, `fqdn`, `domain` | `system.board` → `hostname` |
| `mem_total` | `system.info` → `memory.total` (bytes → KB) |
| `uptime` | `system.info` |

These override the salt-master's host grains so `grains["os"]` returns
`"OpenWrt"` instead of the master's OS.

## Error handling layers

```
State module
  └─ calls __salt__["openwrt_ubus.get"]()
       └─ calls __proxy__["openwrt_ubus_jsonrpc.call"]()
            └─ calls DETAILS["client"].call()           (UbusRpcClient)
                 ├─ UbusError (code 6: permission denied)  ← rpcd ACL
                 ├─ JsonRpcError (-32002: access denied)   ← mapped to UbusError
                 └─ urllib.error.URLError / TimeoutError   ← network/transport
```

Transport errors (`URLError`, `TimeoutError`, `OSError`) flip the
`initialized` flag. Application errors (`UbusError`) propagate to the
caller but don't kill the proxy.

JSON-RPC error `-32002` is special-cased:

```python
# utils/rpc.py:176-183
if "error" in result:
    err = result["error"]
    if err.get("code") == -32002:
        raise UbusError(UBUS_STATUS_PERMISSION_DENIED,
                        f"Access denied: {ubus_object}.{ubus_method}")
    raise JsonRpcError(err["code"], err["message"])
```

This maps a generic JSON-RPC server error to a meaningful ubus error
("Access denied: uci.set" instead of "JSON-RPC error -32002").

## Pure Python utilities

`UbusRpcClient` and `SshRunner` have no Salt dependencies. They use
only Python stdlib (`urllib.request`, `subprocess`, `json`, `ssl`).
This makes them independently testable and reusable outside Salt.
