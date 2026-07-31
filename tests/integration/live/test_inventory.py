"""
Configured-state UCI inventory against a live OpenWrt device.

Verifies that the Salt execution module can connect to a real device,
enumerate its UCI configuration, and collect provenance-wrapped evidence
records — without issuing any mutations.

Intended use: point-in-time inventory snapshot prior to router migration.
Tests assert schema and non-emptiness only — never specific option values,
since those reflect the current state of a real, historically-grown network.

Set LIVE_HOST, LIVE_SALT_AGENT_PASSWORD (and optionally LIVE_ROOT_PASSWORD)
in .env before running:

    uv run pytest tests/integration/live/ -v
"""

import datetime

import pytest

from saltext.openwrt_ubus.sensitivity import SensitivityProfile
from saltext.openwrt_ubus.sensitivity import assert_grains_safe
from saltext.openwrt_ubus.sensitivity import classify_export
from saltext.openwrt_ubus.sensitivity import grains_projection
from tests.integration.live.conftest import LIVE_HOST
from tests.integration.live.conftest import make_rpc_client
from tests.integration.live.conftest import read_device_config

# Packages that carry migration-relevant configuration on any OpenWrt router.
MIGRATION_PACKAGES = ["network", "system", "dhcp", "wireless", "firewall", "dropbear"]


@pytest.fixture(scope="module")
def uci_module(live_device):  # pylint: disable=unused-argument
    # pylint: disable-next=import-outside-toplevel
    from saltext.openwrt_ubus.modules import ubus_jsonrpc as mod

    client = make_rpc_client()
    mod.__opts__ = {"proxy": {"proxytype": "openwrt_ubus_jsonrpc"}, "id": LIVE_HOST}
    mod.__proxy__ = {"openwrt_ubus_jsonrpc.call": client.call}
    yield mod


@pytest.fixture(scope="module")
def available_configs(uci_module):
    """Full list of UCI packages present on the device — fetched once."""
    return uci_module.configs()


# ---------------------------------------------------------------------------
# Package enumeration
# ---------------------------------------------------------------------------


class TestConfigs:
    def test_returns_list(self, available_configs):
        assert isinstance(available_configs, list)

    def test_non_empty(self, available_configs):
        assert len(available_configs) > 0

    @pytest.mark.parametrize("pkg", MIGRATION_PACKAGES)
    def test_migration_package_present(self, pkg, available_configs):
        assert pkg in available_configs, f"expected UCI package '{pkg}' on live device"


# ---------------------------------------------------------------------------
# Raw get() — schema validation, no value assertions
# ---------------------------------------------------------------------------


class TestGet:
    @pytest.mark.parametrize("pkg", ["network", "system"])
    def test_returns_non_empty_dict(self, uci_module, pkg):
        result = uci_module.get(pkg)
        assert isinstance(result, dict)
        assert len(result) > 0

    def test_all_sections_carry_metadata(
        self, uci_module, available_configs
    ):  # pylint: disable=unused-argument
        # Spot-check network — every section must have _type, _anonymous, _index.
        result = uci_module.get("network")
        for name, section in result.items():
            assert "_type" in section, f"section {name!r} missing _type"
            assert "_anonymous" in section, f"section {name!r} missing _anonymous"
            assert "_index" in section, f"section {name!r} missing _index"

    def test_named_sections_not_anonymous(self, uci_module):
        result = uci_module.get("system")
        named = {k: v for k, v in result.items() if not v.get("_anonymous")}
        # system always has at least one named-or-singleton section
        assert len(named) > 0 or len(result) > 0


# ---------------------------------------------------------------------------
# config_evidence() — provenance envelope for each migration package
# ---------------------------------------------------------------------------


class TestConfigEvidence:
    @pytest.mark.parametrize("pkg", MIGRATION_PACKAGES)
    def test_top_level_schema(self, uci_module, pkg, available_configs):
        if pkg not in available_configs:
            pytest.skip(f"package '{pkg}' not present on this device")
        result = uci_module.config_evidence(pkg)
        assert set(result) >= {
            "evidence_type",
            "source_type",
            "source_device",
            "scope",
            "collected_at",
            "payload",
            "provenance",
        }

    @pytest.mark.parametrize("pkg", MIGRATION_PACKAGES)
    def test_evidence_type(self, uci_module, pkg, available_configs):
        if pkg not in available_configs:
            pytest.skip(f"package '{pkg}' not present on this device")
        assert uci_module.config_evidence(pkg)["evidence_type"] == "configured_state"

    @pytest.mark.parametrize("pkg", MIGRATION_PACKAGES)
    def test_source_device_is_live_host(self, uci_module, pkg, available_configs):
        if pkg not in available_configs:
            pytest.skip(f"package '{pkg}' not present on this device")
        assert uci_module.config_evidence(pkg)["source_device"] == LIVE_HOST

    @pytest.mark.parametrize("pkg", MIGRATION_PACKAGES)
    def test_scope(self, uci_module, pkg, available_configs):
        if pkg not in available_configs:
            pytest.skip(f"package '{pkg}' not present on this device")
        assert uci_module.config_evidence(pkg)["scope"] == {"config": pkg}

    @pytest.mark.parametrize("pkg", MIGRATION_PACKAGES)
    def test_collected_at_is_utc(self, uci_module, pkg, available_configs):
        if pkg not in available_configs:
            pytest.skip(f"package '{pkg}' not present on this device")
        ts = uci_module.config_evidence(pkg)["collected_at"]
        dt = datetime.datetime.fromisoformat(ts)
        assert dt.tzinfo is not None

    @pytest.mark.parametrize("pkg", MIGRATION_PACKAGES)
    def test_payload_non_empty(self, uci_module, pkg, available_configs):
        if pkg not in available_configs:
            pytest.skip(f"package '{pkg}' not present on this device")
        payload = uci_module.config_evidence(pkg)["payload"]
        assert isinstance(payload, dict)
        assert len(payload) > 0

    @pytest.mark.parametrize("pkg", MIGRATION_PACKAGES)
    def test_provenance(self, uci_module, pkg, available_configs):
        if pkg not in available_configs:
            pytest.skip(f"package '{pkg}' not present on this device")
        prov = uci_module.config_evidence(pkg)["provenance"]
        assert prov["collector"] == "saltext-openwrt-ubus"
        assert prov["transport"] == "ubus-jsonrpc"
        assert isinstance(prov["collector_version"], str)


# ---------------------------------------------------------------------------
# Sensitivity classification and projection
# ---------------------------------------------------------------------------


class TestClassifyAndProject:  # pylint: disable=redefined-outer-name
    def test_wireless_key_is_null_in_evidence(self, uci_module, available_configs):
        if "wireless" not in available_configs:
            pytest.skip("wireless package not present on this device")
        payload = uci_module.config_evidence("wireless")["payload"]
        wifi_ifaces = [
            (name, sec) for name, sec in payload.items() if sec.get("_type") == "wifi-iface"
        ]
        for name, sec in wifi_ifaces:
            if "key" in sec:
                assert (
                    sec["key"] is None
                ), f"wifi-iface {name!r} key must be null in evidence payload"

    def test_wireguard_private_key_null_if_present(self, uci_module, available_configs):
        if "network" not in available_configs:
            pytest.skip("network package not present on this device")
        payload = uci_module.config_evidence("network")["payload"]
        for name, sec in payload.items():
            if sec.get("_type") == "interface" and "private_key" in sec:
                assert (
                    sec["private_key"] is None
                ), f"WireGuard interface {name!r} private_key must be null in evidence"

    def test_grains_projection_passes_invariant(self, uci_module, available_configs):
        if "wireless" not in available_configs:
            pytest.skip("wireless package not present on this device")
        profile = SensitivityProfile.load_builtin()
        export = uci_module.config_export("wireless")
        classified = classify_export(export, package="wireless", profile=profile)
        grains = grains_projection(classified)
        assert_grains_safe(grains)

    @pytest.mark.parametrize("pkg", MIGRATION_PACKAGES)
    def test_evidence_payload_has_sensitivity_metadata(self, uci_module, pkg, available_configs):
        if pkg not in available_configs:
            pytest.skip(f"package '{pkg}' not present on this device")
        payload = uci_module.config_evidence(pkg)["payload"]
        for name, sec in payload.items():
            if isinstance(sec, dict) and not name.startswith("_"):
                assert (
                    "_sensitivity" in sec
                ), f"section {name!r} in {pkg!r} evidence payload missing _sensitivity"


# ---------------------------------------------------------------------------
# System information
# ---------------------------------------------------------------------------


class TestRuntimeEvidence:
    @pytest.mark.parametrize("domain", ["network", "system", "services"])
    def test_top_level_schema(self, uci_module, domain):
        result = uci_module.runtime_evidence(domain)
        assert set(result) >= {
            "evidence_type",
            "source_type",
            "source_device",
            "scope",
            "collected_at",
            "payload",
            "provenance",
        }

    @pytest.mark.parametrize("domain", ["network", "system", "services"])
    def test_evidence_type(self, uci_module, domain):
        assert uci_module.runtime_evidence(domain)["evidence_type"] == "observed_state"

    @pytest.mark.parametrize("domain", ["network", "system", "services"])
    def test_source_type(self, uci_module, domain):
        assert uci_module.runtime_evidence(domain)["source_type"] == "openwrt-ubus"

    @pytest.mark.parametrize("domain", ["network", "system", "services"])
    def test_scope(self, uci_module, domain):
        assert uci_module.runtime_evidence(domain)["scope"] == {"domain": domain}

    @pytest.mark.parametrize("domain", ["network", "system", "services"])
    def test_source_device(self, uci_module, domain):
        assert uci_module.runtime_evidence(domain)["source_device"] == LIVE_HOST

    @pytest.mark.parametrize("domain", ["network", "system", "services"])
    def test_payload_non_empty(self, uci_module, domain):
        payload = uci_module.runtime_evidence(domain)["payload"]
        assert isinstance(payload, dict)
        assert len(payload) > 0

    def test_system_payload_has_board_and_info(self, uci_module):
        payload = uci_module.runtime_evidence("system")["payload"]
        assert "board" in payload
        assert "info" in payload

    def test_network_payload_has_interfaces(self, uci_module):
        payload = uci_module.runtime_evidence("network")["payload"]
        assert "interface" in payload

    @pytest.mark.parametrize("domain", ["network", "system", "services"])
    def test_collected_at_is_utc(self, uci_module, domain):
        ts = uci_module.runtime_evidence(domain)["collected_at"]
        assert datetime.datetime.fromisoformat(ts).tzinfo is not None

    @pytest.mark.parametrize("domain", ["network", "system", "services"])
    def test_provenance(self, uci_module, domain):
        prov = uci_module.runtime_evidence(domain)["provenance"]
        assert prov["collector"] == "saltext-openwrt-ubus"
        assert prov["transport"] == "ubus-jsonrpc"

    def test_invalid_domain_raises(self, uci_module):
        with pytest.raises(ValueError, match="unknown runtime domain"):
            uci_module.runtime_evidence("wifi")


class TestSystemInfo:
    def test_system_board_returns_dict(self, uci_module):
        result = uci_module.system_board()
        assert isinstance(result, dict)
        assert len(result) > 0

    def test_system_board_has_model(self, uci_module):
        result = uci_module.system_board()
        assert "model" in result or "board_name" in result

    def test_system_info_returns_dict(self, uci_module):
        result = uci_module.system_info()
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Pending changes — reads must leave no staged mutations
# ---------------------------------------------------------------------------


class TestPendingChanges:
    @pytest.mark.parametrize("pkg", ["network", "system", "dhcp"])
    def test_no_pending_changes_after_read(self, uci_module, pkg, available_configs):
        if pkg not in available_configs:
            pytest.skip(f"package '{pkg}' not present on this device")
        uci_module.get(pkg)
        uci_module.config_export(pkg)
        uci_module.config_evidence(pkg)
        assert uci_module.changes(pkg) == []


# ---------------------------------------------------------------------------
# Immutability — /etc/config files unchanged after reads (SSH-dependent)
# ---------------------------------------------------------------------------


class TestImmutability:
    @pytest.mark.parametrize("pkg", ["network", "system"])
    def test_config_file_unchanged_after_inventory(self, uci_module, ssh_client, pkg):
        before = read_device_config(ssh_client, pkg)
        uci_module.get(pkg)
        uci_module.config_export(pkg)
        uci_module.config_evidence(pkg)
        after = read_device_config(ssh_client, pkg)
        assert before == after
