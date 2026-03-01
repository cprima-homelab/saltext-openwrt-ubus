"""
Unit tests for the saltext_ubus SSH proxy module.

All tests mock the SshRunner. No SSH connections are made.
"""

import json
import shlex
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

import saltext.saltext_ubus.proxy.uci_ssh as proxy_mod

BOARD_RESPONSE = {
    "kernel": "6.6.86",
    "hostname": "autan.rss78.ldk35.archam.de",
    "system": "aarch64",
    "model": "GL.iNet GL-MT3000",
    "board_name": "glinet,gl-mt3000",
    "release": {
        "distribution": "OpenWrt",
        "version": "24.10.5",
        "revision": "r29087-d9c5716d1d",
        "target": "mediatek/filogic",
        "description": "OpenWrt 24.10.5 r29087-d9c5716d1d",
    },
}

INFO_RESPONSE = {
    "uptime": 654321,
    "memory": {"total": 524288000, "free": 234567890, "shared": 1234567, "buffered": 9876543},
}


def _mock_runner_run(command):
    """Simulate SshRunner.run for ubus commands."""
    dispatch = {
        "ubus call system board": json.dumps(BOARD_RESPONSE),
        "ubus call system info": json.dumps(INFO_RESPONSE),
        "echo ok": "ok",
    }
    result = dispatch.get(command)
    if result is not None:
        return result
    raise ValueError(f"Unexpected command: {command}")


@pytest.fixture(autouse=True)
def clean_details():
    """Ensure DETAILS is clean before and after each test."""
    proxy_mod.DETAILS.clear()
    yield
    proxy_mod.DETAILS.clear()


@pytest.fixture
def mock_runner():
    """Create a mock SshRunner."""
    runner = MagicMock()
    runner.run.side_effect = _mock_runner_run
    runner.test_connection.return_value = True
    return runner


class TestInit:
    @patch("saltext.saltext_ubus.proxy.uci_ssh.SshRunner")
    def test_creates_runner_and_verifies(self, mock_runner_cls):
        mock_instance = MagicMock()
        mock_instance.run.side_effect = _mock_runner_run
        mock_instance.test_connection.return_value = True
        mock_runner_cls.return_value = mock_instance

        opts = {
            "proxy": {
                "proxytype": "saltext_ubus_ssh",
                "host": "10.38.20.1",
                "username": "root",
                "port": 2222,
                "ssh_options": ["StrictHostKeyChecking=no"],
            }
        }
        proxy_mod.init(opts)

        mock_runner_cls.assert_called_once_with(
            host="10.38.20.1",
            username="root",
            port=2222,
            ssh_options=["StrictHostKeyChecking=no"],
            timeout=30,
        )
        mock_instance.test_connection.assert_called_once()
        assert proxy_mod.DETAILS["initialized"] is True

    @patch("saltext.saltext_ubus.proxy.uci_ssh.SshRunner")
    def test_connection_failure_raises(self, mock_runner_cls):
        mock_instance = MagicMock()
        mock_instance.test_connection.return_value = False
        mock_runner_cls.return_value = mock_instance

        opts = {
            "proxy": {
                "proxytype": "saltext_ubus_ssh",
                "host": "10.38.20.1",
            }
        }
        with pytest.raises(ConnectionError, match="Cannot connect"):
            proxy_mod.init(opts)

    @patch("saltext.saltext_ubus.proxy.uci_ssh.SshRunner")
    def test_fetches_grains_on_init(self, mock_runner_cls):
        mock_instance = MagicMock()
        mock_instance.run.side_effect = _mock_runner_run
        mock_instance.test_connection.return_value = True
        mock_runner_cls.return_value = mock_instance

        opts = {
            "proxy": {
                "proxytype": "saltext_ubus_ssh",
                "host": "10.38.20.1",
            }
        }
        proxy_mod.init(opts)

        grains_cache = proxy_mod.DETAILS["grains_cache"]
        assert grains_cache["os"] == "OpenWrt"
        assert grains_cache["model"] == "GL.iNet GL-MT3000"
        assert grains_cache["osrelease"] == "24.10.5"


class TestAlive:
    def test_true_after_init(self):
        proxy_mod.DETAILS["initialized"] = True
        assert proxy_mod.alive({}) is True

    def test_false_before_init(self):
        assert proxy_mod.alive({}) is False


class TestPing:
    def test_success(self, mock_runner):
        proxy_mod.DETAILS["runner"] = mock_runner
        assert proxy_mod.ping() is True

    def test_failure(self):
        runner = MagicMock()
        runner.run.side_effect = Exception("Connection refused")
        proxy_mod.DETAILS["runner"] = runner
        assert proxy_mod.ping() is False


class TestShutdown:
    def test_clears_details(self, mock_runner):
        proxy_mod.DETAILS["runner"] = mock_runner
        proxy_mod.DETAILS["initialized"] = True
        proxy_mod.DETAILS["grains_cache"] = {"os": "OpenWrt"}

        proxy_mod.shutdown({})
        assert not proxy_mod.DETAILS


class TestGrains:
    def test_returns_cached_grains(self):
        proxy_mod.DETAILS["grains_cache"] = {"os": "OpenWrt", "model": "GL-MT3000"}
        assert proxy_mod.grains()["os"] == "OpenWrt"

    def test_empty_when_no_cache(self):
        assert proxy_mod.grains() == {}


class TestGrainsRefresh:
    def test_refetches(self, mock_runner):
        proxy_mod.DETAILS["runner"] = mock_runner
        proxy_mod.DETAILS["grains_cache"] = {"os": "old"}

        result = proxy_mod.grains_refresh()
        assert result["os"] == "OpenWrt"
        assert result["model"] == "GL.iNet GL-MT3000"


class TestCall:
    def test_simple_call_no_params(self, mock_runner):
        proxy_mod.DETAILS["runner"] = mock_runner
        result = proxy_mod.call("system", "board")
        assert result == BOARD_RESPONSE
        mock_runner.run.assert_called_with("ubus call system board")

    def test_call_with_params(self, mock_runner):
        proxy_mod.DETAILS["runner"] = mock_runner
        mock_runner.run.side_effect = None
        mock_runner.run.return_value = json.dumps({"values": {"lan": {}}})
        params = {"config": "network"}
        result = proxy_mod.call("uci", "get", params)
        expected_cmd = f"ubus call uci get {shlex.quote(json.dumps(params))}"
        mock_runner.run.assert_called_with(expected_cmd)
        assert result == {"values": {"lan": {}}}

    def test_call_returns_none_for_empty_output(self, mock_runner):
        proxy_mod.DETAILS["runner"] = mock_runner
        mock_runner.run.side_effect = None
        mock_runner.run.return_value = ""
        result = proxy_mod.call("uci", "set", {"config": "network", "section": "lan", "values": {}})
        assert result is None

    def test_call_with_single_quote_in_value(self, mock_runner):
        proxy_mod.DETAILS["runner"] = mock_runner
        mock_runner.run.side_effect = None
        mock_runner.run.return_value = "{}"
        params = {"config": "system", "section": "cfg01", "values": {"desc": "it's"}}
        proxy_mod.call("uci", "set", params)
        actual_cmd = mock_runner.run.call_args[0][0]
        assert actual_cmd == f"ubus call uci set {shlex.quote(json.dumps(params))}"
        # Verify the payload round-trips through JSON correctly
        payload_str = actual_cmd.split("ubus call uci set ", 1)[1]
        # shlex.split undoes the shell quoting
        unquoted = shlex.split(payload_str)[0]
        assert json.loads(unquoted) == params

    def test_call_with_double_quote_in_value(self, mock_runner):
        proxy_mod.DETAILS["runner"] = mock_runner
        mock_runner.run.side_effect = None
        mock_runner.run.return_value = "{}"
        params = {"config": "system", "section": "cfg01", "values": {"desc": 'say "hi"'}}
        proxy_mod.call("uci", "set", params)
        actual_cmd = mock_runner.run.call_args[0][0]
        assert actual_cmd == f"ubus call uci set {shlex.quote(json.dumps(params))}"
        payload_str = actual_cmd.split("ubus call uci set ", 1)[1]
        unquoted = shlex.split(payload_str)[0]
        assert json.loads(unquoted) == params

    def test_call_with_shell_metacharacters(self, mock_runner):
        proxy_mod.DETAILS["runner"] = mock_runner
        mock_runner.run.side_effect = None
        mock_runner.run.return_value = "{}"
        params = {"config": "system", "section": "cfg01", "values": {"cmd": "$(whoami)"}}
        proxy_mod.call("uci", "set", params)
        actual_cmd = mock_runner.run.call_args[0][0]
        assert actual_cmd == f"ubus call uci set {shlex.quote(json.dumps(params))}"
        # The $() must NOT be expanded -- it should survive as literal text
        assert "$(whoami)" in json.dumps(params)
        payload_str = actual_cmd.split("ubus call uci set ", 1)[1]
        unquoted = shlex.split(payload_str)[0]
        assert json.loads(unquoted) == params


class TestRunRaw:
    def test_returns_stdout(self, mock_runner):
        proxy_mod.DETAILS["runner"] = mock_runner
        mock_runner.run.side_effect = None
        mock_runner.run.return_value = "done"
        result = proxy_mod.run_raw("reload_config")
        assert result == "done"
        mock_runner.run.assert_called_with("reload_config")


class TestFetchGrains:
    def test_board_grains(self, mock_runner):
        grains_data = proxy_mod._fetch_grains(mock_runner)
        assert grains_data["os"] == "OpenWrt"
        assert grains_data["os_family"] == "OpenWrt"
        assert grains_data["osrelease"] == "24.10.5"
        assert grains_data["oscodename"] == "r29087-d9c5716d1d"
        assert grains_data["model"] == "GL.iNet GL-MT3000"
        assert grains_data["board_name"] == "glinet,gl-mt3000"
        assert grains_data["cpuarch"] == "aarch64"
        assert grains_data["kernel"] == "6.6.86"
        assert grains_data["host"] == "autan.rss78.ldk35.archam.de"
        assert grains_data["domain"] == "rss78.ldk35.archam.de"

    def test_info_grains(self, mock_runner):
        grains_data = proxy_mod._fetch_grains(mock_runner)
        assert grains_data["mem_total"] == 524288000 // 1024
        assert grains_data["uptime"] == 654321

    def test_board_failure_returns_partial(self):
        runner = MagicMock()
        runner.run.side_effect = [
            Exception("board failed"),
            json.dumps(INFO_RESPONSE),
        ]
        grains_data = proxy_mod._fetch_grains(runner)
        assert "os" not in grains_data
        assert grains_data["mem_total"] == 524288000 // 1024

    def test_hostname_without_domain(self):
        board = dict(BOARD_RESPONSE)
        board["hostname"] = "router"
        runner = MagicMock()
        runner.run.side_effect = [
            json.dumps(board),
            json.dumps(INFO_RESPONSE),
        ]
        grains_data = proxy_mod._fetch_grains(runner)
        assert grains_data["host"] == "router"
        assert "domain" not in grains_data
