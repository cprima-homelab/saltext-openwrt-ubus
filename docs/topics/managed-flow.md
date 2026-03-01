# managed() sequence diagram

How `saltext_ubus.managed()` orchestrates a configuration run, from
pillar input to applied config. The flow varies depending on the agent
mode set in `/etc/config/salt-openwrt` on the device.

## Full sequence -- auto mode

The happy path when `mode = auto`. Salt reads, diffs, stages, applies
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
    UCI-->>State: {enabled: "1", mode: "auto"}

    Note over State: Mode = auto, proceed

    State->>UCI: changes(config)
    UCI-->>State: {} (no pending deltas)

    State->>UCI: get(config)
    UCI-->>State: current config state

    Note over State: Resolve sections<br/>(singleton anonymous lookup)
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

    rect rgb(230, 235, 250)
        Note over State,Device: Apply phase (rollback=90s)
        State->>UCI: apply(rollback=90)
        UCI->>Device: uci commit + reload services
        Device-->>UCI: OK
    end

    rect rgb(250, 245, 230)
        Note over State,Device: Verify phase
        State->>UCI: get(config)
        UCI-->>State: new config state
        Note over State: Compare each changed option<br/>against expected value
        alt Verification failed
            Note over State: Rollback will revert<br/>in 90 seconds
            State-->>Master: result=False, verification error
        end
    end

    rect rgb(235, 250, 235)
        Note over State,Device: Confirm phase
        State->>UCI: confirm()
        UCI->>Device: Cancel rollback timer
        Device-->>UCI: OK
    end

    State-->>Master: result=True, "applied and confirmed"
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

## Manual mode

When `mode = manual`, Salt stages UCI changes (`uci set`) but does not
call `uci apply` or `uci confirm`. The staging behavior differs by
transport because rpcd routes changes differently depending on whether
a session ID is present:

- **SSH transport** runs `ubus call uci set` without a session. Changes
  stage to `/tmp/.uci/`, visible to `uci changes` from CLI and LuCI.
  The operator can review and activate at their convenience.

- **JSON-RPC transport** passes the rpcd session token with every call.
  Changes stage to `/var/run/rpcd/uci-<session_id>/`, invisible to
  standard tooling and auto-cleaned when the session expires (~300s).
  Salt must `uci commit` to persist changes to `/etc/config/`.

**Current gap:** The activation step (operator runs `uci apply`) has no
rollback protection. rpcd's confirmed-commit mechanism (`uci apply
{"rollback":true}` + `uci confirm`) works on both transports -- even
over SSH via the local ubus socket -- but the extension does not yet
provide a Salt-side command to trigger it after review. The operator
must either use bare `uci apply` (no safety net) or manually run `ubus
call uci apply '{"rollback":true,"timeout":120}'` + `ubus call uci
confirm` on the device.

### Manual mode -- SSH transport

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
    UCI-->>State: {enabled: "1", mode: "manual"}

    Note over State: Mode = manual<br/>Override: apply_rollback = None

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

    alt Safe: apply with rollback (recommended)
        Human->>UCI: ubus call uci apply '{"rollback":true,"timeout":120}'
        UCI-->>Human: Applied + 120s rollback timer armed
        Note over Human: Verify connectivity / config
        Human->>UCI: ubus call uci confirm
        UCI-->>Human: Timer cancelled, changes permanent
    else Unsafe: bare apply (no rollback)
        Human->>UCI: uci commit && uci apply
        UCI-->>Human: Applied + services reloaded (no safety net)
    end
```

### Manual mode -- JSON-RPC transport

```{mermaid}
sequenceDiagram
    autonumber
    participant Master as Salt Master
    participant State as state.managed()
    participant UCI as UCI (JSON-RPC)
    participant Session as /var/run/rpcd/<br/>uci-<session_id>/
    participant Config as /etc/config/
    participant Human as Operator<br/>(LuCI / CLI)

    Master->>State: managed(config, sections)
    State->>UCI: get("salt-openwrt", "global")
    UCI-->>State: {enabled: "1", mode: "manual"}

    Note over State: Mode = manual<br/>Override: apply_rollback = None

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
            UCI->>Session: staged in session dir<br/>(auto-cleaned ~300s)
        end
    end

    rect rgb(250, 240, 230)
        Note over State,Config: Commit phase (JSON-RPC only)
        Note over State: Session-scoped staging is ephemeral<br/>Must commit to persist
        State->>UCI: commit(config)
        UCI->>Config: written to /etc/config/
    end

    Note over State: Skip apply -- services NOT reloaded

    State-->>Master: result=True, changes={...},<br/>"committed (not applied)"

    Note over Human: Later...

    alt Safe: apply with rollback (recommended)
        Human->>UCI: uci apply {"rollback":true,"timeout":120}
        UCI-->>Human: Applied + 120s rollback timer armed
        Note over Human: Verify connectivity / config
        Human->>UCI: uci confirm {}
        UCI-->>Human: Timer cancelled, changes permanent
    else Unsafe: bare apply (no rollback)
        Human->>UCI: uci apply
        UCI-->>Human: Services reloaded (no safety net)
    end
```

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
    UCI-->>State: {enabled: "0", mode: "auto"}

    Note over State: Device disabled, skip entirely

    State-->>Master: result=True,<br/>"salt-openwrt disabled on device, skipping"
```

## Graceful fallback (package not installed)

When `/etc/config/salt-openwrt` does not exist, the `get()` call raises
an exception. The state module catches it and defaults to `auto` mode,
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

    Note over State: Catch exception<br/>Default: enabled=True, mode="auto"

    Note over State: Continue with full auto flow...
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
    UCI-->>State: {enabled: "1", mode: "auto"}

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
