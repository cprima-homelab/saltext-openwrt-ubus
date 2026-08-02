# saltext-uci

Monorepo for three Salt extensions managing OpenWrt UCI configuration:

| Package | PyPI | What it is |
|---|---|---|
| [`packages/uci`](packages/uci) | `saltext.uci` | Core: UCI data model, diffing, state logic. Transport-agnostic, no transport of its own. |
| [`packages/uci-ubus`](packages/uci-ubus) | `saltext.uci-ubus` | ubus transport (JSON-RPC and local-CLI). Depends on `saltext.uci`. |
| [`packages/uci-ssh`](packages/uci-ssh) | `saltext.uci-ssh` | SSH transport. Depends on `saltext.uci`. |

Install a transport package for the device access method you need; it
pulls in `saltext.uci` automatically. See each package's own README for
install and pillar configuration.

See `SOLUTION-DESIGN.md` (org root) for the architecture and naming
rationale behind this split.
