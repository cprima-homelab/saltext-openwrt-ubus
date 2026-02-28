"""
Unit tests for the saltext_ubus local execution module.

All tests mock subprocess.run. No ubus calls are made.
"""

import json
import subprocess
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from salt.exceptions import CommandExecutionError

import saltext.saltext_ubus.modules.uci_local as uci_mod


@pytest.fixture(autouse=True)
def patch_dunders(monkeypatch):
    """Set up Salt dunders for the execution module."""
    monkeypatch.setattr(uci_mod, "__opts__", {"test": False}, raising=False)


@pytest.fixture
def mock_subprocess():
    """Provide a mock for subprocess.run."""
    with patch("saltext.saltext_ubus.modules.uci_local.subprocess.run") as mock_run:
        yield mock_run


def _make_result(stdout="", stderr="", returncode=0):
    """Helper to create a mock subprocess result."""
    return MagicMock(stdout=stdout, stderr=stderr, returncode=returncode)


# --- get ---


class TestGet:
    def test_full_config(self, mock_subprocess):
        response = {
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
        mock_subprocess.return_value = _make_result(stdout=json.dumps(response))
        result = uci_mod.get("network")
        assert result["lan"]["_type"] == "interface"
        assert result["lan"]["proto"] == "static"
        assert result["wan"]["proto"] == "dhcp"
        mock_subprocess.assert_called_once_with(
            ["ubus", "call", "uci", "get", json.dumps({"config": "network"})],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

    def test_single_section(self, mock_subprocess):
        response = {
            "values": {
                ".type": "interface",
                ".name": "lan",
                ".anonymous": False,
                "proto": "static",
            }
        }
        mock_subprocess.return_value = _make_result(stdout=json.dumps(response))
        result = uci_mod.get("network", "lan")
        assert result["_type"] == "interface"
        assert result["proto"] == "static"
        assert ".type" not in result

    def test_single_option(self, mock_subprocess):
        mock_subprocess.return_value = _make_result(stdout=json.dumps({"value": "static"}))
        result = uci_mod.get("network", "lan", "proto")
        assert result == "static"

    def test_list_option_preserved(self, mock_subprocess):
        response = {
            "values": {
                "wan": {
                    ".type": "interface",
                    ".name": "wan",
                    ".anonymous": False,
                    "dns": ["1.1.1.1", "1.0.0.1"],
                    "proto": "static",
                }
            }
        }
        mock_subprocess.return_value = _make_result(stdout=json.dumps(response))
        result = uci_mod.get("network")
        assert result["wan"]["dns"] == ["1.1.1.1", "1.0.0.1"]


# --- configs ---


class TestConfigs:
    def test_returns_list(self, mock_subprocess):
        mock_subprocess.return_value = _make_result(
            stdout=json.dumps({"configs": ["network", "system", "dhcp"]})
        )
        result = uci_mod.configs()
        assert result == ["network", "system", "dhcp"]
        mock_subprocess.assert_called_once_with(
            ["ubus", "call", "uci", "configs"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )


# --- changes ---


class TestChanges:
    def test_no_changes(self, mock_subprocess):
        mock_subprocess.return_value = _make_result(stdout=json.dumps({"changes": []}))
        result = uci_mod.changes("network")
        assert result == []

    def test_with_changes(self, mock_subprocess):
        mock_subprocess.return_value = _make_result(
            stdout=json.dumps({"changes": [["set", "network.wan.proto", "dhcp"]]})
        )
        result = uci_mod.changes("network")
        assert len(result) == 1


# --- set_ ---


class TestSet:
    def test_passes_correct_params(self, mock_subprocess):
        mock_subprocess.return_value = _make_result(stdout="")
        uci_mod.set_("network", "lan", {"proto": "dhcp"})
        call_args = mock_subprocess.call_args[0][0]
        params = json.loads(call_args[4])
        assert params["config"] == "network"
        assert params["section"] == "lan"
        assert params["values"] == {"proto": "dhcp"}


# --- add ---


class TestAdd:
    def test_named_section(self, mock_subprocess):
        mock_subprocess.return_value = _make_result(stdout=json.dumps({"section": "wan2"}))
        uci_mod.add("network", "interface", name="wan2")
        call_args = mock_subprocess.call_args[0][0]
        params = json.loads(call_args[4])
        assert params["config"] == "network"
        assert params["type"] == "interface"
        assert params["name"] == "wan2"

    def test_anonymous_section(self, mock_subprocess):
        mock_subprocess.return_value = _make_result(stdout=json.dumps({"section": "cfg0a1b2c"}))
        uci_mod.add("firewall", "rule")
        call_args = mock_subprocess.call_args[0][0]
        params = json.loads(call_args[4])
        assert params["config"] == "firewall"
        assert params["type"] == "rule"
        assert "name" not in params


# --- delete ---


class TestDelete:
    def test_delete_section(self, mock_subprocess):
        mock_subprocess.return_value = _make_result(stdout="")
        uci_mod.delete("network", "wan2")
        call_args = mock_subprocess.call_args[0][0]
        params = json.loads(call_args[4])
        assert params["config"] == "network"
        assert params["section"] == "wan2"

    def test_delete_option(self, mock_subprocess):
        mock_subprocess.return_value = _make_result(stdout="")
        uci_mod.delete("network", "lan", "dns")
        call_args = mock_subprocess.call_args[0][0]
        params = json.loads(call_args[4])
        assert params["option"] == "dns"


# --- apply_ ---


class TestApply:
    def test_default_rollback(self, mock_subprocess):
        mock_subprocess.return_value = _make_result(stdout="")
        uci_mod.apply_()
        call_args = mock_subprocess.call_args[0][0]
        params = json.loads(call_args[4])
        assert params == {"rollback": True, "timeout": 90}

    def test_custom_rollback(self, mock_subprocess):
        mock_subprocess.return_value = _make_result(stdout="")
        uci_mod.apply_(rollback=120)
        call_args = mock_subprocess.call_args[0][0]
        params = json.loads(call_args[4])
        assert params["timeout"] == 120


# --- confirm / rollback / revert ---


class TestConfirm:
    def test_confirm(self, mock_subprocess):
        mock_subprocess.return_value = _make_result(stdout="")
        uci_mod.confirm()
        call_args = mock_subprocess.call_args[0][0]
        assert call_args[2:4] == ["uci", "confirm"]


class TestRollback:
    def test_rollback(self, mock_subprocess):
        mock_subprocess.return_value = _make_result(stdout="")
        uci_mod.rollback()
        call_args = mock_subprocess.call_args[0][0]
        assert call_args[2:4] == ["uci", "rollback"]


class TestRevert:
    def test_revert(self, mock_subprocess):
        mock_subprocess.return_value = _make_result(stdout="")
        uci_mod.revert("network")
        call_args = mock_subprocess.call_args[0][0]
        params = json.loads(call_args[4])
        assert params == {"config": "network"}


# --- commit ---


class TestCommit:
    def test_passes_config(self, mock_subprocess):
        mock_subprocess.return_value = _make_result(stdout="")
        uci_mod.commit("network")
        call_args = mock_subprocess.call_args[0][0]
        params = json.loads(call_args[4])
        assert params == {"config": "network"}


# --- state ---


class TestState:
    def test_full_config(self, mock_subprocess):
        response = {
            "values": {
                "lan": {".type": "interface", ".name": "lan", "proto": "static"},
            }
        }
        mock_subprocess.return_value = _make_result(stdout=json.dumps(response))
        result = uci_mod.state("network")
        assert result["lan"]["_type"] == "interface"
        assert result["lan"]["proto"] == "static"

    def test_single_section(self, mock_subprocess):
        response = {"values": {".type": "interface", ".name": "lan", "proto": "static"}}
        mock_subprocess.return_value = _make_result(stdout=json.dumps(response))
        result = uci_mod.state("network", "lan")
        assert result["_type"] == "interface"


# --- system_board / system_info / network_dump ---


class TestSystemBoard:
    def test_returns_board_data(self, mock_subprocess):
        mock_subprocess.return_value = _make_result(
            stdout=json.dumps({"model": "GL-MT3000", "hostname": "autan"})
        )
        result = uci_mod.system_board()
        assert result["model"] == "GL-MT3000"
        mock_subprocess.assert_called_once_with(
            ["ubus", "call", "system", "board"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )


class TestSystemInfo:
    def test_returns_info_data(self, mock_subprocess):
        mock_subprocess.return_value = _make_result(
            stdout=json.dumps({"uptime": 12345, "memory": {"total": 524288000}})
        )
        result = uci_mod.system_info()
        assert result["uptime"] == 12345


class TestNetworkDump:
    def test_returns_interface_data(self, mock_subprocess):
        mock_subprocess.return_value = _make_result(
            stdout=json.dumps({"interface": [{"interface": "lan"}, {"interface": "wan"}]})
        )
        result = uci_mod.network_dump()
        assert len(result["interface"]) == 2


# --- error handling ---


class TestErrorHandling:
    def test_nonzero_exit_raises(self, mock_subprocess):
        mock_subprocess.return_value = _make_result(returncode=1, stderr="Invalid argument")
        with pytest.raises(CommandExecutionError, match="Invalid argument"):
            uci_mod.get("network")

    def test_timeout_raises(self, mock_subprocess):
        mock_subprocess.side_effect = subprocess.TimeoutExpired(cmd="ubus", timeout=30)
        with pytest.raises(subprocess.TimeoutExpired):
            uci_mod.get("network")
