# ubus Object Inventory (austru)

Complete list of ubus objects available on austru (OpenWrt 24.10.5,
Netgear WNDR3800, LuCI installed). Captured via `list *`.

## Objects by Category

### System

| Object     | Key Methods                        | Notes                        |
|------------|------------------------------------|------------------------------|
| `system`   | `board`, `info`                    | Device facts, memory, uptime |
| `log`      | (message log access)               |                              |
| `rc`       | `list`                             | Init script status           |
| `service`  | `list`, `set`, `add`, `delete`     | procd service management     |
| `rpc-sys`  | `upgrade_start`, `packagelist`     | System operations            |

### Network

| Object                     | Key Methods                | Notes                          |
|----------------------------|----------------------------|--------------------------------|
| `network`                  | `get_proto_handlers`       | Available protocol types       |
| `network.device`           | `status`                   | Per-device L2 state            |
| `network.interface`        | `dump`                     | All interfaces summary         |
| `network.interface.<name>` | `status`, `up`, `down`     | Per-interface control          |
| `network.wireless`         | (wireless state)           |                                |
| `network.rrdns`            | `lookup`                   | Reverse DNS                    |

Dynamic objects: `network.interface.lan`, `.wan`, `.loopback`, `.vpn`, `.autan`
are created from UCI `network` config.

### Configuration (UCI)

| Object | Key Methods                                                    |
|--------|----------------------------------------------------------------|
| `uci`  | `get`, `set`, `add`, `delete`, `rename`, `order`              |
|        | `changes`, `commit`, `revert`                                  |
|        | `apply` (with rollback), `confirm`, `rollback`, `reload_config`|
|        | `configs`, `state`                                             |

### LuCI RPC

| Object     | Key Methods                                                      |
|------------|------------------------------------------------------------------|
| `luci`     | `getFeatures`, `getConntrackList`, `getRealtimeStats`,           |
|            | `getProcessList`, `getLEDs`, `getTimezones`, `getUSBDevices`,    |
|            | `getBlockDevices`, `getBuiltinEthernetPorts`, `getMountPoints`,  |
|            | `setInitAction`, `getSwconfigFeatures`, `getSwconfigPortState`   |
| `luci-rpc` | `getBoardJSON`, `getHostHints`, `getNetworkDevices`,             |
|            | `getWirelessDevices`, `getDHCPLeases`, `getDUIDHints`            |
| `luci.ddns`| `get_services_status`, `get_ddns_state`, `get_env`               |

### WiFi

| Object                | Purpose                                          |
|-----------------------|--------------------------------------------------|
| `hostapd`             | Global hostapd control (reload, apsta_state)     |
| `hostapd-auth`        | Authentication events                            |
| `hostapd.phy0-ap0`    | 5GHz AP instance                                 |
| `hostapd.phy1-ap0`    | 2.4GHz AP instance                               |
| `wpa_supplicant`      | WPA client (if used)                             |
| `iwinfo`              | Wireless info: assoclist, scan, freqlist, etc.   |

### DNS

| Object        | Purpose                  |
|---------------|--------------------------|
| `dnsmasq`     | `metrics`                |
| `dnsmasq.dns` | (DNS query interface)    |

### File System

| Object | Methods                                    |
|--------|--------------------------------------------|
| `file` | `read`, `write`, `list`, `stat`, `md5`     |
|        | `remove`, `exec`                           |

ACL-controlled: each path must be explicitly granted in ACL files.

### Hotplug Events

| Object              | Purpose                    |
|---------------------|----------------------------|
| `hotplug.dhcp`      | DHCP lease events          |
| `hotplug.iface`     | Interface up/down events   |
| `hotplug.neigh`     | Neighbor table changes     |
| `hotplug.net`       | Network device hotplug     |
| `hotplug.ntp`       | NTP sync events            |
| `hotplug.openvpn`   | OpenVPN tunnel events      |
| `hotplug.ieee80211` | WiFi radio events          |
| `hotplug.firmware`  | Firmware load events       |
| `hotplug.leds`      | LED trigger events         |
| `hotplug.tftp`      | TFTP events                |
| `hotplug.tty`       | Serial/TTY events          |

### Containers

| Object      | Methods                             |
|-------------|-------------------------------------|
| `container` | `list`, `set`, `add`, `delete`,     |
|             | `state`, `console_set`, `get_features` |

## Relevance for Salt Network Configuration

### Primary (v0.2 scope)

- `uci.*` -- read/write UCI config (network, firewall, dhcp, wireless)
- `system.board` -- device grains (model, version, architecture)
- `system.info` -- runtime grains (memory, uptime, load)
- `network.interface dump` -- live interface state

### Secondary (future)

- `luci-rpc.getNetworkDevices` -- L2 device details with stats
- `luci-rpc.getDHCPLeases` -- active DHCP leases
- `luci-rpc.getHostHints` -- hostname/MAC/IP mappings
- `network.interface.<name> up/down` -- interface control
- `iwinfo` -- wireless client and scan data

### Out of scope

- `file.*` -- direct file access (use UCI instead)
- `container.*` -- LXC container management
- `hotplug.*` -- event subscriptions (not request/response)
- `hostapd.*` / `wpa_supplicant` -- low-level WiFi control
