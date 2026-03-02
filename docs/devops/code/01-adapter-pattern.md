# 01 -- Adapter Pattern

> Last reviewed against: v0.3.0

How three execution modules share one virtualname and one business logic
layer through dependency injection.

## Source files

| File | Role | Lines |
|------|------|-------|
| `utils/ubus_ops.py` | Shared business logic | 159 |
| `modules/ubus_jsonrpc.py` | JSON-RPC adapter (proxy) | 271 |
| `modules/uci_ssh.py` | SSH adapter (proxy) | 274 |
| `modules/uci_local.py` | Local subprocess adapter | 300 |
| `modules/openwrt.py` | Alias (`openwrt` -> `openwrt_ubus`) | 248 |

All paths are relative to `src/saltext/openwrt_ubus/`.

## The pattern

Three adapters register the same `__virtualname__ = "openwrt_ubus"`.
Each provides a `_call()` function that handles transport. All business
logic lives in `ubus_ops.py`, which accepts `call` as a parameter:

```
modules/ubus_jsonrpc.py   modules/uci_ssh.py   modules/uci_local.py
        |                        |                       |
    _call() via              _call() via           _call() via
    __proxy__[               __proxy__[             subprocess.run
    "...jsonrpc.call"]       "...ssh.call"]         ["ubus","call",...]
        |                        |                       |
        +--- all three pass _call into --->  ubus_ops.py
                                                |
                                          get(_call, config, ...)
                                          set_(_call, config, ...)
                                          apply_(_call, timeout)
```

### Adapter: `_call()` definitions

JSON-RPC adapter -- delegates to proxy module:

```python
# modules/ubus_jsonrpc.py:35-37
def _call(ubus_object, ubus_method, params=None):
    """Forward a ubus call through the proxy module."""
    return __proxy__["openwrt_ubus_jsonrpc.call"](ubus_object, ubus_method, params)
```

SSH adapter -- same pattern, different proxytype:

```python
# modules/uci_ssh.py:35-37
def _call(ubus_object, ubus_method, params=None):
    return __proxy__["openwrt_ubus_ssh.call"](ubus_object, ubus_method, params)
```

Local adapter -- no proxy, calls ubus binary directly:

```python
# modules/uci_local.py:43-66
def _call(ubus_object, ubus_method, params=None):
    """Execute a local ubus call and return parsed JSON."""
    args = ["ubus", "call", ubus_object, ubus_method]
    if params is not None:
        args.append(json.dumps(params))
    result = subprocess.run(args, capture_output=True, text=True, check=False, timeout=30)
    if result.returncode != 0:
        raise CommandExecutionError(
            f"ubus call {ubus_object} {ubus_method} failed "
            f"(rc={result.returncode}): {result.stderr.strip()}"
        )
    output = result.stdout.strip()
    if not output:
        return None
    return json.loads(output)
```

### Shared logic: `ubus_ops.py`

Every function takes `call` as its first parameter. The function never
imports or references any transport -- it just calls the callback:

```python
# utils/ubus_ops.py:24-42
def get(call, config, section=None, option=None):
    params = {"config": config}
    if section is not None:
        params["section"] = section
    if option is not None:
        params["option"] = option
    result = call("uci", "get", params)      # <-- transport-agnostic
    if option is not None:
        return result.get("value")
    if section is not None:
        data = result.get("values", result)
        return transform_section(data)
    values = result.get("values", {})
    return {name: transform_section(data) for name, data in values.items()}
```

### Adapter wrappers

Each adapter's public functions are one-liners that inject `_call`:

```python
# modules/ubus_jsonrpc.py:43-59
def get(config, section=None, option=None):
    return ubus_ops.get(_call, config, section, option)
```

This means adding a new adapter requires only two things:
1. Define `_call()` for the new transport
2. Define `__virtual__()` to select when it loads

## Virtualname collision resolution

Only one adapter loads per minion. Each `__virtual__()` uses a different
guard:

```python
# modules/ubus_jsonrpc.py:27-32 -- proxy type check
def __virtual__():
    if "proxy" not in __opts__:
        return False, "Not a proxy minion"
    if __opts__.get("proxy", {}).get("proxytype") != "openwrt_ubus_jsonrpc":
        return False, "proxytype is not openwrt_ubus_jsonrpc"
    return __virtualname__

# modules/uci_local.py:35-40 -- binary presence + anti-proxy guard
def __virtual__():
    if __opts__.get("proxy"):
        return False, "Running as proxy minion -- use the proxy execution module instead"
    if not salt.utils.path.which("ubus"):
        return False, "ubus binary not found"
    return __virtualname__
```

Selection matrix:

| Runtime context | Adapter loaded | Guard |
|-----------------|----------------|-------|
| Proxy minion, proxytype `openwrt_ubus_jsonrpc` | `ubus_jsonrpc.py` | Proxy type match |
| Proxy minion, proxytype `openwrt_ubus_ssh` | `uci_ssh.py` | Proxy type match |
| Regular minion, `ubus` binary on PATH | `uci_local.py` | Binary check, no proxy |
| Regular minion, no `ubus` binary | None | All fail |

## Alias module delegation

`modules/openwrt.py` registers as `openwrt` and delegates to whichever
`openwrt_ubus` adapter loaded:

```python
# modules/openwrt.py:16-19
def __virtual__():
    if "openwrt_ubus.get" not in __salt__:
        return False, "openwrt_ubus module not available"
    return __virtualname__     # "openwrt"

# modules/openwrt.py -- every function delegates
def get(config, section=None, option=None):
    return __salt__["openwrt_ubus.get"](config, section, option)
```

This lets operators use either `openwrt.get` or `openwrt_ubus.get`.
The same pattern exists for the state module: `states/openwrt.py`
delegates to `states/saltext_ubus.py` (virtualname `openwrt_ubus`).

## UCI metadata transformation

ubus returns metadata with dot-prefixed keys (`.type`, `.name`,
`.anonymous`, `.index`). These could collide with actual UCI option
names. `transform_section()` renames them to underscore-prefixed:

```python
# utils/ubus_ops.py:10-18
def transform_section(data):
    result = {}
    for key, value in data.items():
        if key.startswith("."):
            result["_" + key[1:]] = value
        else:
            result[key] = value
    return result
```

Before: `{".type": "interface", ".name": "lan", "proto": "static"}`
After:  `{"_type": "interface", "_name": "lan", "proto": "static"}`

This convention carries through to pillar keys (`_type` in desired
state is metadata, skipped during diff) and singleton resolution
(`_type` used to match anonymous sections by type).

## Function inventory

All functions available through `openwrt_ubus.*`:

| Function | ubus call | Category |
|----------|-----------|----------|
| `get(config, section?, option?)` | `uci.get` | Read |
| `configs()` | `uci.configs` | Read |
| `changes(config)` | `uci.changes` | Read |
| `state(config, section?)` | `uci.state` | Read |
| `set(config, section, values)` | `uci.set` | Write |
| `add(config, type_, name?, values?)` | `uci.add` | Write |
| `delete(config, section, option?)` | `uci.delete` | Write |
| `apply(rollback=90)` | `uci.apply` | Apply |
| `confirm()` | `uci.confirm` | Apply |
| `rollback()` | `uci.rollback` | Apply |
| `revert(config)` | `uci.revert` | Apply |
| `commit(config)` | `uci.commit` | Apply |
| `system_board()` | `system.board` | System |
| `system_info()` | `system.info` | System |
| `network_dump()` | `network.interface.dump` | System |
| `service_list(verbose?)` | `service.list` | System |

`set` and `apply` are exposed via `__func_alias__` because `set` and
`apply` are Python builtins (the Python functions are `set_()` and
`apply_()`).
