# 09 -- Proxy Module Architecture

> Last reviewed against: v0.4.0

## Problem

OpenWrt routers typically have no Python, and low-RAM devices (128 MB
WNDR3800) cannot run salt-ssh's thin client without OOM and hardware
watchdog reboots. The device must be managed remotely without executing
Salt or Python on the target.

## Solution: Proxy Minion Pattern

Salt's standard pattern for managing devices without Python is the
**proxy minion** (used by NAPALM, Netmiko, Juniper, ESXi). A proxy
minion process runs on the salt-master and communicates with the device
over the network.

```
salt 'austru' openwrt_ubus.get network
    | (ZMQ)
proxy minion process (on salt-master)
    | (HTTPS JSON-RPC or SSH)
austru router (ubus call uci get '{"config":"network"}')
```

No Python or Salt runs on the router. The proxy minion translates Salt
execution module calls into ubus API calls over the chosen transport.

## Two Proxy Types

| Proxy | Transport | Use Case |
|-------|-----------|----------|
| `openwrt_ubus_jsonrpc` | HTTPS -> uhttpd -> rpcd -> ubus | Primary. Persistent session, per-session staging |
| `openwrt_ubus_ssh` | SSH -> `ubus call` CLI | Fallback. No rpcd/uhttpd needed |

Both proxies expose the same `call(ubus_object, ubus_method, params)`
interface. The execution module adapters delegate to the proxy via
`__proxy__["openwrt_ubus_jsonrpc.call"]` or
`__proxy__["openwrt_ubus_ssh.call"]`.

## Proxy Module Interface

### JSON-RPC proxy (`proxy/ubus_jsonrpc.py`)

| Function | Purpose |
|----------|---------|
| `init(opts)` | Create `UbusRpcClient`, authenticate, bump rpcd timeout if needed |
| `ping()` | Attempt `system.board` call, return True/False |
| `alive(opts)` | Check session validity via `_ensure_session()` |
| `initialized()` | Check `__context__` |
| `shutdown(opts)` | Clear `__context__` |
| `call(obj, method, params)` | Forward ubus call via HTTPS JSON-RPC |
| `grains()` | Return device facts from `system.board` + `system.info` |

The JSON-RPC proxy maintains a persistent rpcd session. This is crucial
for autoverified mode: `managed()` stages changes in one state run,
`applied()` commits them later, and the staged changes persist because
they share the same rpcd session through the proxy minion.

### SSH proxy (`proxy/uci_ssh.py`)

| Function | Purpose |
|----------|---------|
| `init(opts)` | Create `SshRunner` with host, user, key, options |
| `ping()` | Run `ubus call system board` via SSH |
| `alive(opts)` | Always True (no persistent connection) |
| `initialized()` | Check `__context__` |
| `shutdown(opts)` | Clear `__context__` |
| `call(obj, method, params)` | Run `ssh host 'ubus call <obj> <method> <json>'` |
| `grains()` | Return device facts from `system.board` + `system.info` |

No persistent SSH connection. Each `call()` is a fresh
`subprocess.run(["ssh", ...])`.

## Pillar Configuration

### JSON-RPC proxy

```yaml
proxy:
  proxytype: openwrt_ubus_jsonrpc
  host: 10.35.24.1
  password: secret
  # username: salt-agent      (default)
  # port: 443                 (default)
  # verify_ssl: false         (default)
  # timeout: 30               (default, HTTP request timeout in seconds)
  # session_timeout: 300      (default, rpcd session lifetime in seconds)
  # rpcd_timeout: 300         (default, rpcd ubus invoke timeout in seconds)
```

The three timeout settings control different layers of the request path.
See [11-rpcd-acl-model.md](11-rpcd-acl-model.md#timeout-configuration) for
details on what each controls and how they interact.

### SSH proxy

```yaml
proxy:
  proxytype: openwrt_ubus_ssh
  host: 10.35.24.1
  # username: root                          (default)
  # ssh_key: /root/.ssh/openwrt_ed25519     (optional)
  # ssh_options use sensible defaults for OpenWrt dropbear
```

## Why Not These Alternatives

| Alternative | Reason rejected |
|-------------|----------------|
| Install Python on router | OOM on 128 MB RAM; thin client causes watchdog reboot |
| salt-ssh raw mode (`-r`) | No execution modules, no state modules, just shell |
| `ssh_pre_flight` bootstrap | Still needs Python on target after bootstrap |
| Embedded paramiko/SSH lib | Adds dependency; system `ssh` handles auth, keys, ProxyJump |
| UCI CLI (`uci show` parsing) | Lossy interface, list/scalar ambiguity (see ADR-000) |

## Source Files

| File | Purpose |
|------|---------|
| `src/saltext/openwrt_ubus/proxy/ubus_jsonrpc.py` | JSON-RPC proxy module |
| `src/saltext/openwrt_ubus/proxy/uci_ssh.py` | SSH proxy module |
| `src/saltext/openwrt_ubus/utils/rpc.py` | `UbusRpcClient` (HTTPS transport) |
| `src/saltext/openwrt_ubus/utils/ssh.py` | `SshRunner` (SSH transport) |
| `tests/unit/proxy/test_ubus_jsonrpc.py` | JSON-RPC proxy tests |
| `tests/unit/proxy/test_uci_ssh.py` | SSH proxy tests |
