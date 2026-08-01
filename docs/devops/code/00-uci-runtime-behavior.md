# UCI Runtime Behavior (Captured from austru)

See also: [10-uci-data-model.md](10-uci-data-model.md) for the UCI data model
(section types, value types, naming patterns, scalar-vs-list ambiguity).

Observations from a live OpenWrt router (Netgear WNDR3800, netifd 2025.05.23).
These inform parsing and test fixture design.

## `uci show` Output Format

```
network.lan=interface                        # section type declaration
network.lan.device='br-lan'                  # scalar: pkg.section.option='value'
network.wan.dns='1.1.1.1' '1.0.0.1'         # list: space-separated, each single-quoted
network.@device[0]=device                    # anonymous section: @type[index]
network.@device[0].name='br-lan'             # anonymous section option
network.@switch_vlan[0].ports='0 1 2 3 5'    # scalar with spaces (NOT a list)
```

Key details:
- Values are always single-quoted in `uci show` output
- List values are space-separated on a single line, each quoted: `'val1' 'val2'`
- A scalar containing spaces (e.g., switch ports `'0 1 2 3 5'`) looks similar to a list but is a single quoted string
- There is no syntactic way to distinguish a multi-word scalar from a list in `uci show` output alone; the schema determines which is which
- Section type declaration has no quotes: `network.lan=interface`

## `uci get` Output Format

```sh
uci get network.lan.ipaddr
# stdout: 10.35.24.1
# retcode: 0

uci get network.wan.dns
# stdout: 1.1.1.1 1.0.0.1       (space-separated, NO quotes, single line)
# retcode: 0

uci get network.nonexistent
# stdout: (empty)
# stderr: uci: Entry not found
# retcode: 1
```

Key details:
- Scalars: bare value, no quotes
- Lists: space-separated on one line, no quotes
- Missing key: retcode 1, stderr message, empty stdout

## `uci export` vs `uci show`

| Aspect | `uci export` | `uci show` |
|--------|-------------|------------|
| Format | Block syntax (`config`, `option`, `list`) | Flat `pkg.section.option='value'` |
| List values | One `list` line per value | All values on one line, space-separated |
| Anonymous sections | `config type` (no index) | `pkg.@type[N]` with index |
| Section names | `config type 'name'` | `pkg.name=type` |
| Quoting | Single quotes around values | Single quotes around values |

## netifd Package Structure

netifd owns the `network` UCI package. Files shipped:

```
/sbin/netifd                          # daemon binary
/etc/init.d/network                   # procd init script
/lib/netifd/proto/dhcp.sh             # DHCP protocol handler
/lib/netifd/proto/dhcpv6.sh           # DHCPv6 protocol handler
/lib/netifd/proto/ppp.sh              # PPP protocol handler (from ppp opkg)
/lib/network/config.sh                # shell helper library
```

### Schema from init script (`uci_validate_section` calls)

The init script validates these section types:

| Section type | Options (from validate functions) |
|-------------|----------------------------------|
| `route` | `interface:string`, `target:cidr4`, `netmask:netmask4`, `gateway:ip4addr`, `metric:uinteger`, `mtu:uinteger`, `table` |
| `route6` | `interface:string`, `target:cidr6`, `gateway:ip6addr`, `metric:uinteger`, `mtu:uinteger`, `table` |
| `rule` | `in`, `out`, `src:cidr4`, `dest:cidr4`, `tos`, `mark`, `invert:bool`, `lookup`, `goto`, `action` |
| `rule6` | (same as rule but cidr6) |
| `switch` | `name:string`, `enable:bool`, `enable_vlan:bool`, `reset:bool` |
| `switch_vlan` | `device:string`, `vlan:uinteger`, `ports:list(ports)` |

Note: `interface` section options are NOT validated in the init script -- they are handled internally by the netifd binary. The `proto` option determines which protocol handler's options apply (e.g., `dhcp.sh` adds `ipaddr`, `hostname`, `clientid`, etc.).

### Protocol handler options (from `proto_config_add_*` calls)

**`proto=dhcp`** (from `/lib/netifd/proto/dhcp.sh`):
`ipaddr`, `hostname`, `clientid`, `vendorid`, `broadcast:bool`, `norelease:bool`, `reqopts:list`, `defaultreqopts:bool`, `iface6rd`, `sendopts:list`, `delegate`, `zone6rd`, `zone`, `mtu6rd`, `customroutes`, `classlessroute`

**`proto=static`** (built into netifd binary):
`ipaddr`, `netmask`, `gateway`, `broadcast`, `dns:list`, `metric`, `ip6addr`, `ip6gw`, `ip6prefix`

## Section Types on austru Router

### Named sections (stable paths)

| Path | Type | Options |
|------|------|---------|
| `network.loopback` | `interface` | `device`, `proto`, `ipaddr`, `netmask` |
| `network.globals` | `globals` | (empty) |
| `network.wan` | `interface` | `device`, `proto`, `ipaddr`, `netmask`, `gateway`, `dns` (list) |
| `network.lan` | `interface` | `device`, `proto`, `ipaddr`, `netmask` |
| `network.vpn` | `interface` | `proto`, `device` |
| `network.autan` | `interface` | `proto`, `device` |

### Anonymous sections (unstable indices)

| Path pattern | Type | Count | Options |
|-------------|------|-------|---------|
| `network.@device[N]` | `device` | 2 | `name`, `type`, `ports` / `name`, `macaddr` |
| `network.@switch[0]` | `switch` | 1 | `name`, `reset`, `enable_vlan`, `blinkrate` |
| `network.@switch_vlan[0]` | `switch_vlan` | 1 | `device`, `vlan`, `ports` |
| `network.@switch_port[N]` | `switch_port` | 3 | `device`, `port`, `led` |
