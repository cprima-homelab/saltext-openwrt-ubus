"""
Unit tests for the openwrt_ubus SSH execution module.

All tests use mocked proxy calls. No network calls or device writes.
"""

from unittest.mock import MagicMock

import pytest

import saltext.openwrt_ubus.modules.uci_ssh as uci_mod


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
    patch_dunders["openwrt_ubus_ssh.call"] = call_fn
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
        mock_call.assert_called_once_with(
            "uci", "get", {"config": "network", "section": "lan", "option": "proto"}
        )

    def test_anonymous_section_metadata(self, mock_call):
        mock_call.return_value = {
            "values": {
                "cfg01e48a": {
                    ".type": "system",
                    ".name": "cfg01e48a",
                    ".anonymous": True,
                    ".index": 0,
                    "hostname": "autan",
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
        mock_call.return_value = {"model": "GL-MT3000", "hostname": "autan"}
        result = uci_mod.system_board()
        assert result["model"] == "GL-MT3000"
        mock_call.assert_called_once_with("system", "board", None)


class TestSystemInfo:
    def test_returns_info_data(self, mock_call):
        mock_call.return_value = {"uptime": 12345, "memory": {"total": 524288000}}
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
        mock_call.return_value = {
            "values": {".type": "interface", ".name": "lan", "proto": "static"}
        }
        result = uci_mod.state("network", "lan")
        assert result["_type"] == "interface"
        mock_call.assert_called_once_with("uci", "state", {"config": "network", "section": "lan"})
