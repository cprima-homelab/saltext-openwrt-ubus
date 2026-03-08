# 02 -- Config Reader

> Last reviewed against: v0.5.0

## Goal

Read a running OpenWrt device's UCI configuration via ubus and generate
Salt pillar YAML, so operators do not have to hand-translate config when
onboarding a router into Salt management.

## Status

Implemented. Available as `openwrt_ubus.config_export(config)` and
`openwrt_ubus.config_export_all()` (also via `openwrt.config_export` alias).

## Implemented

- [x] `openwrt_ubus.config_export(config, format="json")` -- reads live
      config, returns grouped sections dict (`format="pillar"` for
      Jinja2-redacted output)
- [x] `openwrt_ubus.config_export_all(format="json")` -- iterates all configs
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
  (`salt 'austru' openwrt_ubus.config_export network`)
