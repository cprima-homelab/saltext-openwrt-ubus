# 05 -- Minimal Scope for v0.1

## Problem

The plan documents (01-04) define the full vision. Before implementing, we need to pick the smallest useful slice grounded in the UCI and opkg taxonomy.

## UCI Package Taxonomy (austru router)

All UCI packages present on the router, mapped to owning opkg:

| UCI package | Owning opkg | Base build? | Section types |
|-------------|------------|-------------|---------------|
| `system` | `base-files` | Yes | anonymous `system`, named `timeserver 'ntp'` |
| `network` | `netifd` | Yes | named `interface`, named `globals`, anonymous `device`, anonymous `switch*` |
| `firewall` | `firewall4` | Yes | anonymous `defaults`, `zone`, `forwarding`, `rule` |
| `dhcp` | `dnsmasq` + `odhcpd-ipv6only` | Yes | anonymous `dnsmasq`, named `dhcp`, named `odhcpd`, anonymous `host` |
| `dropbear` | `dropbear` | Yes | anonymous `dropbear` |
| `wireless` | `wpad-basic-mbedtls` | Yes | named `wifi-device`, named `wifi-iface` |
| `uhttpd` | `uhttpd` (luci dep) | Yes | named `uhttpd 'main'`, named `cert 'defaults'` |
| `luci` | `luci` | Yes | named `core`, `extern`, `internal` |
| `rpcd` | `rpcd` | Yes | anonymous `rpcd`, named `login` |
| `ucitrack` | `uci` | Yes | anonymous (many types) |
| `ubootenv` | `uboot-envtools` | Yes | (empty) |
| `openvpn` | `openvpn` | No | named `openvpn` |
| `ddns` | `ddns-scripts` | No | named `ddns`, named `service` |
| `etherwake` | `etherwake` | No | named `etherwake`, anonymous `target` |
| `watchcat` | `watchcat` | No | anonymous `watchcat` |
| `attendedsysupgrade` | `attendedsysupgrade` | No | named `server`, `client` |

## Section Type Characteristics

| Type | Reference style | `uci set` safe? | Notes |
|------|----------------|-----------------|-------|
| Named section (`config type 'name'`) | `pkg.name.opt` | Yes | Stable path |
| Anonymous section (`config type`) | `pkg.@type[N]` | No, `uci add` always creates new | Needs walk + match |
| Scalar option (`option key 'val'`) | -- | Yes | `uci set` overwrites |
| List option (`list key 'val'`) | -- | No, `uci add_list` always appends | Needs dedup |

## Complexity Tiers

| Tier | UCI packages | What makes it easy/hard |
|------|-------------|------------------------|
| **Tier 1** | `network` (named interfaces), `wireless` | All named sections, scalar options, one list (`dns`) |
| **Tier 2** | `network` (full), `dhcp`, `system`, `dropbear` | Mix of named + anonymous sections |
| **Tier 3** | `firewall` | Mostly anonymous; match-on-field logic essential |

## Recommended First Slice: `network` Named Sections

### Why `network`

- Most essential package (no connectivity without it)
- Named interface sections (`lan`, `wan`, `loopback`) have stable paths
- Exercises both scalar options and list options (`dns`)
- Anonymous sections (`device`, `switch*`) can be deferred without losing usefulness

### In-scope sections and options

From the actual austru `uci export`:

```
config interface 'loopback'
    option device       'lo'
    option proto        'static'
    option ipaddr       '127.0.0.1'
    option netmask      '255.0.0.0'

config globals 'globals'            (empty on austru)

config interface 'wan'
    option device       'eth1'
    option proto        'static'
    option ipaddr       '192.168.16.99'
    option netmask      '255.255.255.0'
    option gateway      '192.168.16.254'
    list dns            '1.1.1.1'
    list dns            '1.0.0.1'

config interface 'lan'
    option device       'br-lan'
    option proto        'static'
    option ipaddr       '10.35.24.1'
    option netmask      '255.255.255.0'
```

### Deferred from `network`

```
config device               (anonymous -- bridge, MAC override)
config switch               (anonymous -- hardware switch)
config switch_vlan           (anonymous)
config switch_port           (anonymous, x3)
config interface 'vpn'      (depends on openvpn -- out of base scope)
config interface 'autan'    (depends on openvpn)
```

## Open Questions

- **Return shape for read functions**: Plain value (`"10.35.24.1"`) is natural for CLI use. Structured dict (`{"result": True, "value": "..."}`) is easier for state modules. Which first?
- **`get_all` parsing**: Return parsed dict or raw `uci show` text?
- **Tier 2 ordering**: After named `network` sections, which package next -- `system` (simple but anonymous), `wireless` (named but has secrets), or `dhcp` (mixed)?
