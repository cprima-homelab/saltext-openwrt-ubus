# Development Plan

Requirements and planning documents for saltext-uci.

## Documents

| # | Document | Status | Summary |
|---|----------|--------|---------|
| 01 | [Salt Module Development](01-salt-module-development.md) | Draft | Execution and state modules for UCI with idempotency |
| 02 | [CLI Config Reader](02-cli-config-reader.md) | Draft | Query routers and generate pillar/state data |
| 03 | [LuCI Integration](03-luci-integration.md) | Future | Snapshot history, change logbook, web dashboard |
| 04 | [LLM Coding Policy](04-llm-coding-policy.md) | Draft | Pair programming instructions and project conventions |
| 05 | [Minimal Scope](05-minimal-scope.md) | Draft | UCI taxonomy, complexity tiers, first implementation slice |
| 06 | [UCI Data Layers](06-uci-data-layers.md) | Done | Config file -> ubus JSON-RPC -> execution module transformation chain |

## Related: Code Guides

Implementation details for each plan item live in [`docs/devops/code/`](../code/):

| Code guide | Plan reference | Summary |
|------------|---------------|---------|
| [00-uci-runtime-behavior](../code/00-uci-runtime-behavior.md) | All | UCI output formats, netifd schema, captured from live router |
| [01-execution-module-network](../code/01-execution-module-network.md) | Plan 01 + 05 | Function signatures, test matrix, parsing notes for `network` named sections |

## Cross-Cutting Considerations

- **SSH key auth** -- assumed as primary access method; password SSH considered out of scope for now (see 01, Assumptions)
- **Package scope** -- a whitelist based on the standard OpenWrt build limits which UCI packages are covered (see 01, Package Scope)
- **Secret handling** -- options under discussion for how the config reader and snapshot system handle credentials (see 02, 03)

## Priority Order

1. **01 Salt Module Development** -- foundation for everything else
2. **04 LLM Coding Policy** -- encode conventions before writing module code
3. **02 CLI Config Reader** -- depends on the execution module's UCI parser
4. **03 LuCI Integration** -- forward-looking, depends on 01 and 02
