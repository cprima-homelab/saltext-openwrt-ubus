"""
Unit tests for the saltext_uci grains module.
"""

from unittest.mock import MagicMock

import pytest

import saltext.saltext_uci.grains.saltext_uci as grains_mod


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
        assert "not saltext_uci_ubus or saltext_uci_ssh" in result[1]

    def test_true_for_ubus_proxytype(self, patch_dunders):
        patch_dunders["proxy"] = {"proxytype": "saltext_uci_ubus"}
        result = grains_mod.__virtual__()
        assert result == "saltext_uci"

    def test_true_for_ssh_proxytype(self, patch_dunders):
        patch_dunders["proxy"] = {"proxytype": "saltext_uci_ssh"}
        result = grains_mod.__virtual__()
        assert result == "saltext_uci"


class TestSaltextUciGrains:
    def test_returns_empty_when_proxy_none(self, patch_dunders):
        patch_dunders["proxy"] = {"proxytype": "saltext_uci_ubus"}
        result = grains_mod.saltext_uci(proxy=None)
        assert result == {}

    def test_returns_empty_when_grains_fn_missing(self, patch_dunders):
        patch_dunders["proxy"] = {"proxytype": "saltext_uci_ubus"}
        proxy = {}
        result = grains_mod.saltext_uci(proxy=proxy)
        assert result == {}

    def test_returns_grains_from_ubus_proxy(self, patch_dunders):
        patch_dunders["proxy"] = {"proxytype": "saltext_uci_ubus"}
        expected = {"os": "OpenWrt", "model": "WNDR3800"}
        proxy = {"saltext_uci_ubus.grains": MagicMock(return_value=expected)}
        result = grains_mod.saltext_uci(proxy=proxy)
        assert result == expected
        proxy["saltext_uci_ubus.grains"].assert_called_once()

    def test_returns_grains_from_ssh_proxy(self, patch_dunders):
        patch_dunders["proxy"] = {"proxytype": "saltext_uci_ssh"}
        expected = {"os": "OpenWrt", "model": "GL-MT3000"}
        proxy = {"saltext_uci_ssh.grains": MagicMock(return_value=expected)}
        result = grains_mod.saltext_uci(proxy=proxy)
        assert result == expected
        proxy["saltext_uci_ssh.grains"].assert_called_once()
