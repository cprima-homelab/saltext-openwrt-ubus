import subprocess
from unittest.mock import patch

import pytest

import saltext.saltext_uci.proxy.saltext_uci_mod as uci_proxy


@pytest.fixture
def proxy_opts():
    return {
        "proxy": {
            "proxytype": "saltext_uci",
            "host": "10.35.24.1",
            "user": "root",
            "port": 22,
            "ssh_priv": "/root/.ssh/id_ed25519",
        }
    }


@pytest.fixture
def proxy_context(monkeypatch, proxy_opts):
    """Initialize the proxy and provide its context."""
    ctx = {}
    monkeypatch.setattr(uci_proxy, "__context__", ctx)
    uci_proxy.init(proxy_opts)
    return ctx


class TestInit:
    def test_stores_config(self, proxy_context):
        conf = proxy_context["saltext_uci"]
        assert conf["host"] == "10.35.24.1"
        assert conf["user"] == "root"
        assert conf["port"] == 22
        assert conf["ssh_priv"] == "/root/.ssh/id_ed25519"
        assert conf["initialized"] is True

    def test_defaults(self, monkeypatch):
        ctx = {}
        monkeypatch.setattr(uci_proxy, "__context__", ctx)
        opts = {"proxy": {"proxytype": "saltext_uci", "host": "192.168.1.1"}}
        uci_proxy.init(opts)
        assert ctx["saltext_uci"]["user"] == "root"
        assert ctx["saltext_uci"]["port"] == 22


class TestInitialized:
    def test_true_after_init(self, proxy_context, monkeypatch):
        monkeypatch.setattr(uci_proxy, "__context__", proxy_context)
        assert uci_proxy.initialized() is True

    def test_false_before_init(self, monkeypatch):
        monkeypatch.setattr(uci_proxy, "__context__", {})
        assert uci_proxy.initialized() is False


class TestPing:
    def test_success(self, proxy_context, monkeypatch):
        monkeypatch.setattr(uci_proxy, "__context__", proxy_context)
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok\n", stderr="")
        with patch("subprocess.run", return_value=mock_result):
            assert uci_proxy.ping() is True

    def test_failure(self, proxy_context, monkeypatch):
        monkeypatch.setattr(uci_proxy, "__context__", proxy_context)
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=255, stdout="", stderr="Connection refused"
        )
        with patch("subprocess.run", return_value=mock_result):
            assert uci_proxy.ping() is False


class TestCmd:
    def test_returns_run_all_format(self, proxy_context, monkeypatch):
        monkeypatch.setattr(uci_proxy, "__context__", proxy_context)
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="10.35.24.1\n", stderr=""
        )
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            ret = uci_proxy.cmd("uci get network.lan.ipaddr")
            assert ret["retcode"] == 0
            assert ret["stdout"] == "10.35.24.1\n"
            assert ret["stderr"] == ""
            # Verify SSH command was constructed correctly
            call_args = mock_run.call_args[0][0]
            assert "ssh" == call_args[0]
            assert "root@10.35.24.1" in call_args
            assert "uci get network.lan.ipaddr" in call_args

    def test_error_retcode(self, proxy_context, monkeypatch):
        monkeypatch.setattr(uci_proxy, "__context__", proxy_context)
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="uci: Entry not found\n"
        )
        with patch("subprocess.run", return_value=mock_result):
            ret = uci_proxy.cmd("uci get network.nonexistent")
            assert ret["retcode"] == 1
            assert "Entry not found" in ret["stderr"]

    def test_ssh_priv_key_used(self, proxy_context, monkeypatch):
        monkeypatch.setattr(uci_proxy, "__context__", proxy_context)
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            uci_proxy.cmd("uci show network")
            call_args = mock_run.call_args[0][0]
            idx = call_args.index("-i")
            assert call_args[idx + 1] == "/root/.ssh/id_ed25519"


class TestShutdown:
    def test_clears_context(self, proxy_context, monkeypatch):
        monkeypatch.setattr(uci_proxy, "__context__", proxy_context)
        assert "saltext_uci" in proxy_context
        uci_proxy.shutdown({})
        assert "saltext_uci" not in proxy_context
