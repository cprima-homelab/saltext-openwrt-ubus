# Plan: UCI Data Layers and Transformation Chain

## Problem

UCI configuration data passes through multiple representations between
the persistent file on the router and the Salt execution module output.
Understanding each layer is essential for debugging, writing correct
state logic, and planning future adapters (SSH+CLI vs JSON-RPC).

## The Three Representations

### 1. Persisted config (`/etc/config/<package>`)

UCI's native text format. Keywords `config`, `option`, and `list`
define the structure. Section type and optional name follow `config`.

```
config timeserver 'ntp'
	list server '0.openwrt.pool.ntp.org'
	list server '1.openwrt.pool.ntp.org'
	list server '2.openwrt.pool.ntp.org'
	list server '3.openwrt.pool.ntp.org'
	list server 'time.cloudflare.com'
```

- `config <type> '<name>'` -- named section
- `config <type>` (no name) -- anonymous section
- `option <key> '<value>'` -- scalar option
- `list <key> '<value>'` (repeated) -- list option

### 2. ubus JSON-RPC response

The raw HTTP response from `uci.get` via uhttpd's JSON-RPC endpoint.

```
POST https://<host>/ubus
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "call",
  "params": ["<session>", "uci", "get", {"config": "system", "section": "ntp"}]
}
```

Response:

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": [
    0,
    {
      "values": {
        ".anonymous": false,
        ".type": "timeserver",
        ".name": "ntp",
        "server": [
          "0.openwrt.pool.ntp.org",
          "1.openwrt.pool.ntp.org",
          "2.openwrt.pool.ntp.org",
          "3.openwrt.pool.ntp.org",
          "time.cloudflare.com"
        ]
      }
    }
  ]
}
```

- `result[0]` is the ubus status code (0 = success)
- `result[1]["values"]` contains the section data
- Metadata keys use dot-prefix: `.type`, `.name`, `.anonymous`
- UCI `list` options become JSON arrays
- UCI `option` values become JSON strings

### 3. Salt execution module output

`saltext_ubus.get system ntp` returns:

```yaml
_anonymous: False
_name: ntp
_type: timeserver
server:
  - 0.openwrt.pool.ntp.org
  - 1.openwrt.pool.ntp.org
  - 2.openwrt.pool.ntp.org
  - 3.openwrt.pool.ntp.org
  - time.cloudflare.com
```

The execution module (`modules/ubus_jsonrpc.py`) applies two
transformations:

1. Unwraps `result[1]["values"]` into a flat dict
2. Remaps dot-prefixed metadata to underscore-prefixed:
   `.type` -> `_type`, `.name` -> `_name`, `.anonymous` -> `_anonymous`

Underscore prefix avoids collision with UCI option names (a UCI option
could theoretically be named `type`; the metadata `.type` is distinct).

## Transformation Summary

| Layer | Metadata format | List format | Wrapper |
|---|---|---|---|
| `/etc/config/*` | keywords (`config`, `option`, `list`) | repeated `list` lines | flat text |
| ubus JSON-RPC | dot-prefix (`.type`, `.name`, `.anonymous`) | JSON array | `result[1]["values"]` |
| execution module | underscore-prefix (`_type`, `_name`, `_anonymous`) | Python list | flat dict |

## Full config vs single section

When fetching a full package (`saltext_ubus.get system` with no section
argument), ubus returns all sections keyed by name:

```json
{
  "values": {
    "cfg01e48a": { ".anonymous": true, ".type": "system", ... },
    "ntp":       { ".anonymous": false, ".type": "timeserver", ... }
  }
}
```

Anonymous sections get auto-generated hex names (`cfg01e48a`). The
execution module transforms each section independently.

## Implications for the state module

- The state module (`states/saltext_ubus_mod.py`) compares pillar values
  against the execution module output (layer 3)
- `_type` is used to decide create-vs-modify: if a section doesn't
  exist, `_type` tells `uci.add` what type to create
- Keys starting with `_` are treated as metadata and skipped during
  diff (partial semantics)
- Singleton anonymous section lookup matches `_anonymous: true` and
  `_type` to find the one section of a given type

## Implications for future adapters

An SSH+CLI adapter would parse the text format (layer 1) or the output
of `uci show`/`uci export` instead of JSON-RPC. The execution module
interface (layer 3) must produce the same dict structure regardless of
transport, so the state module works unchanged.
