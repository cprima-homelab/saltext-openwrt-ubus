# 02 -- Salt Coding Patterns

> Last reviewed against: v0.4.0

Salt-specific conventions and dunder globals used throughout the
extension. These are patterns a Salt developer needs to recognise; an
OpenWrt developer encountering them for the first time will find them
documented here.

## `__virtualname__` and `__virtual__()`

Every Salt-loadable module declares a `__virtualname__` string. Salt
calls `__virtual__()` at load time to decide whether the module should
activate. If it returns `False`, the module is silently skipped.

This extension uses three different guard strategies:

### Proxy type check (execution adapters)

```python
# modules/ubus_jsonrpc.py:18,27-32
__virtualname__ = "openwrt_ubus"

def __virtual__():
    if "proxy" not in __opts__:
        return False, "Not a proxy minion"
    if __opts__.get("proxy", {}).get("proxytype") != "openwrt_ubus_jsonrpc":
        return False, "proxytype is not openwrt_ubus_jsonrpc"
    return __virtualname__
```

Both `ubus_jsonrpc.py` and `uci_ssh.py` use this pattern with their
respective proxytype. Only the adapter matching the configured proxy
loads.

### Binary presence + anti-proxy guard (local adapter)

```python
# modules/uci_local.py:27,35-40
__virtualname__ = "openwrt_ubus"

def __virtual__():
    if __opts__.get("proxy"):
        return False, "Running as proxy minion -- use the proxy execution module instead"
    if not salt.utils.path.which("ubus"):
        return False, "ubus binary not found"
    return __virtualname__
```

The local adapter explicitly refuses to load if a proxy is configured,
even if `ubus` is available on the salt-master. This prevents the wrong
adapter from activating.

### Loader check (alias module)

```python
# modules/openwrt.py:8,16-19
__virtualname__ = "openwrt"

def __virtual__():
    if "openwrt_ubus.get" not in __salt__:
        return False, "openwrt_ubus module not available"
    return __virtualname__
```

The alias module checks whether any `openwrt_ubus` adapter loaded
successfully. It doesn't care which transport -- it delegates via
`__salt__`.

### Proxy module (unconditional)

```python
# proxy/ubus_jsonrpc.py:30,45-46
__virtualname__ = "openwrt_ubus_jsonrpc"

def __virtual__():
    return __virtualname__
```

Proxy modules always load. Salt selects which proxy to use based on
`proxytype` in the pillar, not `__virtual__()`.

## `__proxyenabled__`

Declares which proxy types a module supports. Salt skips modules whose
`__proxyenabled__` list doesn't include the active proxytype.

```python
# modules/ubus_jsonrpc.py:19
__proxyenabled__ = ["openwrt_ubus_jsonrpc"]

# states/saltext_ubus.py
__proxyenabled__ = ["openwrt_ubus_jsonrpc", "openwrt_ubus_ssh"]

# grains/saltext_ubus.py:17
__proxyenabled__ = ["openwrt_ubus_jsonrpc", "openwrt_ubus_ssh"]
```

The state module and grains module list both proxy types because they
work with either transport (via the adapter pattern).

## `__func_alias__`

Python builtins `set` and `apply` can't be used as function names.
The convention is to name them `set_()` and `apply_()` internally
and alias them for Salt:

```python
# modules/ubus_jsonrpc.py:21-24
__func_alias__ = {
    "set_": "set",
    "apply_": "apply",
}
```

Salt exposes them as `openwrt_ubus.set` and `openwrt_ubus.apply`.

## `__opts__`

The minion configuration dict. Injected by Salt before `__virtual__()`
is called. This extension reads:

| Key | Where read | Purpose |
|-----|-----------|---------|
| `__opts__["proxy"]["proxytype"]` | `__virtual__()` | Select which adapter loads |
| `__opts__["proxy"]` | `proxy.init()` | Read connection pillar (host, password, ...) |
| `__opts__["test"]` | `states/saltext_ubus.py` | Test mode (dry run) |

## `__salt__`

The execution module function dict. Injected after all modules load.

Alias modules use it for delegation:

```python
# modules/openwrt.py:37
return __salt__["openwrt_ubus.get"](config, section, option)
```

The state module uses it to call execution module functions:

```python
# states/saltext_ubus.py
current = __salt__["openwrt_ubus.get"](config)
__salt__["openwrt_ubus.set"](config, section, values)
__salt__["openwrt_ubus.apply"](rollback=timeout)
```

## `__proxy__`

The proxy module function dict. Execution modules use it to access
the proxy's `call()` method:

```python
# modules/ubus_jsonrpc.py:35-37
def _call(ubus_object, ubus_method, params=None):
    return __proxy__["openwrt_ubus_jsonrpc.call"](ubus_object, ubus_method, params)
```

The string `"openwrt_ubus_jsonrpc.call"` is `<proxytype>.<method>`.

## `DETAILS` module-level dict

Both proxy modules use a module-level dict to persist state across
Salt's proxy lifecycle calls (`init`, `alive`, `ping`, `call`,
`shutdown`):

```python
# proxy/ubus_jsonrpc.py:33
DETAILS = {}
```

### Lifecycle

```python
def init(opts):
    DETAILS.clear()
    # ... create client, authenticate ...
    DETAILS["client"] = client
    DETAILS["grains_cache"] = _fetch_grains(client)
    DETAILS["initialized"] = True

def alive(opts):
    return DETAILS.get("initialized", False)     # no I/O

def ping():
    try:
        DETAILS["client"].call("system", "board")
        return True
    except (urllib.error.URLError, TimeoutError, OSError):
        DETAILS["initialized"] = False           # flag dead
        return False

def call(ubus_object, ubus_method, params=None):
    try:
        return DETAILS["client"].call(ubus_object, ubus_method, params)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        DETAILS["initialized"] = False           # flag dead
        raise

def shutdown(opts):
    DETAILS.clear()
```

### Why a dict?

Salt's proxy loader creates a single module instance. Functions share
state through module-level variables. A dict is used rather than
separate variables so `DETAILS.clear()` resets everything atomically.

### Flag-based health detection

`alive()` does no network I/O -- it only reads the `initialized` flag.
Transport errors in `call()` and `ping()` flip the flag to False. Salt
then calls `init()` on the next cycle to re-establish the connection.
This is pessimistic: any error triggers reconnection.

## Grains proxy parameter injection

Grains modules load before `__proxy__` is injected. Salt works around
this by passing the proxy LazyLoader as a function parameter:

```python
# grains/saltext_ubus.py:31-43
def openwrt_ubus(proxy=None):
    """Return device grains from the proxy module."""
    if proxy is None:
        return {}
    proxytype = __opts__.get("proxy", {}).get("proxytype", "")
    grains_fn = f"{proxytype}.grains"
    if grains_fn not in proxy:
        return {}
    return proxy[grains_fn]()
```

The function dynamically constructs `"openwrt_ubus_jsonrpc.grains"` (or
SSH variant) and calls it. This lets device grains (OS version, memory,
board name) override the salt-master's host grains.

## State return dict

Every code path through `managed()` and `applied()` builds Salt's
canonical state return dict:

```python
ret = {"name": name, "result": True, "changes": {}, "comment": ""}
```

| `result` value | Meaning |
|----------------|---------|
| `True` | Success (or no changes needed) |
| `False` | Error |
| `None` | Test mode -- would have changed, didn't |

The `changes` dict uses section names as keys:

```python
ret["changes"]["lan"] = {"ipaddr": {"old": "192.168.1.1", "new": "10.35.24.1"}}
```

## Progressive defaults in proxy init

The proxy `init()` validates only required parameters and fills
sensible defaults for everything else:

```python
# proxy/ubus_jsonrpc.py:49-68
def init(opts):
    proxy_conf = opts["proxy"]
    for key in ("host", "password"):               # only these are required
        if key not in proxy_conf:
            raise ValueError(...)
    client = UbusRpcClient(
        host=proxy_conf["host"],
        username=proxy_conf.get("username", "salt-agent"),   # default
        password=proxy_conf["password"],
        port=proxy_conf.get("port", 443),                    # default
        verify_ssl=proxy_conf.get("verify_ssl", False),      # default (self-signed)
        timeout=proxy_conf.get("timeout", 30),               # default
        session_timeout=session_timeout,                      # default 300s
    )
```

This minimizes pillar boilerplate. A working pillar needs only:

```yaml
proxy:
  proxytype: openwrt_ubus_jsonrpc
  host: 10.35.24.1
  password: secret
```
