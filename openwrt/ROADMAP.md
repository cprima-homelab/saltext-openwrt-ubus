# salt-agent-ubus Package Roadmap

## v0.1.0

First installable package. Creates the salt user, rpcd login, and ACL
file. Enough to authenticate via JSON-RPC and explore the ubus API.

- [x] System user `salt` (uid 1000) created in postinst
- [x] rpcd login with `$p$salt` shadow-based authentication
- [x] ACL group `saltext-ubus` with scoped ubus method access
- [x] ACL covers UCI CRUD, system board/info, network interface state
- [x] ACL covers luci-rpc convenience methods (requires `rpcd-mod-luci`)
- [x] `uci` package scope set to `*` (all packages, intentionally broad for exploration)
- [x] postrm cleans up rpcd login, keeps system user
- [x] build.sh assembles .ipk without OpenWrt SDK/buildroot
- [x] Makefile for OpenWrt SDK integration
- [ ] Verify Makefile builds correctly in an OpenWrt SDK or ImageBuilder
  environment (the Makefile has only been used as reference so far;
  all tested .ipk files were built with build.sh)

### Uninstall behavior

`opkg remove salt-agent-ubus` removes the ACL file and the rpcd
login entry. The system user is intentionally **not** removed --
deleting users can break ownership of files created while the account
existed. The README and postrm output should clearly state what is and
is not cleaned up, and provide manual removal instructions.

- [ ] Document uninstall residuals in README (user, home dir, password)
- [ ] Document manual full-cleanup commands in README
- [ ] Print summary in postrm output listing what was kept and why

### Known limitations

- `uci: ["*"]` grants read/write to all UCI packages including
  security-sensitive ones (rpcd, dropbear, openvpn). Acceptable during
  exploration, must be tightened before production use.
- Password must be set manually after install (`passwd salt-agent`).
- No TLS certificate validation guidance -- relies on uhttpd's
  self-signed cert by default.

## v0.2.0

Rename system user from `salt` to `salt-agent` with dynamic uid
allocation in the system range (100-999).

- [x] System user renamed to `salt-agent`
- [x] Dynamic uid allocation (scan 999 down to 100, Debian-style)
- [x] Shell set to `/bin/false` (service account, no login needed)
- [x] rpcd login username changed to `salt-agent`
- [x] rpcd password changed to `$p$salt-agent`
- [x] postrm updated for `salt-agent` username
- [x] Version bump CONTROL/control and Makefile

### Next: Tighten ACL scope

- [ ] Scope `uci` read to packages actually used: `network`, `wireless`,
  `dhcp`, `firewall`, `system`, `openvpn` (and others as needed)
- [ ] Scope `uci` write to the same list
- [ ] Document which UCI packages each saltext-ubus Salt state touches
- [ ] Add `conffiles` to CONTROL so `/usr/share/rpcd/acl.d/salt-agent-ubus.json`
  survives upgrades if locally modified

## v0.3.0

Hardening and operational polish.

- [ ] Optional: generate random password during postinst, print to
  stdout (one-time display), avoid manual `passwd` step
- [ ] Add preinst script to check minimum OpenWrt version (21.02+)
- [ ] Add health-check script (`/usr/bin/salt-agent-check`) that verifies
  rpcd login exists, shadow entry is not locked, ACL file is loaded
- [ ] Document TLS options: custom cert, ACME via uhttpd, or
  `px5g-wolfssl` for stronger self-signed certs

## v1.0.0

Production-ready package with stable ACL contract.

- [ ] ACL scope locked to documented UCI packages only
- [ ] ACL file versioned with a comment header for change tracking
- [ ] Tested on OpenWrt 23.05 and 24.10
- [ ] Integration test: install package, set password, verify JSON-RPC
  login and a UCI get/set/apply cycle from a Salt master
- [ ] Published to a package feed or documented `opkg` custom feed setup

## salt-baseline (future package)

Baseline configuration for Salt-managed devices.

- [ ] NTP server and timezone defaults
- [ ] DNS upstream configuration
- [ ] Syslog remote forwarding
- [ ] SSH hardening (disable password auth for root, key-only)
- [ ] Depends on `salt-agent-ubus`

## Notes

- `network.interface.*` wildcard ACL matching confirmed working on
  OpenWrt 24.10.5. Older versions may require explicit interface names.
- `luci-rpc` methods (getBoardJSON, getNetworkDevices, etc.) require
  `rpcd-mod-luci`, which ships with any standard LuCI installation.
  On headless devices these methods are unavailable but core
  functionality is unaffected.
- The `.ipk` format is a gzipped tar (not ar), matching OpenWrt's
  `ipkg-build` output.
