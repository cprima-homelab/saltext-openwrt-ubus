"""
Unit tests for the uci grains module.
"""

from unittest.mock import MagicMock

import pytest

import saltext.uci.grains.saltext_ubus as grains_mod


@pytest.fixture(autouse=True)
def patch_dunders(monkeypatch):
    """Set up Salt dunders for the grains module."""
    opts = {}
    monkeypatch.setattr(grains_mod, "__opts__", opts, raising=False)
    return opts


class TestVirtual:
    def test_false_when_not_proxy(self, patch_dunders):
        # No "proxy" key in opts -- patch_dunders starts empty
        assert not patch_dunders
        result = grains_mod.__virtual__()
        assert result == (False, "Not a proxy minion")

    def test_false_for_wrong_proxytype(self, patch_dunders):
        patch_dunders["proxy"] = {"proxytype": "napalm"}
        result = grains_mod.__virtual__()
        assert result[0] is False
        assert "not uci_ubus_jsonrpc or uci_ssh" in result[1]

    def test_true_for_ubus_proxytype(self, patch_dunders):
        patch_dunders["proxy"] = {"proxytype": "uci_ubus_jsonrpc"}
        result = grains_mod.__virtual__()
        assert result == "uci"

    def test_true_for_ssh_proxytype(self, patch_dunders):
        patch_dunders["proxy"] = {"proxytype": "uci_ssh"}
        result = grains_mod.__virtual__()
        assert result == "uci"


class TestSaltextUciGrains:
    def test_returns_empty_when_proxy_none(self, patch_dunders):
        patch_dunders["proxy"] = {"proxytype": "uci_ubus_jsonrpc"}
        result = grains_mod.uci(proxy=None)
        assert result == {}

    def test_returns_empty_when_grains_fn_missing(self, patch_dunders):
        patch_dunders["proxy"] = {"proxytype": "uci_ubus_jsonrpc"}
        proxy = {}
        result = grains_mod.uci(proxy=proxy)
        assert result == {}

    def test_returns_grains_from_ubus_proxy(self, patch_dunders):
        patch_dunders["proxy"] = {"proxytype": "uci_ubus_jsonrpc"}
        expected = {"os": "OpenWrt", "model": "WNDR3800"}
        proxy = {"uci_ubus_jsonrpc.grains": MagicMock(return_value=expected)}
        result = grains_mod.uci(proxy=proxy)
        assert result == expected
        proxy["uci_ubus_jsonrpc.grains"].assert_called_once()

    def test_returns_grains_from_ssh_proxy(self, patch_dunders):
        patch_dunders["proxy"] = {"proxytype": "uci_ssh"}
        expected = {"os": "OpenWrt", "model": "GL-MT3000"}
        proxy = {"uci_ssh.grains": MagicMock(return_value=expected)}
        result = grains_mod.uci(proxy=proxy)
        assert result == expected
        proxy["uci_ssh.grains"].assert_called_once()
