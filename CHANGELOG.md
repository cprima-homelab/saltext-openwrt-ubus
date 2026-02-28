The changelog format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

This project uses [Semantic Versioning](https://semver.org/) - MAJOR.MINOR.PATCH

# Changelog

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
