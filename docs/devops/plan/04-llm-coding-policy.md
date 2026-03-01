# 04 -- LLM Coding Policy

> Last reviewed against: v0.3.0

## Purpose

This document defines conventions for AI-assisted development on saltext-ubus. It is the source material for generating CLAUDE.md, .cursorrules, and similar instruction files.

## UCI Domain Knowledge

### Config Structure

```
package
  section (named or anonymous)
    option (scalar value)
    list (multi-value option)
```

Example in `uci show` format:
```
network.lan=interface           # named section "lan" of type "interface"
network.lan.proto=static        # scalar option
network.wan.dns='1.1.1.1' '1.0.0.1'  # list option (space-separated, each quoted)
firewall.@rule[0]=rule          # anonymous section (index-based reference)
firewall.@rule[0].name=Allow-SSH
```

Example in `uci export` format:
```
config interface 'lan'
    option proto 'static'
    option ipaddr '10.35.24.1'

config rule
    option name 'Allow-SSH'
    option src 'wan'
    list proto 'tcp'
    option dest_port '22'
    option target 'ACCEPT'
```

### Key Rules

- Named sections have stable references: `network.lan`
- Anonymous sections have **unstable** index-based references: `firewall.@rule[3]`
- Adding/removing anonymous sections shifts all higher indices
- Changes are staged until `uci commit <package>` writes them to `/etc/config/<package>`
- `uci revert <package>` discards staged changes
- **This extension uses ubus, not the uci CLI** (see ADR-000)

## Salt Extension Patterns

### Module Structure

All three adapters (JSON-RPC, SSH, local) share the same pattern.
Each defines only `__virtual__()` and `_call()`, delegating all logic
to `utils/ubus_ops.py`:

```python
# Execution module adapter: src/saltext/saltext_ubus/modules/ubus_jsonrpc.py

from saltext.saltext_ubus.utils import ubus_ops

__virtualname__ = "openwrt_ubus"
__proxyenabled__ = ["openwrt_ubus_jsonrpc"]

def __virtual__():
    if __opts__.get("proxy", {}).get("proxytype") != "openwrt_ubus_jsonrpc":
        return False, "proxytype is not openwrt_ubus_jsonrpc"
    return __virtualname__

def _call(ubus_object, ubus_method, params=None):
    """Forward a ubus call through the proxy module."""
    return __proxy__["openwrt_ubus_jsonrpc.call"](ubus_object, ubus_method, params)

# All public functions delegate to ubus_ops:
def get(config, section=None, option=None):
    return ubus_ops.get(_call, config, section=section, option=option)
```

### Dunder Globals

| Global | Purpose | Available In |
|--------|---------|-------------|
| `__salt__` | Call other execution modules | Execution + state modules |
| `__opts__` | Minion/master configuration | All modules |
| `__grains__` | System grains (OS, kernel, etc.) | All modules |
| `__pillar__` | Pillar data | All modules |
| `__context__` | Per-module persistent cache | All modules |
| `__proxy__` | Call proxy module functions | Proxy-aware modules |

### State Return Dict

Every state function must return:
```python
{
    "name": name,        # The state ID
    "changes": {},       # Dict of what changed (empty if no changes)
    "result": True,      # True=success, False=failure, None=dry-run
    "comment": "",       # Human-readable description
}
```

### Test Mode

State functions must support `test=True` (dry run):
```python
def managed(name, config, sections, ...):
    # ... diff desired vs current ...
    if __opts__["test"]:
        return {"name": name, "changes": changes,
                "result": None, "comment": "Would apply changes"}
    # ... stage changes via openwrt_ubus.set / openwrt_ubus.add ...
    return {"name": name, "changes": changes,
            "result": True, "comment": "Applied changes"}
```

## Idempotency Rules

1. **Never stage changes without diffing first.** The state module reads
   current config via `openwrt_ubus.get(config)` and computes a delta
   with `_diff_section()`. Only changed options are staged.
2. **Use partial semantics.** Only options listed in the pillar are managed.
   Other options on the same section are left untouched.
3. **Handle anonymous sections carefully.** Singleton anonymous sections
   can be resolved by `_type` match. Multi-instance anonymous section
   management is not yet implemented.
4. **Use the apply/confirm cycle for safety.** `ubus call uci apply`
   with rollback ensures connectivity-breaking changes auto-revert.
5. **Check for uncommitted changes before staging.** The state module
   verifies no prior uncommitted changes exist (or reverts them if
   `revert_pending=True`).

## Code Style

- **Formatter**: black, line length 100
- **Import sorting**: isort, profile=black
- **Linting**: pylint (config in `.pylintrc`), bandit for security
- **Type hints**: use for public API functions, not required for internal helpers
- **Docstrings**: Google style (napoleon), required for all public functions
- **CLI examples**: required in execution module docstrings (checked by pre-commit hook)

Example docstring:
```python
def get(config, section=None, option=None):
    """
    Read UCI configuration.

    Args:
        config: UCI config package name (e.g., ``network``)
        section: Optional section name
        option: Optional option name

    Returns:
        Full config dict, single section dict, or single option value

    CLI Example:

    .. code-block:: bash

        salt 'austru' openwrt_ubus.get network
        salt 'austru' openwrt_ubus.get network lan proto
    """
```

## Commit Policy

- No emoji in messages
- No Co-Authored-By trailer (enforced by pre-commit hook)
- Imperative mood subject line ("Add feature" not "Added feature")
- Subject under 72 characters
- Body explains **why**, not what
- Changelog fragment required for user-facing changes (towncrier)

## Testing Requirements

- Every public execution module function needs a unit test
- Unit tests mock the adapter's `_call()` function with known ubus JSON responses
- State module tests mock `openwrt_ubus.get`, `openwrt_ubus.set`, etc. via `__salt__`
- Proxy tests mock `UbusRpcClient` / `SshRunner`
- Utils tests cover `ubus_ops.transform_section()` and shared logic
- Test both success and error paths
- Test idempotency: calling a state function twice should produce no-op on second call

## Transport Awareness

The extension does **not** run shell commands on the target device. All
three adapters talk to the same ubusd daemon via different transports,
returning identical JSON. Code in `ubus_ops.py` is fully transport-agnostic.

When writing new functions:
- Add the logic to `ubus_ops.py` with a `call` parameter (dependency injection)
- Each adapter's public function delegates: `return ubus_ops.new_func(_call, ...)`
- Never assume a specific transport -- no SSH-specific or HTTP-specific logic in shared code

## Files to Generate

| File | Location | Purpose |
|------|----------|---------|
| `CLAUDE.md` | saltext-ubus repo root | Claude Code instructions (gitignored) |
| `.cursorrules` | saltext-ubus repo root | Cursor AI instructions (optional, committed) |

Neither file exists yet. When created, they should be derived from this
policy document.
