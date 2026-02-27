# Code: Scaling by UCI Package

How the source tree grows as we add support for more opkg packages.

## What stays generic

The execution module (`modules/saltext_uci_mod.py`) provides generic UCI
operations: `get`, `set_`, `delete`, `add_list`, `set_list`, `commit`.
These work for any UCI package unchanged and do not grow per-package.

The parser (`utils/uci_parser.py`) provides `parse_show` and `to_pillar`.
These handle any `uci show` output regardless of which package produced it.

## What grows per package

Schema declarations in `utils/packages/` are the primary scaling point.
Each opkg package that owns a UCI config file gets one Python file:

```
utils/packages/
    netifd.py       # network    (Tier 1, named sections)
    firewall4.py    # firewall   (Tier 3, mostly anonymous -- future)
    dnsmasq.py      # dhcp       (Tier 2, mixed -- future)
```

Each schema file declares:
- `UCI_PACKAGE` -- which `/etc/config/` file it maps to
- `OPKG` -- owning opkg package name
- `NAMED_SECTION_TYPES` -- section types with stable paths
- `ANONYMOUS_SECTION_TYPES` -- section types addressed as `@type[N]`
- `LIST_OPTIONS` -- options that are lists, keyed by section type
  (needed to disambiguate `uci show` output where a multi-word scalar
  looks identical to a list)

## States: one file for now, may split later

State functions live in `states/saltext_uci_mod.py`. For Tier 1 (named
sections only), a single `managed` state using `set_`/`delete` is
straightforward.

When Tier 2/3 support arrives (anonymous sections with walk+match logic),
the state file may warrant splitting per-package. That decision is
deferred until the complexity justifies it.

## Filename convention

The `saltext_uci_mod.py` naming comes from the `salt-extension-copier`
template (`{project_name}_mod.py`). Salt does not use the filename for
dispatch -- it uses `__virtualname__`. The repetitive path
`saltext/saltext_uci/modules/saltext_uci_mod.py` is a copier convention,
not a design choice.
