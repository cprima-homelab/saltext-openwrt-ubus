"""
Unit tests for the openwrt_ubus state module.

All tests use mocked execution module calls. No network calls or device writes.
"""

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

import saltext.openwrt_ubus.states.saltext_ubus as state_mod

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
        patch_dunders["openwrt_ubus.changes"] = MagicMock(return_value=[])
        patch_dunders["openwrt_ubus.get"] = MagicMock(return_value=NETWORK_STATE)

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
        patch_dunders["openwrt_ubus.changes"] = MagicMock(
            return_value=[["set", "network.wan.proto", "dhcp"]]
        )
        ret = state_mod.managed("test", "network", {"lan": {"proto": "static"}})
        assert ret["result"] is False
        assert "Uncommitted changes exist" in ret["comment"]

    def test_reverts_when_revert_pending_true(self, patch_dunders):
        patch_dunders["openwrt_ubus.changes"] = MagicMock(
            return_value=[["set", "network.wan.proto", "dhcp"]]
        )
        patch_dunders["openwrt_ubus.revert"] = MagicMock()
        patch_dunders["openwrt_ubus.get"] = MagicMock(return_value=NETWORK_STATE)

        ret = state_mod.managed(
            "test",
            "network",
            {"lan": {"_type": "interface", "proto": "static", "ipaddr": "10.35.24.1"}},
            revert_pending=True,
        )
        patch_dunders["openwrt_ubus.revert"].assert_called_once_with("network")
        assert ret["result"] is True


# --- Test mode ---


class TestTestMode:
    def test_reports_would_change(self, patch_dunders, monkeypatch):
        monkeypatch.setattr(state_mod, "__opts__", {"test": True}, raising=False)
        patch_dunders["openwrt_ubus.changes"] = MagicMock(return_value=[])
        patch_dunders["openwrt_ubus.get"] = MagicMock(return_value=NETWORK_STATE)

        ret = state_mod.managed(
            "test", "network", {"lan": {"_type": "interface", "ipaddr": "10.35.24.2"}}
        )
        assert ret["result"] is None
        assert "would be updated" in ret["comment"]
        assert "lan" in ret["changes"]
        assert ret["changes"]["lan"]["ipaddr"]["old"] == "10.35.24.1"
        assert ret["changes"]["lan"]["ipaddr"]["new"] == "10.35.24.2"

    def test_no_revert_in_test_mode(self, patch_dunders, monkeypatch):
        monkeypatch.setattr(state_mod, "__opts__", {"test": True}, raising=False)
        patch_dunders["openwrt_ubus.changes"] = MagicMock(
            return_value=[["set", "network.wan.proto", "dhcp"]]
        )
        patch_dunders["openwrt_ubus.revert"] = MagicMock()
        patch_dunders["openwrt_ubus.get"] = MagicMock(return_value=NETWORK_STATE)

        ret = state_mod.managed(
            "test",
            "network",
            {"lan": {"_type": "interface", "ipaddr": "10.35.24.2"}},
            revert_pending=True,
        )
        assert ret["result"] is None
        patch_dunders["openwrt_ubus.revert"].assert_not_called()


# --- Partial diff ---


class TestPartialDiff:
    def test_unmanaged_options_ignored(self, patch_dunders):
        patch_dunders["openwrt_ubus.changes"] = MagicMock(return_value=[])
        patch_dunders["openwrt_ubus.get"] = MagicMock(return_value=NETWORK_STATE)

        # Only manage proto, not device/ipaddr/netmask
        ret = state_mod.managed("test", "network", {"lan": {"proto": "static"}})
        assert ret["result"] is True
        assert not ret["changes"]

    @patch("saltext.openwrt_ubus.states.saltext_ubus.time")
    def test_detects_changed_option(self, mock_time, patch_dunders):
        mock_time.monotonic.side_effect = [0, 3]
        mock_time.sleep = MagicMock()
        patch_dunders["openwrt_ubus.changes"] = MagicMock(return_value=[])
        patch_dunders["openwrt_ubus.set"] = MagicMock()
        patch_dunders["openwrt_ubus.apply"] = MagicMock()
        # Return updated state on verify read
        updated = dict(NETWORK_STATE)
        updated["lan"] = dict(NETWORK_STATE["lan"])
        updated["lan"]["ipaddr"] = "10.35.24.2"
        patch_dunders["openwrt_ubus.get"] = MagicMock(
            side_effect=[AGENT_ONESHOT, NETWORK_STATE, updated]
        )
        patch_dunders["openwrt_ubus.confirm"] = MagicMock()
        patch_dunders["openwrt_ubus.service_list"] = MagicMock(
            side_effect=[SERVICES_RUNNING, SERVICES_AFTER_RESTART]
        )

        ret = state_mod.managed("test", "network", {"lan": {"ipaddr": "10.35.24.2"}})
        assert ret["result"] is True
        assert "lan" in ret["changes"]
        assert ret["changes"]["lan"]["ipaddr"]["old"] == "10.35.24.1"
        assert ret["changes"]["lan"]["ipaddr"]["new"] == "10.35.24.2"

    @patch("saltext.openwrt_ubus.states.saltext_ubus.time")
    def test_list_option_diff(self, mock_time, patch_dunders):
        mock_time.monotonic.side_effect = [0, 3]
        mock_time.sleep = MagicMock()
        patch_dunders["openwrt_ubus.changes"] = MagicMock(return_value=[])
        patch_dunders["openwrt_ubus.set"] = MagicMock()
        patch_dunders["openwrt_ubus.apply"] = MagicMock()
        updated = dict(NETWORK_STATE)
        updated["wan"] = dict(NETWORK_STATE["wan"])
        updated["wan"]["dns"] = ["8.8.8.8", "8.8.4.4"]
        patch_dunders["openwrt_ubus.get"] = MagicMock(
            side_effect=[AGENT_ONESHOT, NETWORK_STATE, updated]
        )
        patch_dunders["openwrt_ubus.confirm"] = MagicMock()
        patch_dunders["openwrt_ubus.service_list"] = MagicMock(
            side_effect=[SERVICES_RUNNING, SERVICES_AFTER_RESTART]
        )

        ret = state_mod.managed("test", "network", {"wan": {"dns": ["8.8.8.8", "8.8.4.4"]}})
        assert ret["result"] is True
        assert ret["changes"]["wan"]["dns"]["old"] == ["1.1.1.1", "1.0.0.1"]
        assert ret["changes"]["wan"]["dns"]["new"] == ["8.8.8.8", "8.8.4.4"]


# --- Singleton anonymous section resolution ---


class TestSingletonResolution:
    def test_resolves_singleton(self, patch_dunders):
        patch_dunders["openwrt_ubus.changes"] = MagicMock(return_value=[])
        patch_dunders["openwrt_ubus.get"] = MagicMock(return_value=SYSTEM_STATE)

        # _system with _type=system should resolve to cfg01e48a
        ret = state_mod.managed(
            "test", "system", {"_system": {"_type": "system", "hostname": "austru"}}
        )
        assert ret["result"] is True
        assert "already in desired state" in ret["comment"]

    @patch("saltext.openwrt_ubus.states.saltext_ubus.time")
    def test_singleton_with_change(self, mock_time, patch_dunders):
        mock_time.monotonic.side_effect = [0, 3]
        mock_time.sleep = MagicMock()
        patch_dunders["openwrt_ubus.changes"] = MagicMock(return_value=[])
        patch_dunders["openwrt_ubus.set"] = MagicMock()
        patch_dunders["openwrt_ubus.apply"] = MagicMock()
        updated = dict(SYSTEM_STATE)
        updated["cfg01e48a"] = dict(SYSTEM_STATE["cfg01e48a"])
        updated["cfg01e48a"]["hostname"] = "newname"
        patch_dunders["openwrt_ubus.get"] = MagicMock(
            side_effect=[AGENT_ONESHOT, SYSTEM_STATE, updated]
        )
        patch_dunders["openwrt_ubus.confirm"] = MagicMock()
        patch_dunders["openwrt_ubus.service_list"] = MagicMock(
            side_effect=[SERVICES_RUNNING, SERVICES_AFTER_RESTART]
        )

        ret = state_mod.managed(
            "test", "system", {"_system": {"_type": "system", "hostname": "newname"}}
        )
        assert ret["result"] is True
        # Resolved to the actual section name cfg01e48a
        assert "cfg01e48a" in ret["changes"]
        assert ret["changes"]["cfg01e48a"]["hostname"]["old"] == "austru"
        assert ret["changes"]["cfg01e48a"]["hostname"]["new"] == "newname"

    def test_fails_no_match(self, patch_dunders):
        patch_dunders["openwrt_ubus.changes"] = MagicMock(return_value=[])
        patch_dunders["openwrt_ubus.get"] = MagicMock(return_value=SYSTEM_STATE)

        ret = state_mod.managed(
            "test", "system", {"_dnsmasq": {"_type": "dnsmasq", "option": "value"}}
        )
        assert ret["result"] is False
        assert "No anonymous section of type 'dnsmasq'" in ret["comment"]

    def test_fails_multiple_matches(self, patch_dunders):
        state_with_dupes = {
            "cfg01": {"_type": "rule", "_anonymous": True, "name": "r1"},
            "cfg02": {"_type": "rule", "_anonymous": True, "name": "r2"},
        }
        patch_dunders["openwrt_ubus.changes"] = MagicMock(return_value=[])
        patch_dunders["openwrt_ubus.get"] = MagicMock(return_value=state_with_dupes)

        ret = state_mod.managed("test", "firewall", {"_rule": {"_type": "rule", "name": "r1"}})
        assert ret["result"] is False
        assert "Multiple anonymous sections" in ret["comment"]


# --- Section creation ---


class TestSectionCreate:
    @patch("saltext.openwrt_ubus.states.saltext_ubus.time")
    def test_creates_new_section(self, mock_time, patch_dunders):
        mock_time.monotonic.side_effect = [0, 3]
        mock_time.sleep = MagicMock()
        patch_dunders["openwrt_ubus.changes"] = MagicMock(return_value=[])
        patch_dunders["openwrt_ubus.add"] = MagicMock()
        patch_dunders["openwrt_ubus.set"] = MagicMock()
        patch_dunders["openwrt_ubus.apply"] = MagicMock()
        # After apply, wan2 exists
        updated = dict(NETWORK_STATE)
        updated["wan2"] = {
            "_type": "interface",
            "_name": "wan2",
            "_anonymous": False,
            "proto": "dhcp",
        }
        patch_dunders["openwrt_ubus.get"] = MagicMock(
            side_effect=[AGENT_ONESHOT, NETWORK_STATE, updated]
        )
        patch_dunders["openwrt_ubus.confirm"] = MagicMock()
        patch_dunders["openwrt_ubus.service_list"] = MagicMock(
            side_effect=[SERVICES_RUNNING, SERVICES_AFTER_RESTART]
        )

        ret = state_mod.managed(
            "test", "network", {"wan2": {"_type": "interface", "proto": "dhcp"}}
        )
        assert ret["result"] is True
        patch_dunders["openwrt_ubus.add"].assert_called_once_with(
            "network", "interface", name="wan2"
        )

    def test_fails_without_type(self, patch_dunders):
        patch_dunders["openwrt_ubus.changes"] = MagicMock(return_value=[])
        patch_dunders["openwrt_ubus.get"] = MagicMock(return_value=NETWORK_STATE)

        ret = state_mod.managed("test", "network", {"wan2": {"proto": "dhcp"}})  # No _type
        assert ret["result"] is False
        assert "no _type specified" in ret["comment"]


# --- Type mismatch ---


class TestTypeMismatch:
    def test_fails_on_type_mismatch(self, patch_dunders):
        patch_dunders["openwrt_ubus.changes"] = MagicMock(return_value=[])
        patch_dunders["openwrt_ubus.get"] = MagicMock(return_value=NETWORK_STATE)

        # lan is type "interface", try to set it as "bridge"
        ret = state_mod.managed("test", "network", {"lan": {"_type": "bridge", "proto": "static"}})
        assert ret["result"] is False
        assert "Type mismatch" in ret["comment"]
        assert "'bridge'" in ret["comment"]
        assert "'interface'" in ret["comment"]


# --- Apply + verify + confirm ---


class TestApplyFlow:
    @patch("saltext.openwrt_ubus.states.saltext_ubus.time")
    def test_apply_verify_confirm(self, mock_time, patch_dunders):
        mock_time.monotonic.side_effect = [0, 3]
        mock_time.sleep = MagicMock()
        patch_dunders["openwrt_ubus.changes"] = MagicMock(return_value=[])
        updated = dict(NETWORK_STATE)
        updated["lan"] = dict(NETWORK_STATE["lan"])
        updated["lan"]["ipaddr"] = "10.35.24.2"
        patch_dunders["openwrt_ubus.get"] = MagicMock(
            side_effect=[AGENT_ONESHOT, NETWORK_STATE, updated]
        )
        patch_dunders["openwrt_ubus.set"] = MagicMock()
        patch_dunders["openwrt_ubus.apply"] = MagicMock()
        patch_dunders["openwrt_ubus.confirm"] = MagicMock()
        patch_dunders["openwrt_ubus.service_list"] = MagicMock(
            side_effect=[SERVICES_RUNNING, SERVICES_AFTER_RESTART]
        )

        ret = state_mod.managed("test", "network", {"lan": {"ipaddr": "10.35.24.2"}})
        assert ret["result"] is True
        patch_dunders["openwrt_ubus.set"].assert_called_once_with(
            "network", "lan", {"ipaddr": "10.35.24.2"}
        )
        patch_dunders["openwrt_ubus.apply"].assert_called_once_with(rollback=120)
        patch_dunders["openwrt_ubus.confirm"].assert_called_once()
        assert "applied, and confirmed" in ret["comment"]

    def test_verification_failure(self, patch_dunders):
        patch_dunders["openwrt_ubus.changes"] = MagicMock(return_value=[])
        # After apply, value doesn't match
        bad_state = dict(NETWORK_STATE)
        bad_state["lan"] = dict(NETWORK_STATE["lan"])
        bad_state["lan"]["ipaddr"] = "10.35.24.1"  # Still old value
        patch_dunders["openwrt_ubus.get"] = MagicMock(
            side_effect=[AGENT_ONESHOT, NETWORK_STATE, bad_state]
        )
        patch_dunders["openwrt_ubus.set"] = MagicMock()
        patch_dunders["openwrt_ubus.apply"] = MagicMock()
        patch_dunders["openwrt_ubus.service_list"] = MagicMock(return_value=SERVICES_RUNNING)

        ret = state_mod.managed("test", "network", {"lan": {"ipaddr": "10.35.24.2"}})
        assert ret["result"] is False
        assert "Verification failed" in ret["comment"]
        assert "Rollback will revert" in ret["comment"]

    @patch("saltext.openwrt_ubus.states.saltext_ubus.time")
    def test_custom_rollback_timeout(self, mock_time, patch_dunders):
        mock_time.monotonic.side_effect = [0, 3]
        mock_time.sleep = MagicMock()
        patch_dunders["openwrt_ubus.changes"] = MagicMock(return_value=[])
        updated = dict(NETWORK_STATE)
        updated["lan"] = dict(NETWORK_STATE["lan"])
        updated["lan"]["proto"] = "dhcp"
        patch_dunders["openwrt_ubus.get"] = MagicMock(
            side_effect=[AGENT_ONESHOT, NETWORK_STATE, updated]
        )
        patch_dunders["openwrt_ubus.set"] = MagicMock()
        patch_dunders["openwrt_ubus.apply"] = MagicMock()
        patch_dunders["openwrt_ubus.confirm"] = MagicMock()
        patch_dunders["openwrt_ubus.service_list"] = MagicMock(
            side_effect=[SERVICES_RUNNING, SERVICES_AFTER_RESTART]
        )

        state_mod.managed(
            "test",
            "network",
            {"lan": {"proto": "dhcp"}},
            apply_rollback=120,
        )
        patch_dunders["openwrt_ubus.apply"].assert_called_once_with(rollback=120)

    @patch("saltext.openwrt_ubus.states.saltext_ubus.time")
    def test_oneshot_snapshots_and_polls(self, mock_time, patch_dunders):
        """managed() in oneshot mode does snapshot -> apply -> poll -> confirm."""
        mock_time.monotonic.side_effect = [0, 3]
        mock_time.sleep = MagicMock()
        patch_dunders["openwrt_ubus.changes"] = MagicMock(return_value=[])
        updated = dict(NETWORK_STATE)
        updated["lan"] = dict(NETWORK_STATE["lan"])
        updated["lan"]["ipaddr"] = "10.35.24.2"
        patch_dunders["openwrt_ubus.get"] = MagicMock(
            side_effect=[AGENT_ONESHOT, NETWORK_STATE, updated]
        )
        patch_dunders["openwrt_ubus.set"] = MagicMock()
        patch_dunders["openwrt_ubus.apply"] = MagicMock()
        patch_dunders["openwrt_ubus.confirm"] = MagicMock()
        patch_dunders["openwrt_ubus.service_list"] = MagicMock(
            side_effect=[SERVICES_RUNNING, SERVICES_AFTER_RESTART]
        )

        ret = state_mod.managed("test", "network", {"lan": {"ipaddr": "10.35.24.2"}})
        assert ret["result"] is True
        # service_list called twice: snapshot + one poll
        assert patch_dunders["openwrt_ubus.service_list"].call_count == 2
        patch_dunders["openwrt_ubus.confirm"].assert_called_once()

    @patch("saltext.openwrt_ubus.states.saltext_ubus.time")
    def test_oneshot_rollback_on_service_failure(self, mock_time, patch_dunders):
        """managed() in oneshot mode: services don't recover -> no confirm."""
        mock_time.monotonic.side_effect = [0, 200]
        mock_time.sleep = MagicMock()
        patch_dunders["openwrt_ubus.changes"] = MagicMock(return_value=[])
        updated = dict(NETWORK_STATE)
        updated["lan"] = dict(NETWORK_STATE["lan"])
        updated["lan"]["ipaddr"] = "10.35.24.2"
        patch_dunders["openwrt_ubus.get"] = MagicMock(
            side_effect=[AGENT_ONESHOT, NETWORK_STATE, updated]
        )
        patch_dunders["openwrt_ubus.set"] = MagicMock()
        patch_dunders["openwrt_ubus.apply"] = MagicMock()
        patch_dunders["openwrt_ubus.service_list"] = MagicMock(
            side_effect=[SERVICES_RUNNING, SERVICES_PARTIAL_DOWN]
        )

        ret = state_mod.managed("test", "network", {"lan": {"ipaddr": "10.35.24.2"}})
        assert ret["result"] is False
        assert "NOT confirming" in ret["comment"]
        assert "dnsmasq/cfg01411c" in ret["comment"]
        assert "openwrt_ubus.confirm" not in patch_dunders


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
        resolved = state_mod._resolve_sections("network", sections, NETWORK_STATE)
        assert resolved == sections

    def test_singleton_resolves(self):
        sections = {"_system": {"_type": "system", "hostname": "newname"}}
        resolved = state_mod._resolve_sections("system", sections, SYSTEM_STATE)
        assert "cfg01e48a" in resolved
        assert "_system" not in resolved

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
        patch_dunders["openwrt_ubus.changes"] = MagicMock(return_value=[])
        patch_dunders["openwrt_ubus.get"] = MagicMock(side_effect=[AGENT_AUDIT, NETWORK_STATE])

        ret = state_mod.managed("test", "network", {"lan": {"ipaddr": "10.35.24.2"}})
        assert ret["result"] is True
        assert "audit mode" in ret["comment"]
        assert "1 section(s) drifted" in ret["comment"]
        assert "lan" in ret["changes"]
        # No write operations should have been called
        assert "openwrt_ubus.set" not in patch_dunders
        assert "openwrt_ubus.apply" not in patch_dunders
        assert "openwrt_ubus.confirm" not in patch_dunders

    def test_audit_mode_no_drift(self, patch_dunders):
        patch_dunders["openwrt_ubus.changes"] = MagicMock(return_value=[])
        patch_dunders["openwrt_ubus.get"] = MagicMock(side_effect=[AGENT_AUDIT, NETWORK_STATE])

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
            {"test": False, "proxy": {"proxytype": "openwrt_ubus_jsonrpc"}},
            raising=False,
        )
        patch_dunders["openwrt_ubus.changes"] = MagicMock(return_value=[])
        patch_dunders["openwrt_ubus.get"] = MagicMock(
            side_effect=[AGENT_AUTOVERIFIED, NETWORK_STATE]
        )
        patch_dunders["openwrt_ubus.set"] = MagicMock()

        ret = state_mod.managed("test", "network", {"lan": {"ipaddr": "10.35.24.2"}})
        assert ret["result"] is True
        assert "staged in rpcd session" in ret["comment"]
        assert "openwrt_ubus.applied" in ret["comment"]
        patch_dunders["openwrt_ubus.set"].assert_called_once()
        assert "openwrt_ubus.commit" not in patch_dunders
        assert "openwrt_ubus.apply" not in patch_dunders
        assert "openwrt_ubus.confirm" not in patch_dunders

    def test_autoverified_mode_ssh_stages_no_commit(self, patch_dunders, monkeypatch):
        monkeypatch.setattr(
            state_mod,
            "__opts__",
            {"test": False, "proxy": {"proxytype": "openwrt_ubus_ssh"}},
            raising=False,
        )
        patch_dunders["openwrt_ubus.changes"] = MagicMock(return_value=[])
        patch_dunders["openwrt_ubus.get"] = MagicMock(
            side_effect=[AGENT_AUTOVERIFIED, NETWORK_STATE]
        )
        patch_dunders["openwrt_ubus.set"] = MagicMock()

        ret = state_mod.managed("test", "network", {"lan": {"ipaddr": "10.35.24.2"}})
        assert ret["result"] is True
        assert "staged" in ret["comment"]
        assert "openwrt_ubus.applied" in ret["comment"]
        patch_dunders["openwrt_ubus.set"].assert_called_once()
        assert "openwrt_ubus.commit" not in patch_dunders
        assert "openwrt_ubus.apply" not in patch_dunders
        assert "openwrt_ubus.confirm" not in patch_dunders

    def test_humanreviewed_mode_stages_no_commit(self, patch_dunders, monkeypatch):
        monkeypatch.setattr(
            state_mod,
            "__opts__",
            {"test": False, "proxy": {"proxytype": "openwrt_ubus_jsonrpc"}},
            raising=False,
        )
        patch_dunders["openwrt_ubus.changes"] = MagicMock(return_value=[])
        patch_dunders["openwrt_ubus.get"] = MagicMock(
            side_effect=[AGENT_HUMANREVIEWED, NETWORK_STATE]
        )
        patch_dunders["openwrt_ubus.set"] = MagicMock()

        ret = state_mod.managed("test", "network", {"lan": {"ipaddr": "10.35.24.2"}})
        assert ret["result"] is True
        assert "staged in rpcd session" in ret["comment"]
        patch_dunders["openwrt_ubus.set"].assert_called_once()
        assert "openwrt_ubus.apply" not in patch_dunders
        assert "openwrt_ubus.confirm" not in patch_dunders

    def test_disabled_skips_everything(self, patch_dunders):
        patch_dunders["openwrt_ubus.get"] = MagicMock(return_value=AGENT_DISABLED)

        ret = state_mod.managed("test", "network", {"lan": {"ipaddr": "10.35.24.2"}})
        assert ret["result"] is True
        assert "salt-openwrt disabled" in ret["comment"]
        # Only one get call (agent config), no changes/set/apply
        patch_dunders["openwrt_ubus.get"].assert_called_once_with("salt-openwrt", "global")

    def test_missing_config_defaults_oneshot(self, patch_dunders):
        """When salt-openwrt config is absent, default to oneshot mode."""
        patch_dunders["openwrt_ubus.changes"] = MagicMock(return_value=[])
        call_count = [0]
        original_state = NETWORK_STATE

        def get_side_effect(*args, **kwargs):  # pylint: disable=unused-argument
            call_count[0] += 1
            if call_count[0] == 1:
                # First call is agent config -- raise to simulate missing config
                raise KeyError("salt-openwrt")
            return original_state

        patch_dunders["openwrt_ubus.get"] = MagicMock(side_effect=get_side_effect)

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
    @patch("saltext.openwrt_ubus.states.saltext_ubus.time")
    def test_apply_confirm_with_service_check(self, mock_time, patch_dunders):
        """Happy path: snapshot -> apply -> poll (all back) -> confirm."""
        mock_time.monotonic.side_effect = [0, 3]  # deadline calc, first poll check
        mock_time.sleep = MagicMock()
        patch_dunders["openwrt_ubus.get"] = MagicMock(return_value=AGENT_ONESHOT)
        patch_dunders["openwrt_ubus.apply"] = MagicMock()
        patch_dunders["openwrt_ubus.confirm"] = MagicMock()
        patch_dunders["openwrt_ubus.service_list"] = MagicMock(
            side_effect=[SERVICES_RUNNING, SERVICES_AFTER_RESTART]
        )

        ret = state_mod.applied("test", config="network")
        assert ret["result"] is True
        assert "applied and confirmed" in ret["comment"]
        assert "4 service(s) verified running" in ret["comment"]
        patch_dunders["openwrt_ubus.apply"].assert_called_once_with(rollback=120)
        patch_dunders["openwrt_ubus.confirm"].assert_called_once()

    @patch("saltext.openwrt_ubus.states.saltext_ubus.time")
    def test_services_recover_after_delay(self, mock_time, patch_dunders):
        """service_list returns partial-down on first poll, all-up on second."""
        mock_time.monotonic.side_effect = [0, 3, 6]  # deadline calc, poll 1, poll 2
        mock_time.sleep = MagicMock()
        patch_dunders["openwrt_ubus.get"] = MagicMock(return_value=AGENT_ONESHOT)
        patch_dunders["openwrt_ubus.apply"] = MagicMock()
        patch_dunders["openwrt_ubus.confirm"] = MagicMock()
        patch_dunders["openwrt_ubus.service_list"] = MagicMock(
            side_effect=[SERVICES_RUNNING, SERVICES_PARTIAL_DOWN, SERVICES_AFTER_RESTART]
        )

        ret = state_mod.applied("test", config="network")
        assert ret["result"] is True
        assert "applied and confirmed" in ret["comment"]
        patch_dunders["openwrt_ubus.confirm"].assert_called_once()

    @patch("saltext.openwrt_ubus.states.saltext_ubus.time")
    def test_services_not_recovered_no_confirm(self, mock_time, patch_dunders):
        """Poll always returns partial-down -> no confirm, lists down services."""
        # deadline calc returns 0, first poll check exceeds deadline
        mock_time.monotonic.side_effect = [0, 200]
        mock_time.sleep = MagicMock()
        patch_dunders["openwrt_ubus.get"] = MagicMock(return_value=AGENT_ONESHOT)
        patch_dunders["openwrt_ubus.apply"] = MagicMock()
        patch_dunders["openwrt_ubus.service_list"] = MagicMock(
            side_effect=[SERVICES_RUNNING, SERVICES_PARTIAL_DOWN]
        )

        ret = state_mod.applied("test", config="network")
        assert ret["result"] is False
        assert "NOT confirming" in ret["comment"]
        assert "dnsmasq/cfg01411c" in ret["comment"]
        assert "openwrt_ubus.confirm" not in patch_dunders

    def test_apply_without_config(self, patch_dunders):
        """applied() without config labels as 'all'."""
        patch_dunders["openwrt_ubus.get"] = MagicMock(return_value=AGENT_ONESHOT)
        patch_dunders["openwrt_ubus.apply"] = MagicMock()
        patch_dunders["openwrt_ubus.confirm"] = MagicMock()
        # No running services -> empty snapshot -> skip polling
        patch_dunders["openwrt_ubus.service_list"] = MagicMock(return_value={})

        ret = state_mod.applied("test")
        assert ret["result"] is True
        assert "all: applied and confirmed" in ret["comment"]

    def test_disabled_skips(self, patch_dunders):
        patch_dunders["openwrt_ubus.get"] = MagicMock(return_value=AGENT_DISABLED)

        ret = state_mod.applied("test", config="network")
        assert ret["result"] is True
        assert "salt-openwrt disabled" in ret["comment"]
        patch_dunders["openwrt_ubus.get"].assert_called_once_with("salt-openwrt", "global")

    def test_test_mode(self, patch_dunders, monkeypatch):
        monkeypatch.setattr(state_mod, "__opts__", {"test": True}, raising=False)
        patch_dunders["openwrt_ubus.get"] = MagicMock(return_value=AGENT_ONESHOT)

        ret = state_mod.applied("test", config="network")
        assert ret["result"] is None
        assert "would apply" in ret["comment"]
        assert "openwrt_ubus.apply" not in patch_dunders

    def test_apply_failure(self, patch_dunders):
        patch_dunders["openwrt_ubus.get"] = MagicMock(return_value=AGENT_ONESHOT)
        patch_dunders["openwrt_ubus.apply"] = MagicMock(side_effect=RuntimeError("connection lost"))
        patch_dunders["openwrt_ubus.service_list"] = MagicMock(return_value=SERVICES_RUNNING)

        ret = state_mod.applied("test", config="network")
        assert ret["result"] is False
        assert "Failed to apply" in ret["comment"]
        assert "connection lost" in ret["comment"]

    def test_apply_noop_status5(self, patch_dunders):
        """ubus status 5 (No data) means nothing to apply -- no snapshot/poll."""
        patch_dunders["openwrt_ubus.get"] = MagicMock(return_value=AGENT_ONESHOT)
        patch_dunders["openwrt_ubus.service_list"] = MagicMock(return_value=SERVICES_RUNNING)
        patch_dunders["openwrt_ubus.apply"] = MagicMock(
            side_effect=RuntimeError("ubus call failed: status 5 (No data)")
        )

        ret = state_mod.applied("test")
        assert ret["result"] is True
        assert "nothing to apply" in ret["comment"]

    @patch("saltext.openwrt_ubus.states.saltext_ubus.time")
    def test_confirm_failure(self, mock_time, patch_dunders):
        """Services come back but confirm() raises."""
        mock_time.monotonic.side_effect = [0, 3]
        mock_time.sleep = MagicMock()
        patch_dunders["openwrt_ubus.get"] = MagicMock(return_value=AGENT_ONESHOT)
        patch_dunders["openwrt_ubus.apply"] = MagicMock()
        patch_dunders["openwrt_ubus.service_list"] = MagicMock(
            side_effect=[SERVICES_RUNNING, SERVICES_AFTER_RESTART]
        )
        patch_dunders["openwrt_ubus.confirm"] = MagicMock(
            side_effect=RuntimeError("confirm failed")
        )

        ret = state_mod.applied("test", config="network")
        assert ret["result"] is False
        assert "Failed to confirm" in ret["comment"]
        assert "Rollback will revert" in ret["comment"]

    @patch("saltext.openwrt_ubus.states.saltext_ubus.time")
    def test_custom_rollback(self, mock_time, patch_dunders):
        mock_time.monotonic.side_effect = [0, 3]
        mock_time.sleep = MagicMock()
        patch_dunders["openwrt_ubus.get"] = MagicMock(return_value=AGENT_ONESHOT)
        patch_dunders["openwrt_ubus.apply"] = MagicMock()
        patch_dunders["openwrt_ubus.confirm"] = MagicMock()
        patch_dunders["openwrt_ubus.service_list"] = MagicMock(
            side_effect=[SERVICES_RUNNING, SERVICES_AFTER_RESTART]
        )

        ret = state_mod.applied("test", config="network", rollback=180)
        assert ret["result"] is True
        patch_dunders["openwrt_ubus.apply"].assert_called_once_with(rollback=180)

    @patch("saltext.openwrt_ubus.states.saltext_ubus.time")
    def test_rollback_timeout_from_device_config(self, mock_time, patch_dunders):
        """rollback_timeout is read from device config when rollback=None."""
        mock_time.monotonic.side_effect = [0, 3]
        mock_time.sleep = MagicMock()
        agent = dict(AGENT_ONESHOT)
        agent["rollback_timeout"] = "90"
        patch_dunders["openwrt_ubus.get"] = MagicMock(return_value=agent)
        patch_dunders["openwrt_ubus.apply"] = MagicMock()
        patch_dunders["openwrt_ubus.confirm"] = MagicMock()
        patch_dunders["openwrt_ubus.service_list"] = MagicMock(
            side_effect=[SERVICES_RUNNING, SERVICES_AFTER_RESTART]
        )

        ret = state_mod.applied("test", config="network")
        assert ret["result"] is True
        patch_dunders["openwrt_ubus.apply"].assert_called_once_with(rollback=90)

    def test_snapshot_failure_skips_health_check(self, patch_dunders):
        """If service_list fails on snapshot, proceed without health check."""
        patch_dunders["openwrt_ubus.get"] = MagicMock(return_value=AGENT_ONESHOT)
        patch_dunders["openwrt_ubus.apply"] = MagicMock()
        patch_dunders["openwrt_ubus.confirm"] = MagicMock()
        patch_dunders["openwrt_ubus.service_list"] = MagicMock(
            side_effect=RuntimeError("ubus unavailable")
        )

        ret = state_mod.applied("test", config="network")
        assert ret["result"] is True
        assert "applied and confirmed" in ret["comment"]
        patch_dunders["openwrt_ubus.confirm"].assert_called_once()
