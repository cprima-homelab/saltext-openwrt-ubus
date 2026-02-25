# 04 -- LLM Coding Policy

## Purpose

This document defines conventions for AI-assisted development on saltext-uci. It is the source material for generating CLAUDE.md, .cursorrules, and similar instruction files.

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
network.wan.dns=1.1.1.1 1.0.0.1  # list option (space-separated in show)
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
- `uci show` returns list values space-separated; `uci get` returns them newline-separated
- `uci -q` suppresses errors (useful for `delete` on possibly-missing paths)
- Changes are staged until `uci commit <package>` writes them to `/etc/config/<package>`
- `uci revert <package>` discards staged changes

## Salt Extension Patterns

### Module Structure

```python
# Execution module: src/saltext/saltext_uci/modules/saltext_uci_mod.py

__virtualname__ = "saltext_uci"

def __virtual__():
    """Only load if we can run uci commands."""
    return __virtualname__

def get(key):
    """Get a UCI value."""
    ret = __salt__["cmd.run_all"](f"uci get {key}")
    if ret["retcode"] != 0:
        return None
    return ret["stdout"].strip()
```

### Dunder Globals

| Global | Purpose | Available In |
|--------|---------|-------------|
| `__salt__` | Call other execution modules | Execution + state modules |
| `__opts__` | Minion/master configuration | All modules |
| `__grains__` | System grains (OS, kernel, etc.) | All modules |
| `__pillar__` | Pillar data | All modules |
| `__context__` | Per-module persistent cache | All modules |

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
def option_present(name, key, value):
    current = __salt__["saltext_uci.get"](key)
    if current == value:
        return {"name": name, "changes": {}, "result": True, "comment": "Already set"}
    if __opts__["test"]:
        return {"name": name, "changes": {key: {"old": current, "new": value}},
                "result": None, "comment": f"Would set {key}={value}"}
    __salt__["saltext_uci.set"](key, value)
    return {"name": name, "changes": {key: {"old": current, "new": value}},
            "result": True, "comment": f"Set {key}={value}"}
```

## Idempotency Rules

1. **Never call `uci add` without checking for existing sections first.** Always walk existing sections and match on identifying fields.
2. **Never call `uci add_list` without checking the current list.** Read first, add only if the value is missing.
3. **Prefer `uci set` for named sections.** `uci set firewall.my_rule=rule` is idempotent.
4. **Use `uci -q delete` for cleanup.** The `-q` flag prevents errors when the target doesn't exist.
5. **Always `uci commit` explicitly.** Don't rely on implicit commits.

## Code Style

- **Formatter**: black, line length 100
- **Import sorting**: isort, single-line imports, profile=black
- **Linting**: pylint (config in `.pylintrc`), bandit for security
- **Type hints**: use for public API functions, not required for internal helpers
- **Docstrings**: Google style (napoleon), required for all public functions
- **CLI examples**: required in execution module docstrings (checked by pre-commit hook)

Example docstring:
```python
def set(key, value):
    """
    Set a UCI option.

    Args:
        key: UCI path (e.g., ``network.lan.ipaddr``)
        value: Value to set

    Returns:
        True if changed, False if already set

    CLI Example:

    .. code-block:: bash

        salt '*' saltext_uci.set network.lan.ipaddr 10.35.24.1
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
- Unit tests mock `__salt__["cmd.run_all"]` with known UCI output
- Test both success and error paths
- Test idempotency: calling a function twice should produce the same result
- Use captured `uci show` output from real routers as test fixtures
- Integration tests use the SSH fixtures from `tests/conftest.py`

## Salt-SSH Awareness

All execution module functions must work when called via salt-ssh:
- Use `cmd.run_all` (not `cmd.run`) to capture return codes
- Handle the case where the target shell is `/bin/sh` (ash), not bash
- Don't assume GNU coreutils; OpenWrt uses BusyBox
- Don't assume Python is available on the target (raw mode generates shell scripts)

## Files to Generate

| File | Location | Purpose |
|------|----------|---------|
| `CLAUDE.md` | saltext-uci repo root | Claude Code instructions (gitignored) |
| `.cursorrules` | saltext-uci repo root | Cursor AI instructions (optional, committed) |

These files should be generated from this document and updated when policy changes.

### Keeping Instruction Files in Sync

Policy drift between this document and the generated instruction files is a known risk. Mitigation:

1. **Manual regeneration**: When this document changes, regenerate CLAUDE.md and .cursorrules as part of the same commit. The commit message should reference the policy change.
2. **Pre-commit reminder**: The `docs/devops/plan/04-llm-coding-policy.md` file is listed in a pre-commit check that warns (not blocks) when it is modified without a corresponding change to CLAUDE.md. This is advisory, not enforced, to avoid blocking legitimate doc-only edits.
3. **Section header anchors**: CLAUDE.md references this document by section anchor (e.g., `See 04-llm-coding-policy.md#idempotency-rules`) so that stale content can be traced to its source.

There is no automated generation tool. The instruction files are hand-written derivatives of this policy document, not templates rendered by a script. Automation is deferred until the policy stabilizes.
