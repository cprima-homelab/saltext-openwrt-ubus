# Operational Flow

How the extension orchestrates a configuration run, from pillar input
to applied config. The flow varies depending on the agent mode set in
`/etc/config/salt-openwrt` on the device.

## Full sequence -- oneshot mode

The happy path when `mode = oneshot`. Salt reads, diffs, stages, applies
with rollback protection, verifies, and confirms.

```{mermaid}
sequenceDiagram
    autonumber
    participant Master as Salt Master
    participant State as state.managed()
    participant Agent as /etc/config/<br/>salt-openwrt
    participant UCI as UCI (ubus/SSH)
    participant Device as OpenWrt Device

    Master->>State: managed(config, sections)
    State->>UCI: get("salt-openwrt", "global")
    UCI-->>State: {enabled: "1", mode: "oneshot"}

    Note over State: Mode = oneshot, proceed

    State->>UCI: changes(config)
    UCI-->>State: {} (no pending deltas)

    State->>UCI: get(config)
    UCI-->>State: current config state

    Note over State: Resolve sections<br/>(singleton & multi-instance anonymous)
    Note over State: Diff desired vs current<br/>(partial semantics)

    alt No drift detected
        State-->>Master: result=True, "already in desired state"
    end

    Note over State: Drift detected

    alt test=True (dry run)
        State-->>Master: result=None, changes preview
    end

    rect rgb(230, 245, 230)
        Note over State,Device: Stage phase
        loop Each changed section
            opt Section does not exist yet
                State->>UCI: add(config, type, name)
            end
            State->>UCI: set(config, section, values)
        end
    end

    rect rgb(245, 240, 250)
        Note over State,Device: Service snapshot
        State->>UCI: service_list()
        UCI-->>State: {svc: {inst: pid}, ...}
        Note over State: Record running services + PIDs
    end

    rect rgb(230, 235, 250)
        Note over State,Device: Apply phase (rollback=90s)
        State->>UCI: apply(rollback=90)
        UCI->>Device: uci commit + reload services
        Device-->>UCI: OK
    end

    rect rgb(250, 245, 230)
        Note over State,Device: Verify phase -- UCI values
        State->>UCI: get(config)
        UCI-->>State: new config state
        Note over State: Compare each changed option<br/>against expected value
        alt Verification failed
            Note over State: Rollback will revert<br/>in 90 seconds
            State-->>Master: result=False, verification error
        end
    end

    rect rgb(250, 240, 245)
        Note over State,Device: Verify phase -- service health
        loop Poll until all services running or deadline
            State->>UCI: service_list()
            UCI-->>State: {svc: {inst: running, pid}, ...}
        end
        alt Services not recovered
            Note over State: Do NOT confirm<br/>Rollback reverts automatically
            State-->>Master: result=False, "services not recovered"
        end
    end

    rect rgb(235, 250, 235)
        Note over State,Device: Confirm phase
        State->>UCI: confirm()
        UCI->>Device: Cancel rollback timer
        Device-->>UCI: OK
    end

    State-->>Master: result=True, "applied and confirmed<br/>(N service(s) verified running)"
```

## Audit mode

When `mode = audit`, Salt reads and diffs but never writes. The device
is protected from any configuration changes.

```{mermaid}
sequenceDiagram
    autonumber
    participant Master as Salt Master
    participant State as state.managed()
    participant UCI as UCI (ubus/SSH)

    Master->>State: managed(config, sections)
    State->>UCI: get("salt-openwrt", "global")
    UCI-->>State: {enabled: "1", mode: "audit"}

    Note over State: Mode = audit

    State->>UCI: changes(config)
    UCI-->>State: pending deltas (if any)

    State->>UCI: get(config)
    UCI-->>State: current config state

    Note over State: Resolve sections
    Note over State: Diff desired vs current

    alt No drift
        State-->>Master: result=True,<br/>"audit mode -- no drift detected"
    else Drift detected
        Note over State: Report drift in changes dict<br/>but do NOT call set/apply/confirm
        State-->>Master: result=True, changes={...},<br/>"audit mode -- N section(s) drifted,<br/>no changes applied"
    end
```

## Autoverified mode

When `mode = autoverified`, Salt stages UCI changes (`uci set`) but does
not call `uci apply` or `uci confirm`. The `applied()` state activates
staged changes with rollback protection. The staging behavior differs by
transport because rpcd routes changes differently depending on whether
a session ID is present:

- **SSH transport** runs `ubus call uci set` without a session. Changes
  stage to `/tmp/.uci/`, visible to `uci changes` from CLI and LuCI.

- **JSON-RPC transport** passes the rpcd session token with every call.
  Changes stage in the rpcd session, kept alive by the proxy minion.

The `applied()` state applies all staged changes globally with rollback
protection, verifies that all previously-running services are healthy, and
confirms. It can be called without a `config` parameter for session-global
apply.

### Autoverified mode -- SSH transport

```{mermaid}
sequenceDiagram
    autonumber
    participant Master as Salt Master
    participant State as state.managed()
    participant UCI as UCI (SSH)
    participant Device as /tmp/.uci/
    participant Human as Operator<br/>(LuCI / CLI)

    Master->>State: managed(config, sections)
    State->>UCI: get("salt-openwrt", "global")
    UCI-->>State: {enabled: "1", mode: "autoverified"}

    Note over State: Mode = autoverified<br/>Override: apply_rollback = None

    State->>UCI: changes(config)
    UCI-->>State: {} (no pending)

    State->>UCI: get(config)
    UCI-->>State: current config state

    Note over State: Resolve + Diff

    rect rgb(230, 245, 230)
        Note over State,Device: Stage phase
        loop Each changed section
            opt New section
                State->>UCI: add(config, type, name)
            end
            State->>UCI: set(config, section, values)
            UCI->>Device: staged in /tmp/.uci/
        end
    end

    Note over State: SSH transport detected<br/>Skip commit -- changes are<br/>in /tmp/.uci/ for review

    State-->>Master: result=True, changes={...},<br/>"staged (review with 'uci changes')"

    Note over Human: Later...
    Human->>Device: uci changes (review staged)

    rect rgb(230, 235, 250)
        Note over Human,Device: applied() state
        Human->>UCI: saltext_ubus.applied()
        Note over UCI: snapshot services<br/>→ apply(rollback)<br/>→ poll services until healthy<br/>→ confirm
        UCI-->>Human: Applied and confirmed<br/>(N service(s) verified running)
    end
```

### Autoverified mode -- JSON-RPC transport

```{mermaid}
sequenceDiagram
    autonumber
    participant Master as Salt Master
    participant State as state.managed()
    participant UCI as UCI (JSON-RPC)
    participant Session as /var/run/rpcd/<br/>uci-<session_id>/
    participant Human as Operator<br/>(LuCI / CLI)

    Master->>State: managed(config, sections)
    State->>UCI: get("salt-openwrt", "global")
    UCI-->>State: {enabled: "1", mode: "autoverified"}

    Note over State: Mode = autoverified<br/>Override: apply_rollback = None

    State->>UCI: changes(config)
    UCI-->>State: {} (no pending)

    State->>UCI: get(config)
    UCI-->>State: current config state

    Note over State: Resolve + Diff

    rect rgb(230, 245, 230)
        Note over State,Session: Stage phase
        loop Each changed section
            opt New section
                State->>UCI: add(config, type, name)
            end
            State->>UCI: set(config, section, values)
            UCI->>Session: staged in rpcd session<br/>(kept alive by proxy minion)
        end
    end

    Note over State: No commit, no apply<br/>Changes live in rpcd session

    State-->>Master: result=True, changes={...},<br/>"staged in rpcd session"

    Note over Human: Later...

    rect rgb(230, 235, 250)
        Note over Human,Session: applied() state
        Human->>UCI: saltext_ubus.applied()
        Note over UCI: snapshot services<br/>→ apply(rollback)<br/>→ poll services until healthy<br/>→ confirm
        UCI-->>Human: Applied and confirmed<br/>(N service(s) verified running)
    end
```

## Humanreviewed mode

When `mode = humanreviewed`, Salt behaves identically to autoverified
mode. This mode is reserved for a future LuCI approval gate where an
operator must explicitly approve staged changes through the web
interface before `applied()` activates them.

## Disabled device

When `enabled = 0`, Salt returns immediately without reading any config.

```{mermaid}
sequenceDiagram
    autonumber
    participant Master as Salt Master
    participant State as state.managed()
    participant UCI as UCI (ubus/SSH)

    Master->>State: managed(config, sections)
    State->>UCI: get("salt-openwrt", "global")
    UCI-->>State: {enabled: "0", mode: "oneshot"}

    Note over State: Device disabled, skip entirely

    State-->>Master: result=True,<br/>"salt-openwrt disabled on device, skipping"
```

## Graceful fallback (package not installed)

When `/etc/config/salt-openwrt` does not exist, the `get()` call raises
an exception. The state module catches it and defaults to `oneshot` mode,
preserving backward compatibility.

```{mermaid}
sequenceDiagram
    autonumber
    participant Master as Salt Master
    participant State as state.managed()
    participant UCI as UCI (ubus/SSH)

    Master->>State: managed(config, sections)
    State->>UCI: get("salt-openwrt", "global")
    UCI--xState: Exception (config not found)

    Note over State: Catch exception<br/>Default: enabled=True, mode="oneshot"

    Note over State: Continue with full oneshot flow...
```

## Pending deltas handling

When uncommitted changes exist for the target config package, the
behavior depends on the `revert_pending` parameter.

```{mermaid}
sequenceDiagram
    autonumber
    participant Master as Salt Master
    participant State as state.managed()
    participant UCI as UCI (ubus/SSH)

    Master->>State: managed(config, sections)
    State->>UCI: get("salt-openwrt", "global")
    UCI-->>State: {enabled: "1", mode: "oneshot"}

    State->>UCI: changes(config)
    UCI-->>State: {section: {option: delta}}

    Note over State: Pending deltas detected!

    alt revert_pending = False (default)
        State-->>Master: result=False,<br/>"Uncommitted changes exist..."
    else revert_pending = True
        State->>UCI: revert(config)
        UCI-->>State: OK
        Note over State: Continue with normal flow...
    end
```
