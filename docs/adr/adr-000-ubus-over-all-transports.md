# ADR-000: Use ubus as the unified device interface across all transports

- **Status**: Accepted
- **Date**: 2026-02-28
- **Context**: saltext-uci v0.2.1 SSH adapter design
- **Last reviewed against**: v0.3.0

## Context

saltext-uci manages OpenWrt devices via Salt. The extension needs a device
interface that:

1. Returns structured data suitable for delta calculation in the state module
2. Works identically across multiple transports (HTTP, SSH, local subprocess)
3. Supports the apply/confirm rollback safety pattern
4. Handles anonymous UCI sections with stable identifiers

Three transports are needed:

| Transport | Use case | Salt pattern |
|-----------|----------|--------------|
| **HTTPS** (JSON-RPC) | Remote devices with uhttpd + rpcd | Proxy minion on Salt master |
| **SSH** | Remote devices with SSH access | Proxy minion on Salt master |
| **Local subprocess** | Devices with Python3 | salt-ssh thin tarball on device |

## Decision

**All transports use `ubus call` as the device interface.** No transport
uses the `uci` CLI.

- **HTTPS**: `POST /ubus` with JSON-RPC envelope -> uhttpd -> rpcd -> ubusd
- **SSH**: `ssh host 'ubus call uci get ...'` -> ubusd
- **Local**: `subprocess.run(["ubus", "call", "uci", "get", ...])` -> ubusd

All three paths reach the same ubusd daemon and return identical JSON.

## Rationale

### The `uci` CLI is a lossy interface

The `uci show` / `uci get` CLI was considered for the SSH adapter but
rejected because it loses information the state module needs:

**List vs scalar ambiguity** -- `uci show` cannot distinguish a multi-word
scalar from a list of values:

```
# Is this a string or a list of five items?
network.@switch_vlan[0].ports='0 1 2 3 5'

# ubus resolves it unambiguously:
{"ports": "0 1 2 3 5"}      # string
{"dns": ["1.1.1.1", "1.0.0.1"]}  # array
```

This ambiguity is **unsolvable** without per-option schema knowledge.

**Anonymous section identity** -- `uci show` uses positional indices
(`@rule[6]`) that change when sections are reordered. Firewall configs
commonly have dozens of anonymous rules, zones, and forwardings:

```
# CLI: positional, unstable
firewall.@rule[0]=rule
firewall.@rule[1]=rule
...
firewall.@rule[18]=rule

# ubus: stable internal IDs with explicit metadata
{
  "cfg09b3c1": {
    ".anonymous": true,
    ".type": "rule",
    ".name": "cfg09b3c1",
    ".index": 0,
    "name": "Allow-DHCP-Renew",
    ...
  }
}
```

The state module's `_diff_section()` and `_resolve_sections()` depend on
stable section identifiers, explicit `.anonymous` flags, and unambiguous
list/scalar types. Only ubus provides all three.

**No rollback via CLI** -- The `uci` CLI has no equivalent of
`ubus call uci apply '{"rollback":true,"timeout":90}'` +
`ubus call uci confirm`. The apply/confirm pattern is essential for
safe remote configuration changes that auto-revert on connectivity loss.

### `ubus call` is universally available

Every OpenWrt device with `ubusd` running (which is all standard images)
has the `ubus` CLI tool. It returns the **exact same JSON** as the
JSON-RPC HTTP API. The only difference between transports is how the
command reaches the device:

```
JSON-RPC:  HTTPS POST {"method":"call","params":["<session>","uci","get",{...}]}
SSH:       ssh host 'ubus call uci get '{"config":"network"}''
Local:     ubus call uci get '{"config":"network"}'
```

All three return:

```json
{
  "values": {
    "lan": {
      ".type": "interface",
      ".name": "lan",
      ".anonymous": false,
      "proto": "static"
    }
  }
}
```

### Consequences for code reuse

Because all adapters get the same JSON, the execution module logic is
identical across transports. Each adapter only differs in its `_call()`
function:

- `modules/ubus_jsonrpc.py`: `__proxy__["openwrt_ubus_jsonrpc.call"](...)`
- `modules/uci_ssh.py`: `__proxy__["openwrt_ubus_ssh.call"](...)`
- `modules/uci_local.py`: `subprocess.run(["ubus", "call", ...])`

All business logic (including `transform_section()`, diffing, and
post-processing) lives in `utils/ubus_ops.py`. Each adapter only defines
`_call()` and delegates to `ubus_ops` via dependency injection. The state
module and grains module are fully transport-agnostic.

## Consequences

- No UCI text parser is needed anywhere in the codebase
- The SSH adapter requires `ubusd` on the target (standard on all OpenWrt)
- The SSH adapter does **not** require uhttpd, rpcd, or ACL configuration
- The local adapter requires Python3 on the target device
- The extension was renamed from `saltext-uci` to `saltext-ubus` in
  v0.3.0, reflecting that the interface is ubus, not the UCI CLI.

## Alternatives considered

### `uci show` parsing over SSH

Would eliminate the ubusd dependency but introduces:
- A custom text parser (`uci_parse.py`) with inherent ambiguities
- Schema files or heuristics for list detection
- Unstable anonymous section addressing
- No rollback support

Rejected: the data quality gap is fundamental and unsolvable.

### Mixed approach (ubus for reads, `uci` CLI for writes)

Would reduce parsing needs since writes don't return structured data.
But `uci commit` + service reload has no rollback, and consistency
between read and write paths is valuable.

Rejected: partial solution with no clear benefit.
