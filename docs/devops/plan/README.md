# Development Plan

> Last reviewed against: v0.4.0

Design and planning documents for saltext-openwrt-ubus.

## Documents

| # | Document | Status | Summary |
|---|----------|--------|---------|
| 01 | [Salt Module Development](01-salt-module-development.md) | Done | Execution and state modules, transport adapters, idempotency, agent modes |
| 02 | [Config Reader](02-cli-config-reader.md) | Future | Read device config via ubus, generate pillar YAML for onboarding |
| 03 | [LuCI Integration](03-luci-integration.md) | Future | Make Salt-staged changes visible in LuCI for humanreviewed mode |
| 04 | [LLM Coding Policy](04-llm-coding-policy.md) | Done | AI pair programming conventions, code style, commit policy |
| 06 | [OpenWrt Config Layers](06-openwrt-config-layers.md) | Done | Full OpenWrt architecture stack: UCI, ubus, rpcd, uhttpd, procd |
| 07 | [Package Support Tiers](07-package-support-tiers.md) | Draft | Scope control: which UCI packages the state module should manage |
| 09 | [Proxy Module Architecture](09-proxy-module-architecture.md) | Done | Proxy minion pattern for Python-less targets, two proxy types |
| 10 | [JSON-RPC vs CLI](10-jsonrpc-vs-cli.md) | Done | Interface comparison: why ubus JSON-RPC over UCI CLI |
| 11 | [rpcd ACL Model](11-rpcd-acl-model.md) | Done | rpcd layers, session lifecycle, ACL structure, timeout mechanisms |
| 12 | [Static Data in Extensions](12-static-data-in-extensions.md) | Done | Where protocol constants, method names, and config belong |
| -- | [Roadmap](roadmap.md) | Done | Release history (v0.1--v0.3) and planned features |

## Related: Code Guides

Implementation details live in [`docs/devops/code/`](../code/):

| Code guide | Summary |
|------------|---------|
| [00-uci-runtime-behavior](../code/00-uci-runtime-behavior.md) | UCI output formats, netifd schema, captured from live router |
| [01-adapter-pattern](../code/01-adapter-pattern.md) | Three adapters, one virtualname, dependency injection via `_call` |
| [02-salt-coding-patterns](../code/02-salt-coding-patterns.md) | Salt dunders, DETAILS dict, proxy parameter injection, progressive defaults |
| [03-state-module-logic](../code/03-state-module-logic.md) | Partial diff, singleton & multi-instance resolution, rollback safety, agent modes |
| [04-ubus-jsonrpc-api](../code/04-ubus-jsonrpc-api.md) | Complete ubus JSON-RPC method signatures and response formats |
| [05-proxy-lifecycle](../code/05-proxy-lifecycle.md) | Session persistence, dead detection, rpcd timeout, error layers |
| [06-openwrt-device-packages](../code/06-openwrt-device-packages.md) | opkg packages: rpcd ACL, agent config, LuCI app, dual-sided architecture |
| [07-ubus-object-inventory](../code/07-ubus-object-inventory.md) | ubus objects available on austru by category |

## Cross-Cutting Considerations

- **Transport independence** -- all adapters use ubus, never the uci CLI (ADR-000)
- **Device-controlled behavior** -- agent mode set on the device, not the master (ADR-001)
- **Package scope** -- rpcd ACL currently grants `uci: ["*"]`; tier-based scope proposed in 07
- **Secret handling** -- pillar generator (02) needs to redact sensitive fields
