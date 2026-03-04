# 02 -- Config Reader (not yet implemented)

> Last reviewed against: v0.4.0

## Goal

Read a running OpenWrt device's UCI configuration via ubus and generate
Salt pillar YAML, so operators do not have to hand-translate config when
onboarding a router into Salt management.

## Status

Not started. The execution module can already read full config via
`openwrt_ubus.get(config)`, but there is no pillar-generation output
formatter.

## TODO

- [ ] Add `openwrt_ubus.dump(config, format="pillar")` execution module
      function that reads live config and returns pillar-ready YAML
- [ ] Handle secrets: replace known sensitive fields (password, key, psk,
      secret, token) with Jinja2 pillar references
- [ ] Add `openwrt_ubus.dump_all(format="pillar")` to iterate all configs
- [ ] Optional: diff function to compare live config against declared pillar

## Design Notes

- Use `openwrt_ubus.get(config)` as the data source (ubus, not `uci show`)
- Transform the returned dict into the pillar YAML structure used by the
  state module (`uci:` -> `config:` -> `section:` -> `{options}`)
- Anonymous sections: emit `_match`/`_items` pillar syntax for
  multi-instance types; use singleton `_type` for single-instance types
- No standalone CLI; the execution module function is sufficient
  (`salt 'austru' openwrt_ubus.dump network format=pillar`)
