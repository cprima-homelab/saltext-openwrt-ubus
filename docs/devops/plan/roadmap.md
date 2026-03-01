# Roadmap

> Last reviewed against: v0.3.0

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

## Planned

- **Config reader / pillar generator** -- read device config via ubus,
  output Salt pillar YAML for onboarding existing routers.
  See [02-cli-config-reader.md](02-cli-config-reader.md).
- **Anonymous section management** -- address anonymous sections by type
  and match criteria, beyond the current singleton-only support.
- **Integration tests** -- containerized OpenWrt with rpcd for
  end-to-end testing.
- **LuCI staging visibility** -- explore making Salt-staged changes
  visible in LuCI's "Unsaved Changes" view for humanreviewed mode.
