"""
Unit tests for the saltext_uci proxy module.

All tests use a mocked RPC client. No network calls are made.
"""

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

import saltext.saltext_uci.proxy.ubus_jsonrpc as proxy_mod

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


@pytest.fixture(autouse=True)
def clean_details():
    """Ensure DETAILS is clean before and after each test."""
    proxy_mod.DETAILS.clear()
    yield
    proxy_mod.DETAILS.clear()


@pytest.fixture
def mock_client():
    """Create a mock RPC client."""
    client = MagicMock()
    client.call.side_effect = lambda obj, method, params=None: {
        ("system", "board"): BOARD_RESPONSE,
        ("system", "info"): INFO_RESPONSE,
    }.get((obj, method))
    return client


class TestInit:
    @patch("saltext.saltext_uci.proxy.ubus_jsonrpc.UbusRpcClient")
    def test_creates_client_and_logs_in(self, mock_client_cls):
        mock_instance = MagicMock()
        mock_instance.call.side_effect = lambda obj, method, params=None: {
            ("system", "board"): BOARD_RESPONSE,
            ("system", "info"): INFO_RESPONSE,
        }.get((obj, method))
        mock_client_cls.return_value = mock_instance

        opts = {
            "proxy": {
                "proxytype": "saltext_uci_ubus",
                "host": "10.35.24.1",
                "username": "salt",
                "password": "secret",
                "port": 443,
                "verify_ssl": False,
            }
        }
        proxy_mod.init(opts)

        mock_client_cls.assert_called_once_with(
            host="10.35.24.1",
            username="salt",
            password="secret",
            port=443,
            verify_ssl=False,
            timeout=30,
        )
        mock_instance.login.assert_called_once()
        assert proxy_mod.DETAILS["initialized"] is True

    @patch("saltext.saltext_uci.proxy.ubus_jsonrpc.UbusRpcClient")
    def test_fetches_grains_on_init(self, mock_client_cls):
        mock_instance = MagicMock()
        mock_instance.call.side_effect = lambda obj, method, params=None: {
            ("system", "board"): BOARD_RESPONSE,
            ("system", "info"): INFO_RESPONSE,
        }.get((obj, method))
        mock_client_cls.return_value = mock_instance

        opts = {
            "proxy": {
                "proxytype": "saltext_uci_ubus",
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
