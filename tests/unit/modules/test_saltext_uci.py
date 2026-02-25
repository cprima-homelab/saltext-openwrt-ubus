import pytest

import saltext.saltext_uci.modules.saltext_uci_mod as uci_mod

# --- Fixtures ---


def _make_run_all(retcode=0, stdout="", stderr=""):
    """Build a mock return dict for cmd.run_all."""
    return {"retcode": retcode, "stdout": stdout, "stderr": stderr, "pid": 1234}


@pytest.fixture
def configure_loader_modules():
    return {
        uci_mod: {
            "__salt__": {
                "cmd.run_all": None,  # replaced per-test via mock_run_all
            },
        },
    }


@pytest.fixture
def mock_run_all(monkeypatch):
    """Return a helper that sets cmd.run_all to a given side_effect list or callable."""

    def _setup(side_effect):
        if callable(side_effect) and not isinstance(side_effect, list):
            monkeypatch.setitem(uci_mod.__salt__, "cmd.run_all", side_effect)
        else:
            calls = iter(side_effect)
            monkeypatch.setitem(uci_mod.__salt__, "cmd.run_all", lambda *a, **kw: next(calls))

    return _setup


# --- uci_mod.get ---


class TestGet:
    def test_existing_key(self, mock_run_all):
        mock_run_all([_make_run_all(stdout="10.35.24.1")])
        assert uci_mod.get("network.lan.ipaddr") == "10.35.24.1"

    def test_missing_key(self, mock_run_all):
        mock_run_all([_make_run_all(retcode=1, stderr="uci: Entry not found")])
        assert uci_mod.get("network.nonexistent") is None

    def test_empty_value(self, mock_run_all):
        mock_run_all([_make_run_all(stdout="")])
        assert uci_mod.get("network.globals.ula_prefix") == ""

    def test_list_value(self, mock_run_all):
        mock_run_all([_make_run_all(stdout="1.1.1.1 1.0.0.1")])
        result = uci_mod.get("network.wan.dns")
        assert result == "1.1.1.1 1.0.0.1"


# --- uci_mod.get_all ---


class TestGetAll:
    def test_normal_section(self, mock_run_all):
        stdout = (
            "network.lan=interface\n"
            "network.lan.device='br-lan'\n"
            "network.lan.proto='static'\n"
            "network.lan.ipaddr='10.35.24.1'\n"
            "network.lan.netmask='255.255.255.0'"
        )
        mock_run_all([_make_run_all(stdout=stdout)])
        result = uci_mod.get_all("network", "lan")
        assert result == {
            "_type": "interface",
            "device": "br-lan",
            "proto": "static",
            "ipaddr": "10.35.24.1",
            "netmask": "255.255.255.0",
        }

    def test_section_with_list(self, mock_run_all):
        stdout = (
            "network.wan=interface\n"
            "network.wan.device='eth1'\n"
            "network.wan.proto='static'\n"
            "network.wan.dns='1.1.1.1' '1.0.0.1'"
        )
        mock_run_all([_make_run_all(stdout=stdout)])
        result = uci_mod.get_all("network", "wan")
        assert result["dns"] == ["1.1.1.1", "1.0.0.1"]
        assert result["device"] == "eth1"

    def test_missing_section(self, mock_run_all):
        mock_run_all([_make_run_all(retcode=1, stderr="uci: Entry not found")])
        assert uci_mod.get_all("network", "nonexistent") is None


# --- uci_mod.show ---


class TestShow:
    def test_package(self, mock_run_all):
        stdout = "network.lan=interface\nnetwork.lan.proto='static'"
        mock_run_all([_make_run_all(stdout=stdout)])
        result = uci_mod.show("network")
        assert "network.lan=interface" in result

    def test_missing_package(self, mock_run_all):
        mock_run_all([_make_run_all(retcode=1, stderr="uci: Entry not found")])
        assert uci_mod.show("nonexistent") is None


# --- uci_mod.set_ ---


class TestSet:
    def test_new_value(self, mock_run_all):
        mock_run_all(
            [
                _make_run_all(stdout="10.35.24.1"),  # get current
                _make_run_all(),  # uci set
            ]
        )
        assert uci_mod.set_("network.lan.ipaddr", "10.35.24.100") is True

    def test_same_value_noop(self, mock_run_all):
        mock_run_all([_make_run_all(stdout="10.35.24.1")])
        assert uci_mod.set_("network.lan.ipaddr", "10.35.24.1") is False

    def test_error(self, mock_run_all):
        mock_run_all(
            [
                _make_run_all(retcode=1, stderr="uci: Entry not found"),  # get
                _make_run_all(retcode=1, stderr="uci: Entry not found"),  # set fails
            ]
        )
        with pytest.raises(Exception, match="uci set failed"):
            uci_mod.set_("bad.path", "value")


# --- uci_mod.delete ---


class TestDelete:
    def test_existing_key(self, mock_run_all):
        mock_run_all([_make_run_all()])
        assert uci_mod.delete("network.wan6") is True

    def test_already_absent(self, mock_run_all):
        mock_run_all([_make_run_all(retcode=1)])
        assert uci_mod.delete("network.wan6") is True


# --- uci_mod.add_list ---


class TestAddList:
    def test_value_not_in_list(self, mock_run_all):
        mock_run_all(
            [
                _make_run_all(stdout="1.1.1.1"),  # get current
                _make_run_all(),  # add_list
            ]
        )
        assert uci_mod.add_list("network.wan.dns", "8.8.8.8") is True

    def test_value_already_present(self, mock_run_all):
        mock_run_all([_make_run_all(stdout="1.1.1.1 1.0.0.1")])
        assert uci_mod.add_list("network.wan.dns", "1.1.1.1") is False

    def test_list_unset(self, mock_run_all):
        mock_run_all(
            [
                _make_run_all(retcode=1, stderr="uci: Entry not found"),  # get
                _make_run_all(),  # add_list
            ]
        )
        assert uci_mod.add_list("network.wan.dns", "1.1.1.1") is True


# --- uci_mod.set_list ---


class TestSetList:
    def test_same_list_noop(self, mock_run_all):
        mock_run_all([_make_run_all(stdout="1.1.1.1 1.0.0.1")])
        assert uci_mod.set_list("network.wan.dns", ["1.1.1.1", "1.0.0.1"]) is False

    def test_different_list(self, mock_run_all):
        mock_run_all(
            [
                _make_run_all(stdout="1.1.1.1 1.0.0.1"),  # get current
                _make_run_all(),  # delete
                _make_run_all(),  # add_list 8.8.8.8
                _make_run_all(),  # add_list 8.8.4.4
            ]
        )
        assert uci_mod.set_list("network.wan.dns", ["8.8.8.8", "8.8.4.4"]) is True

    def test_empty_target(self, mock_run_all):
        mock_run_all(
            [
                _make_run_all(retcode=1, stderr="uci: Entry not found"),  # get
                _make_run_all(),  # delete (no-op via -q)
                _make_run_all(),  # add_list
            ]
        )
        assert uci_mod.set_list("network.wan.dns", ["1.1.1.1"]) is True


# --- uci_mod.commit ---


class TestCommit:
    def test_success(self, mock_run_all):
        mock_run_all([_make_run_all()])
        assert uci_mod.commit("network") is True

    def test_error(self, mock_run_all):
        mock_run_all([_make_run_all(retcode=1, stderr="uci: I/O error")])
        with pytest.raises(Exception, match="uci commit failed"):
            uci_mod.commit("network")
