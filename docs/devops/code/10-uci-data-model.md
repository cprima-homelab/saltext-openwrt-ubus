# UCI Data Model Patterns

> Last reviewed against: v0.4.0

Reference for the UCI data model -- section types, value types, naming
patterns, and the scalar-vs-list ambiguity -- with real examples from
both devices (austru and autan).

For CLI output formats, see [00-uci-runtime-behavior.md](00-uci-runtime-behavior.md).
For how ubus returns this data as JSON, see [04-ubus-jsonrpc-api.md](04-ubus-jsonrpc-api.md).

Source material: `austru/austru-uci-export.txt` (601 lines, 18 packages)
and `autan/autan-uci-export.txt` (1561 lines, 25 packages) in the austru repo.


## 1. UCI structure

UCI organizes configuration as:

```
Package  ->  Section  ->  Option / List
```

Each package maps to a file under `/etc/config/`. A package contains
sections; each section has a type and optionally a name. Sections
contain options (scalar key-value pairs) and lists (multi-value keys).

```
package network                          # package = file /etc/config/network

config interface 'lan'                   # section: type=interface, name=lan
    option device 'br-lan'               # scalar option
    option proto 'static'
    option ipaddr '10.35.24.1'

config interface 'wan'                   # another section of same type
    option device 'eth1'
    list dns '1.1.1.1'                   # list option (one line per value)
    list dns '1.0.0.1'
```


## 2. Section types

### Named sections

Syntax: `config <type> '<name>'`

The name is stable and addressable: `network.lan`, `openvpn.austru_server`.
Named sections dominate in packages where the section identity matters.

Examples from both devices:

| Package | Section | Type |
|---------|---------|------|
| attendedsysupgrade | `'server'`, `'client'` | server, client |
| ddns | `'global'` | ddns |
| ddns | `'austru_ipv4'` (austru), `'inwx'` (autan) | service |
| dhcp | `'lan'`, `'wan'`, `'test'`, `'guest'`, `'work'` | dhcp |
| dhcp | `'odhcpd'` | odhcpd |
| etherwake | `'setup'` | etherwake |
| fail2ban | `'fail2ban'` (autan) | fail2ban |
| luci | `'main'`, `'flash_keep'`, `'languages'`, `'sauth'`, `'ccache'`, `'themes'`, `'apply'`, `'diag'` | core, extern, internal |
| network | `'loopback'`, `'lan'`, `'wan'`, `'vpn'`, `'autan'` (austru) | interface |
| network | `'globals'` | globals |
| nextdns | `'main'` (autan) | nextdns |
| openvpn | `'austru_server'`, `'autan_client'` (austru) | openvpn |
| system | `'ntp'` | timeserver |
| system | `'led_usb1'`, `'led_usb2'`, `'led_wan'`, `'led_esata'` (autan) | led |
| uhttpd | `'main'`, `'wol'`, `'wol1'` (autan) | uhttpd |
| uhttpd | `'defaults'` | cert |
| watchcat | `'wan_check'` (austru) | watchcat |
| wireless | `'radio0'`, `'radio1'` | wifi-device |
| wireless | `'default_radio0'`, `'default_radio1'` | wifi-iface |

### Anonymous sections

Syntax: `config <type>` (no name)

rpcd assigns an internal ID at parse time. In `uci show` output, these
appear as `pkg.@type[N]` with positional indices that can shift when
sections are added or removed.

**Singleton anonymous** -- exactly one section of a type per package.
These function like a global config block:

| Package | Type | Purpose |
|---------|------|---------|
| dhcp | dnsmasq | DNS/DHCP daemon settings |
| dropbear | dropbear | SSH daemon settings |
| firewall | defaults | Default policy (input/output/forward) |
| fstab | global | Mount behavior defaults (autan) |
| rpcd | rpcd | Daemon socket and timeout |
| samba | samba | Workgroup and share defaults (autan) |
| samba4 | samba | Samba4 global settings (autan) |
| system | system | Hostname, timezone, logging |
| ubootenv | ubootenv | Bootloader env offset (autan) |
| umdns | umdns | mDNS daemon settings (autan) |

**Multi-instance anonymous** -- variable count, order-dependent:

| Package | Type | austru count | autan count |
|---------|------|:------------:|:-----------:|
| adblock-fast | file_url | -- | 14 |
| dhcp | host | 5 | 33 |
| dhcp | domain | -- | 10 |
| etherwake | target | 1 | 2 |
| firewall | zone | 3 | 5 |
| firewall | forwarding | 5 | 6 |
| firewall | rule | 7 | 16 |
| firewall | redirect | -- | 8 |
| firewall | include | -- | 1 |
| fstab | mount | -- | 1 |
| network | device | 2 | 5 |
| network | switch_vlan | 1 | 2 |
| network | switch_port | 3 | -- |
| network | route | -- | 1 |
| rpcd | login | 1 | 1 |
| samba | sambashare | -- | 1 |
| samba4 | sambashare | -- | 1 |
| ucitrack | *(per-package)* | 16 | 16 |

### Mixed -- same type appears both named and anonymous

This is the trickiest pattern for tooling. Within a single package, the
same section type has some instances with names and some without.

**watchcat** (austru) -- one anonymous + one named:

```
config watchcat                          # anonymous
    option period '6h'
    option mode 'ping_reboot'
    option pinghosts '8.8.8.8'

config watchcat 'wan_check'              # named
    option mode 'ping_reboot'
    option period '900'
    option pinghosts '1.1.1.1'
```

**firewall** (austru) -- zone type is mostly anonymous but has one named:

```
config zone                              # anonymous
    option name 'lan'
    ...

config zone                              # anonymous
    option name 'wan'
    ...

config zone 'autan'                      # named
    option name 'autan'
    ...
```

Note: the `option name` inside the section is a firewall-level
display name, distinct from the UCI section name (the quoted string
after the type keyword).

**adblock-fast** (autan) -- config section is named, file_url sections
are anonymous:

```
config adblock-fast 'config'             # named (name = 'config')
    option enabled '1'
    ...

config file_url                          # anonymous
    option url 'https://...'
    ...
```


## 3. Value types

### Scalar option

```
option hostname 'austru.rss78.ldk35.archam.de'
option port '22'
option enabled '1'
option ipaddr '10.35.24.1'
```

Everything is a string at the UCI level. Numbers (`'22'`), booleans
(`'1'`/`'0'`), IP addresses (`'10.35.24.1'`) -- all stored as
single-quoted strings in `uci export` output. Type interpretation
is up to the consuming daemon.

### List option

```
list dns '1.1.1.1'                       # network.wan (austru)
list dns '1.0.0.1'

list server '0.openwrt.pool.ntp.org'     # system.ntp (both)
list server '1.openwrt.pool.ntp.org'

list tag 'homeoffice'                    # dhcp host (autan)
list tag 'ethernet'
```

Each value gets its own `list` line in `uci export`. ubus returns
these as JSON arrays. A list can have one element or many.

### The scalar-vs-list ambiguity

The same option name can be a scalar in one section type and a list in
another. There is no schema enforcement -- the section type determines
interpretation.

**`ports` -- scalar with spaces vs single-element list:**

```
# network package, switch_vlan section (austru)
config switch_vlan
    option ports '0 1 2 3 5'             # SCALAR -- space-separated port numbers

# network package, device section (austru)
config device
    option name 'br-lan'
    option type 'bridge'
    list ports 'eth0'                    # LIST -- single interface name
```

`uci show` renders both similarly:
```
network.@switch_vlan[0].ports='0 1 2 3 5'   # scalar (one quoted string)
network.@device[0].ports='eth0'              # list (happens to have one element)
```

Only `uci export` or `ubus call uci get` (which returns string vs
JSON array) can distinguish them.

**`mac` -- scalar vs list for the same logical field:**

```
# dhcp host on autan -- some use option, some use list
config host
    option mac '60:67:20:ED:4D:04'       # SCALAR

config host
    option name 'AtemMiniPro'
    list mac '7C:2E:0D:18:DE:0B'         # LIST (single element)
```

Both are valid. The dhcp daemon accepts either form for a single MAC.
When a host has multiple MACs (e.g., ethernet + wifi), only the list
form works.

**`icmp_type` -- scalar on one device, list on another:**

```
# firewall rule on austru
config rule
    option name 'Allow-Ping'
    option icmp_type 'echo-request'      # SCALAR

# firewall rule on autan
config rule
    option name 'Allow-Ping'
    list icmp_type 'echo-request'        # LIST (single element)
```

The firewall daemon treats a single-element list identically to a
scalar. This inconsistency arises from different LuCI versions or
manual editing producing different but equivalent configs.

**`proto` -- same package, different rules:**

```
# firewall on austru
config rule
    option name 'Allow-OpenVPN'
    option proto 'udp'                   # SCALAR

config rule
    option name 'Allow-SSH'
    list proto 'tcp'                     # LIST (single element)
```


## 4. Naming patterns

### ucitrack: type-as-identity

ucitrack is unique -- all sections are anonymous, and the section TYPE
carries the semantics (the package being tracked):

```
package ucitrack

config network                           # type = 'network' (the tracked package)
    option init 'network'
    list affects 'dhcp'

config firewall                          # type = 'firewall'
    option init 'firewall'
    list affects 'luci-splash'
    list affects 'qos'
    list affects 'miniupnpd'

config system                            # type = 'system'
    option init 'led'
```

This creates a naming collision: the type `network` in ucitrack refers
to the package, not the interface section type used within the network
package itself. Tooling that maps type-to-schema must be package-aware.

### Singleton anonymous as implicit global

Several packages use a single anonymous section as a global config
block. The type name often matches the package name or the daemon name:

```
package rpcd
config rpcd                              # type = package name
    option socket '/var/run/ubus/ubus.sock'
    option timeout '30'

package dropbear
config dropbear                          # type = package name
    option Port '22'

package system
config system                            # type = package name
    option hostname 'austru.rss78.ldk35.archam.de'
```

These are effectively singletons -- a second section of the same type
would be unexpected. rpcd `config login` is also anonymous but could
in principle support multiple users (currently one per device).

### The `option name` pattern

Many anonymous sections carry an `option name` that serves as a
human-readable identifier but is NOT the UCI section name:

```
config zone                              # anonymous -- no UCI name
    option name 'wan'                    # firewall display name
    option input 'REJECT'

config host                              # anonymous -- no UCI name
    option name 'boreas'                 # hostname for DHCP reservation
    option ip '10.35.24.2'
```

The `option name` is visible in LuCI and referenced by firewall rules,
but UCI operations must use `@type[N]` indexing to address these sections.


## 5. Package inventory

All packages observed across both devices with their section type
characteristics.

### Packages on both devices

| Package | Section types | Naming | Notes |
|---------|--------------|--------|-------|
| attendedsysupgrade | server, client | all named | |
| ddns | ddns, service | all named | |
| dhcp | dnsmasq, dhcp, odhcpd, host, domain | mixed | dnsmasq=anon singleton, dhcp/odhcpd=named, host/domain=anon multi |
| dropbear | dropbear | anon singleton | |
| etherwake | etherwake, target | mixed | setup=named, target=anon multi |
| firewall | defaults, zone, forwarding, rule, redirect, include | mostly anon | defaults=singleton; austru has one named zone |
| luci | core, extern, internal | all named | |
| luci-opkg | core, extern, internal | all named | subset of luci |
| network | interface, globals, device, switch, switch_vlan, switch_port, route | mixed | interfaces/globals=named, devices/switch*=anon |
| openvpn | openvpn | all named | |
| openvpn_recipes | openvpn_recipe | all named | empty on austru |
| rpcd | rpcd, login | all anon | rpcd=singleton, login=effectively singleton |
| system | system, timeserver, led | mixed | system=anon singleton, ntp/led=named |
| ubootenv | ubootenv | anon singleton | empty on austru |
| ucitrack | *(per-package types)* | all anon | type=tracked package name |
| uhttpd | uhttpd, cert | all named | |
| wireless | wifi-device, wifi-iface | all named | |

### Packages only on austru

| Package | Section types | Naming | Notes |
|---------|--------------|--------|-------|
| watchcat | watchcat | mixed | one anon + one named ('wan_check') |

### Packages only on autan

| Package | Section types | Naming | Notes |
|---------|--------------|--------|-------|
| adblock-fast | adblock-fast, file_url | mixed | config=named, file_url=anon multi (14) |
| fail2ban | fail2ban | named singleton | |
| fstab | global, mount | all anon | global=singleton, mount=multi |
| nextdns | nextdns | named singleton | |
| samba | samba, sambashare | all anon | samba=singleton, sambashare=multi |
| samba4 | samba, sambashare | all anon | samba=singleton, sambashare=multi |
| ucitrack-opkg | *(per-package types)* | all anon | duplicate of ucitrack (opkg-managed copy) |
| umdns | umdns | anon singleton | |


## 6. Cross-references

- [00-uci-runtime-behavior.md](00-uci-runtime-behavior.md) -- CLI output formats, `uci show` vs `uci export` vs `uci get`
- [04-ubus-jsonrpc-api.md](04-ubus-jsonrpc-api.md) -- how ubus returns UCI data as JSON (string vs array)
- [09-ubus-system-architecture.md](09-ubus-system-architecture.md) -- ubus call paths and rpcd authentication
