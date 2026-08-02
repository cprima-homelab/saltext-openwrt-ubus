"""
Unit tests for the uci state module.

All tests use mocked execution module calls. No network calls or device writes.
"""

from unittest.mock import MagicMock, patch

import pytest

import saltext.uci.states.saltext_ubus as state_mod

# --- Agent config (what uci.get returns for salt-openwrt) ---

AGENT_ONESHOT = {
    "_type": "salt-openwrt",
    "enabled": "1",
    "mode": "oneshot",
    "rollback_timeout": "120",
}
AGENT_AUDIT = {"_type": "salt-openwrt", "enabled": "1", "mode": "audit"}
AGENT_AUTOVERIFIED = {
    "_type": "salt-openwrt",
    "enabled": "1",
    "mode": "autoverified",
    "rollback_timeout": "120",
}
AGENT_HUMANREVIEWED = {
    "_type": "salt-openwrt",
    "enabled": "1",
    "mode": "humanreviewed",
    "rollback_timeout": "120",
}
AGENT_DISABLED = {"_type": "salt-openwrt", "enabled": "0", "mode": "oneshot"}

# --- Sample device state (what uci.get returns after _transform) ---

NETWORK_STATE = {
    "lan": {
        "_type": "interface",
        "_name": "lan",
        "_anonymous": False,
        "_index": 1,
        "proto": "static",
        "device": "br-lan",
        "ipaddr": "10.35.24.1",
        "netmask": "255.255.255.0",
    },
    "wan": {
        "_type": "interface",
        "_name": "wan",
        "_anonymous": False,
        "_index": 2,
        "proto": "static",
        "device": "eth1",
        "ipaddr": "192.168.16.99",
        "dns": ["1.1.1.1", "1.0.0.1"],
    },
}

SYSTEM_STATE = {
    "cfg01e48a": {
        "_type": "system",
        "_name": "cfg01e48a",
        "_anonymous": True,
        "_index": 0,
        "hostname": "austru",
        "zonename": "Europe/Berlin",
    },
    "ntp": {
        "_type": "timeserver",
        "_name": "ntp",
        "_anonymous": False,
        "_index": 1,
        "server": ["0.openwrt.pool.ntp.org", "1.openwrt.pool.ntp.org"],
    },
}


# --- Service list snapshots (what service list returns) ---

SERVICES_RUNNING = {
    "cron": {"instances": {"instance1": {"running": True, "pid": 1847}}},
    "dnsmasq": {"instances": {"cfg01411c": {"running": True, "pid": 2990}}},
    "network": {"instances": {"instance1": {"running": True, "pid": 1727}}},
    "sshd": {"instances": {"instance1": {"running": True, "pid": 1907}}},
}

SERVICES_AFTER_RESTART = {
    "cron": {"instances": {"instance1": {"running": True, "pid": 1847}}},
    "dnsmasq": {"instances": {"cfg01411c": {"running": True, "pid": 5001}}},
    "network": {"instances": {"instance1": {"running": True, "pid": 5002}}},
    "sshd": {"instances": {"instance1": {"running": True, "pid": 1907}}},
}

SERVICES_PARTIAL_DOWN = {
    "cron": {"instances": {"instance1": {"running": True, "pid": 1847}}},
    "dnsmasq": {"instances": {"cfg01411c": {"running": False}}},
    "network": {"instances": {"instance1": {"running": True, "pid": 5002}}},
    "sshd": {"instances": {"instance1": {"running": True, "pid": 1907}}},
}


@pytest.fixture(autouse=True)
def patch_dunders(monkeypatch):
    """Set up Salt dunders for the state module."""
    salt_fns = {}
    monkeypatch.setattr(state_mod, "__salt__", salt_fns, raising=False)
    monkeypatch.setattr(state_mod, "__opts__", {"test": False}, raising=False)
    return salt_fns


# --- Already in desired state ---


class TestAlreadyDesired:
    def test_no_changes_needed(self, patch_dunders):
        patch_dunders["uci.changes"] = MagicMock(return_value=[])
        patch_dunders["uci.get"] = MagicMock(return_value=NETWORK_STATE)

        ret = state_mod.managed(
            "test",
            "network",
            {"lan": {"_type": "interface", "proto": "static", "ipaddr": "10.35.24.1"}},
        )
        assert ret["result"] is True
        assert "already in desired state" in ret["comment"]
        assert not ret["changes"]


# --- Pending deltas ---


class TestPendingDeltas:
    def test_fails_when_pending_and_no_revert(self, patch_dunders):
        patch_dunders["uci.changes"] = MagicMock(return_value=[["set", "network.wan.proto", "dhcp"]])
        ret = state_mod.managed("test", "network", {"lan": {"proto": "static"}})
        assert ret["result"] is False
        assert "Uncommitted changes exist" in ret["comment"]

    def test_reverts_when_revert_pending_true(self, patch_dunders):
        patch_dunders["uci.changes"] = MagicMock(return_value=[["set", "network.wan.proto", "dhcp"]])
        patch_dunders["uci.revert"] = MagicMock()
        patch_dunders["uci.get"] = MagicMock(return_value=NETWORK_STATE)

        ret = state_mod.managed(
            "test",
            "network",
            {"lan": {"_type": "interface", "proto": "static", "ipaddr": "10.35.24.1"}},
            revert_pending=True,
        )
        patch_dunders["uci.revert"].assert_called_once_with("network")
        assert ret["result"] is True


# --- Test mode ---


class TestTestMode:
    def test_reports_would_change(self, patch_dunders, monkeypatch):
        monkeypatch.setattr(state_mod, "__opts__", {"test": True}, raising=False)
        patch_dunders["uci.changes"] = MagicMock(return_value=[])
        patch_dunders["uci.get"] = MagicMock(return_value=NETWORK_STATE)

        ret = state_mod.managed("test", "network", {"lan": {"_type": "interface", "ipaddr": "10.35.24.2"}})
        assert ret["result"] is None
        assert "would be updated" in ret["comment"]
        assert "lan" in ret["changes"]
        assert ret["changes"]["lan"]["ipaddr"]["old"] == "10.35.24.1"
        assert ret["changes"]["lan"]["ipaddr"]["new"] == "10.35.24.2"

    def test_no_revert_in_test_mode(self, patch_dunders, monkeypatch):
        monkeypatch.setattr(state_mod, "__opts__", {"test": True}, raising=False)
        patch_dunders["uci.changes"] = MagicMock(return_value=[["set", "network.wan.proto", "dhcp"]])
        patch_dunders["uci.revert"] = MagicMock()
        patch_dunders["uci.get"] = MagicMock(return_value=NETWORK_STATE)

        ret = state_mod.managed(
            "test",
            "network",
            {"lan": {"_type": "interface", "ipaddr": "10.35.24.2"}},
            revert_pending=True,
        )
        assert ret["result"] is None
        patch_dunders["uci.revert"].assert_not_called()


# --- Partial diff ---


class TestPartialDiff:
    def test_unmanaged_options_ignored(self, patch_dunders):
        patch_dunders["uci.changes"] = MagicMock(return_value=[])
        patch_dunders["uci.get"] = MagicMock(return_value=NETWORK_STATE)

        # Only manage proto, not device/ipaddr/netmask
        ret = state_mod.managed("test", "network", {"lan": {"proto": "static"}})
        assert ret["result"] is True
        assert not ret["changes"]

    @patch("saltext.uci.states.saltext_ubus.time")
    def test_detects_changed_option(self, mock_time, patch_dunders):
        mock_time.monotonic.side_effect = [0, 3]
        mock_time.sleep = MagicMock()
        patch_dunders["uci.changes"] = MagicMock(return_value=[])
        patch_dunders["uci.set"] = MagicMock()
        patch_dunders["uci.apply"] = MagicMock()
        # Return updated state on verify read
        updated = dict(NETWORK_STATE)
        updated["lan"] = dict(NETWORK_STATE["lan"])
        updated["lan"]["ipaddr"] = "10.35.24.2"
        patch_dunders["uci.get"] = MagicMock(side_effect=[AGENT_ONESHOT, NETWORK_STATE, updated])
        patch_dunders["uci.confirm"] = MagicMock()
        patch_dunders["uci.service_list"] = MagicMock(side_effect=[SERVICES_RUNNING, SERVICES_AFTER_RESTART])

        ret = state_mod.managed("test", "network", {"lan": {"ipaddr": "10.35.24.2"}})
        assert ret["result"] is True
        assert "lan" in ret["changes"]
        assert ret["changes"]["lan"]["ipaddr"]["old"] == "10.35.24.1"
        assert ret["changes"]["lan"]["ipaddr"]["new"] == "10.35.24.2"

    @patch("saltext.uci.states.saltext_ubus.time")
    def test_list_option_diff(self, mock_time, patch_dunders):
        mock_time.monotonic.side_effect = [0, 3]
        mock_time.sleep = MagicMock()
        patch_dunders["uci.changes"] = MagicMock(return_value=[])
        patch_dunders["uci.set"] = MagicMock()
        patch_dunders["uci.apply"] = MagicMock()
        updated = dict(NETWORK_STATE)
        updated["wan"] = dict(NETWORK_STATE["wan"])
        updated["wan"]["dns"] = ["8.8.8.8", "8.8.4.4"]
        patch_dunders["uci.get"] = MagicMock(side_effect=[AGENT_ONESHOT, NETWORK_STATE, updated])
        patch_dunders["uci.confirm"] = MagicMock()
        patch_dunders["uci.service_list"] = MagicMock(side_effect=[SERVICES_RUNNING, SERVICES_AFTER_RESTART])

        ret = state_mod.managed("test", "network", {"wan": {"dns": ["8.8.8.8", "8.8.4.4"]}})
        assert ret["result"] is True
        assert ret["changes"]["wan"]["dns"]["old"] == ["1.1.1.1", "1.0.0.1"]
        assert ret["changes"]["wan"]["dns"]["new"] == ["8.8.8.8", "8.8.4.4"]


# --- Singleton anonymous section resolution ---


class TestSingletonResolution:
    def test_resolves_singleton(self, patch_dunders):
        patch_dunders["uci.changes"] = MagicMock(return_value=[])
        patch_dunders["uci.get"] = MagicMock(return_value=SYSTEM_STATE)

        # _system with _type=system should resolve to cfg01e48a
        ret = state_mod.managed("test", "system", {"_system": {"_type": "system", "hostname": "austru"}})
        assert ret["result"] is True
        assert "already in desired state" in ret["comment"]

    @patch("saltext.uci.states.saltext_ubus.time")
    def test_singleton_with_change(self, mock_time, patch_dunders):
        mock_time.monotonic.side_effect = [0, 3]
        mock_time.sleep = MagicMock()
        patch_dunders["uci.changes"] = MagicMock(return_value=[])
        patch_dunders["uci.set"] = MagicMock()
        patch_dunders["uci.apply"] = MagicMock()
        updated = dict(SYSTEM_STATE)
        updated["cfg01e48a"] = dict(SYSTEM_STATE["cfg01e48a"])
        updated["cfg01e48a"]["hostname"] = "newname"
        patch_dunders["uci.get"] = MagicMock(side_effect=[AGENT_ONESHOT, SYSTEM_STATE, updated])
        patch_dunders["uci.confirm"] = MagicMock()
        patch_dunders["uci.service_list"] = MagicMock(side_effect=[SERVICES_RUNNING, SERVICES_AFTER_RESTART])

        ret = state_mod.managed("test", "system", {"_system": {"_type": "system", "hostname": "newname"}})
        assert ret["result"] is True
        # Resolved to the actual section name cfg01e48a
        assert "cfg01e48a" in ret["changes"]
        assert ret["changes"]["cfg01e48a"]["hostname"]["old"] == "austru"
        assert ret["changes"]["cfg01e48a"]["hostname"]["new"] == "newname"

    def test_fails_no_match(self, patch_dunders):
        patch_dunders["uci.changes"] = MagicMock(return_value=[])
        patch_dunders["uci.get"] = MagicMock(return_value=SYSTEM_STATE)

        ret = state_mod.managed("test", "system", {"_dnsmasq": {"_type": "dnsmasq", "option": "value"}})
        assert ret["result"] is False
        assert "No anonymous section of type 'dnsmasq'" in ret["comment"]

    def test_fails_multiple_matches(self, patch_dunders):
        state_with_dupes = {
            "cfg01": {"_type": "rule", "_anonymous": True, "name": "r1"},
            "cfg02": {"_type": "rule", "_anonymous": True, "name": "r2"},
        }
        patch_dunders["uci.changes"] = MagicMock(return_value=[])
        patch_dunders["uci.get"] = MagicMock(return_value=state_with_dupes)

        ret = state_mod.managed(
            "test",
            "firewall",
            {"_rule": {"_type": "rule", "name": "r1"}},
            allow_experimental=True,
        )
        assert ret["result"] is False
        assert "Multiple anonymous sections" in ret["comment"]


# --- Section creation ---


class TestSectionCreate:
    @patch("saltext.uci.states.saltext_ubus.time")
    def test_creates_new_section(self, mock_time, patch_dunders):
        mock_time.monotonic.side_effect = [0, 3]
        mock_time.sleep = MagicMock()
        patch_dunders["uci.changes"] = MagicMock(return_value=[])
        patch_dunders["uci.add"] = MagicMock()
        patch_dunders["uci.set"] = MagicMock()
        patch_dunders["uci.apply"] = MagicMock()
        # After apply, wan2 exists
        updated = dict(NETWORK_STATE)
        updated["wan2"] = {
            "_type": "interface",
            "_name": "wan2",
            "_anonymous": False,
            "proto": "dhcp",
        }
        patch_dunders["uci.get"] = MagicMock(side_effect=[AGENT_ONESHOT, NETWORK_STATE, updated])
        patch_dunders["uci.confirm"] = MagicMock()
        patch_dunders["uci.service_list"] = MagicMock(side_effect=[SERVICES_RUNNING, SERVICES_AFTER_RESTART])

        ret = state_mod.managed("test", "network", {"wan2": {"_type": "interface", "proto": "dhcp"}})
        assert ret["result"] is True
        patch_dunders["uci.add"].assert_called_once_with("network", "interface", name="wan2")

    def test_fails_without_type(self, patch_dunders):
        patch_dunders["uci.changes"] = MagicMock(return_value=[])
        patch_dunders["uci.get"] = MagicMock(return_value=NETWORK_STATE)

        ret = state_mod.managed("test", "network", {"wan2": {"proto": "dhcp"}})  # No _type
        assert ret["result"] is False
        assert "no _type specified" in ret["comment"]


# --- Type mismatch ---


class TestTypeMismatch:
    def test_fails_on_type_mismatch(self, patch_dunders):
        patch_dunders["uci.changes"] = MagicMock(return_value=[])
        patch_dunders["uci.get"] = MagicMock(return_value=NETWORK_STATE)

        # lan is type "interface", try to set it as "bridge"
        ret = state_mod.managed("test", "network", {"lan": {"_type": "bridge", "proto": "static"}})
        assert ret["result"] is False
        assert "Type mismatch" in ret["comment"]
        assert "'bridge'" in ret["comment"]
        assert "'interface'" in ret["comment"]


# --- Apply + verify + confirm ---


class TestApplyFlow:
    @patch("saltext.uci.states.saltext_ubus.time")
    def test_apply_verify_confirm(self, mock_time, patch_dunders):
        mock_time.monotonic.side_effect = [0, 3]
        mock_time.sleep = MagicMock()
        patch_dunders["uci.changes"] = MagicMock(return_value=[])
        updated = dict(NETWORK_STATE)
        updated["lan"] = dict(NETWORK_STATE["lan"])
        updated["lan"]["ipaddr"] = "10.35.24.2"
        patch_dunders["uci.get"] = MagicMock(side_effect=[AGENT_ONESHOT, NETWORK_STATE, updated])
        patch_dunders["uci.set"] = MagicMock()
        patch_dunders["uci.apply"] = MagicMock()
        patch_dunders["uci.confirm"] = MagicMock()
        patch_dunders["uci.service_list"] = MagicMock(side_effect=[SERVICES_RUNNING, SERVICES_AFTER_RESTART])

        ret = state_mod.managed("test", "network", {"lan": {"ipaddr": "10.35.24.2"}})
        assert ret["result"] is True
        patch_dunders["uci.set"].assert_called_once_with("network", "lan", {"ipaddr": "10.35.24.2"})
        patch_dunders["uci.apply"].assert_called_once_with(rollback=120)
        patch_dunders["uci.confirm"].assert_called_once()
        assert "applied, and confirmed" in ret["comment"]

    def test_verification_failure(self, patch_dunders):
        patch_dunders["uci.changes"] = MagicMock(return_value=[])
        # After apply, value doesn't match
        bad_state = dict(NETWORK_STATE)
        bad_state["lan"] = dict(NETWORK_STATE["lan"])
        bad_state["lan"]["ipaddr"] = "10.35.24.1"  # Still old value
        patch_dunders["uci.get"] = MagicMock(side_effect=[AGENT_ONESHOT, NETWORK_STATE, bad_state])
        patch_dunders["uci.set"] = MagicMock()
        patch_dunders["uci.apply"] = MagicMock()
        patch_dunders["uci.service_list"] = MagicMock(return_value=SERVICES_RUNNING)

        ret = state_mod.managed("test", "network", {"lan": {"ipaddr": "10.35.24.2"}})
        assert ret["result"] is False
        assert "Verification failed" in ret["comment"]
        assert "Rollback will revert" in ret["comment"]

    @patch("saltext.uci.states.saltext_ubus.time")
    def test_custom_rollback_timeout(self, mock_time, patch_dunders):
        mock_time.monotonic.side_effect = [0, 3]
        mock_time.sleep = MagicMock()
        patch_dunders["uci.changes"] = MagicMock(return_value=[])
        updated = dict(NETWORK_STATE)
        updated["lan"] = dict(NETWORK_STATE["lan"])
        updated["lan"]["proto"] = "dhcp"
        patch_dunders["uci.get"] = MagicMock(side_effect=[AGENT_ONESHOT, NETWORK_STATE, updated])
        patch_dunders["uci.set"] = MagicMock()
        patch_dunders["uci.apply"] = MagicMock()
        patch_dunders["uci.confirm"] = MagicMock()
        patch_dunders["uci.service_list"] = MagicMock(side_effect=[SERVICES_RUNNING, SERVICES_AFTER_RESTART])

        state_mod.managed(
            "test",
            "network",
            {"lan": {"proto": "dhcp"}},
            apply_rollback=120,
        )
        patch_dunders["uci.apply"].assert_called_once_with(rollback=120)

    @patch("saltext.uci.states.saltext_ubus.time")
    def test_oneshot_snapshots_and_polls(self, mock_time, patch_dunders):
        """managed() in oneshot mode does snapshot -> apply -> poll -> confirm."""
        mock_time.monotonic.side_effect = [0, 3]
        mock_time.sleep = MagicMock()
        patch_dunders["uci.changes"] = MagicMock(return_value=[])
        updated = dict(NETWORK_STATE)
        updated["lan"] = dict(NETWORK_STATE["lan"])
        updated["lan"]["ipaddr"] = "10.35.24.2"
        patch_dunders["uci.get"] = MagicMock(side_effect=[AGENT_ONESHOT, NETWORK_STATE, updated])
        patch_dunders["uci.set"] = MagicMock()
        patch_dunders["uci.apply"] = MagicMock()
        patch_dunders["uci.confirm"] = MagicMock()
        patch_dunders["uci.service_list"] = MagicMock(side_effect=[SERVICES_RUNNING, SERVICES_AFTER_RESTART])

        ret = state_mod.managed("test", "network", {"lan": {"ipaddr": "10.35.24.2"}})
        assert ret["result"] is True
        # service_list called twice: snapshot + one poll
        assert patch_dunders["uci.service_list"].call_count == 2
        patch_dunders["uci.confirm"].assert_called_once()

    @patch("saltext.uci.states.saltext_ubus.time")
    def test_oneshot_rollback_on_service_failure(self, mock_time, patch_dunders):
        """managed() in oneshot mode: services don't recover -> no confirm."""
        mock_time.monotonic.side_effect = [0, 200]
        mock_time.sleep = MagicMock()
        patch_dunders["uci.changes"] = MagicMock(return_value=[])
        updated = dict(NETWORK_STATE)
        updated["lan"] = dict(NETWORK_STATE["lan"])
        updated["lan"]["ipaddr"] = "10.35.24.2"
        patch_dunders["uci.get"] = MagicMock(side_effect=[AGENT_ONESHOT, NETWORK_STATE, updated])
        patch_dunders["uci.set"] = MagicMock()
        patch_dunders["uci.apply"] = MagicMock()
        patch_dunders["uci.service_list"] = MagicMock(side_effect=[SERVICES_RUNNING, SERVICES_PARTIAL_DOWN])

        ret = state_mod.managed("test", "network", {"lan": {"ipaddr": "10.35.24.2"}})
        assert ret["result"] is False
        assert "NOT confirming" in ret["comment"]
        assert "dnsmasq/cfg01411c" in ret["comment"]
        assert "uci.confirm" not in patch_dunders


# --- Helper functions ---


class TestDiffSection:
    def test_no_diff(self):
        desired = {"proto": "static", "ipaddr": "10.0.0.1"}
        current = {
            "_type": "interface",
            "proto": "static",
            "ipaddr": "10.0.0.1",
            "device": "br-lan",
        }
        assert not state_mod._diff_section(desired, current)

    def test_changed_option(self):
        desired = {"proto": "dhcp"}
        current = {"_type": "interface", "proto": "static"}
        diff = state_mod._diff_section(desired, current)
        assert diff == {"proto": {"old": "static", "new": "dhcp"}}

    def test_new_option(self):
        desired = {"dns": ["1.1.1.1"]}
        current = {"_type": "interface", "proto": "static"}
        diff = state_mod._diff_section(desired, current)
        assert diff == {"dns": {"old": None, "new": ["1.1.1.1"]}}

    def test_skips_metadata(self):
        desired = {"_type": "interface", "proto": "static"}
        current = {"_type": "interface", "proto": "static"}
        assert not state_mod._diff_section(desired, current)

    def test_list_change(self):
        desired = {"dns": ["8.8.8.8", "8.8.4.4"]}
        current = {"dns": ["1.1.1.1", "1.0.0.1"]}
        diff = state_mod._diff_section(desired, current)
        assert diff["dns"]["old"] == ["1.1.1.1", "1.0.0.1"]
        assert diff["dns"]["new"] == ["8.8.8.8", "8.8.4.4"]


class TestResolveSections:
    def test_named_sections_pass_through(self):
        sections = {"lan": {"proto": "static"}, "wan": {"proto": "dhcp"}}
        resolved, prune = state_mod._resolve_sections("network", sections, NETWORK_STATE)
        assert resolved == sections
        assert not prune

    def test_singleton_resolves(self):
        sections = {"_system": {"_type": "system", "hostname": "newname"}}
        resolved, prune = state_mod._resolve_sections("system", sections, SYSTEM_STATE)
        assert "cfg01e48a" in resolved
        assert "_system" not in resolved
        assert not prune

    def test_singleton_no_match_raises(self):
        sections = {"_dnsmasq": {"_type": "dnsmasq"}}
        with pytest.raises(ValueError, match="No anonymous section"):
            state_mod._resolve_sections("system", sections, SYSTEM_STATE)

    def test_singleton_multiple_raises(self):
        current = {
            "cfg01": {"_type": "rule", "_anonymous": True},
            "cfg02": {"_type": "rule", "_anonymous": True},
        }
        with pytest.raises(ValueError, match="Multiple anonymous sections"):
            state_mod._resolve_sections("firewall", {"_rule": {"_type": "rule"}}, current)


# --- Agent mode enforcement ---


class TestAgentMode:
    def test_audit_mode_reports_drift(self, patch_dunders):
        patch_dunders["uci.changes"] = MagicMock(return_value=[])
        patch_dunders["uci.get"] = MagicMock(side_effect=[AGENT_AUDIT, NETWORK_STATE])

        ret = state_mod.managed("test", "network", {"lan": {"ipaddr": "10.35.24.2"}})
        assert ret["result"] is True
        assert "audit mode" in ret["comment"]
        assert "1 section(s) drifted" in ret["comment"]
        assert "lan" in ret["changes"]
        # No write operations should have been called
        assert "uci.set" not in patch_dunders
        assert "uci.apply" not in patch_dunders
        assert "uci.confirm" not in patch_dunders

    def test_audit_mode_no_drift(self, patch_dunders):
        patch_dunders["uci.changes"] = MagicMock(return_value=[])
        patch_dunders["uci.get"] = MagicMock(side_effect=[AGENT_AUDIT, NETWORK_STATE])

        ret = state_mod.managed(
            "test",
            "network",
            {"lan": {"_type": "interface", "proto": "static", "ipaddr": "10.35.24.1"}},
        )
        assert ret["result"] is True
        assert "audit mode -- no drift detected" in ret["comment"]
        assert not ret["changes"]

    def test_autoverified_mode_jsonrpc_stages_no_commit(self, patch_dunders, monkeypatch):
        monkeypatch.setattr(
            state_mod,
            "__opts__",
            {"test": False, "proxy": {"proxytype": "uci_ubus_jsonrpc"}},
            raising=False,
        )
        patch_dunders["uci.changes"] = MagicMock(return_value=[])
        patch_dunders["uci.get"] = MagicMock(side_effect=[AGENT_AUTOVERIFIED, NETWORK_STATE])
        patch_dunders["uci.set"] = MagicMock()

        ret = state_mod.managed("test", "network", {"lan": {"ipaddr": "10.35.24.2"}})
        assert ret["result"] is True
        assert "staged in rpcd session" in ret["comment"]
        assert "uci.applied" in ret["comment"]
        patch_dunders["uci.set"].assert_called_once()
        assert "uci.commit" not in patch_dunders
        assert "uci.apply" not in patch_dunders
        assert "uci.confirm" not in patch_dunders

    def test_autoverified_mode_ssh_stages_no_commit(self, patch_dunders, monkeypatch):
        monkeypatch.setattr(
            state_mod,
            "__opts__",
            {"test": False, "proxy": {"proxytype": "uci_ssh"}},
            raising=False,
        )
        patch_dunders["uci.changes"] = MagicMock(return_value=[])
        patch_dunders["uci.get"] = MagicMock(side_effect=[AGENT_AUTOVERIFIED, NETWORK_STATE])
        patch_dunders["uci.set"] = MagicMock()

        ret = state_mod.managed("test", "network", {"lan": {"ipaddr": "10.35.24.2"}})
        assert ret["result"] is True
        assert "staged" in ret["comment"]
        assert "uci.applied" in ret["comment"]
        patch_dunders["uci.set"].assert_called_once()
        assert "uci.commit" not in patch_dunders
        assert "uci.apply" not in patch_dunders
        assert "uci.confirm" not in patch_dunders

    def test_humanreviewed_mode_stages_no_commit(self, patch_dunders, monkeypatch):
        monkeypatch.setattr(
            state_mod,
            "__opts__",
            {"test": False, "proxy": {"proxytype": "uci_ubus_jsonrpc"}},
            raising=False,
        )
        patch_dunders["uci.changes"] = MagicMock(return_value=[])
        patch_dunders["uci.get"] = MagicMock(side_effect=[AGENT_HUMANREVIEWED, NETWORK_STATE])
        patch_dunders["uci.set"] = MagicMock()

        ret = state_mod.managed("test", "network", {"lan": {"ipaddr": "10.35.24.2"}})
        assert ret["result"] is True
        assert "staged in rpcd session" in ret["comment"]
        patch_dunders["uci.set"].assert_called_once()
        assert "uci.apply" not in patch_dunders
        assert "uci.confirm" not in patch_dunders

    def test_disabled_skips_everything(self, patch_dunders):
        patch_dunders["uci.get"] = MagicMock(return_value=AGENT_DISABLED)

        ret = state_mod.managed("test", "network", {"lan": {"ipaddr": "10.35.24.2"}})
        assert ret["result"] is True
        assert "salt-openwrt disabled" in ret["comment"]
        # Only one get call (agent config), no changes/set/apply
        patch_dunders["uci.get"].assert_called_once_with("salt-openwrt", "global")

    def test_missing_config_defaults_oneshot(self, patch_dunders):
        """When salt-openwrt config is absent, default to oneshot mode."""
        patch_dunders["uci.changes"] = MagicMock(return_value=[])
        call_count = [0]
        original_state = NETWORK_STATE

        def get_side_effect(*args, **kwargs):  # pylint: disable=unused-argument
            call_count[0] += 1
            if call_count[0] == 1:
                # First call is agent config -- raise to simulate missing config
                raise KeyError("salt-openwrt")
            return original_state

        patch_dunders["uci.get"] = MagicMock(side_effect=get_side_effect)

        ret = state_mod.managed(
            "test",
            "network",
            {"lan": {"_type": "interface", "proto": "static", "ipaddr": "10.35.24.1"}},
        )
        # Should proceed in oneshot mode, no drift
        assert ret["result"] is True
        assert "already in desired state" in ret["comment"]


# --- Applied state ---


class TestApplied:
    @patch("saltext.uci.states.saltext_ubus.time")
    def test_apply_confirm_with_service_check(self, mock_time, patch_dunders):
        """Happy path: snapshot -> apply -> poll (all back) -> confirm."""
        mock_time.monotonic.side_effect = [0, 3]  # deadline calc, first poll check
        mock_time.sleep = MagicMock()
        patch_dunders["uci.get"] = MagicMock(return_value=AGENT_ONESHOT)
        patch_dunders["uci.apply"] = MagicMock()
        patch_dunders["uci.confirm"] = MagicMock()
        patch_dunders["uci.service_list"] = MagicMock(side_effect=[SERVICES_RUNNING, SERVICES_AFTER_RESTART])

        ret = state_mod.applied("test", config="network")
        assert ret["result"] is True
        assert "applied and confirmed" in ret["comment"]
        assert "4 service(s) verified running" in ret["comment"]
        patch_dunders["uci.apply"].assert_called_once_with(rollback=120)
        patch_dunders["uci.confirm"].assert_called_once()

    @patch("saltext.uci.states.saltext_ubus.time")
    def test_services_recover_after_delay(self, mock_time, patch_dunders):
        """service_list returns partial-down on first poll, all-up on second."""
        mock_time.monotonic.side_effect = [0, 3, 6]  # deadline calc, poll 1, poll 2
        mock_time.sleep = MagicMock()
        patch_dunders["uci.get"] = MagicMock(return_value=AGENT_ONESHOT)
        patch_dunders["uci.apply"] = MagicMock()
        patch_dunders["uci.confirm"] = MagicMock()
        patch_dunders["uci.service_list"] = MagicMock(
            side_effect=[SERVICES_RUNNING, SERVICES_PARTIAL_DOWN, SERVICES_AFTER_RESTART]
        )

        ret = state_mod.applied("test", config="network")
        assert ret["result"] is True
        assert "applied and confirmed" in ret["comment"]
        patch_dunders["uci.confirm"].assert_called_once()

    @patch("saltext.uci.states.saltext_ubus.time")
    def test_services_not_recovered_no_confirm(self, mock_time, patch_dunders):
        """Poll always returns partial-down -> no confirm, lists down services."""
        # deadline calc returns 0, first poll check exceeds deadline
        mock_time.monotonic.side_effect = [0, 200]
        mock_time.sleep = MagicMock()
        patch_dunders["uci.get"] = MagicMock(return_value=AGENT_ONESHOT)
        patch_dunders["uci.apply"] = MagicMock()
        patch_dunders["uci.service_list"] = MagicMock(side_effect=[SERVICES_RUNNING, SERVICES_PARTIAL_DOWN])

        ret = state_mod.applied("test", config="network")
        assert ret["result"] is False
        assert "NOT confirming" in ret["comment"]
        assert "dnsmasq/cfg01411c" in ret["comment"]
        assert "uci.confirm" not in patch_dunders

    def test_apply_without_config(self, patch_dunders):
        """applied() without config labels as 'all'."""
        patch_dunders["uci.get"] = MagicMock(return_value=AGENT_ONESHOT)
        patch_dunders["uci.apply"] = MagicMock()
        patch_dunders["uci.confirm"] = MagicMock()
        # No running services -> empty snapshot -> skip polling
        patch_dunders["uci.service_list"] = MagicMock(return_value={})

        ret = state_mod.applied("test")
        assert ret["result"] is True
        assert "all: applied and confirmed" in ret["comment"]

    def test_disabled_skips(self, patch_dunders):
        patch_dunders["uci.get"] = MagicMock(return_value=AGENT_DISABLED)

        ret = state_mod.applied("test", config="network")
        assert ret["result"] is True
        assert "salt-openwrt disabled" in ret["comment"]
        patch_dunders["uci.get"].assert_called_once_with("salt-openwrt", "global")

    def test_test_mode(self, patch_dunders, monkeypatch):
        monkeypatch.setattr(state_mod, "__opts__", {"test": True}, raising=False)
        patch_dunders["uci.get"] = MagicMock(return_value=AGENT_ONESHOT)

        ret = state_mod.applied("test", config="network")
        assert ret["result"] is None
        assert "would apply" in ret["comment"]
        assert "uci.apply" not in patch_dunders

    def test_apply_failure(self, patch_dunders):
        patch_dunders["uci.get"] = MagicMock(return_value=AGENT_ONESHOT)
        patch_dunders["uci.apply"] = MagicMock(side_effect=RuntimeError("connection lost"))
        patch_dunders["uci.service_list"] = MagicMock(return_value=SERVICES_RUNNING)

        ret = state_mod.applied("test", config="network")
        assert ret["result"] is False
        assert "Failed to apply" in ret["comment"]
        assert "connection lost" in ret["comment"]

    def test_apply_noop_status5(self, patch_dunders):
        """ubus status 5 (No data) means nothing to apply -- no snapshot/poll."""
        patch_dunders["uci.get"] = MagicMock(return_value=AGENT_ONESHOT)
        patch_dunders["uci.service_list"] = MagicMock(return_value=SERVICES_RUNNING)
        patch_dunders["uci.apply"] = MagicMock(side_effect=RuntimeError("ubus call failed: status 5 (No data)"))

        ret = state_mod.applied("test")
        assert ret["result"] is True
        assert "nothing to apply" in ret["comment"]

    @patch("saltext.uci.states.saltext_ubus.time")
    def test_confirm_failure(self, mock_time, patch_dunders):
        """Services come back but confirm() raises."""
        mock_time.monotonic.side_effect = [0, 3]
        mock_time.sleep = MagicMock()
        patch_dunders["uci.get"] = MagicMock(return_value=AGENT_ONESHOT)
        patch_dunders["uci.apply"] = MagicMock()
        patch_dunders["uci.service_list"] = MagicMock(side_effect=[SERVICES_RUNNING, SERVICES_AFTER_RESTART])
        patch_dunders["uci.confirm"] = MagicMock(side_effect=RuntimeError("confirm failed"))

        ret = state_mod.applied("test", config="network")
        assert ret["result"] is False
        assert "Failed to confirm" in ret["comment"]
        assert "Rollback will revert" in ret["comment"]

    @patch("saltext.uci.states.saltext_ubus.time")
    def test_custom_rollback(self, mock_time, patch_dunders):
        mock_time.monotonic.side_effect = [0, 3]
        mock_time.sleep = MagicMock()
        patch_dunders["uci.get"] = MagicMock(return_value=AGENT_ONESHOT)
        patch_dunders["uci.apply"] = MagicMock()
        patch_dunders["uci.confirm"] = MagicMock()
        patch_dunders["uci.service_list"] = MagicMock(side_effect=[SERVICES_RUNNING, SERVICES_AFTER_RESTART])

        ret = state_mod.applied("test", config="network", rollback=180)
        assert ret["result"] is True
        patch_dunders["uci.apply"].assert_called_once_with(rollback=180)

    @patch("saltext.uci.states.saltext_ubus.time")
    def test_rollback_timeout_from_device_config(self, mock_time, patch_dunders):
        """rollback_timeout is read from device config when rollback=None."""
        mock_time.monotonic.side_effect = [0, 3]
        mock_time.sleep = MagicMock()
        agent = dict(AGENT_ONESHOT)
        agent["rollback_timeout"] = "90"
        patch_dunders["uci.get"] = MagicMock(return_value=agent)
        patch_dunders["uci.apply"] = MagicMock()
        patch_dunders["uci.confirm"] = MagicMock()
        patch_dunders["uci.service_list"] = MagicMock(side_effect=[SERVICES_RUNNING, SERVICES_AFTER_RESTART])

        ret = state_mod.applied("test", config="network")
        assert ret["result"] is True
        patch_dunders["uci.apply"].assert_called_once_with(rollback=90)

    def test_snapshot_failure_skips_health_check(self, patch_dunders):
        """If service_list fails on snapshot, proceed without health check."""
        patch_dunders["uci.get"] = MagicMock(return_value=AGENT_ONESHOT)
        patch_dunders["uci.apply"] = MagicMock()
        patch_dunders["uci.confirm"] = MagicMock()
        patch_dunders["uci.service_list"] = MagicMock(side_effect=RuntimeError("ubus unavailable"))

        ret = state_mod.applied("test", config="network")
        assert ret["result"] is True
        assert "applied and confirmed" in ret["comment"]
        patch_dunders["uci.confirm"].assert_called_once()


# --- Multi-instance anonymous section management ---

# Device state simulating DHCP hosts (anonymous sections matched by 'name')
DHCP_STATE = {
    "cfg0a": {
        "_type": "host",
        "_name": "cfg0a",
        "_anonymous": True,
        "_index": 0,
        "name": "heckle_cam",
        "mac": "DE:AD:BE:EF:00:01",
        "ip": "10.99.42.10",
        "leasetime": "12h",
    },
    "cfg0b": {
        "_type": "host",
        "_name": "cfg0b",
        "_anonymous": True,
        "_index": 1,
        "name": "overhead_cam",
        "mac": "DE:AD:BE:EF:00:02",
        "ip": "10.99.42.11",
        "leasetime": "12h",
    },
    "cfg0c": {
        "_type": "host",
        "_name": "cfg0c",
        "_anonymous": True,
        "_index": 2,
        "name": "face_cam",
        "mac": "DE:AD:BE:EF:00:03",
        "ip": "10.99.42.12",
        "leasetime": "12h",
    },
    "lan": {
        "_type": "dhcp",
        "_name": "lan",
        "_anonymous": False,
        "_index": 3,
        "interface": "lan",
    },
}

# Device state simulating firewall forwardings (composite match key)
FIREWALL_FWD_STATE = {
    "cfg10": {
        "_type": "forwarding",
        "_name": "cfg10",
        "_anonymous": True,
        "_index": 0,
        "src": "lan",
        "dest": "wan",
    },
    "cfg11": {
        "_type": "forwarding",
        "_name": "cfg11",
        "_anonymous": True,
        "_index": 1,
        "src": "guest",
        "dest": "wan",
    },
}

# Device state simulating firewall rules (order matters)
FIREWALL_RULES_STATE = {
    "cfg20": {
        "_type": "rule",
        "_name": "cfg20",
        "_anonymous": True,
        "_index": 0,
        "name": "Allow SSH",
        "src": "lan",
        "dest_port": "22",
        "target": "ACCEPT",
    },
    "cfg21": {
        "_type": "rule",
        "_name": "cfg21",
        "_anonymous": True,
        "_index": 1,
        "name": "Block telemetry",
        "src": "lan",
        "dest_ip": "203.0.113.0/24",
        "target": "REJECT",
    },
    "cfg22": {
        "_type": "rule",
        "_name": "cfg22",
        "_anonymous": True,
        "_index": 2,
        "name": "Drop all",
        "src": "*",
        "target": "DROP",
    },
}


class TestMultiInstanceResolve:
    """Tests for _resolve_multi_instance() via _resolve_sections()."""

    def test_match_single_key(self):
        """Match anonymous sections by single 'name' option."""
        sections = {
            "_hosts": {
                "_type": "host",
                "_match": "name",
                "_items": [
                    {"name": "heckle_cam", "mac": "DE:AD:BE:EF:00:01", "ip": "10.99.42.10"},
                    {"name": "overhead_cam", "mac": "DE:AD:BE:EF:00:02", "ip": "10.99.42.11"},
                ],
            }
        }
        resolved, prune = state_mod._resolve_sections("dhcp", sections, DHCP_STATE)
        # Should resolve to actual device section names
        assert "cfg0a" in resolved  # heckle_cam
        assert "cfg0b" in resolved  # overhead_cam
        assert "_hosts" not in resolved
        assert not prune

    def test_match_composite_key(self):
        """Match anonymous sections by composite (src, dest) key."""
        sections = {
            "_forwardings": {
                "_type": "forwarding",
                "_match": ["src", "dest"],
                "_items": [
                    {"src": "lan", "dest": "wan"},
                ],
            }
        }
        resolved, prune = state_mod._resolve_sections("firewall", sections, FIREWALL_FWD_STATE)
        assert "cfg10" in resolved  # lan->wan
        assert "cfg11" not in resolved  # guest->wan not in pillar
        assert not prune

    def test_new_item_triggers_add(self):
        """Pillar item with no device match creates placeholder for anonymous add."""
        sections = {
            "_hosts": {
                "_type": "host",
                "_match": "name",
                "_items": [
                    {"name": "heckle_cam", "mac": "DE:AD:BE:EF:00:01", "ip": "10.99.42.10"},
                    {"name": "new_device", "mac": "AA:BB:CC:DD:EE:FF", "ip": "10.99.42.99"},
                ],
            }
        }
        resolved, _prune = state_mod._resolve_sections("dhcp", sections, DHCP_STATE)
        assert "cfg0a" in resolved  # existing heckle_cam
        # New item gets placeholder name
        new_keys = [k for k in resolved if k.startswith("_new_")]
        assert len(new_keys) == 1
        assert resolved[new_keys[0]]["_anonymous_new"] is True
        assert resolved[new_keys[0]]["name"] == "new_device"

    def test_prune_false_default(self):
        """Unmatched device sections left alone when _prune is not set."""
        sections = {
            "_hosts": {
                "_type": "host",
                "_match": "name",
                "_items": [
                    {"name": "heckle_cam", "mac": "DE:AD:BE:EF:00:01", "ip": "10.99.42.10"},
                ],
            }
        }
        _resolved, prune = state_mod._resolve_sections("dhcp", sections, DHCP_STATE)
        # cfg0b (overhead) and cfg0c (face_cam) not in pillar but not pruned
        assert not prune

    def test_prune_true(self):
        """Unmatched device sections are pruned when _prune=True."""
        sections = {
            "_hosts": {
                "_type": "host",
                "_match": "name",
                "_prune": True,
                "_items": [
                    {"name": "heckle_cam", "mac": "DE:AD:BE:EF:00:01", "ip": "10.99.42.10"},
                ],
            }
        }
        _resolved, prune = state_mod._resolve_sections("dhcp", sections, DHCP_STATE)
        # cfg0b and cfg0c should be pruned (unmatched host sections)
        assert "cfg0b" in prune
        assert "cfg0c" in prune
        assert "cfg0a" not in prune  # matched, not pruned

    def test_order_correct_no_reorder(self):
        """No reorder when device section order matches pillar order."""
        sections = {
            "_rules": {
                "_type": "rule",
                "_match": "name",
                "_items": [
                    {"name": "Allow SSH", "target": "ACCEPT"},
                    {"name": "Block telemetry", "target": "REJECT"},
                    {"name": "Drop all", "target": "DROP"},
                ],
            }
        }
        resolved, prune = state_mod._resolve_sections("firewall", sections, FIREWALL_RULES_STATE)
        # All matched to existing sections, no reorder
        assert "cfg20" in resolved
        assert "cfg21" in resolved
        assert "cfg22" in resolved
        assert not prune
        # No _anonymous_new placeholders
        assert not any(k.startswith("_new_") for k in resolved)

    def test_order_correct_with_new_item(self):
        """No reorder when existing items are in correct order and a new item is appended."""
        sections = {
            "_rules": {
                "_type": "rule",
                "_match": "name",
                "_items": [
                    {"name": "Allow SSH", "target": "ACCEPT"},
                    {"name": "Block telemetry", "target": "REJECT"},
                    {"name": "Drop all", "target": "DROP"},
                    {"name": "New rule", "target": "ACCEPT"},  # new, not on device
                ],
            }
        }
        resolved, prune = state_mod._resolve_sections("firewall", sections, FIREWALL_RULES_STATE)
        # Existing sections matched, no reorder
        assert "cfg20" in resolved
        assert "cfg21" in resolved
        assert "cfg22" in resolved
        assert not prune
        # Only the new item should be a placeholder
        new_keys = [k for k in resolved if k.startswith("_new_")]
        assert len(new_keys) == 1
        assert resolved[new_keys[0]]["_anonymous_new"] is True
        assert resolved[new_keys[0]]["name"] == "New rule"

    def test_order_wrong_triggers_reorder(self):
        """Reorder via delete+re-add when device order differs from pillar."""
        sections = {
            "_rules": {
                "_type": "rule",
                "_match": "name",
                "_items": [
                    # Reversed order from device
                    {"name": "Drop all", "target": "DROP"},
                    {"name": "Block telemetry", "target": "REJECT"},
                    {"name": "Allow SSH", "target": "ACCEPT"},
                ],
            }
        }
        resolved, prune = state_mod._resolve_sections("firewall", sections, FIREWALL_RULES_STATE)
        # All existing sections should be in prune (deleted for reorder)
        assert "cfg20" in prune
        assert "cfg21" in prune
        assert "cfg22" in prune
        # All items should be new placeholders
        new_keys = [k for k in resolved if k.startswith("_new_")]
        assert len(new_keys) == 3
        for k in new_keys:
            assert resolved[k]["_anonymous_new"] is True

    def test_idempotent_no_changes(self, patch_dunders):
        """Second run with matching state produces no changes."""
        patch_dunders["uci.changes"] = MagicMock(return_value=[])
        patch_dunders["uci.get"] = MagicMock(return_value=DHCP_STATE)

        ret = state_mod.managed(
            "test",
            "dhcp",
            {
                "_hosts": {
                    "_type": "host",
                    "_match": "name",
                    "_items": [
                        {
                            "name": "heckle_cam",
                            "mac": "DE:AD:BE:EF:00:01",
                            "ip": "10.99.42.10",
                            "leasetime": "12h",
                        },
                        {
                            "name": "overhead_cam",
                            "mac": "DE:AD:BE:EF:00:02",
                            "ip": "10.99.42.11",
                            "leasetime": "12h",
                        },
                        {
                            "name": "face_cam",
                            "mac": "DE:AD:BE:EF:00:03",
                            "ip": "10.99.42.12",
                            "leasetime": "12h",
                        },
                    ],
                }
            },
        )
        assert ret["result"] is True
        assert "already in desired state" in ret["comment"]
        assert not ret["changes"]

    def test_mixed_named_and_anonymous(self, patch_dunders):
        """Same config has both named and multi-instance sections."""
        patch_dunders["uci.changes"] = MagicMock(return_value=[])
        patch_dunders["uci.get"] = MagicMock(return_value=DHCP_STATE)

        ret = state_mod.managed(
            "test",
            "dhcp",
            {
                # Named section (existing)
                "lan": {"_type": "dhcp", "interface": "lan"},
                # Multi-instance anonymous
                "_hosts": {
                    "_type": "host",
                    "_match": "name",
                    "_items": [
                        {
                            "name": "heckle_cam",
                            "mac": "DE:AD:BE:EF:00:01",
                            "ip": "10.99.42.10",
                            "leasetime": "12h",
                        },
                    ],
                },
            },
        )
        assert ret["result"] is True
        assert "already in desired state" in ret["comment"]


# --- Absent sentinel tests ---


class TestAbsentOption:
    """Tests for _absent sentinel on options."""

    def test_absent_option_detected(self):
        """_absent on existing option produces a diff."""
        desired = {"proto": "static", "netmask": "_absent"}
        current = {
            "_type": "interface",
            "proto": "static",
            "netmask": "255.255.255.0",
        }
        diff = state_mod._diff_section(desired, current)
        assert "netmask" in diff
        assert diff["netmask"]["old"] == "255.255.255.0"
        assert diff["netmask"]["new"] == "_absent"

    def test_absent_option_not_present(self):
        """_absent on missing option produces no diff."""
        desired = {"proto": "static", "netmask": "_absent"}
        current = {"_type": "interface", "proto": "static"}
        diff = state_mod._diff_section(desired, current)
        assert "netmask" not in diff

    def test_absent_section(self, patch_dunders):
        """_absent on entire section marks it for deletion."""
        patch_dunders["uci.changes"] = MagicMock(return_value=[])
        patch_dunders["uci.get"] = MagicMock(return_value=NETWORK_STATE)

        sections = {
            "lan": {"_type": "interface", "proto": "static", "ipaddr": "10.35.24.1"},
            "wan": "_absent",
        }
        resolved, _prune = state_mod._resolve_sections("network", sections, NETWORK_STATE)
        assert resolved["wan"] == "_absent"

    def test_absent_section_not_present(self, patch_dunders):
        """_absent on non-existent section produces no changes."""
        patch_dunders["uci.changes"] = MagicMock(return_value=[])
        patch_dunders["uci.get"] = MagicMock(return_value=NETWORK_STATE)

        ret = state_mod.managed(
            "test",
            "network",
            {"nonexistent": "_absent"},
        )
        assert ret["result"] is True
        assert "already in desired state" in ret["comment"]

    def test_absent_section_exists_audit_mode(self, patch_dunders):
        """_absent on existing section reports drift in audit mode."""
        patch_dunders["uci.changes"] = MagicMock(return_value=[])
        patch_dunders["uci.get"] = MagicMock(side_effect=[AGENT_AUDIT, NETWORK_STATE])

        ret = state_mod.managed("test", "network", {"wan": "_absent"})
        assert ret["result"] is True
        assert "audit mode" in ret["comment"]
        assert "wan" in ret["changes"]
        assert ret["changes"]["wan"]["_action"] == "delete"

    def test_absent_section_staged(self, patch_dunders):
        """_absent on existing section triggers delete in autoverified mode."""
        patch_dunders["uci.changes"] = MagicMock(return_value=[])
        patch_dunders["uci.get"] = MagicMock(side_effect=[AGENT_AUTOVERIFIED, NETWORK_STATE])
        patch_dunders["uci.delete"] = MagicMock()

        ret = state_mod.managed("test", "network", {"wan": "_absent"})
        assert ret["result"] is True
        patch_dunders["uci.delete"].assert_called_once_with("network", "wan")


# --- Stage changes tests ---


class TestStageChanges:
    """Tests for _stage_changes() with new action types."""

    def test_anonymous_add(self, patch_dunders):
        """Anonymous section creation calls add() without name."""
        patch_dunders["uci.add"] = MagicMock(return_value="cfg0f")
        patch_dunders["uci.set"] = MagicMock()

        resolved = {
            "_new_host_0": {
                "_type": "host",
                "_anonymous_new": True,
                "name": "new_dev",
                "mac": "AA:BB:CC:DD:EE:FF",
            }
        }
        all_changes = {
            "_new_host_0": {
                "name": {"old": None, "new": "new_dev"},
                "mac": {"old": None, "new": "AA:BB:CC:DD:EE:FF"},
            }
        }
        ret = {"result": True, "comment": ""}
        state_mod._stage_changes(ret, "dhcp", all_changes, resolved, current={})
        assert ret["result"] is True
        patch_dunders["uci.add"].assert_called_once_with("dhcp", "host")
        patch_dunders["uci.set"].assert_called_once_with(
            "dhcp", "cfg0f", {"name": "new_dev", "mac": "AA:BB:CC:DD:EE:FF"}
        )

    def test_section_delete(self, patch_dunders):
        """Section deletion calls delete() on the section."""
        patch_dunders["uci.delete"] = MagicMock()

        all_changes = {"cfg0b": {"_action": "delete"}}
        ret = {"result": True, "comment": ""}
        state_mod._stage_changes(ret, "dhcp", all_changes, resolved={}, current=DHCP_STATE)
        assert ret["result"] is True
        patch_dunders["uci.delete"].assert_called_once_with("dhcp", "cfg0b")

    def test_option_absent_delete(self, patch_dunders):
        """_absent option calls delete() on the option."""
        patch_dunders["uci.set"] = MagicMock()
        patch_dunders["uci.delete"] = MagicMock()

        all_changes = {
            "lan": {
                "ipaddr": {"old": "10.35.24.1", "new": "10.35.24.2"},
                "netmask": {"old": "255.255.255.0", "new": "_absent"},
            }
        }
        ret = {"result": True, "comment": ""}
        state_mod._stage_changes(ret, "network", all_changes, resolved={}, current=NETWORK_STATE)
        assert ret["result"] is True
        patch_dunders["uci.set"].assert_called_once_with("network", "lan", {"ipaddr": "10.35.24.2"})
        patch_dunders["uci.delete"].assert_called_once_with("network", "lan", "netmask")

    def test_deletes_before_adds(self, patch_dunders):
        """Deletions are processed before additions (for reorder)."""
        call_order = []
        patch_dunders["uci.delete"] = MagicMock(side_effect=lambda *a, **kw: call_order.append(("delete", a)))
        patch_dunders["uci.add"] = MagicMock(side_effect=lambda *a, **kw: (call_order.append(("add", a)), "cfg_new")[1])
        patch_dunders["uci.set"] = MagicMock(side_effect=lambda *a, **kw: call_order.append(("set", a)))

        resolved = {
            "_new_rule_0": {
                "_type": "rule",
                "_anonymous_new": True,
                "name": "Allow SSH",
                "target": "ACCEPT",
            }
        }
        all_changes = {
            "cfg20": {"_action": "delete"},
            "_new_rule_0": {
                "name": {"old": None, "new": "Allow SSH"},
                "target": {"old": None, "new": "ACCEPT"},
            },
        }
        current = {"cfg20": FIREWALL_RULES_STATE["cfg20"]}
        ret = {"result": True, "comment": ""}
        state_mod._stage_changes(ret, "firewall", all_changes, resolved, current)

        # First call should be delete, then add
        assert call_order[0][0] == "delete"
        add_idx = next(i for i, (op, _) in enumerate(call_order) if op == "add")
        assert add_idx > 0


# --- Package scope gate ---


class TestPackageScope:
    """Tests for the package scope gate in managed()."""

    def test_stable_package_proceeds(self, patch_dunders):
        """Stable package (network) passes scope gate normally."""
        patch_dunders["uci.changes"] = MagicMock(return_value=[])
        patch_dunders["uci.get"] = MagicMock(return_value=NETWORK_STATE)

        ret = state_mod.managed(
            "test",
            "network",
            {"lan": {"_type": "interface", "proto": "static", "ipaddr": "10.35.24.1"}},
        )
        assert ret["result"] is True
        assert "already in desired state" in ret["comment"]

    def test_experimental_without_optin_fails(self, patch_dunders):
        """Experimental package without opt-in fails with guidance."""
        patch_dunders["pillar.get"] = MagicMock(return_value=False)

        ret = state_mod.managed("test", "firewall", {"_defaults": {"_type": "defaults", "input": "ACCEPT"}})
        assert ret["result"] is False
        assert "experimental support" in ret["comment"]
        assert "allow_experimental=True" in ret["comment"]

    def test_experimental_with_param_true_proceeds(self, patch_dunders):
        """Experimental package with allow_experimental=True param proceeds."""
        patch_dunders["uci.changes"] = MagicMock(return_value=[])
        patch_dunders["uci.get"] = MagicMock(return_value={})

        ret = state_mod.managed(
            "test",
            "firewall",
            {"_defaults": {"_type": "defaults", "input": "ACCEPT"}},
            allow_experimental=True,
        )
        # Should get past scope gate (may fail later, but not on scope)
        assert "experimental support" not in ret.get("comment", "")

    def test_experimental_with_pillar_true_proceeds(self, patch_dunders):
        """Experimental package with pillar openwrt:allow_experimental proceeds."""
        patch_dunders["pillar.get"] = MagicMock(return_value=True)
        patch_dunders["uci.changes"] = MagicMock(return_value=[])
        patch_dunders["uci.get"] = MagicMock(return_value={})

        ret = state_mod.managed(
            "test",
            "firewall",
            {"_defaults": {"_type": "defaults", "input": "ACCEPT"}},
        )
        # Should get past scope gate
        assert "experimental support" not in ret.get("comment", "")

    def test_param_false_overrides_pillar_true(self, patch_dunders):
        """Explicit allow_experimental=False overrides pillar True."""
        patch_dunders["pillar.get"] = MagicMock(return_value=True)

        ret = state_mod.managed(
            "test",
            "firewall",
            {"_defaults": {"_type": "defaults", "input": "ACCEPT"}},
            allow_experimental=False,
        )
        assert ret["result"] is False
        assert "experimental support" in ret["comment"]
        # pillar.get should NOT have been called
        patch_dunders["pillar.get"].assert_not_called()

    def test_unregistered_package_fails(self):
        """Unregistered package fails with supported-packages list."""
        ret = state_mod.managed("test", "uhttpd", {"main": {"listen_http": "0.0.0.0:80"}})
        assert ret["result"] is False
        assert "not in saltext-uci-ubus scope" in ret["comment"]
        assert "network" in ret["comment"]  # listed in supported packages
