# 07 -- Package Support Tiers

> Last reviewed against: v0.3.0

## Preface

This document addresses a fundamental gap in saltext-openwrt-ubus: the extension
will manage any UCI package without question. There is no mechanism to
declare which packages have been validated, tested, or are even
structurally compatible with the current state module.

The execution modules (`ubus_jsonrpc.py`, `uci_ssh.py`, `uci_local.py`)
are transport adapters -- they pass the `config` parameter straight
through to `ubus_ops.py` which passes it straight to the ubus API. A
state file targeting `dropbear`, `rpcd`, or `uhttpd` executes with the
same confidence as one targeting `network`, even though the extension has
never been tested against those packages and some of them contain
security-sensitive configuration (SSH keys, authentication credentials,
TLS certificates).

By design, the extension code does not grow per-package. Adding support
for a new UCI package requires zero code changes -- the operator writes
pillar and state SLS files, and `managed()` handles the rest generically.
Only if per-package schema or tier enforcement is added would the
extension itself gain per-package files (see alternatives below).

This gap exists at every layer:

- **Python code**: No filtering of the `config` parameter anywhere in
  the call chain -- not in the execution modules, not in `ubus_ops.py`,
  not in the `managed()` state function.
- **rpcd ACL**: The ACL file uses `"uci": ["*"]` for both read and
  write, granting unrestricted access to all UCI packages on the device.
- **Pillar/state layer**: The operator controls what gets managed by
  choosing which states to apply, but a typo or copy-paste error has
  no safety net.

The existing agent mode system (`audit` / `autoverified` / `oneshot`)
controls *how aggressively* Salt acts on a device, but says nothing
about *which packages* are in scope. A device in `oneshot` mode will
happily apply
changes to any UCI package, including ones that could lock the operator
out of the device.

This document proposes three alternatives for adding a second dimension
-- **support tiers** -- that declares which UCI packages and section
types each version of saltext-openwrt-ubus has been validated for. The two
dimensions are orthogonal and use non-clashing vocabulary:

- **Mode** (existing, device-controlled): audit / autoverified /
  humanreviewed / oneshot -- answers "how aggressively does Salt act
  on this device?"
- **Tier** (proposed, code-controlled): stable / experimental --
  answers "what has this version of the extension been validated for?"

## Problem

### The convenience-vs-safety tension

UCI is a uniform configuration system. Every UCI package follows the
same structure: packages contain sections, sections contain options.
The saltext-openwrt-ubus execution module exploits this uniformity -- a single
`get()` / `set_()` / `commit()` implementation works for every package.

This uniformity is both the extension's strength and its risk:

- **Convenient**: One `managed()` state function handles network, dhcp,
  system, firewall, wireless -- anything UCI touches.
- **Scary**: The same function will also modify `dropbear` (SSH daemon
  config), `rpcd` (the authentication system the extension itself uses),
  or `uhttpd` (the HTTPS server that carries the JSON-RPC traffic).

A single state file with a wrong `config:` value can brick a remote
device with no physical access for recovery.

### The capability constraint

Beyond safety, there is a capability constraint. The `managed()` state
currently supports:

| Section addressing | Status | Mechanism |
|--------------------|--------|-----------|
| Named sections (`config type 'name'`) | Supported | Direct `uci set pkg.name.opt=val` |
| Singleton anonymous sections | Supported | `_resolve_sections()` finds the one section of a given type |
| Multiple anonymous sections | **Not supported** | Requires walk+match logic, not yet implemented |

This means packages like `firewall` (mostly anonymous sections: rules,
zones, forwardings) cannot be fully managed by the current state module,
regardless of how much testing is done. Declaring support tiers makes
this limitation explicit rather than leaving it as a runtime surprise.

### What exists in planning docs

Several existing documents touch on this problem without resolving it:

- **`01-salt-module-development.md`** (section "Package Scope"): lists
  priority-ranked UCI packages on the target build. Notes that the
  module does not whitelist packages -- the rpcd ACL on the device
  grants `uci: ["*"]`, so any config package is manageable.

- **`openwrt/ROADMAP.md`** (v0.2.0): "Scope `uci` read/write to
  packages actually used." (v1.0.0): "ACL scope locked to documented
  UCI packages only."

This document synthesizes these threads into concrete alternatives.

## UCI Package Landscape

For reference, these are the UCI-relevant packages on the target
platform (OpenWrt 24.10.5, Netgear WNDR3800), mapped to the
complexity tier:

| UCI package | Owning opkg | Tier | Section types | Security-sensitive |
|-------------|-------------|------|---------------|-------------------|
| `network` | `netifd` | 1/2 | named `interface`, `globals`; anon `device`, `switch*` | No |
| `wireless` | `wpad-basic-mbedtls` | 1 | named `wifi-device`, `wifi-iface` | Moderate (PSK) |
| `system` | `base-files` | 2 | anon singleton `system`; named `ntp` | No |
| `dhcp` | `dnsmasq` + `odhcpd` | 2 | anon singleton `dnsmasq`; named `dhcp`, `odhcpd`; anon `host` | No |
| `dropbear` | `dropbear` | 2 | anon singleton `dropbear` | **Yes** (SSH daemon) |
| `firewall` | `firewall4` | 3 | anon `defaults`, `zone`, `forwarding`, `rule` | No |
| `uhttpd` | `uhttpd` | 1 | named `main`, `defaults` | **Yes** (HTTPS/TLS) |
| `rpcd` | `rpcd` | 2 | anon `rpcd`; named `login` | **Yes** (auth/ACL) |
| `luci` | `luci` | 1 | named `core`, `extern`, `internal` | No |
| `openvpn` | `openvpn` | 1 | named instances | **Yes** (VPN keys) |

Tier 1 packages (all named sections) are structurally compatible with
the current state module. Tier 2 packages work for their named and
singleton anonymous sections. Tier 3 packages require the multi-instance anonymous
section support that is not yet implemented.

## The Two Dimensions

### Mode (existing)

Controlled by the device operator via `/etc/config/salt-openwrt`.
Implemented in `_get_agent_mode()` in the state module. Determines
how the extension behaves:

| Mode | Reads | Diffs | Stages | Applies | Confirms |
|------|-------|-------|--------|---------|----------|
| `audit` | yes | yes | no | no | no |
| `autoverified` | yes | yes | yes | no | no |
| `humanreviewed` | yes | yes | yes | no | no |
| `oneshot` | yes | yes | yes | yes | yes |

### Tier (proposed)

Controlled by the extension code, ships with each release. Determines
whether the extension should attempt to manage a given package:

| Tier | Meaning |
|------|---------|
| `stable` | Fully tested, all relevant section types handled |
| `experimental` | Works for some section types, may have edge cases |
| (unregistered) | Unknown package -- refuse by default |

### Orthogonality

The two dimensions combine as a matrix. Mode controls behavior, tier
controls scope:

```
              audit       autoverified   humanreviewed   oneshot
stable        observe     stage          stage           apply
experimental  observe*    stage*         stage*          apply*    (* opt-in)
unregistered  REFUSE      REFUSE         REFUSE          REFUSE
```

An unregistered package is refused regardless of mode. An experimental
package requires explicit opt-in (state parameter or pillar flag)
regardless of mode. Mode and tier never conflict because they answer
different questions.

## Where enforcement happens

The gate belongs in `managed()` in `states/saltext_ubus.py`, inserted
after the existing mode check (step 1) and before the first ubus read
(step 3). This is the only function that makes changes. The execution
module functions (`get`, `set_`, etc.) remain unrestricted -- an
operator can always call `openwrt_ubus.get("dropbear")` directly for
inspection.

```python
def managed(name, config, sections, apply_rollback=90,
            revert_pending=False, allow_experimental=False):
    # 1. Check agent mode  (existing)
    # 2. Check support tier (NEW -- gate inserted here)
    # 3. Check for pending deltas
    # 4. Read current state
    # ...
```

## Three Alternatives

All three use the same taxonomy (mode + tier) and the same enforcement
point (`managed()`). They differ in how the tier registry is structured.

---

### Alternative A: Per-package module files with schema

Build a `utils/packages/` directory. Each UCI package gets a
Python file declaring its tier, named section types, anonymous section
types, and list options. The registry serves dual purpose: tier
whitelist and schema metadata for future features.

#### File structure

```
src/saltext/openwrt_ubus/utils/
    packages/
        __init__.py          # auto-discovers package modules
        _registry.py         # lookup functions
        netifd.py            # network
        base_files.py        # system
        dnsmasq.py           # dhcp
        firewall4.py         # firewall (experimental)
        wpad.py              # wireless (experimental)
```

#### Package module example

```python
# utils/packages/netifd.py
"""Schema for the 'network' UCI package (owned by netifd)."""

UCI_PACKAGE = "network"
OPKG = "netifd"
TIER = "stable"

NAMED_SECTIONS = {
    "interface": {
        "list_options": ["dns", "ipaddr", "ip6addr"],
    },
    "globals": {
        "list_options": [],
    },
}

# Not yet handled by managed() -- not yet implemented
ANONYMOUS_SECTIONS = {
    "device": {},
    "switch": {},
    "switch_vlan": {},
    "switch_port": {},
}
```

#### Registry API

```python
# utils/packages/_registry.py
def get(config_name):
    """Return package info dict or None."""

def tier(config_name):
    """Return 'stable', 'experimental', or None."""

def is_named_section(config_name, section_type):
    """True if this section type is in NAMED_SECTIONS."""

def list_options(config_name, section_type):
    """Return list of options that are UCI lists for this section type."""

def supported_packages(tier=None):
    """Return list of supported package names, optionally filtered by tier."""
```

#### Enforcement

```python
pkg_tier = registry.tier(config)
if pkg_tier is None:
    ret["result"] = False
    ret["comment"] = (
        f"{config}: not supported by saltext-openwrt-ubus. "
        f"Supported: {registry.supported_packages()}"
    )
    return ret
if pkg_tier == "experimental" and not allow_experimental:
    ret["result"] = False
    ret["comment"] = (
        f"{config}: experimental support. "
        f"Pass allow_experimental=True to proceed."
    )
    return ret
```

#### Pros

- Builds directly on the existing plan from `02-scaling-by-package.md`
- Schema metadata (list_options, section types) solves real future
  problems: list disambiguation, anonymous section dispatch
- Natural release narrative: "v0.4 promotes wireless from experimental
  to stable"
- Per-section-type granularity available when needed
- Each file is small, self-documenting, individually reviewable

#### Cons

- One file per package (~6 files now, grows with scope)
- Schema metadata is extra work upfront, not needed until anonymous
  section support lands
- Boilerplate for packages that need no schema (just a tier label)
- Tight coupling between extension releases and package additions

---

### Alternative B: Single scope manifest (minimal)

One Python file with a flat dict mapping package names to tiers. No
schema metadata -- just the whitelist. The lightest implementation
that achieves the tier goal.

#### File structure

```
src/saltext/openwrt_ubus/utils/
    scope.py               # single file, ~30 lines
```

#### The manifest

```python
# utils/scope.py
"""
Package support tiers for saltext-openwrt-ubus.

Packages not listed here cannot be managed by the managed() state.
"""

STABLE = {
    "network",
    "system",
    "dhcp",
}

EXPERIMENTAL = {
    "wireless",
    "firewall",
    "dropbear",
}

def tier(config_name):
    if config_name in STABLE:
        return "stable"
    if config_name in EXPERIMENTAL:
        return "experimental"
    return None

def is_supported(config_name):
    return config_name in STABLE or config_name in EXPERIMENTAL

def supported():
    return sorted(STABLE | EXPERIMENTAL)
```

#### Enforcement

Identical gate logic to Alternative A. Only the import path changes.

#### Schema metadata

Not included. The state module already handles list vs scalar correctly
by relying on what ubus returns (lists come back as JSON arrays). If
explicit schema is needed when anonymous section support lands, it
can be added then -- either by extending `scope.py` or by adopting
Alternative A's structure at that point.

#### Pros

- Minimal: one file, ~30 lines, trivially reviewable in a PR
- Fast to implement -- no per-package boilerplate
- Adding a package = one line change
- Promoting experimental to stable = move one string between sets
- YAGNI-friendly: no premature schema work
- Can evolve toward Alternative A later without breaking changes

#### Cons

- No schema metadata (list_options, section types) -- adding it later
  requires a structural change
- Does not capture the named-vs-anonymous distinction per package
- Less protection against attempting unsupported section types
- All knowledge about a package's characteristics lives in docs only,
  not enforced by code

---

### Alternative C: Tiered scope with section-type dispatch

The registry declares support per **section type within a package**,
not just per package. Named and anonymous section types get different
handling based on the state module's current capabilities. The package
tier is derived from its section types.

#### Core idea

The state module's capabilities are per-section-type, not per-package.
The `network` package has both named `interface` sections (fully
handled) and anonymous `device` sections (not yet handled). Instead
of labeling the whole package, label each section type with both its
handling category and its quality tier.

#### File structure

```
src/saltext/openwrt_ubus/utils/
    scope.py               # section-type registry + lookup functions
```

#### The registry

```python
# utils/scope.py
"""
Section-type support registry for saltext-openwrt-ubus.

Each entry maps a (uci_package, section_type) pair to a handling
category and a quality tier. The managed() state uses this to decide
whether to proceed, warn, or refuse for each section.
"""

# Handling categories -- what the state module can do with this section type
NAMED = "named"          # stable path: get, diff, set, apply
SINGLETON = "singleton"  # anonymous but exactly one per package: supported
ANONYMOUS = "anonymous"  # multiple anonymous: NOT YET supported

REGISTRY = {
    "network": {
        "interface":   (NAMED, "stable"),
        "globals":     (NAMED, "stable"),
        "device":      (ANONYMOUS, "experimental"),
        "switch":      (ANONYMOUS, "experimental"),
        "switch_vlan": (ANONYMOUS, "experimental"),
    },
    "system": {
        "system":      (SINGLETON, "stable"),
        "timeserver":  (NAMED, "stable"),
    },
    "dhcp": {
        "dnsmasq":     (SINGLETON, "stable"),
        "dhcp":        (NAMED, "stable"),
        "odhcpd":      (NAMED, "stable"),
        "host":        (ANONYMOUS, "experimental"),
    },
    "wireless": {
        "wifi-device": (NAMED, "experimental"),
        "wifi-iface":  (NAMED, "experimental"),
    },
    "firewall": {
        "defaults":    (SINGLETON, "experimental"),
        "zone":        (ANONYMOUS, "experimental"),
        "forwarding":  (ANONYMOUS, "experimental"),
        "rule":        (ANONYMOUS, "experimental"),
    },
    "dropbear": {
        "dropbear":    (SINGLETON, "experimental"),
    },
}


def package_tier(config_name):
    """Derive package tier from its section types.

    stable: all section types are stable.
    experimental: at least one is registered but not all stable.
    None: unknown package.
    """
    pkg = REGISTRY.get(config_name)
    if pkg is None:
        return None
    tiers = {t for _, t in pkg.values()}
    return "stable" if tiers == {"stable"} else "experimental"


def section_info(config_name, section_type):
    """Return (handling, tier) for a section type, or None."""
    pkg = REGISTRY.get(config_name)
    if pkg is None:
        return None
    return pkg.get(section_type)
```

#### Enforcement

Two-level check: package gate first, then per-section during the
diff loop.

```python
# Package-level gate (same position as A and B)
pkg_tier = scope.package_tier(config)
if pkg_tier is None:
    return _refuse(ret, f"{config}: not in saltext-openwrt-ubus scope")
if pkg_tier == "experimental" and not allow_experimental:
    return _refuse(ret, f"{config}: experimental, opt in required")

# Section-level gate (inside the diff loop, after resolving sections)
for section_name, desired in resolved.items():
    section_type = (desired.get("_type")
                    or current.get(section_name, {}).get("_type"))
    if section_type:
        info = scope.section_info(config, section_type)
        if info is None:
            return _refuse(ret,
                f"{config}.{section_name}: section type "
                f"'{section_type}' not in scope")
        handling, tier = info
        if handling == scope.ANONYMOUS:
            return _refuse(ret,
                f"{config}.{section_name}: anonymous section type "
                f"'{section_type}' not yet supported")
```

#### Interaction matrix

The anonymous handling column is gated by **capability**, not just tier:

```
              named+stable    singleton+stable    anonymous+experimental
audit         observe         observe             observe (if opted in)
autoverified  stage           stage               REFUSE (can't handle)
oneshot       apply           apply               REFUSE (can't handle)
```

#### Pros

- Captures the real constraint: support is per-section-type, not
  per-package
- Makes the named-vs-anonymous distinction explicit and enforced
- Clear error messages: "firewall.@rule: anonymous section type 'rule'
  not yet supported" rather than "firewall is experimental"
- Prevents the state module from attempting operations it structurally
  cannot handle
- Natural upgrade path: when anonymous section support lands, change
  the handling category and the gate opens automatically
- Single file, moderate complexity

#### Cons

- Most complex of the three alternatives
- Requires knowing all section types for each package upfront
- Mixes two concerns (handling capability + quality tier) in one tuple
- The `_type` field must be present in pillar data or derivable from
  the current device state for the section-level gate to work
- Could over-constrain: what if an operator just wants to `set_()` one
  option on a named section without the state module knowing its type?
- Audit mode on anonymous sections works (read-only), but the
  interaction matrix shows REFUSE -- is audit of unsupported types
  useful as a preview?

---

## Comparison

| Concern | A (per-file + schema) | B (flat manifest) | C (section-type) |
|---------|----------------------|-------------------|------------------|
| Files to create | ~6 modules + registry | 1 module | 1 module |
| Lines of code | ~200 total | ~30 | ~80 |
| Granularity | per-package | per-package | per-section-type |
| Schema metadata | yes | no | partial (handling) |
| Named vs anonymous | in schema, not enforced | not captured | enforced |
| Capability gating | tier only | tier only | tier + handling |
| Implementation effort | medium | small | medium |
| Adding a package | new file | one line | ~3-5 lines |
| Evolves toward | already the target | A (when schema needed) | A (when schema needed) |

## Notes

### rpcd ACL alignment

Whichever alternative is chosen, the rpcd ACL file
(`salt-agent-ubus.json`) should be tightened to match. Replace
`"uci": ["*"]` with the explicit list of packages from the registry.
This creates defense-in-depth: Python refuses unregistered packages,
rpcd blocks them even if the Python check is bypassed.

This is already on the ROADMAP (v0.2.0) and can be done as a follow-up.

### Execution modules stay generic

None of the alternatives change the execution modules or `ubus_ops.py`.
The gate lives in `managed()` only. The execution module functions
(`get`, `set_`, `delete`, etc.) remain unrestricted -- an operator can
always call `openwrt_ubus.get("dropbear")` directly for inspection or
ad-hoc changes. The whitelist restricts only the `managed()` state
function, which is the high-level path that reads, diffs, stages,
applies, and confirms.

### Open questions

- Should `allow_experimental` be a state parameter, a pillar key, or
  both? A pillar key allows per-device control without changing state
  files. A state parameter makes intent explicit in the state file.
- Should audit mode be allowed on unregistered packages? Observing a
  package the extension doesn't officially support is read-only and
  arguably useful for exploration.
- Should the tier gate produce `result=False` (hard failure) or
  `result=True` with a skip comment (soft skip, like disabled mode)?
  Hard failure is safer. Soft skip is more forgiving in highstate runs.
