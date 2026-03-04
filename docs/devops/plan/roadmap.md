# Roadmap

> Last reviewed against: v0.4.0

## Resolved

### v0.1 -- Initial implementation

- Salt proxy minion pattern (no Python on target)
- SSH and JSON-RPC transport adapters
- Execution module: get, set, add, delete, apply, confirm, rollback,
  revert, commit, state, configs, changes
- Input escaping via `shlex.quote()`

### v0.2 -- Proxy and state module

- State module: `managed()` with partial semantics, `applied()` with
  service health verification
- Grains module: device facts via proxy (os, model, kernel, memory, etc.)
- Agent modes: oneshot, autoverified, humanreviewed, audit
- rpcd session management: login, timeout bumping, session keep-alive
- Singleton anonymous section resolution (by `_type`)
- Local subprocess adapter (`uci_local.py`)
- System/network/service query functions
- Shared logic via `ubus_ops.py` (dependency injection)

### v0.3 -- Virtualname rename

- Rename virtualnames: `saltext_ubus` -> `openwrt_ubus`
- Add `openwrt` shorthand alias modules
- Proxy virtualnames: `openwrt_ubus_jsonrpc`, `openwrt_ubus_ssh`

### v0.4 -- Anonymous section management

- Multi-instance anonymous sections via `_match`/`_items` pillar syntax
- `_absent` sentinel for deleting options or entire sections
- `_prune` flag for removing unmanaged anonymous sections
- Order enforcement (delete+re-add strategy)
- 12/12 testcorpus validation

## Planned

- **Config reader / pillar generator** -- read device config via ubus,
  output Salt pillar YAML for onboarding existing routers.
  See [02-cli-config-reader.md](02-cli-config-reader.md).
- **Integration tests** -- containerized OpenWrt with rpcd for
  end-to-end testing.
- **LuCI staging visibility** -- explore making Salt-staged changes
  visible in LuCI's "Unsaved Changes" view for humanreviewed mode.
