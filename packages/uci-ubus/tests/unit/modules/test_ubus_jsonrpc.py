"""
Unit tests for the uci execution module.

All tests use mocked proxy calls. No network calls or device writes.
"""

import datetime
from unittest.mock import MagicMock

import pytest

import saltext.uci_ubus.modules.ubus_jsonrpc as uci_mod


@pytest.fixture(autouse=True)
def patch_dunders(monkeypatch):
    """Set up Salt dunders for the execution module."""
    proxy = {}
    monkeypatch.setattr(uci_mod, "__proxy__", proxy, raising=False)
    monkeypatch.setattr(uci_mod, "__opts__", {"test": False}, raising=False)
    return proxy


@pytest.fixture
def mock_call(patch_dunders):
    """Provide a mock for the proxy's call function."""
    call_fn = MagicMock()
    patch_dunders["uci_ubus_jsonrpc.call"] = call_fn
    return call_fn


# --- get ---


class TestGet:
    def test_full_config(self, mock_call):
        mock_call.return_value = {
            "values": {
                "lan": {
                    ".type": "interface",
                    ".name": "lan",
                    ".anonymous": False,
                    ".index": 1,
                    "proto": "static",
                    "ipaddr": "10.35.24.1",
                },
                "wan": {
                    ".type": "interface",
                    ".name": "wan",
                    ".anonymous": False,
                    ".index": 2,
                    "proto": "dhcp",
                },
            }
        }
        result = uci_mod.get("network")
        assert result["lan"]["_type"] == "interface"
        assert result["lan"]["_name"] == "lan"
        assert result["lan"]["_anonymous"] is False
        assert result["lan"]["proto"] == "static"
        assert result["wan"]["proto"] == "dhcp"
        mock_call.assert_called_once_with("uci", "get", {"config": "network"})

    def test_single_section(self, mock_call):
        # ubus wraps single-section results in "values" too
        mock_call.return_value = {
            "values": {
                ".type": "interface",
                ".name": "lan",
                ".anonymous": False,
                ".index": 1,
                "proto": "static",
                "device": "br-lan",
            }
        }
        result = uci_mod.get("network", "lan")
        assert result["_type"] == "interface"
        assert result["proto"] == "static"
        assert ".type" not in result
        mock_call.assert_called_once_with("uci", "get", {"config": "network", "section": "lan"})

    def test_single_option(self, mock_call):
        mock_call.return_value = {"value": "static"}
        result = uci_mod.get("network", "lan", "proto")
        assert result == "static"
        mock_call.assert_called_once_with("uci", "get", {"config": "network", "section": "lan", "option": "proto"})

    def test_anonymous_section_metadata(self, mock_call):
        mock_call.return_value = {
            "values": {
                "cfg01e48a": {
                    ".type": "system",
                    ".name": "cfg01e48a",
                    ".anonymous": True,
                    ".index": 0,
                    "hostname": "austru",
                }
            }
        }
        result = uci_mod.get("system")
        assert result["cfg01e48a"]["_anonymous"] is True
        assert result["cfg01e48a"]["_type"] == "system"

    def test_list_option_preserved(self, mock_call):
        mock_call.return_value = {
            "values": {
                "wan": {
                    ".type": "interface",
                    ".name": "wan",
                    ".anonymous": False,
                    ".index": 0,
                    "dns": ["1.1.1.1", "1.0.0.1"],
                    "proto": "static",
                }
            }
        }
        result = uci_mod.get("network")
        assert result["wan"]["dns"] == ["1.1.1.1", "1.0.0.1"]
        assert result["wan"]["proto"] == "static"


# --- configs ---


class TestConfigs:
    def test_returns_list(self, mock_call):
        mock_call.return_value = {"configs": ["network", "system", "dhcp", "firewall"]}
        result = uci_mod.configs()
        assert result == ["network", "system", "dhcp", "firewall"]
        mock_call.assert_called_once_with("uci", "configs", None)


# --- changes ---


class TestChanges:
    def test_no_changes(self, mock_call):
        mock_call.return_value = {"changes": []}
        result = uci_mod.changes("network")
        assert result == []

    def test_with_changes(self, mock_call):
        mock_call.return_value = {"changes": [["set", "network.wan.proto", "dhcp"]]}
        result = uci_mod.changes("network")
        assert len(result) == 1
        assert result[0] == ["set", "network.wan.proto", "dhcp"]


# --- set_ ---


class TestSet:
    def test_passes_correct_params(self, mock_call):
        mock_call.return_value = None
        uci_mod.set_("network", "lan", {"proto": "dhcp", "ipaddr": "10.0.0.1"})
        mock_call.assert_called_once_with(
            "uci",
            "set",
            {
                "config": "network",
                "section": "lan",
                "values": {"proto": "dhcp", "ipaddr": "10.0.0.1"},
            },
        )


# --- add ---


class TestAdd:
    def test_named_section(self, mock_call):
        mock_call.return_value = {"section": "wan2"}
        uci_mod.add("network", "interface", name="wan2")
        mock_call.assert_called_once_with(
            "uci",
            "add",
            {
                "config": "network",
                "type": "interface",
                "name": "wan2",
            },
        )

    def test_anonymous_section(self, mock_call):
        mock_call.return_value = {"section": "cfg0a1b2c"}
        uci_mod.add("firewall", "rule")
        mock_call.assert_called_once_with(
            "uci",
            "add",
            {
                "config": "firewall",
                "type": "rule",
            },
        )

    def test_with_values(self, mock_call):
        mock_call.return_value = {"section": "wan2"}
        uci_mod.add("network", "interface", name="wan2", values={"proto": "dhcp"})
        call_params = mock_call.call_args[0][2]
        assert call_params["values"] == {"proto": "dhcp"}


# --- delete ---


class TestDelete:
    def test_delete_section(self, mock_call):
        mock_call.return_value = None
        uci_mod.delete("network", "wan2")
        mock_call.assert_called_once_with(
            "uci",
            "delete",
            {
                "config": "network",
                "section": "wan2",
            },
        )

    def test_delete_option(self, mock_call):
        mock_call.return_value = None
        uci_mod.delete("network", "lan", "dns")
        mock_call.assert_called_once_with(
            "uci",
            "delete",
            {
                "config": "network",
                "section": "lan",
                "option": "dns",
            },
        )


# --- apply_ ---


class TestApply:
    def test_default_rollback(self, mock_call):
        mock_call.return_value = None
        uci_mod.apply_()
        mock_call.assert_called_once_with("uci", "apply", {"rollback": True, "timeout": 90})

    def test_custom_rollback(self, mock_call):
        mock_call.return_value = None
        uci_mod.apply_(rollback=120)
        mock_call.assert_called_once_with("uci", "apply", {"rollback": True, "timeout": 120})


# --- confirm / rollback / revert ---


class TestConfirm:
    def test_confirm(self, mock_call):
        mock_call.return_value = None
        uci_mod.confirm()
        mock_call.assert_called_once_with("uci", "confirm", {})


class TestRollback:
    def test_rollback(self, mock_call):
        mock_call.return_value = None
        uci_mod.rollback()
        mock_call.assert_called_once_with("uci", "rollback", {})


class TestRevert:
    def test_revert(self, mock_call):
        mock_call.return_value = None
        uci_mod.revert("network")
        mock_call.assert_called_once_with("uci", "revert", {"config": "network"})


# --- system_board / system_info / network_dump ---


class TestSystemBoard:
    def test_returns_board_data(self, mock_call):
        mock_call.return_value = {"model": "WNDR3800", "hostname": "austru"}
        result = uci_mod.system_board()
        assert result["model"] == "WNDR3800"
        mock_call.assert_called_once_with("system", "board", None)


class TestSystemInfo:
    def test_returns_info_data(self, mock_call):
        mock_call.return_value = {"uptime": 12345, "memory": {"total": 128000000}}
        result = uci_mod.system_info()
        assert result["uptime"] == 12345


class TestNetworkDump:
    def test_returns_interface_data(self, mock_call):
        mock_call.return_value = {"interface": [{"interface": "lan"}, {"interface": "wan"}]}
        result = uci_mod.network_dump()
        assert len(result["interface"]) == 2
        mock_call.assert_called_once_with("network.interface", "dump", None)


# --- commit ---


class TestCommit:
    def test_passes_config(self, mock_call):
        mock_call.return_value = None
        uci_mod.commit("network")
        mock_call.assert_called_once_with("uci", "commit", {"config": "network"})


# --- state ---


class TestState:
    def test_full_config(self, mock_call):
        mock_call.return_value = {
            "values": {
                "lan": {".type": "interface", ".name": "lan", "proto": "static"},
            }
        }
        result = uci_mod.state("network")
        assert result["lan"]["_type"] == "interface"
        assert result["lan"]["proto"] == "static"
        mock_call.assert_called_once_with("uci", "state", {"config": "network"})

    def test_single_section(self, mock_call):
        mock_call.return_value = {"values": {".type": "interface", ".name": "lan", "proto": "static"}}
        result = uci_mod.state("network", "lan")
        assert result["_type"] == "interface"
        mock_call.assert_called_once_with("uci", "state", {"config": "network", "section": "lan"})


# --- runtime_evidence ---


class TestRuntimeEvidence:
    _MOCK_NETWORK = {"interface": [{"interface": "lan", "up": True}]}
    _MOCK_BOARD = {"model": "GL-MT3000", "hostname": "bora"}
    _MOCK_INFO = {"uptime": 3600, "memory": {"total": 524288000}}
    _MOCK_SERVICES = {"rpcd": {"instances": {}}}

    def _side_effect(self, obj, method, _params=None):
        if obj == "network.interface":
            return self._MOCK_NETWORK
        if obj == "system" and method == "board":
            return self._MOCK_BOARD
        if obj == "system" and method == "info":
            return self._MOCK_INFO
        if obj == "service":
            return self._MOCK_SERVICES
        return None

    def test_network_top_level_schema(self, mock_call):
        mock_call.side_effect = self._side_effect
        result = uci_mod.runtime_evidence("network")
        assert set(result) >= {
            "evidence_type",
            "source_type",
            "source_device",
            "scope",
            "collected_at",
            "payload",
            "provenance",
        }

    def test_evidence_type_is_observed_state(self, mock_call):
        mock_call.side_effect = self._side_effect
        assert uci_mod.runtime_evidence("network")["evidence_type"] == "observed_state"

    def test_source_type(self, mock_call):
        mock_call.side_effect = self._side_effect
        assert uci_mod.runtime_evidence("network")["source_type"] == "openwrt"

    def test_network_scope(self, mock_call):
        mock_call.side_effect = self._side_effect
        assert uci_mod.runtime_evidence("network")["scope"] == {"domain": "network"}

    def test_system_scope(self, mock_call):
        mock_call.side_effect = self._side_effect
        assert uci_mod.runtime_evidence("system")["scope"] == {"domain": "system"}

    def test_services_scope(self, mock_call):
        mock_call.side_effect = self._side_effect
        assert uci_mod.runtime_evidence("services")["scope"] == {"domain": "services"}

    def test_network_payload(self, mock_call):
        mock_call.side_effect = self._side_effect
        assert uci_mod.runtime_evidence("network")["payload"] == self._MOCK_NETWORK

    def test_system_payload_has_board_and_info(self, mock_call):
        mock_call.side_effect = self._side_effect
        payload = uci_mod.runtime_evidence("system")["payload"]
        assert set(payload) == {"board", "info"}
        assert payload["board"] == self._MOCK_BOARD
        assert payload["info"] == self._MOCK_INFO

    def test_services_payload(self, mock_call):
        mock_call.side_effect = self._side_effect
        assert uci_mod.runtime_evidence("services")["payload"] == self._MOCK_SERVICES

    def test_collected_at_is_utc(self, mock_call):
        mock_call.side_effect = self._side_effect
        ts = uci_mod.runtime_evidence("network")["collected_at"]
        assert datetime.datetime.fromisoformat(ts).tzinfo is not None

    def test_transport(self, mock_call):
        mock_call.side_effect = self._side_effect
        assert uci_mod.runtime_evidence("network")["provenance"]["transport"] == "ubus-jsonrpc"

    def test_collector_name(self, mock_call):
        mock_call.side_effect = self._side_effect
        assert uci_mod.runtime_evidence("network")["provenance"]["collector"] == "saltext-uci-ubus"

    def test_source_device_from_opts(self, mock_call, monkeypatch):
        monkeypatch.setattr(uci_mod, "__opts__", {"test": False, "id": "bora"}, raising=False)
        mock_call.side_effect = self._side_effect
        assert uci_mod.runtime_evidence("network")["source_device"] == "bora"

    def test_invalid_domain_raises(self, mock_call):  # pylint: disable=unused-argument
        with pytest.raises(ValueError, match="unknown runtime domain"):
            uci_mod.runtime_evidence("wifi")


# --- config_evidence ---


class TestConfigEvidence:
    _MOCK_UCI_RESPONSE = {
        "values": {
            "lan": {
                ".type": "interface",
                ".name": "lan",
                ".anonymous": False,
                ".index": 0,
                "proto": "static",
                "ipaddr": "192.168.1.1",
            }
        }
    }
    _MOCK_UCI_WITH_SECRET = {
        "values": {
            "wg0": {
                ".type": "interface",
                ".name": "wg0",
                ".anonymous": False,
                ".index": 0,
                "proto": "wireguard",
                "addresses": "10.0.0.1/24",
                "private_key": "gHcbXXXXXXXXsecret==",
            }
        }
    }

    def test_top_level_schema(self, mock_call):
        mock_call.return_value = self._MOCK_UCI_RESPONSE
        result = uci_mod.config_evidence("network")
        assert set(result) >= {
            "evidence_type",
            "source_type",
            "source_device",
            "scope",
            "collected_at",
            "payload",
            "provenance",
        }

    def test_evidence_type(self, mock_call):
        mock_call.return_value = self._MOCK_UCI_RESPONSE
        assert uci_mod.config_evidence("network")["evidence_type"] == "configured_state"

    def test_source_type(self, mock_call):
        mock_call.return_value = self._MOCK_UCI_RESPONSE
        assert uci_mod.config_evidence("network")["source_type"] == "uci"

    def test_scope(self, mock_call):
        mock_call.return_value = self._MOCK_UCI_RESPONSE
        assert uci_mod.config_evidence("network")["scope"] == {"config": "network"}

    def test_collected_at_is_utc_iso8601(self, mock_call):
        mock_call.return_value = self._MOCK_UCI_RESPONSE
        ts = uci_mod.config_evidence("network")["collected_at"]
        dt = datetime.datetime.fromisoformat(ts)
        assert dt.tzinfo is not None

    def test_payload_has_sensitivity_metadata(self, mock_call):
        mock_call.return_value = self._MOCK_UCI_RESPONSE
        payload = uci_mod.config_evidence("network")["payload"]
        assert "_sensitivity" in payload["lan"]
        assert "taint" in payload["lan"]["_sensitivity"]

    def test_secret_value_is_null_in_payload(self, mock_call):
        mock_call.return_value = self._MOCK_UCI_WITH_SECRET
        payload = uci_mod.config_evidence("network")["payload"]
        assert payload["wg0"]["private_key"] is None

    def test_sensitivity_taint_in_payload_section(self, mock_call):
        mock_call.return_value = self._MOCK_UCI_WITH_SECRET
        payload = uci_mod.config_evidence("network")["payload"]
        assert payload["wg0"]["_sensitivity"]["taint"] == "secret"

    def test_provenance_has_sensitivity_field(self, mock_call):
        mock_call.return_value = self._MOCK_UCI_RESPONSE
        prov = uci_mod.config_evidence("network")["provenance"]
        assert "sensitivity" in prov
        assert "profile" in prov["sensitivity"]
        assert "version" in prov["sensitivity"]

    def test_provenance_keys(self, mock_call):
        mock_call.return_value = self._MOCK_UCI_RESPONSE
        prov = uci_mod.config_evidence("network")["provenance"]
        assert set(prov) >= {"collector", "transport", "collector_version", "sensitivity"}

    def test_transport_is_ubus_jsonrpc(self, mock_call):
        mock_call.return_value = self._MOCK_UCI_RESPONSE
        prov = uci_mod.config_evidence("network")["provenance"]
        assert prov["transport"] == "ubus-jsonrpc"

    def test_collector_name(self, mock_call):
        mock_call.return_value = self._MOCK_UCI_RESPONSE
        prov = uci_mod.config_evidence("network")["provenance"]
        assert prov["collector"] == "saltext-uci-ubus"

    def test_source_device_from_opts(self, mock_call, monkeypatch):
        monkeypatch.setattr(uci_mod, "__opts__", {"test": False, "id": "openwrt-test-target"}, raising=False)
        mock_call.return_value = self._MOCK_UCI_RESPONSE
        assert uci_mod.config_evidence("network")["source_device"] == "openwrt-test-target"

    def test_source_device_empty_when_no_id(self, mock_call):
        mock_call.return_value = self._MOCK_UCI_RESPONSE
        assert uci_mod.config_evidence("network")["source_device"] == ""

    def test_no_mutating_calls(self, mock_call):
        mock_call.return_value = self._MOCK_UCI_RESPONSE
        uci_mod.config_evidence("network")
        for args in mock_call.call_args_list:
            obj, method = args[0][0], args[0][1]
            assert not (obj == "uci" and method in {"set", "commit", "apply", "delete", "add"})
