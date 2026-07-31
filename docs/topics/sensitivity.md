# UCI Sensitivity Classification

OpenWrt UCI configuration contains secrets — WireGuard `private_key`,
Wi-Fi `key`, OpenVPN credentials — stored as ordinary strings alongside
non-sensitive options like `proto`, `ssid`, and `hostname`. Without
explicit classification, every option must be treated as potentially
secret, making evidence payloads useless or dangerous.

The sensitivity module classifies each UCI option, tracks how that
classification propagates through a section (taint), and applies a
surface-specific policy to decide what each output channel is allowed
to reveal.

## Core concepts

Three concepts govern the system:

**Classification** is a property of a single UCI option (field). It
answers: "how sensitive is this value?"

**Taint** is a property of a UCI section (container). It is derived
automatically as the maximum classification of all options in the
section. A section containing one `secret` option is tainted `secret`
even if every other option is `public`. Taint is a summary for
consumers (dashboards, quick triage) and is not a policy driver.
Policy decisions are made per option using each field's individual
classification, not the section's taint. A `secret`-tainted section
still exposes its `ssid`, `device`, and other `internal` options.

**Policy** is a per-surface rule. It answers: "given this
classification, what is this output surface allowed to do?"

## Classification levels

Five levels, ordered by severity:

| Level | Rank | Meaning |
|---|---|---|
| `public` | 0 | Safe to expose everywhere |
| `internal` | 1 | Operational data; safe for evidence and grains |
| `unknown` | 2 | No matching rule; treated conservatively |
| `sensitive` | 3 | Should not appear in grains or logs |
| `secret` | 4 | Must never appear as a value in any output |

`unknown` is not a soft version of `public` or `internal`. Any option
with no matching rule in the profile gets `unknown`, and the default
policies treat it conservatively (denied from grains, redacted to null
in evidence). The distinction between `unknown` and `internal` matters:
promoting a known-safe option to `internal` in the profile is an
explicit operator decision; leaving an unrecognised option as `unknown`
is a safe default that surfaces as a redacted value rather than a leak.

Severity ranking uses an explicit `TAINT_RANK` dict rather than enum
ordering. This means adding or reordering enum members never silently
changes severity comparisons.

## Policies and surfaces

Five output surfaces are governed:

| Surface | What it is |
|---|---|
| `evidence` | Collected UCI state payload stored for audit |
| `grains` | Salt grains returned to the master |
| `config_diff` | Diff result from `config_diff()` |
| `logs` | Structured log entries |
| `cli_output` | Output from Salt CLI commands |

> Note: pillar is an *input* surface and is not governed here.

Four policy values control what a surface may reveal:

| Policy | Effect |
|---|---|
| `allow` | Value and key both present, unchanged |
| `redact` | Key present, value replaced with `null`; `_sensitivity` retained |
| `deny` | Key absent from the section dict; `_sensitivity` retained |
| `report-change` | `config_diff` only: `{changed: true}` replaces `{old, new}` |

`redact` and `deny` both retain `_sensitivity` metadata. The distinction
is whether the key itself appears in the output. Neither removes all
trace — if the key must also disappear, callers must strip `_sensitivity`
themselves.

## Default policies (builtin profile)

|   | grains | evidence | logs | cli_output | config_diff |
|---|---|---|---|---|---|
| **public** | allow | allow | allow | allow | allow |
| **internal** | allow | allow | allow | allow | allow |
| **unknown** | deny | redact | deny | redact | report-change |
| **sensitive** | redact | redact | redact | redact | report-change |
| **secret** | deny | redact | deny | redact | report-change |

The grains invariant: no `secret`, `sensitive`, or `unknown` option may
have a non-null value in a grains projection. `assert_grains_safe()`
verifies this and is used in the test suite.

## Classification pipeline

```
raw UCI state  (config_export())
      │
      ▼
classify_export()          every option classified; values untouched
      │
      ▼
classified state           intermediate: ALL options annotated + taint per section
      │
      ├── evidence_projection()    evidence surface
      ├── grains_projection()      grains surface
      └── diff_projection()        config_diff surface
```

`classify_export()` annotates every non-metadata option with its
classification and computes a `taint` for the section. Values are
**not** modified at this stage. The classified state is an internal
intermediate that all projections consume.

## Rule matching

Rules live in a YAML profile and are matched against the triplet
`(package, section_type, option)`. Specificity determines priority:

| Specificity | Dimensions matched |
|---|---|
| 1 | `option` only |
| 2 | `section_type` + `option` |
| 3 | `package` + `section_type` + `option` |

The highest-specificity matching rule wins. At equal specificity, the
last matching rule wins. Unmatched options default to `unknown`.

`section_type` and `option` may be a list in the YAML, allowing one
rule to cover multiple values:

```yaml
- match:
    section_type: wifi-iface
    option: [key, wpa_psk, wep_key0, wep_key1, wep_key2, wep_key3]
  classification: secret
```

## Built-in profile

The built-in profile (`saltext-openwrt-ubus/default`) ships with two
layers of rules.

**Known-secret rules** classify credentials at their correct level:

- `password`, `passwd`, `psk` anywhere → `sensitive` (specificity 1)
- `wifi-iface/key`, `openvpn/key`, `radius/auth_secret` etc. → `secret` (specificity 2)
- `network/interface/private_key`, `network/wireguard/private_key` → `secret` (specificity 3)

**Baseline safe rules** promote common known-safe UCI options to
`internal` so that ordinary evidence payloads remain useful under the
conservative `unknown` default. Without these rules, most standard
options (`proto`, `ipaddr`, `ssid`, `hostname`, `channel`, ...) would
be redacted to null in evidence.

Safe rules cover: common structural options (`disabled`, `proto`,
`mtu`, etc.), `network/interface` addressing options, `wifi-device`
RF options, `wifi-iface` non-secret options, `system`, `dhcp`,
`firewall`, and `dropbear`.

## Annotated example

Input from `config_export("wireless")`:

```python
{
    "wlan0": {
        "_type": "wifi-iface",
        "device": "radio0",
        "ssid": "HomeNetwork",
        "encryption": "psk2",
        "key": "mysupersecretpassword",
    }
}
```

After `classify_export()`:

```python
{
    "wlan0": {
        "_type": "wifi-iface",
        "_sensitivity": {
            "taint": "secret",
            "fields": {
                "device":      "internal",
                "ssid":        "internal",
                "encryption":  "internal",
                "key":         "secret",
            }
        },
        "device":     "radio0",
        "ssid":       "HomeNetwork",
        "encryption": "psk2",
        "key":        "mysupersecretpassword",   # still present
    }
}
```

After `evidence_projection()`:

```python
{
    "wlan0": {
        "_type": "wifi-iface",
        "_sensitivity": {
            "taint": "secret",
            "fields": {"key": "secret"},          # compacted: public/internal omitted
        },
        "device":     "radio0",
        "ssid":       "HomeNetwork",
        "encryption": "psk2",
        "key":        None,                       # secret → null, key kept
    }
}
```

After `grains_projection()`:

```python
{
    "wlan0": {
        "_type": "wifi-iface",
        "_sensitivity": {
            "taint": "secret",
            "fields": {"key": "secret"},
        },
        "device":     "radio0",
        "ssid":       "HomeNetwork",
        "encryption": "psk2",
        # "key" absent — secret → deny
    }
}
```

## config_diff redaction

`diff_projection()` applies redaction to the output of `config_diff()`.

For **changed** and **new** sections: any option classified
`secret`, `sensitive`, or `unknown` has its `{old, new}` entry
replaced with `{changed: true}`. The fact that a change occurred is
reported; the values are not.

```python
# input
{"changed": {"wg0": {"private_key": {"old": "aaaa==", "new": "bbbb=="}}}}

# after diff_projection()
{"changed": {"wg0": {"private_key": {"changed": True}}}}
```

For **removed** and **reordered** sections: sensitive option values are
set to null (same policy as evidence projection applied to raw section
dicts).

## Custom profiles

The built-in profile can be extended without replacing it:

```python
from saltext.openwrt_ubus.sensitivity.model import (
    Classification, ClassificationRule, MatchCriteria, SensitivityProfile,
)

override = SensitivityProfile(
    name="myorg/openwrt",
    version="1",
    rules=[
        ClassificationRule(
            match=MatchCriteria(package="mycustom", section_type="vpn", option="token"),
            classification=Classification.SECRET,
        ),
    ],
    policies={},   # inherit all policies from builtin
)

profile = SensitivityProfile.load_builtin().overlay(override)
```

`overlay()` appends the new rules (so they can override by specificity),
merges policies (override wins per key), and adopts the overlay's
`name` and `version`. The original built-in rules remain in effect for
all unmatched options.

**Provenance limitation**: the composed profile reports only the overlay
identity. The base profile is lost:

```yaml
# what gets emitted today
sensitivity:
  profile: myorg/openwrt
  version: "3"

# what would be needed for full composition provenance
sensitivity:
  profile: myorg/openwrt
  version: "3"
  base:
    profile: saltext-openwrt-ubus/default
    version: "1"
```

The current flat `name + version` is accurate for the built-in-only
case. Supporting composition provenance requires adding an optional
`base` field to `SensitivityProfile` and populating it in `overlay()`.
This is deferred until overlays are actively used.

## Module reference

| Module | Purpose |
|---|---|
| `saltext.openwrt_ubus.sensitivity.model` | `Classification`, `TAINT_RANK`, `max_taint()`, `Surface`, `Policy`, `PolicyDecision`, `MatchCriteria`, `ClassificationRule`, `SensitivityProfile` |
| `saltext.openwrt_ubus.sensitivity.classify` | `classify_export()` |
| `saltext.openwrt_ubus.sensitivity.project` | `evidence_projection()`, `grains_projection()`, `diff_projection()`, `assert_grains_safe()` |
