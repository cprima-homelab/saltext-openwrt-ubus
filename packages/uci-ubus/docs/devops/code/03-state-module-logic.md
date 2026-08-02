# 03 -- State Module Logic

How the state module (`states/saltext_ubus.py`, 530 lines) achieves
idempotent configuration management with rollback safety.

Source: `src/saltext/uci_ubus/states/saltext_ubus.py`

## Two public states

| State | Purpose | When to use |
|-------|---------|-------------|
| `managed()` | Ensure sections match desired state | Always |
| `applied()` | Apply staged changes with health checks | After `managed()` in autoverified/humanreviewed mode |

In **oneshot** mode, `managed()` handles apply and confirm internally.
`applied()` is not needed.

## Device-controlled behavior (inversion of control)

The state module reads `/etc/config/salt-openwrt` from the managed
device to decide its own behavior:

```python
# states/saltext_ubus.py:241-254
def _get_agent_mode():
    try:
        agent = __salt__["uci_ubus.get"]("salt-openwrt", "global")
    except Exception:
        log.debug("salt-openwrt config not found, defaulting to oneshot mode")
        return True, "oneshot", 120
    enabled = agent.get("enabled", "1") == "1"
    mode = agent.get("mode", "oneshot")
    rollback_timeout = int(agent.get("rollback_timeout", "120"))
    return enabled, mode, rollback_timeout
```

The device controls Salt, not vice versa. If the `salt-openwrt`
package is not installed, the state defaults to oneshot mode.

| Mode | `managed()` behavior | `applied()` needed? |
|------|---------------------|---------------------|
| `audit` | Report drift, never write | No |
| `autoverified` | Stage changes only | Yes |
| `humanreviewed` | Stage changes only (operator reviews in LuCI) | Yes |
| `oneshot` | Stage + apply + confirm in one run | No |
| disabled (`enabled=0`) | Skip entirely | -- |

## `managed()` control flow

```
1. _get_agent_mode()           → enabled, mode, rollback_timeout
2. _check_pending()            → fail or revert uncommitted deltas
3. _read_and_resolve()         → current config + resolve pillar names
4. _diff_section() per section → partial comparison
5. audit mode?                 → report drift, return
6. test mode?                  → report changes, return
7. _stage_changes()            → issue uci.add + uci.set calls
8. _commit_or_apply()          → stage-only or apply+confirm
```

## Partial diff semantics

`_diff_section()` only compares options present in the desired state.
Unmanaged options are left untouched:

```python
# states/saltext_ubus.py:515-529
def _diff_section(desired, current):
    changes = {}
    for option, desired_value in desired.items():
        if option.startswith("_"):
            continue                        # skip metadata (_type, _name, ...)
        current_value = current.get(option)
        if current_value != desired_value:
            changes[option] = {"old": current_value, "new": desired_value}
    return changes
```

Given pillar:

```yaml
sections:
  lan:
    _type: interface
    proto: static
    ipaddr: 10.35.24.1
```

And device state:

```
lan.proto = static
lan.ipaddr = 10.35.24.1
lan.netmask = 255.255.255.0    # unmanaged -- not in pillar
lan.ip6assign = 60              # unmanaged
```

Result: no drift. `_type` is skipped (metadata), `netmask` and
`ip6assign` are not in pillar so they are not compared.

This matches LuCI's option-by-option model. Salt doesn't replace
the entire section -- it manages only the options you declare.

## Anonymous section resolution

UCI anonymous sections have auto-generated IDs (e.g., `cfg040f15`) that
change across reboots. The resolver (`_resolve_sections()`) handles
three cases and returns a `(resolved, prune_targets)` tuple:

### Singleton anonymous sections

Use a `_` prefix with a `_type` field:

```yaml
sections:
  _dhcp:
    _type: dhcp
    authoritative: "1"
    leasefile: /tmp/dhcp.leases
```

The resolver finds the one anonymous section of that type. `_dhcp`
resolves to e.g. `cfg040f15` if exactly one anonymous section of type
`dhcp` exists. Fails explicitly if zero or multiple matches.

### Multi-instance anonymous sections (`_items`)

For packages with multiple anonymous sections of the same type (e.g.,
firewall rules, DHCP hosts), use `_match` and `_items`:

```yaml
sections:
  firewall_rules:
    _type: rule
    _match: name
    _items:
      - name: Allow-SSH
        src: wan
        dest_port: "22"
        target: ACCEPT
      - name: Allow-HTTPS
        src: wan
        dest_port: "443"
        target: ACCEPT
```

`_resolve_multi_instance()` matches each item against existing
anonymous sections using the `_match` field as a key. Unmatched items
are created as new sections.

When `_prune: true` is set, existing anonymous sections of the same
type that are not present in `_items` are marked for deletion and
returned in the `prune_targets` list.

### Order enforcement (`_check_order`)

After resolving multi-instance sections, `_check_order()` verifies that
the on-device order of anonymous sections matches the pillar order. If
sections are out of order, they are deleted and re-added in the correct
sequence (delete+re-add strategy), since UCI has no reorder primitive.

### `_absent` sentinel

The `_absent` sentinel in `_diff_section()` marks options or entire
sections for deletion. Setting an option to `_absent` removes it from
the section; setting the entire section value to `_absent` deletes the
section.

## Type-mismatch guard

Before staging any changes, checks that the section's type matches:

```python
# states/saltext_ubus.py:89-100
if current_section:
    desired_type = desired.get("_type")
    current_type = current_section.get("_type")
    if desired_type and current_type and desired_type != current_type:
        ret["result"] = False
        ret["comment"] = (
            f"Type mismatch on {config}.{section_name}: "
            f"desired _type '{desired_type}' != current _type '{current_type}'"
        )
        return ret
```

This prevents cascading errors: if you accidentally target `_type: route`
on an `interface` section, the state fails before issuing any `uci.set`
calls.

## Pending changes check

Before writing, checks for uncommitted deltas from another session or
a previous failed run:

```python
# states/saltext_ubus.py:262-283
def _check_pending(ret, config, revert_pending):
    pending = __salt__["uci_ubus.changes"](config)
    if pending:
        if not revert_pending:
            ret["result"] = False
            ret["comment"] = (
                f"Uncommitted changes exist for {config}. "
                f"Set revert_pending=True to discard them..."
            )
            return pending
        if not __opts__["test"]:
            __salt__["uci_ubus.revert"](config)
    return pending
```

By default, fail. The operator must explicitly pass `revert_pending=True`
to discard someone else's staged changes.

## Transport-aware staging comments

The state module detects the transport to explain where staged changes
live:

```python
# states/saltext_ubus.py:257-259, 335-345
def _is_json_rpc():
    return __opts__.get("proxy", {}).get("proxytype") == "uci_ubus_jsonrpc"

# In _commit_or_apply():
if _is_json_rpc():
    ret["comment"] = f"{config}: staged in rpcd session (apply with uci_ubus.applied)"
else:
    ret["comment"] = f"{config}: staged (review with 'uci changes {config}')"
```

JSON-RPC changes live in an rpcd session (invisible to SSH). SSH changes
live in `/tmp/.uci/` (reviewable on the device). The operator gets a
clear message about where their changes are and how to inspect them.

## Stage-then-apply with service health verification

The `_apply_and_confirm()` function implements a multi-step commit:

```
1. _snapshot_services()     → record running services + PIDs
2. uci_ubus.apply()    → commit, reload daemons, arm rollback timer
3. uci_ubus.get()      → re-read config, verify values match
4. _wait_for_services()    → poll until all services are back
5. uci_ubus.confirm()  → cancel rollback timer
```

### Service health polling

```python
# states/saltext_ubus.py:19-20, 437-477
POLL_INTERVAL = 3
SAFETY_MARGIN_FRACTION = 4

def _wait_for_services(snapshot, rollback):
    safety_margin = max(10, rollback // SAFETY_MARGIN_FRACTION)
    deadline = time.monotonic() + rollback - safety_margin

    while True:
        time.sleep(POLL_INTERVAL)
        services = __salt__["uci_ubus.service_list"]()
        down = []
        for svc_name, instances in snapshot.items():
            svc_data = (services or {}).get(svc_name, {})
            svc_instances = svc_data.get("instances", {})
            for inst_name in instances:
                inst_data = svc_instances.get(inst_name, {})
                if not inst_data.get("running"):
                    down.append(f"{svc_name}/{inst_name}")
        if not down:
            return True, []
        if time.monotonic() >= deadline:
            return False, down
```

The safety margin prevents a last-second race:
- Rollback timeout: 90s
- Safety margin: `max(10, 90 // 4)` = 22s
- Polling deadline: 68s
- Even if the last poll fails, rpcd still has 22s to auto-revert

### Post-apply verification

After apply, the state re-reads the config and checks every changed
option against the expected value:

```python
# states/saltext_ubus.py:366-387
new_state = __salt__["uci_ubus.get"](config)
for section_name, section_changes in all_changes.items():
    new_section = new_state.get(section_name, {})
    for option, change in section_changes.items():
        actual = new_section.get(option)
        if actual != change["new"]:
            ret["result"] = False
            ret["comment"] = (
                f"Verification failed: {config}.{section_name}.{option} "
                f"expected {change['new']!r}, got {actual!r}. "
                f"Rollback will revert in {apply_rollback}s."
            )
            return
```

This catches cases where `uci apply` silently fails (e.g., a package
reload hangs). The rollback timer is still running, so if verification
fails, the changes auto-revert.

## Section creation

If a section doesn't exist yet, the state creates it before setting
values:

```python
# states/saltext_ubus.py:305-322
if section_name not in current:
    desired = resolved[section_name]
    type_ = desired.get("_type")
    if not type_:
        ret["result"] = False
        ret["comment"] = f"Section '{section_name}' does not exist and no _type specified"
        return
    __salt__["uci_ubus.add"](config, type_, name=section_name)
```

This requires `_type` in the pillar. Without it, the state cannot know
what UCI section type to create.
