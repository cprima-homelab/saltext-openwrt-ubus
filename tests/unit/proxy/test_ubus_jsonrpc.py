"""
Unit tests for the saltext_ubus proxy module.

All tests use a mocked RPC client. No network calls are made.
"""

import urllib.error
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

import saltext.saltext_ubus.proxy.ubus_jsonrpc as proxy_mod
from saltext.saltext_ubus.utils.rpc import JsonRpcError
from saltext.saltext_ubus.utils.rpc import UbusError

BOARD_RESPONSE = {
    "kernel": "6.6.86",
    "hostname": "austru.rss78.ldk35.archam.de",
    "system": "mips",
    "model": "Netgear WNDR3800",
    "board_name": "netgear,wndr3800",
    "release": {
        "distribution": "OpenWrt",
        "version": "24.10.5",
        "revision": "r29087-d9c5716d1d",
        "target": "ath79/generic",
        "description": "OpenWrt 24.10.5 r29087-d9c5716d1d",
    },
}

INFO_RESPONSE = {
    "uptime": 123456,
    "memory": {"total": 124059648, "free": 45678592, "shared": 1234567, "buffered": 9876543},
}

RPCD_CONFIG_RESPONSE = {
    "values": {
        "cfg01rpcd": {
            ".type": "rpcd",
            ".name": "cfg01rpcd",
            "socket": "/var/run/ubus/ubus.sock",
            "timeout": "300",
        }
    }
}


@pytest.fixture(autouse=True)
def clean_details():
    """Ensure DETAILS is clean before and after each test."""
    proxy_mod.DETAILS.clear()
    yield
    proxy_mod.DETAILS.clear()


def _mock_call_dispatch(obj, method, params=None):
    """Default mock dispatch for ubus calls used across tests."""
    if obj == "uci" and method == "get" and params and params.get("config") == "rpcd":
        return RPCD_CONFIG_RESPONSE
    return {
        ("system", "board"): BOARD_RESPONSE,
        ("system", "info"): INFO_RESPONSE,
    }.get((obj, method))


@pytest.fixture
def mock_client():
    """Create a mock RPC client."""
    client = MagicMock()
    client.session_timeout = 300
    client.call.side_effect = _mock_call_dispatch
    return client


class TestInit:
    @patch("saltext.saltext_ubus.proxy.ubus_jsonrpc.UbusRpcClient")
    def test_creates_client_and_logs_in(self, mock_client_cls):
        mock_instance = MagicMock()
        mock_instance.session_timeout = 300
        mock_instance.call.side_effect = _mock_call_dispatch
        mock_client_cls.return_value = mock_instance

        opts = {
            "proxy": {
                "proxytype": "saltext_ubus_jsonrpc",
                "host": "10.35.24.1",
                "username": "salt-agent",
                "password": "secret",
                "port": 443,
                "verify_ssl": False,
            }
        }
        proxy_mod.init(opts)

        mock_client_cls.assert_called_once_with(
            host="10.35.24.1",
            username="salt-agent",
            password="secret",
            port=443,
            verify_ssl=False,
            timeout=30,
            session_timeout=300,
        )
        mock_instance.login.assert_called_once()
        assert proxy_mod.DETAILS["initialized"] is True

    @patch("saltext.saltext_ubus.proxy.ubus_jsonrpc.UbusRpcClient")
    def test_default_username(self, mock_client_cls):
        """init() without explicit username defaults to salt-agent."""
        mock_instance = MagicMock()
        mock_instance.session_timeout = 300
        mock_instance.call.side_effect = _mock_call_dispatch
        mock_client_cls.return_value = mock_instance

        opts = {
            "proxy": {
                "proxytype": "saltext_ubus_jsonrpc",
                "host": "10.35.24.1",
                "password": "secret",
            }
        }
        proxy_mod.init(opts)

        mock_client_cls.assert_called_once_with(
            host="10.35.24.1",
            username="salt-agent",
            password="secret",
            port=443,
            verify_ssl=False,
            timeout=30,
            session_timeout=300,
        )

    @patch("saltext.saltext_ubus.proxy.ubus_jsonrpc.UbusRpcClient")
    def test_fetches_grains_on_init(self, mock_client_cls):
        mock_instance = MagicMock()
        mock_instance.session_timeout = 300
        mock_instance.call.side_effect = _mock_call_dispatch
        mock_client_cls.return_value = mock_instance

        opts = {
            "proxy": {
                "proxytype": "saltext_ubus_jsonrpc",
                "host": "10.0.0.1",
                "username": "u",
                "password": "p",
            }
        }
        proxy_mod.init(opts)

        grains = proxy_mod.DETAILS["grains_cache"]
        assert grains["os"] == "OpenWrt"
        assert grains["osrelease"] == "24.10.5"
        assert grains["model"] == "Netgear WNDR3800"

    @patch("saltext.saltext_ubus.proxy.ubus_jsonrpc.UbusRpcClient")
    def test_pillar_session_timeout(self, mock_client_cls):
        """session_timeout pillar overrides the default."""
        mock_instance = MagicMock()
        mock_instance.session_timeout = 600
        mock_instance.call.side_effect = _mock_call_dispatch
        mock_client_cls.return_value = mock_instance

        opts = {
            "proxy": {
                "proxytype": "saltext_ubus_jsonrpc",
                "host": "10.0.0.1",
                "password": "p",
                "session_timeout": 600,
            }
        }
        proxy_mod.init(opts)

        mock_client_cls.assert_called_once_with(
            host="10.0.0.1",
            username="salt-agent",
            password="p",
            port=443,
            verify_ssl=False,
            timeout=30,
            session_timeout=600,
        )

    @patch("saltext.saltext_ubus.proxy.ubus_jsonrpc.time")
    @patch("saltext.saltext_ubus.proxy.ubus_jsonrpc.UbusRpcClient")
    def test_rpcd_timeout_bumped_when_low(self, mock_client_cls, mock_time):
        """init() updates rpcd invoke timeout via UCI when too low."""
        rpcd_low = {
            "values": {
                "cfg01rpcd": {
                    ".type": "rpcd",
                    ".name": "cfg01rpcd",
                    "timeout": "30",
                }
            }
        }
        calls_made = []

        def dispatch(obj, method, params=None):
            calls_made.append((obj, method, params))
            if obj == "uci" and method == "get" and params and params.get("config") == "rpcd":
                return rpcd_low
            return {("system", "board"): BOARD_RESPONSE, ("system", "info"): INFO_RESPONSE}.get(
                (obj, method)
            )

        mock_instance = MagicMock()
        mock_instance.session_timeout = 300
        mock_instance.call.side_effect = dispatch
        mock_client_cls.return_value = mock_instance

        opts = {
            "proxy": {
                "proxytype": "saltext_ubus_jsonrpc",
                "host": "10.0.0.1",
                "password": "p",
                "rpcd_timeout": 300,
            }
        }
        proxy_mod.init(opts)

        # Should have called uci set to bump timeout
        set_calls = [(o, m, p) for o, m, p in calls_made if o == "uci" and m == "set"]
        assert len(set_calls) == 1
        assert set_calls[0][2]["values"]["timeout"] == "300"
        # Should have committed and reloaded
        commit_calls = [(o, m) for o, m, _ in calls_made if o == "uci" and m == "commit"]
        assert len(commit_calls) == 1
        mock_time.sleep.assert_called_once_with(2)

    @patch("saltext.saltext_ubus.proxy.ubus_jsonrpc.UbusRpcClient")
    def test_rpcd_timeout_skipped_when_sufficient(self, mock_client_cls):
        """init() does not touch rpcd config when timeout is already sufficient."""
        mock_instance = MagicMock()
        mock_instance.session_timeout = 300
        mock_instance.call.side_effect = _mock_call_dispatch
        mock_client_cls.return_value = mock_instance

        opts = {
            "proxy": {
                "proxytype": "saltext_ubus_jsonrpc",
                "host": "10.0.0.1",
                "password": "p",
            }
        }
        proxy_mod.init(opts)

        # No uci set calls -- rpcd timeout in fixture is already 300
        set_calls = [
            c for c in mock_instance.call.call_args_list if c[0][0] == "uci" and c[0][1] == "set"
        ]
        assert len(set_calls) == 0

    def test_missing_host_raises(self):
        opts = {"proxy": {"proxytype": "saltext_ubus_jsonrpc", "password": "secret"}}
        with pytest.raises(ValueError, match="required pillar key 'host'"):
            proxy_mod.init(opts)

    def test_missing_password_raises(self):
        opts = {"proxy": {"proxytype": "saltext_ubus_jsonrpc", "host": "10.0.0.1"}}
        with pytest.raises(ValueError, match="required pillar key 'password'"):
            proxy_mod.init(opts)


class TestAlive:
    def test_true_after_init(self):
        proxy_mod.DETAILS["initialized"] = True
        assert proxy_mod.alive({}) is True

    def test_false_before_init(self):
        assert proxy_mod.alive({}) is False


class TestPing:
    def test_success(self, mock_client):
        proxy_mod.DETAILS["client"] = mock_client
        assert proxy_mod.ping() is True

    def test_failure(self):
        client = MagicMock()
        client.call.side_effect = Exception("Connection refused")
        proxy_mod.DETAILS["client"] = client
        assert proxy_mod.ping() is False

    def test_transport_error_marks_unhealthy(self):
        client = MagicMock()
        client.call.side_effect = urllib.error.URLError("connection refused")
        proxy_mod.DETAILS["client"] = client
        proxy_mod.DETAILS["initialized"] = True
        assert proxy_mod.ping() is False
        assert proxy_mod.DETAILS["initialized"] is False

    def test_application_error_keeps_healthy(self):
        client = MagicMock()
        client.call.side_effect = UbusError(4, "Not found")
        proxy_mod.DETAILS["client"] = client
        proxy_mod.DETAILS["initialized"] = True
        assert proxy_mod.ping() is False
        assert proxy_mod.DETAILS["initialized"] is True


class TestShutdown:
    def test_clears_details(self, mock_client):
        proxy_mod.DETAILS["client"] = mock_client
        proxy_mod.DETAILS["initialized"] = True
        proxy_mod.DETAILS["grains_cache"] = {"os": "OpenWrt"}

        proxy_mod.shutdown({})
        assert not proxy_mod.DETAILS


class TestGrains:
    def test_returns_cached_grains(self):
        proxy_mod.DETAILS["grains_cache"] = {"os": "OpenWrt", "model": "WNDR3800"}
        assert proxy_mod.grains()["os"] == "OpenWrt"

    def test_empty_when_no_cache(self):
        assert proxy_mod.grains() == {}


class TestGrainsRefresh:
    def test_refetches(self, mock_client):
        proxy_mod.DETAILS["client"] = mock_client
        proxy_mod.DETAILS["grains_cache"] = {"os": "old"}

        result = proxy_mod.grains_refresh()
        assert result["os"] == "OpenWrt"
        assert result["model"] == "Netgear WNDR3800"


class TestCall:
    def test_delegates_to_client(self, mock_client):
        proxy_mod.DETAILS["client"] = mock_client
        result = proxy_mod.call("system", "board")
        assert result == BOARD_RESPONSE
        mock_client.call.assert_called_once_with("system", "board", None)


class TestCallErrorHandling:
    def test_url_error_marks_unhealthy(self):
        client = MagicMock()
        client.call.side_effect = urllib.error.URLError("connection refused")
        proxy_mod.DETAILS["client"] = client
        proxy_mod.DETAILS["initialized"] = True
        with pytest.raises(urllib.error.URLError):
            proxy_mod.call("system", "board")
        assert proxy_mod.DETAILS["initialized"] is False

    def test_timeout_marks_unhealthy(self):
        client = MagicMock()
        client.call.side_effect = TimeoutError("timed out")
        proxy_mod.DETAILS["client"] = client
        proxy_mod.DETAILS["initialized"] = True
        with pytest.raises(TimeoutError):
            proxy_mod.call("system", "board")
        assert proxy_mod.DETAILS["initialized"] is False

    def test_os_error_marks_unhealthy(self):
        client = MagicMock()
        client.call.side_effect = OSError("Network unreachable")
        proxy_mod.DETAILS["client"] = client
        proxy_mod.DETAILS["initialized"] = True
        with pytest.raises(OSError):
            proxy_mod.call("system", "board")
        assert proxy_mod.DETAILS["initialized"] is False

    def test_ubus_error_keeps_healthy(self):
        client = MagicMock()
        client.call.side_effect = UbusError(4, "Not found")
        proxy_mod.DETAILS["client"] = client
        proxy_mod.DETAILS["initialized"] = True
        with pytest.raises(UbusError):
            proxy_mod.call("uci", "get")
        assert proxy_mod.DETAILS["initialized"] is True

    def test_jsonrpc_error_keeps_healthy(self):
        client = MagicMock()
        client.call.side_effect = JsonRpcError(-32600, "Invalid request")
        proxy_mod.DETAILS["client"] = client
        proxy_mod.DETAILS["initialized"] = True
        with pytest.raises(JsonRpcError):
            proxy_mod.call("uci", "get")
        assert proxy_mod.DETAILS["initialized"] is True


class TestFetchGrains:
    def test_board_grains(self, mock_client):
        grains = proxy_mod._fetch_grains(mock_client)
        assert grains["os"] == "OpenWrt"
        assert grains["os_family"] == "OpenWrt"
        assert grains["osrelease"] == "24.10.5"
        assert grains["oscodename"] == "r29087-d9c5716d1d"
        assert grains["model"] == "Netgear WNDR3800"
        assert grains["board_name"] == "netgear,wndr3800"
        assert grains["cpuarch"] == "mips"
        assert grains["kernel"] == "6.6.86"
        assert grains["host"] == "austru.rss78.ldk35.archam.de"
        assert grains["domain"] == "rss78.ldk35.archam.de"

    def test_info_grains(self, mock_client):
        grains = proxy_mod._fetch_grains(mock_client)
        assert grains["mem_total"] == 124059648 // 1024
        assert grains["uptime"] == 123456

    def test_board_failure_returns_partial(self):
        client = MagicMock()
        client.call.side_effect = [Exception("board failed"), INFO_RESPONSE]
        grains = proxy_mod._fetch_grains(client)
        assert "os" not in grains
        assert grains["mem_total"] == 124059648 // 1024

    def test_hostname_without_domain(self):
        board = dict(BOARD_RESPONSE)
        board["hostname"] = "router"
        client = MagicMock()
        client.call.side_effect = lambda obj, method, params=None: {
            ("system", "board"): board,
            ("system", "info"): INFO_RESPONSE,
        }.get((obj, method))
        grains = proxy_mod._fetch_grains(client)
        assert grains["host"] == "router"
        assert "domain" not in grains
