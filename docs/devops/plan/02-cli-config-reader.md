# 02 -- CLI Config Reader

## Problem

Onboarding an existing OpenWrt router into Salt management requires knowing its current configuration. Manually translating `uci show` output into Salt pillar YAML is tedious and error-prone. A tool should automate this.

## Use Cases

1. **Onboard existing router**: SSH into router, read config, generate pillar YAML as starting point
2. **Audit config drift**: Compare current router state against declared pillar, report differences
3. **Generate baseline**: Snapshot a known-good config for version control
4. **Migration**: Export config from one router, import to another via Salt states

## Input Sources

| Source | Method | When to Use |
|--------|--------|-------------|
| Live router via SSH | `salt-ssh '*' -r 'uci show'` | Primary use case |
| Local file | Read `uci show` output from file | Offline analysis, testing |
| `uci export` format | Parse UCI syntax blocks | Full config backup/restore |

## Output Formats

### Salt Pillar YAML

UCI config contains secrets (Wi-Fi PSKs, PPPoE credentials, VPN keys). The config reader needs a strategy for handling them when generating YAML output. Two options under consideration:

**Option A: Structure-only output with secret placeholders**

Replace known secret fields with Jinja2 pillar references and extract actual values to a separate `secrets.yaml`:

```yaml
uci:
  network:
    wan:
      _type: interface
      password: "{{ pillar['pppoe_password'] }}"  # extracted to secrets.yaml
  wireless:
    default_radio0:
      _type: wifi-iface
      key: "{{ pillar['wifi_key'] }}"  # extracted to secrets.yaml
```

This would use a list of known secret option names (`password`, `key`, `psk`, `secret`, `token`, etc.) to detect which values to extract.

**Option B: Raw dump with a warning**

Output everything as-is, print a prominent warning that the output contains secrets, and leave scrubbing to the operator.

```yaml
# WARNING: This file may contain secrets. Review before committing.
uci:
  network:
    wan:
      _type: interface
      password: my-actual-pppoe-password
```

Simpler to implement; puts the burden on the operator.

**Open question**: Which approach better fits the workflow? Option A is safer but more complex. Option B ships faster. A hybrid (flag to toggle behavior) is also possible.

Regardless of approach, the basic YAML structure looks like:

```yaml
uci:
  network:
    lan:
      _type: interface
      proto: static
      ipaddr: 10.35.24.1
      netmask: 255.255.255.0
    wan:
      _type: interface
      proto: static
      ipaddr: 192.168.16.99
      dns:
        - 1.1.1.1
        - 1.0.0.1
  firewall:
    _anonymous:
      - _type: rule
        _match_on: [name]
        name: Allow-SSH
        src: wan
        dest_port: "22"
        proto:
          - tcp
        target: ACCEPT
```

Key conventions:
- `_type`: UCI section type (maps to `config <type>` in UCI export)
- `_anonymous`: list of unnamed sections within a package
- `_match_on`: fields used for idempotent matching (see 01-salt-module-development.md)
- List options rendered as YAML lists
- Named sections as dict keys, anonymous sections in `_anonymous` list
- Secret values replaced with pillar references (see above)

### UCI Batch Script

```
set network.lan.proto=static
set network.lan.ipaddr=10.35.24.1
delete network.wan.dns
add_list network.wan.dns=1.1.1.1
add_list network.wan.dns=1.0.0.1
commit network
```

Useful for raw mode application or manual review.

### Human-Readable Diff

```
network.lan.ipaddr: 10.35.24.1 -> 10.35.24.100
network.wan.dns: [1.1.1.1, 1.0.0.1] -> [8.8.8.8, 8.8.4.4]
+ firewall.@rule[new]: Allow-HTTPS (src=wan, dest_port=443)
- firewall.@rule[5]: Allow-Telnet (removed)
```

## Data Model

Parsed UCI config as nested Python dict:

```python
{
    "network": {
        "lan": {
            "_type": "interface",
            "_named": True,
            "proto": "static",
            "ipaddr": "10.35.24.1",
        },
        "_anonymous": [
            {
                "_type": "route",
                "_index": 0,
                "interface": "lan",
                "target": "10.38.20.0",
                "netmask": "255.255.255.0",
                "gateway": "10.8.1.2",
            },
        ],
    },
}
```

The parser must handle:
- Named sections (`config interface 'lan'`)
- Anonymous sections (`config rule` with no name)
- Scalar options (`option proto 'static'`)
- List options (`list dns '1.1.1.1'`)
- Nested references (`firewall.@zone[0]`)

### Known Limitations and Out-of-Scope

The following UCI features exist but are deferred or explicitly out of scope for v1:

| Feature | Status | Rationale |
|---------|--------|-----------|
| `uci -c <confdir>` (custom config directory) | Deferred | Non-standard setup; add as optional `confdir` param later |
| `/etc/config.d/` include directories | Out of scope | Rare in practice; standard `uci show` flattens includes |
| Encrypted option values (e.g., PPPoE passwords) | Pass-through | Parser stores them as opaque strings; no decryption |
| Negative indices (`@zone[-1]`) | Must handle | `uci show` resolves these to positive indices; parser sees resolved form |
| Config file comments | Dropped | `uci show`/`uci export` strips comments; no round-trip possible |

The parser operates on `uci show` or `uci export` **output**, not raw config files. This means UCI internally resolves includes, config directory overrides, and index arithmetic before the parser sees the data. Edge cases in raw `/etc/config/*` files are therefore not a concern for parsing, but operators should be aware that round-tripping through `uci export` loses comments and include structure.

## Implementation

### Phase 1: Parser Library

Internal module `saltext.saltext_uci.utils.uci_parser`:
- `parse_show(text: str) -> dict` -- parse `uci show` output
- `parse_export(text: str) -> dict` -- parse `uci export` output
- `to_pillar(config: dict) -> dict` -- convert to pillar-ready YAML structure
- `to_batch(config: dict) -> str` -- convert to UCI batch commands
- `diff(current: dict, desired: dict) -> list` -- compute changes

### Phase 2: Execution Module Integration

Add to the execution module:
- `saltext_uci.dump(package=None, format="pillar")` -- read live config, return formatted output
- `saltext_uci.diff_pillar(pillar_data)` -- compare live config against pillar, return changes

### Phase 3: CLI Entry Point (optional)

Entry point in `pyproject.toml`:
```toml
[project.scripts]
uci-reader = "saltext.saltext_uci.cli:main"
```

Standalone CLI that doesn't require Salt:
```bash
uci-reader --host 10.35.24.1 --format pillar > pillar/austru.yaml
uci-reader --file austru-uci-export.txt --format batch > apply.sh
```

#### SSH Transport for CLI

The CLI needs to SSH into routers independently of Salt. Transport design:

| Concern | Approach |
|---------|----------|
| SSH client | `subprocess.run(["ssh", ...])` -- delegates to the system's OpenSSH client |
| Authentication | Relies on the operator's SSH agent or `~/.ssh/config` (no built-in key management) |
| Host specification | `--host` accepts a hostname/IP; `--ssh-config-host` accepts an SSH config alias |
| Privilege escalation | Not needed -- `uci show` runs as the SSH login user (typically `root` on OpenWrt) |
| Known hosts | Delegated to system SSH; no host-key bypass by default |

The CLI does **not** embed paramiko or any Python SSH library. It shells out to `ssh`, which means it works with any authentication method the operator has configured (agent forwarding, hardware keys, ProxyJump, etc.) without reimplementing credential management.

For environments without a system `ssh` binary (e.g., Windows without OpenSSH), the `--file` input mode is the fallback.

## Dependencies

- Requires the UCI parser from the execution module (01)
- No additional Python packages beyond stdlib (SSH via system `ssh` binary, not paramiko)

## Testing

- Unit tests with captured `uci show` and `uci export` output from real routers
- Test data: `austru-uci-export.txt` from the austru repo as fixture
- Round-trip test: parse -> serialize -> parse should be identity
