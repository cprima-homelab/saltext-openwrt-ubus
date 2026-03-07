# 02 -- Config Reader

> Last reviewed against: v0.5.0

## Goal

Read a running OpenWrt device's UCI configuration via ubus and generate
Salt pillar YAML, so operators do not have to hand-translate config when
onboarding a router into Salt management.

## Status

Implemented. Available as `openwrt_ubus.dump(config)` and
`openwrt_ubus.dump_all()` (also via `openwrt.dump` alias).

## Implemented

- [x] `openwrt_ubus.dump(config, redact=True)` -- reads live config,
      returns pillar-ready sections dict
- [x] `openwrt_ubus.dump_all(redact=True)` -- iterates all configs
- [x] Sensitive field redaction via Jinja2 pillar references
      (password, key, psk, secret, token, passphrase, credential)
- [x] Auto-detection of `_match` keys for multi-instance anonymous
      sections (prefers `name`, falls back to first unique option,
      tries composite keys of 2)

## Not implemented

- [ ] Diff function to compare live config against declared pillar

## Design Notes

- Data source: `openwrt_ubus.get(config)` (ubus, not `uci show`)
- Returns a Python dict (Salt renders as YAML in CLI output)
- Core logic in `utils/ubus_ops.py` (transport-agnostic)
- Named sections: strip `_name`, `_anonymous`, `_index`; keep `_type`
- Singleton anonymous: emit as `_<type>` with `_type` field
- Multi-instance anonymous: emit as `_<type>s` with `_match` and `_items`
- No standalone CLI; the execution module function is sufficient
  (`salt 'austru' openwrt_ubus.dump network`)
