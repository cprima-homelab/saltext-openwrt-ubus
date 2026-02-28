# Static Data in Salt Extensions

Salt extensions package Python modules that extend Salt. They do
**not** package SLS files, pillar data, or Jinja templates.

## What goes inside the extension

- Python modules (`modules/`, `states/`, `proxy/`, `pillar/`, `utils/`)
- Protocol constants and lookup tables that are the same everywhere

## What stays on the Salt master

- Pillar SLS files (connection credentials, per-device settings)
- State SLS files (orchestration)

## The pillar misconception

The salt-extension-copier asks whether the extension needs a `pillar`
module. This means a **Python ext_pillar module** -- code that
programmatically generates pillar data (querying a database, API, etc.).
It does not mean a place to store static pillar YAML.

Putting static configuration into an ext_pillar module makes it
uneditable by the operator. If it is so static it should never change
from server to server, just put it in a Python variable in the module.
If it needs to vary per minion, it belongs in pillar SLS on the master.

## How saltext-uci handles this

The codebase has three categories of data and each lives in a different
place:

### Protocol constants: `utils/rpc.py`

Ubus JSON-RPC status codes and the null session token are module-level
constants. These are part of the protocol specification and never vary.

```python
UBUS_STATUS_OK = 0
UBUS_STATUS_PERMISSION_DENIED = 6
NULL_SESSION = "00000000000000000000000000000000"
```

### Ubus method names: string literals in each function

The execution module (`modules/ubus_jsonrpc.py`) passes ubus object
and method names as string literals directly in each function call:

```python
def configs():
    result = _call("uci", "configs")
    return result.get("configs", [])

def system_board():
    return _call("system", "board")
```

These are not extracted to constants because they are self-documenting
and each appears exactly once. The function name maps directly to the
ubus method it calls.

### Per-device connection config: proxy pillar

Host, credentials, port, and TLS settings come from the proxy pillar
on the Salt master. The proxy module reads them from `opts["proxy"]`:

```python
def init(opts):
    proxy_conf = opts["proxy"]
    client = UbusRpcClient(
        host=proxy_conf["host"],
        username=proxy_conf["username"],
        password=proxy_conf["password"],
        port=proxy_conf.get("port", 443),
        verify_ssl=proxy_conf.get("verify_ssl", False),
    )
```

The corresponding pillar SLS on the master:

```yaml
# /srv/salt/pillar/router.sls
proxy:
  proxytype: saltext_uci
  host: 10.35.24.1
  username: salt
  password: secret
  verify_ssl: false
```

### Summary

| Data | Location | Reason |
|------|----------|--------|
| Ubus status codes | `utils/rpc.py` constants | Protocol spec, never varies |
| Null session token | `utils/rpc.py` constant | Protocol spec |
| Ubus object/method names | String literals in functions | Self-documenting, each used once |
| Connection details | Proxy pillar on Salt master | Per-device, operator-managed |
| UCI section metadata keys | `_transform_section()` logic | Fixed mapping (`.type` -> `_type`) |

## Converting a formula to an extension

When converting an existing Salt formula (SLS + pillar + `map.jinja`)
to a Salt extension:

- SLS state logic becomes a Python state module
- `map.jinja` / YAML defaults become Python dicts in the module if they
  are truly static (same on every deployment)
- Per-minion pillar data stays in pillar SLS on the master
- There is no mechanism to ship pillar YAML inside an extension, and
  there should not be

saltext-uci was never a formula, so this conversion did not apply.
The guidance above is from a Salt community discussion and is included
for reference since the copier scaffold creates pillar module stubs
that can be misleading.

## Source

Salt Community Discord (2024-09-11), MattBoston and Whytewolf:
clarifying the boundary between extension code and pillar data when
converting a Salt formula to an extension.
