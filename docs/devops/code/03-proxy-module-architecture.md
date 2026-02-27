# Code: Proxy Module for Python-less Targets

## Problem

The execution module uses `cmd.run_all` which requires salt-ssh's thin
client on the target -- which requires Python. OpenWrt routers typically
have no Python, and low-RAM devices (128 MB WNDR3800) cannot run the
thin client without OOM and hardware watchdog reboots.

## Solution: Proxy Minion Pattern

Salt's standard pattern for managing devices without Python is the
**proxy minion** (used by NAPALM, Netmiko, Juniper, ESXi). A proxy
minion process runs on the salt-master and SSHes into the device.

```
salt 'austru' saltext_uci.get network.lan.ipaddr
    | (ZMQ)
proxy minion process (on salt-master)
    | (SSH via subprocess)
austru router (runs: uci get network.lan.ipaddr)
```

## Two Operating Modes

The execution module supports both modes via `_run()`:

| Mode | When | Transport | Python on target? |
|------|------|-----------|-------------------|
| **Direct** | salt-ssh thin client | `cmd.run_all` | Yes |
| **Proxy** | proxy minion | `__proxy__["saltext_uci.cmd"]` | No |

```python
def _run(cmd, ignore_retcode=True):
    if "__proxy__" in globals() and "saltext_uci.cmd" in __proxy__:
        return __proxy__["saltext_uci.cmd"](cmd)
    return __salt__["cmd.run_all"](cmd, ignore_retcode=ignore_retcode)
```

All other functions (`get`, `set_`, `delete`, etc.) are unchanged -- they
call `_run()` and don't know which transport is in use.

## Proxy Module Interface

`src/saltext/saltext_uci/proxy/saltext_uci_mod.py` implements:

| Function | Purpose |
|----------|---------|
| `init(opts)` | Read pillar config, store SSH details in `__context__` |
| `ping()` | `ssh <host> "echo ok"` |
| `alive(opts)` | Always True (no persistent connection) |
| `initialized()` | Check `__context__` |
| `shutdown(opts)` | Clear `__context__` |
| `cmd(command)` | `subprocess.run(["ssh", ...])`, returns `cmd.run_all`-format dict |

No persistent SSH connection. Each `cmd()` call is a fresh
`subprocess.run(["ssh", ...])`. This avoids connection state management.
OpenWrt SSH is fast enough for UCI commands.

## Pillar Configuration

```yaml
proxy:
  proxytype: saltext_uci
  host: 10.35.24.1
  user: root
  port: 22
  ssh_priv: /root/.ssh/id_ed25519
```

## Running a Proxy Minion

```bash
# On the salt-master:
salt-proxy --proxyid=austru -d

# Then use regular salt commands:
salt austru saltext_uci.get network.lan.ipaddr
```

## Why Not These Alternatives

| Alternative | Reason rejected |
|-------------|----------------|
| Install Python on router | OOM on 128 MB RAM; thin client causes watchdog reboot |
| salt-ssh raw mode (`-r`) | No execution modules, no state modules, just shell |
| `ssh_pre_flight` bootstrap | Still needs Python on target after bootstrap |
| Embedded paramiko/SSH lib | Adds dependency; system `ssh` handles auth, keys, ProxyJump |

## Source Files

| File | Purpose |
|------|---------|
| `src/saltext/saltext_uci/proxy/saltext_uci_mod.py` | Proxy module |
| `src/saltext/saltext_uci/modules/saltext_uci_mod.py` | Execution module (dual-mode `_run`) |
| `tests/unit/proxy/test_saltext_uci.py` | Proxy tests (10 tests) |
