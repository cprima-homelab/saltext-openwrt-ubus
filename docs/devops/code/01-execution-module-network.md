# Code: Execution Module -- `network` Named Sections

Implements the minimal scope defined in [plan/05-minimal-scope.md](../plan/05-minimal-scope.md).

## Target File

`src/saltext/saltext_uci/modules/saltext_uci_mod.py`

## Functions

### Read operations

| Function | UCI command | Input | Output |
|----------|-----------|-------|--------|
| `get(key)` | `uci get <key>` | `"network.lan.ipaddr"` | `"10.35.24.1"` or `None` |
| `get_all(package, section)` | `uci show <package>.<section>` | `"network", "lan"` | dict of option->value |
| `show(package=None)` | `uci show [package]` | `"network"` | raw text |
| `commit(package)` | `uci commit <package>` | `"network"` | `True` or error string |

### Write operations

| Function | UCI command | Input | Output |
|----------|-----------|-------|--------|
| `set_(key, value)` | `uci set <key>=<value>` | `"network.lan.ipaddr", "10.35.24.1"` | `True` if changed, `False` if already set |
| `delete(key)` | `uci -q delete <key>` | `"network.wan6"` | `True` |
| `add_list(key, value)` | read + `uci add_list` | `"network.wan.dns", "1.1.1.1"` | `True` if added, `False` if already present |
| `set_list(key, values)` | `uci delete` + N x `uci add_list` | `"network.wan.dns", ["1.1.1.1", "1.0.0.1"]` | `True` if changed, `False` if identical |

## Implementation Notes

### `__virtual__`

```python
def __virtual__():
    if salt.utils.path.which("uci") is None:
        return (False, "uci binary not found on target")
    return __virtualname__
```

### `set` is a Python builtin

```python
__func_alias__ = {"set_": "set"}
```

This lets Salt expose it as `saltext_uci.set` while the Python function is `set_()`.

### Shell command API

All functions use `cmd.run_all` to capture return codes:

```python
ret = __salt__["cmd.run_all"]("uci get network.lan.ipaddr", ignore_retcode=True)
# ret = {"retcode": 0, "stdout": "10.35.24.1", "stderr": ""}
```

### `get_all` parsing

`uci show network.lan` returns:

```
network.lan=interface
network.lan.device='br-lan'
network.lan.proto='static'
network.lan.ipaddr='10.35.24.1'
network.lan.netmask='255.255.255.0'
```

Parse into:

```python
{"_type": "interface", "device": "br-lan", "proto": "static",
 "ipaddr": "10.35.24.1", "netmask": "255.255.255.0"}
```

The first line (`network.lan=interface`) gives the section type. Subsequent lines are `key='value'` pairs. List values appear as `network.wan.dns='1.1.1.1' '1.0.0.1'` (space-separated, each quoted).

### `add_list` idempotency

```
1. uci get <key>  ->  current values (space-separated) or error if unset
2. if desired value already in current  ->  return False (no change)
3. uci add_list <key>=<value>  ->  return True
```

### `set_list` idempotency

```
1. uci get <key>  ->  current values
2. if current == desired  ->  return False (no change)
3. uci delete <key>
4. for each value: uci add_list <key>=<value>
5. return True
```

## Test File

`tests/unit/modules/test_saltext_uci.py`

### Test fixtures

Mock `cmd.run_all` returns based on captured austru output:

```python
# Successful get
{"retcode": 0, "stdout": "10.35.24.1", "stderr": ""}

# Missing key
{"retcode": 1, "stdout": "", "stderr": "uci: Entry not found"}

# uci show network.lan
{"retcode": 0, "stdout": "network.lan=interface\nnetwork.lan.device='br-lan'\nnetwork.lan.proto='static'\nnetwork.lan.ipaddr='10.35.24.1'\nnetwork.lan.netmask='255.255.255.0'", "stderr": ""}

# uci get for list (dns)
{"retcode": 0, "stdout": "1.1.1.1\n1.0.0.1", "stderr": ""}
```

### Test matrix

| Function | Test case |
|----------|-----------|
| `get` | existing key, missing key, empty value |
| `get_all` | normal section, missing section |
| `set_` | new value, same value (no-op), missing section error |
| `delete` | existing key, already absent (no-op) |
| `add_list` | value not in list, value already present, list doesn't exist yet |
| `set_list` | same list (no-op), different list, empty target list |
| `commit` | success, error |
| `show` | full package, missing package |
