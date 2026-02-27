# ubus JSON-RPC API (Captured from austru)

Observations from a live OpenWrt 24.10.5 router (Netgear WNDR3800).
All examples use the `/ubus` endpoint over HTTPS with uhttpd.

## Authentication

Login returns a session token (300s TTL). All subsequent calls include the token.

```
POST https://<host>/ubus
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "call",
  "params": [
    "00000000000000000000000000000000",   // null session (for login only)
    "session", "login",
    {"username": "salt", "password": "<password>"}
  ]
}
```

Response (success):

```json
{
  "result": [
    0,
    {
      "ubus_rpc_session": "31736d560cc4389424d55bb042854f80",
      "timeout": 300,
      "expires": 299,
      "acls": { ... },
      "data": {"username": "salt"}
    }
  ]
}
```

Result code 0 = success. Result code 6 = UBUS_STATUS_PERMISSION_DENIED.

## JSON-RPC Methods

| Method   | Purpose                                 |
|----------|-----------------------------------------|
| `call`   | Invoke a ubus method on an object       |
| `list`   | List available ubus objects and methods |

## Available ubus Objects (austru)

```
container           hostapd.phy0-ap0    luci-rpc            network.interface.vpn
dnsmasq             hostapd.phy1-ap0    luci.ddns           network.interface.wan
dnsmasq.dns         hotplug.*           network             network.rrdns
file                iwinfo              network.device      network.wireless
hostapd             log                 network.interface    rc
hostapd-auth        luci                network.interface.*  rpc-sys
                                                            service
                                                            session
                                                            system
                                                            uci
                                                            wpa_supplicant
```

Per-interface objects (`network.interface.lan`, `.wan`, `.autan`, `.vpn`) are
created dynamically from UCI network config.

## UCI Object -- Full Method Signatures

From `list uci`:

| Method          | Parameters                                                  |
|-----------------|-------------------------------------------------------------|
| `configs`       | (none)                                                      |
| `get`           | config, section?, option?, type?, match?                    |
| `state`         | config, section?, option?, type?, match?                    |
| `add`           | config, type, name?, values?                                |
| `set`           | config, section, type?, match?, values                      |
| `delete`        | config, section, type?, match?, option?, options?           |
| `rename`        | config, section, option?, name                              |
| `order`         | config, sections[]                                          |
| `changes`       | config                                                      |
| `revert`        | config                                                      |
| `commit`        | config                                                      |
| `apply`         | rollback?, timeout?                                         |
| `confirm`       | (none)                                                      |
| `rollback`      | (none)                                                      |
| `reload_config` | (none)                                                      |

All methods also accept `ubus_rpc_session` as a parameter (rarely needed;
the session from the outer JSON-RPC envelope is used).

### uci.get -- Package Level

Request: `{"config": "network"}`

Returns all sections with metadata:

```json
{
  "values": {
    "lan": {
      ".anonymous": false,
      ".type": "interface",
      ".name": "lan",
      ".index": 5,
      "device": "br-lan",
      "proto": "static",
      "ipaddr": "10.35.24.1",
      "netmask": "255.255.255.0"
    },
    "cfg040f15": {
      ".anonymous": true,
      ".type": "device",
      ".name": "cfg040f15",
      ".index": 3,
      "name": "br-lan",
      "type": "bridge",
      "ports": ["eth0"]
    }
  }
}
```

Key differences from `uci show` CLI:
- **Lists are native JSON arrays** (no ambiguity with multi-word scalars)
- **Section metadata** (`.anonymous`, `.type`, `.name`, `.index`) is inline
- **Anonymous sections** use their internal config ID as key (e.g., `cfg040f15`)
- **Values are unquoted** (no single-quote wrapping)
- **Multi-word scalars stay as strings**: `"ports": "0 1 2 3 5"` (switch_vlan)
  vs `"ports": ["eth0"]` (device) -- the schema ambiguity is resolved by UCI itself

### uci.get -- Section Level

Request: `{"config": "network", "section": "lan"}`

```json
{
  "values": {
    ".anonymous": false,
    ".type": "interface",
    ".name": "lan",
    "device": "br-lan",
    "proto": "static",
    "ipaddr": "10.35.24.1",
    "netmask": "255.255.255.0"
  }
}
```

### uci.get -- Option Level

Request: `{"config": "network", "section": "wan", "option": "dns"}`

```json
{"value": ["1.1.1.1", "1.0.0.1"]}
```

For scalars the response uses `"value": "string"` (not an array).

### uci.set

Request: `{"config": "network", "section": "lan", "values": {"_test_key": "_test_value"}}`

Response: `[0]` (success, no body).

Changes are staged (not committed). Use `uci.changes` to inspect, `uci.commit`
to persist, or `uci.revert` to discard.

### uci.changes

Request: `{"config": "network"}`

```json
{
  "changes": [
    ["set", "lan", "_test_key", "_test_value"]
  ]
}
```

Each change is an array: `[operation, section, option?, value?]`.

### uci.apply with Rollback

The `apply` method supports a safe-apply pattern:

1. `uci.set` + `uci.commit` -- stage and persist changes
2. `uci.apply {"rollback": true, "timeout": 30}` -- apply with 30s rollback timer
3. Test connectivity
4. `uci.confirm` -- cancel the rollback timer (changes stick)
5. If `confirm` is not called within timeout, config auto-reverts

This is the same mechanism LuCI uses for safe network changes.

## System Object

### system.board

```json
{
  "kernel": "6.6.119",
  "hostname": "austru.rss78.ldk35.archam.de",
  "system": "Atheros AR7161 rev 2",
  "model": "Netgear WNDR3800",
  "board_name": "netgear,wndr3800",
  "rootfs_type": "squashfs",
  "release": {
    "distribution": "OpenWrt",
    "version": "24.10.5",
    "revision": "r29087-d9c5716d1d",
    "target": "ath79/generic",
    "description": "OpenWrt 24.10.5 r29087-d9c5716d1d"
  }
}
```

### system.info

```json
{
  "localtime": 1772160964,
  "uptime": 183748,
  "load": [5536, 5472, 1536],
  "memory": {
    "total": 124059648,
    "free": 36220928,
    "shared": 1421312,
    "buffered": 0,
    "available": 33476608,
    "cached": 42708992
  },
  "root": {"total": 5888, "free": 5564, "used": 324},
  "tmp":  {"total": 60576, "free": 59188, "used": 1388},
  "swap": {"total": 0, "free": 0}
}
```

## luci-rpc Object

### luci-rpc.getNetworkDevices

Returns per-device details including IPs, stats, flags, and carrier state:

```json
{
  "br-lan": {
    "name": "br-lan",
    "wireless": false,
    "up": true,
    "mtu": 1500,
    "ipaddrs": [{"address": "10.35.24.1", "netmask": "255.255.255.0"}],
    "stats": {"rx_bytes": ..., "tx_bytes": ..., ...},
    "flags": {"up": true, "broadcast": true, ...},
    "link": {"carrier": true, ...}
  }
}
```

Also available: `getHostHints`, `getDHCPLeases`, `getDUIDHints`,
`getWirelessDevices`, `getBoardJSON`.

## Error Codes

| Code     | Meaning                    | JSON-RPC layer |
|----------|----------------------------|----------------|
| `[0]`    | Success (ubus)             | result         |
| `[6]`    | Permission denied (ubus)   | result         |
| `-32002` | Access denied (rpcd ACL)   | error          |
| `-32600` | Invalid request            | error          |
