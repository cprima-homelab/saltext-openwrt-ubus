# salt-agent-ubus

OpenWrt `.ipk` package that prepares a device for Salt management via
the ubus JSON-RPC API. No cross-compilation or OpenWrt SDK required --
the package contains only config files and shell scripts.

## What it does

On install the package:

1. Creates a system user `salt` (uid 1000) with a locked password
2. Adds an rpcd login entry using `$p$salt` (verify against `/etc/shadow`)
3. Installs an rpcd ACL file granting scoped access to ubus objects

After install you must set a password for the salt user:

```sh
ssh root@<host> 'passwd salt'
```

The salt user can then authenticate via JSON-RPC at `https://<host>/ubus`
and call ubus methods within the granted ACL scope.

## ACL scope

The ACL group `saltext-ubus` grants access to:

| Category | Objects | Methods |
|----------|---------|---------|
| UCI | `uci` | configs, get, state, changes, add, set, delete, rename, order, commit, revert, apply, confirm, rollback, reload_config |
| System | `system` | board, info |
| Network | `network`, `network.device`, `network.interface`, `network.interface.*` | dump, status, get_proto_handlers |
| LuCI RPC | `luci-rpc` | getBoardJSON, getNetworkDevices, getDHCPLeases, getHostHints, getWirelessDevices |
| Session | `session` | access, login |

UCI package scope is currently set to `*` (all packages). See
[ROADMAP.md](ROADMAP.md) for the plan to tighten this.

The `luci-rpc` methods require `rpcd-mod-luci`, which ships with any
standard LuCI installation. On headless devices without LuCI those
methods are unavailable; core functionality is unaffected.

## Dependencies

- `rpcd` -- ubus RPC daemon (standard on OpenWrt)
- `uhttpd-mod-ubus` -- exposes ubus over HTTP/HTTPS (standard with LuCI)

## Building

```sh
./build.sh salt-agent-ubus
```

Creates `build/salt-agent-ubus_0.1.0-1_all.ipk`.

Or using [just](https://github.com/casey/just):

```sh
just build
```

The `.ipk` is a gzipped tar archive containing `debian-binary`,
`control.tar.gz`, and `data.tar.gz`. No OpenWrt SDK or buildroot needed.

## Install

```sh
scp build/salt-agent-ubus_0.1.0-1_all.ipk root@<host>:/tmp/
ssh root@<host> 'opkg install /tmp/salt-agent-ubus_0.1.0-1_all.ipk'
ssh root@<host> 'passwd salt'
```

Or with just:

```sh
just install
just passwd
```

## Uninstall

```sh
ssh root@<host> 'opkg remove salt-agent-ubus'
```

### What gets removed

- ACL file `/usr/share/rpcd/acl.d/salt-agent-ubus.json`
- rpcd login entry for `salt` (UCI section deleted, rpcd restarted)

### What is intentionally kept

- System user `salt` in `/etc/passwd`, `/etc/shadow`, `/etc/group`
- Home directory `/home/salt`
- The password set via `passwd salt`
- Any UCI changes the salt user made via the API

Removing system users can break file ownership. To fully clean up
manually after uninstall:

```sh
sed -i '/^salt:/d' /etc/passwd /etc/shadow /etc/group
rm -rf /home/salt
```

## Justfile recipes

| Recipe | Description |
|--------|-------------|
| `just build` | Build the .ipk |
| `just install` | Build, upload, and install on target |
| `just remove` | Remove package from target |
| `just reinstall` | Remove and reinstall |
| `just passwd` | Set salt user password (interactive) |
| `just status` | Show package, ACL, rpcd login, and user state |
| `just test-login` | Test JSON-RPC login (needs `AUSTRU_PASSWORD` env var) |
| `just clean` | Remove build artifacts |

Override the target host: `just host=myrouter install`

## Directory structure

```
├── packages/
│   └── salt-agent-ubus/
│       ├── Makefile                        ← OpenWrt SDK Makefile
│       ├── files/
│       │   └── usr/share/rpcd/acl.d/
│       │       └── salt-agent-ubus.json    ← rpcd ACL definitions
│       └── CONTROL/
│           ├── control                     ← package metadata
│           ├── postinst                    ← creates user + rpcd login
│           └── postrm                      ← removes rpcd login
├── build/                                  ← .ipk output (gitignored)
├── build.sh                                ← assembles .ipk without SDK
├── justfile                                ← task runner recipes
├── ROADMAP.md                              ← package versioning roadmap
└── README.md
```

## Notes

- Two build paths exist side by side:
  - `build.sh` -- assembles `.ipk` directly with tar/gzip. No SDK needed.
    Good for development and GitHub Releases.
  - `Makefile` -- OpenWrt buildroot format for SDK builds. Required for
    official package feeds, `opkg update` discovery, image integration,
    and package signing.
- The `files/` directory mirrors the target filesystem layout
  (`files/usr/share/rpcd/acl.d/` installs to `/usr/share/rpcd/acl.d/`).
  Both build paths use this directly -- no path remapping.
- The rpcd password `$p$salt` tells rpcd to verify the salt user's
  credentials against `/etc/shadow`. The password must be set separately.
- `network.interface.*` wildcard ACL matching confirmed working on
  OpenWrt 24.10.5. Older versions may require explicit interface names.
- Tested on OpenWrt 24.10.5 (ath79, Netgear WNDR3800).

## License

Apache-2.0
