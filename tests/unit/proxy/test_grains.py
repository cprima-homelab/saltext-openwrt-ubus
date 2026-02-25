import subprocess
from unittest.mock import patch

import pytest

import saltext.saltext_uci.proxy.saltext_uci_mod as uci_proxy

# Captured live output from austru, delimited by ---DELIM---
FULL_OUTPUT = """\
DISTRIB_ID='OpenWrt'
DISTRIB_RELEASE='24.10.5'
DISTRIB_REVISION='r29087-d9c5716d1d'
DISTRIB_TARGET='ath79/generic'
DISTRIB_ARCH='mips_24kc'
DISTRIB_DESCRIPTION='OpenWrt 24.10.5 r29087-d9c5716d1d'
---DELIM---
Netgear WNDR3800
---DELIM---
netgear,wndr3800
---DELIM---
austru.rss78.ldk35.archam.de
---DELIM---
MemTotal:         121152 kB
---DELIM---
Filesystem           1K-blocks      Used Available Use% Mounted on
/dev/mtdblock5            5888       320      5568   5% /overlay
"""

# Output with /tmp/sysinfo/model missing (empty section)
PARTIAL_OUTPUT = """\
DISTRIB_ID='OpenWrt'
DISTRIB_RELEASE='24.10.5'
DISTRIB_REVISION='r29087-d9c5716d1d'
DISTRIB_TARGET='ath79/generic'
DISTRIB_ARCH='mips_24kc'
DISTRIB_DESCRIPTION='OpenWrt 24.10.5 r29087-d9c5716d1d'
---DELIM---

---DELIM---
netgear,wndr3800
---DELIM---
austru.rss78.ldk35.archam.de
---DELIM---
MemTotal:         121152 kB
---DELIM---
Filesystem           1K-blocks      Used Available Use% Mounted on
/dev/mtdblock5            5888       320      5568   5% /overlay
"""


@pytest.fixture
def proxy_context(monkeypatch):
    """Initialize the proxy and provide its context."""
    ctx = {}
    monkeypatch.setattr(uci_proxy, "__context__", ctx)
    opts = {
        "proxy": {
            "proxytype": "saltext_uci",
            "host": "10.35.24.1",
            "user": "root",
            "port": 22,
            "ssh_priv": "/root/.ssh/id_ed25519",
        }
    }
    uci_proxy.init(opts)
    return ctx


def _mock_ssh(stdout, retcode=0):
    return subprocess.CompletedProcess(args=[], returncode=retcode, stdout=stdout, stderr="")


class TestGetGrains:
    def test_full_output(self, proxy_context, monkeypatch):
        monkeypatch.setattr(uci_proxy, "__context__", proxy_context)
        with patch("subprocess.run", return_value=_mock_ssh(FULL_OUTPUT)):
            grains = uci_proxy.get_grains()

        assert grains["os"] == "OpenWrt"
        assert grains["os_version"] == "24.10.5"
        assert grains["os_revision"] == "r29087-d9c5716d1d"
        assert grains["os_target"] == "ath79/generic"
        assert grains["os_arch"] == "mips_24kc"
        assert grains["model"] == "Netgear WNDR3800"
        assert grains["board_name"] == "netgear,wndr3800"
        assert grains["hostname"] == "austru.rss78.ldk35.archam.de"
        assert grains["mem_total_kb"] == 121152
        assert grains["flash_total_kb"] == 5888
        assert grains["flash_used_kb"] == 320

    def test_caches_in_context(self, proxy_context, monkeypatch):
        monkeypatch.setattr(uci_proxy, "__context__", proxy_context)
        with patch("subprocess.run", return_value=_mock_ssh(FULL_OUTPUT)) as mock_run:
            first = uci_proxy.get_grains()
            second = uci_proxy.get_grains()

        assert first is second
        assert mock_run.call_count == 1

    def test_ssh_failure_returns_empty(self, proxy_context, monkeypatch):
        monkeypatch.setattr(uci_proxy, "__context__", proxy_context)
        result = subprocess.CompletedProcess(
            args=[], returncode=255, stdout="", stderr="Connection refused"
        )
        with patch("subprocess.run", return_value=result):
            grains = uci_proxy.get_grains()

        assert grains == {}

    def test_partial_output_missing_model(self, proxy_context, monkeypatch):
        monkeypatch.setattr(uci_proxy, "__context__", proxy_context)
        with patch("subprocess.run", return_value=_mock_ssh(PARTIAL_OUTPUT)):
            grains = uci_proxy.get_grains()

        assert "model" not in grains
        assert grains["os"] == "OpenWrt"
        assert grains["board_name"] == "netgear,wndr3800"
        assert grains["mem_total_kb"] == 121152


class TestGrainsRefresh:
    def test_clears_cache_and_refetches(self, proxy_context, monkeypatch):
        monkeypatch.setattr(uci_proxy, "__context__", proxy_context)
        with patch("subprocess.run", return_value=_mock_ssh(FULL_OUTPUT)) as mock_run:
            uci_proxy.get_grains()
            refreshed = uci_proxy.grains_refresh()

        assert mock_run.call_count == 2
        assert refreshed["os"] == "OpenWrt"


class TestFns:
    def test_returns_details(self):
        result = uci_proxy.fns()
        assert result == {"details": "OpenWrt device grains."}
