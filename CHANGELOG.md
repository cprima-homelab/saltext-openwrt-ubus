The changelog format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

This project uses [Semantic Versioning](https://semver.org/) - MAJOR.MINOR.PATCH

# Changelog

## 0.3.1 (2026-03-02)

### Changed

- Renamed package from `saltext.saltext-ubus` to `saltext.openwrt-ubus`
  so the distribution name matches the TestPyPI/PyPI project name
  `saltext-openwrt-ubus`.

### Added

- OpenSSH ControlMaster connection multiplexing for SSH proxy.

## 0.3.0 (2026-03-01)

### Breaking changes

- Renamed all virtualnames from `saltext_ubus*` to `openwrt_ubus*`:
  `openwrt_ubus` (execution), `openwrt_ubus_jsonrpc` (proxy/module),
  `openwrt_ubus_ssh` (proxy/module). Pillar `proxytype` values must be
  updated accordingly.

### Added

- `applied()` state for confirmed-commit workflow: snapshots running
  services, calls `uci apply` with rollback timer, polls service health,
  and only confirms when all services are running.
- Service health verification in `managed()` oneshot mode: same
  snapshot-apply-poll-confirm cycle as `applied()`.
- Preemptive rpcd invoke timeout adjustment: proxy reads
  `rpcd.@rpcd[0].timeout` at init and bumps it if below desired value
  to prevent timeouts during slow `uci apply`.
- Session timeout negotiation via ubus `session login` parameter instead
  of UCI config manipulation.
- ADR-001: device-controlled agent mode via UCI config.
- Comprehensive devops/code documentation: adapter pattern, Salt coding
  patterns, state module logic, proxy lifecycle, OpenWrt device packages.
- Operational flow diagrams for all agent modes (oneshot, audit,
  autoverified, humanreviewed, disabled, graceful fallback).

### Changed

- Agent modes renamed: `manual` to `oneshot`, `auto` to `autoverified`.
  New modes: `audit` (read-only), `humanreviewed` (future LuCI gate).
- State module staging comments are now transport-aware: JSON-RPC says
  "staged in rpcd session", SSH says "review with `uci changes`".

### Fixed

- Proxy now marks connection unhealthy on any transport error, triggering
  automatic re-initialization by Salt.
- Fixed `_ensure_rpcd_timeout` referencing stale package name after
  extension rename.

### Security

- Fixed shell injection vulnerability in SSH proxy `ubus call` argument
  escaping.

## 0.2.5 (2026-03-01)

### Fixed

- Mark proxy unhealthy on transport errors: `call()` and `ping()` set
  `DETAILS["initialized"] = False` on any exception, so `alive()` triggers
  reconnection. Lightened SSH `ping()` to use `ubus call session list`
  instead of full `system board` call.

## 0.2.4 (2026-03-01)

### Added

- Pillar defaults and guards: progressive defaults for proxy init
  (only `host` and `password` required), OpenWrt-aware values for port,
  SSL, username, timeouts.
- Package support tiers analysis document.

## 0.2.3 (2026-03-01)

### Changed

- Renamed JSON-RPC proxy virtualname from `saltext_ubus` to
  `saltext_ubus_jsonrpc` for symmetry with `saltext_ubus_ssh`.
- Renamed system user from `salt` to `salt-agent` on OpenWrt device.

### Added

- `luci-app-salt-openwrt` LuCI package for web-based agent mode
  configuration.

### Security

- Fixed shell injection in SSH proxy ubus call argument construction.

## 0.2.2 (2026-02-28)

### Breaking changes

- Renamed extension from `saltext-uci` to `saltext-ubus`. Package name,
  import paths, and virtualnames changed.

### Added

- Shared ubus operations module (`utils/ubus_ops.py`): dependency
  injection via `call` parameter, all adapters delegate business logic here.
- `salt-openwrt` opkg package with agent mode enforcement via
  `/etc/config/salt-openwrt` (enabled, mode, rollback_timeout).
- ADR-001: device-controlled agent mode via UCI config.
- Mermaid diagram support in Sphinx docs with `managed()` sequence diagrams.
- Transport-aware staging in manual mode (SSH vs JSON-RPC).

## 0.2.1 (2026-02-28)

### Added

- SSH proxy module (`proxy/uci_ssh.py`): manages OpenWrt devices by running
  `ubus call` over SSH, returning the same structured JSON as JSON-RPC.
- SSH execution module (`modules/uci_ssh.py`): full UCI CRUD, apply/confirm
  rollback, system info -- delegates to SSH proxy's `call()`.
- Local execution module (`modules/uci_local.py`): runs `ubus call` via
  subprocess for devices with Python3, managed via salt-ssh thin tarball.
- SSH runner utility (`utils/ssh.py`): `SshRunner` class for subprocess-based
  SSH command execution with `BatchMode=yes` and configurable `ssh_options`.
- ADR-000: documents the decision to use ubus as the unified device interface
  across all transports (HTTP, SSH, local subprocess).
- Unit tests for all new modules (84 new tests, 179 total).

## 0.2.0 (2026-02-27)

### Changed

- Renamed proxy virtualname from `saltext_ubus` to `saltext_ubus_jsonrpc` for
  symmetry with `saltext_ubus_ssh`.
- Renamed module files from `*_mod.py` to match Salt conventions.
- Added `__virtual__` proxytype guard to execution modules.

### Added

- `commit()` and `state()` functions in the execution module.
- Type mismatch guard in the state module's diff phase.
- Grains unit tests.

## 0.1.0 (2026-02-25)


### Added

- Initial project scaffold from salt-extension-copier v0.8.0 with execution module, state module, test structure, CI workflows, and documentation setup.
