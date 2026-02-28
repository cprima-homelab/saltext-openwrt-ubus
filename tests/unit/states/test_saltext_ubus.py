"""
Unit tests for the saltext_ubus state module.

All tests use mocked execution module calls. No network calls or device writes.
"""

from unittest.mock import MagicMock

import pytest

import saltext.saltext_ubus.states.saltext_ubus as state_mod

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
        patch_dunders["saltext_ubus.changes"] = MagicMock(return_value=[])
        patch_dunders["saltext_ubus.get"] = MagicMock(return_value=NETWORK_STATE)

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
        patch_dunders["saltext_ubus.changes"] = MagicMock(
            return_value=[["set", "network.wan.proto", "dhcp"]]
        )
        ret = state_mod.managed("test", "network", {"lan": {"proto": "static"}})
        assert ret["result"] is False
        assert "Uncommitted changes exist" in ret["comment"]

    def test_reverts_when_revert_pending_true(self, patch_dunders):
        patch_dunders["saltext_ubus.changes"] = MagicMock(
            return_value=[["set", "network.wan.proto", "dhcp"]]
        )
        patch_dunders["saltext_ubus.revert"] = MagicMock()
        patch_dunders["saltext_ubus.get"] = MagicMock(return_value=NETWORK_STATE)

        ret = state_mod.managed(
            "test",
            "network",
            {"lan": {"_type": "interface", "proto": "static", "ipaddr": "10.35.24.1"}},
            revert_pending=True,
        )
        patch_dunders["saltext_ubus.revert"].assert_called_once_with("network")
        assert ret["result"] is True


# --- Test mode ---


class TestTestMode:
    def test_reports_would_change(self, patch_dunders, monkeypatch):
        monkeypatch.setattr(state_mod, "__opts__", {"test": True}, raising=False)
        patch_dunders["saltext_ubus.changes"] = MagicMock(return_value=[])
        patch_dunders["saltext_ubus.get"] = MagicMock(return_value=NETWORK_STATE)

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
        patch_dunders["saltext_ubus.changes"] = MagicMock(
            return_value=[["set", "network.wan.proto", "dhcp"]]
        )
        patch_dunders["saltext_ubus.revert"] = MagicMock()
        patch_dunders["saltext_ubus.get"] = MagicMock(return_value=NETWORK_STATE)

        ret = state_mod.managed(
            "test",
            "network",
            {"lan": {"_type": "interface", "ipaddr": "10.35.24.2"}},
            revert_pending=True,
        )
        assert ret["result"] is None
        patch_dunders["saltext_ubus.revert"].assert_not_called()


# --- Partial diff ---


class TestPartialDiff:
    def test_unmanaged_options_ignored(self, patch_dunders):
        patch_dunders["saltext_ubus.changes"] = MagicMock(return_value=[])
        patch_dunders["saltext_ubus.get"] = MagicMock(return_value=NETWORK_STATE)

        # Only manage proto, not device/ipaddr/netmask
        ret = state_mod.managed("test", "network", {"lan": {"proto": "static"}})
        assert ret["result"] is True
        assert not ret["changes"]

    def test_detects_changed_option(self, patch_dunders):
        patch_dunders["saltext_ubus.changes"] = MagicMock(return_value=[])
        patch_dunders["saltext_ubus.get"] = MagicMock(return_value=NETWORK_STATE)
        patch_dunders["saltext_ubus.set"] = MagicMock()
        patch_dunders["saltext_ubus.apply"] = MagicMock()
        # Return updated state on verify read
        updated = dict(NETWORK_STATE)
        updated["lan"] = dict(NETWORK_STATE["lan"])
        updated["lan"]["ipaddr"] = "10.35.24.2"
        patch_dunders["saltext_ubus.get"] = MagicMock(side_effect=[NETWORK_STATE, updated])
        patch_dunders["saltext_ubus.confirm"] = MagicMock()

        ret = state_mod.managed("test", "network", {"lan": {"ipaddr": "10.35.24.2"}})
        assert ret["result"] is True
        assert "lan" in ret["changes"]
        assert ret["changes"]["lan"]["ipaddr"]["old"] == "10.35.24.1"
        assert ret["changes"]["lan"]["ipaddr"]["new"] == "10.35.24.2"

    def test_list_option_diff(self, patch_dunders):
        patch_dunders["saltext_ubus.changes"] = MagicMock(return_value=[])
        patch_dunders["saltext_ubus.get"] = MagicMock(return_value=NETWORK_STATE)
        patch_dunders["saltext_ubus.set"] = MagicMock()
        patch_dunders["saltext_ubus.apply"] = MagicMock()
        updated = dict(NETWORK_STATE)
        updated["wan"] = dict(NETWORK_STATE["wan"])
        updated["wan"]["dns"] = ["8.8.8.8", "8.8.4.4"]
        patch_dunders["saltext_ubus.get"] = MagicMock(side_effect=[NETWORK_STATE, updated])
        patch_dunders["saltext_ubus.confirm"] = MagicMock()

        ret = state_mod.managed("test", "network", {"wan": {"dns": ["8.8.8.8", "8.8.4.4"]}})
        assert ret["result"] is True
        assert ret["changes"]["wan"]["dns"]["old"] == ["1.1.1.1", "1.0.0.1"]
        assert ret["changes"]["wan"]["dns"]["new"] == ["8.8.8.8", "8.8.4.4"]


# --- Singleton anonymous section resolution ---


class TestSingletonResolution:
    def test_resolves_singleton(self, patch_dunders):
        patch_dunders["saltext_ubus.changes"] = MagicMock(return_value=[])
        patch_dunders["saltext_ubus.get"] = MagicMock(return_value=SYSTEM_STATE)

        # _system with _type=system should resolve to cfg01e48a
        ret = state_mod.managed(
            "test", "system", {"_system": {"_type": "system", "hostname": "austru"}}
        )
        assert ret["result"] is True
        assert "already in desired state" in ret["comment"]

    def test_singleton_with_change(self, patch_dunders):
        patch_dunders["saltext_ubus.changes"] = MagicMock(return_value=[])
        patch_dunders["saltext_ubus.set"] = MagicMock()
        patch_dunders["saltext_ubus.apply"] = MagicMock()
        updated = dict(SYSTEM_STATE)
        updated["cfg01e48a"] = dict(SYSTEM_STATE["cfg01e48a"])
        updated["cfg01e48a"]["hostname"] = "newname"
        patch_dunders["saltext_ubus.get"] = MagicMock(side_effect=[SYSTEM_STATE, updated])
        patch_dunders["saltext_ubus.confirm"] = MagicMock()

        ret = state_mod.managed(
            "test", "system", {"_system": {"_type": "system", "hostname": "newname"}}
        )
        assert ret["result"] is True
        # Resolved to the actual section name cfg01e48a
        assert "cfg01e48a" in ret["changes"]
        assert ret["changes"]["cfg01e48a"]["hostname"]["old"] == "austru"
        assert ret["changes"]["cfg01e48a"]["hostname"]["new"] == "newname"

    def test_fails_no_match(self, patch_dunders):
        patch_dunders["saltext_ubus.changes"] = MagicMock(return_value=[])
        patch_dunders["saltext_ubus.get"] = MagicMock(return_value=SYSTEM_STATE)

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
        patch_dunders["saltext_ubus.changes"] = MagicMock(return_value=[])
        patch_dunders["saltext_ubus.get"] = MagicMock(return_value=state_with_dupes)

        ret = state_mod.managed("test", "firewall", {"_rule": {"_type": "rule", "name": "r1"}})
        assert ret["result"] is False
        assert "Multiple anonymous sections" in ret["comment"]


# --- Section creation ---


class TestSectionCreate:
    def test_creates_new_section(self, patch_dunders):
        patch_dunders["saltext_ubus.changes"] = MagicMock(return_value=[])
        patch_dunders["saltext_ubus.get"] = MagicMock(return_value=NETWORK_STATE)
        patch_dunders["saltext_ubus.add"] = MagicMock()
        patch_dunders["saltext_ubus.set"] = MagicMock()
        patch_dunders["saltext_ubus.apply"] = MagicMock()
        # After apply, wan2 exists
        updated = dict(NETWORK_STATE)
        updated["wan2"] = {
            "_type": "interface",
            "_name": "wan2",
            "_anonymous": False,
            "proto": "dhcp",
        }
        patch_dunders["saltext_ubus.get"] = MagicMock(side_effect=[NETWORK_STATE, updated])
        patch_dunders["saltext_ubus.confirm"] = MagicMock()

        ret = state_mod.managed(
            "test", "network", {"wan2": {"_type": "interface", "proto": "dhcp"}}
        )
        assert ret["result"] is True
        patch_dunders["saltext_ubus.add"].assert_called_once_with(
            "network", "interface", name="wan2"
        )

    def test_fails_without_type(self, patch_dunders):
        patch_dunders["saltext_ubus.changes"] = MagicMock(return_value=[])
        patch_dunders["saltext_ubus.get"] = MagicMock(return_value=NETWORK_STATE)

        ret = state_mod.managed("test", "network", {"wan2": {"proto": "dhcp"}})  # No _type
        assert ret["result"] is False
        assert "no _type specified" in ret["comment"]


# --- Type mismatch ---


class TestTypeMismatch:
    def test_fails_on_type_mismatch(self, patch_dunders):
        patch_dunders["saltext_ubus.changes"] = MagicMock(return_value=[])
        patch_dunders["saltext_ubus.get"] = MagicMock(return_value=NETWORK_STATE)

        # lan is type "interface", try to set it as "bridge"
        ret = state_mod.managed("test", "network", {"lan": {"_type": "bridge", "proto": "static"}})
        assert ret["result"] is False
        assert "Type mismatch" in ret["comment"]
        assert "'bridge'" in ret["comment"]
        assert "'interface'" in ret["comment"]


# --- Apply + verify + confirm ---


class TestApplyFlow:
    def test_apply_verify_confirm(self, patch_dunders):
        patch_dunders["saltext_ubus.changes"] = MagicMock(return_value=[])
        updated = dict(NETWORK_STATE)
        updated["lan"] = dict(NETWORK_STATE["lan"])
        updated["lan"]["ipaddr"] = "10.35.24.2"
        patch_dunders["saltext_ubus.get"] = MagicMock(side_effect=[NETWORK_STATE, updated])
        patch_dunders["saltext_ubus.set"] = MagicMock()
        patch_dunders["saltext_ubus.apply"] = MagicMock()
        patch_dunders["saltext_ubus.confirm"] = MagicMock()

        ret = state_mod.managed("test", "network", {"lan": {"ipaddr": "10.35.24.2"}})
        assert ret["result"] is True
        patch_dunders["saltext_ubus.set"].assert_called_once_with(
            "network", "lan", {"ipaddr": "10.35.24.2"}
        )
        patch_dunders["saltext_ubus.apply"].assert_called_once_with(rollback=90)
        patch_dunders["saltext_ubus.confirm"].assert_called_once()
        assert "applied, and confirmed" in ret["comment"]

    def test_staged_only_when_apply_none(self, patch_dunders):
        patch_dunders["saltext_ubus.changes"] = MagicMock(return_value=[])
        patch_dunders["saltext_ubus.get"] = MagicMock(return_value=NETWORK_STATE)
        patch_dunders["saltext_ubus.set"] = MagicMock()

        ret = state_mod.managed(
            "test",
            "network",
            {"lan": {"ipaddr": "10.35.24.2"}},
            apply_rollback=None,
        )
        assert ret["result"] is True
        assert "staged only" in ret["comment"]
        assert "saltext_ubus.apply" not in patch_dunders
        assert "saltext_ubus.confirm" not in patch_dunders

    def test_verification_failure(self, patch_dunders):
        patch_dunders["saltext_ubus.changes"] = MagicMock(return_value=[])
        # After apply, value doesn't match
        bad_state = dict(NETWORK_STATE)
        bad_state["lan"] = dict(NETWORK_STATE["lan"])
        bad_state["lan"]["ipaddr"] = "10.35.24.1"  # Still old value
        patch_dunders["saltext_ubus.get"] = MagicMock(side_effect=[NETWORK_STATE, bad_state])
        patch_dunders["saltext_ubus.set"] = MagicMock()
        patch_dunders["saltext_ubus.apply"] = MagicMock()

        ret = state_mod.managed("test", "network", {"lan": {"ipaddr": "10.35.24.2"}})
        assert ret["result"] is False
        assert "Verification failed" in ret["comment"]
        assert "Rollback will revert" in ret["comment"]

    def test_custom_rollback_timeout(self, patch_dunders):
        patch_dunders["saltext_ubus.changes"] = MagicMock(return_value=[])
        updated = dict(NETWORK_STATE)
        updated["lan"] = dict(NETWORK_STATE["lan"])
        updated["lan"]["proto"] = "dhcp"
        patch_dunders["saltext_ubus.get"] = MagicMock(side_effect=[NETWORK_STATE, updated])
        patch_dunders["saltext_ubus.set"] = MagicMock()
        patch_dunders["saltext_ubus.apply"] = MagicMock()
        patch_dunders["saltext_ubus.confirm"] = MagicMock()

        state_mod.managed(
            "test",
            "network",
            {"lan": {"proto": "dhcp"}},
            apply_rollback=120,
        )
        patch_dunders["saltext_ubus.apply"].assert_called_once_with(rollback=120)


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
