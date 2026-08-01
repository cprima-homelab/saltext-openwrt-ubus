"""
Configured-state UCI inventory and evidence collection: Salt execution module against the live container.

Flow:
    testcorpus fixture
        → container /etc/config/testcorpus
        → rpcd / ubus JSON-RPC (HTTP)
        → saltext.uci_ubus.modules.ubus_jsonrpc (Salt execution module)
        → normalized inventory result
        → assertions vs known corpus
        → /etc/config/testcorpus byte-for-byte unchanged

Test setup (make_rpc_client, __proxy__ injection) uses UbusRpcClient directly.
All inventory calls go through the Salt execution module API — the production
code path used by proxy minions in the field.
"""

import datetime

import pytest

from tests.integration.openwrt.conftest import CONTAINER_NAME, make_rpc_client, read_container_config


@pytest.fixture(scope="module")
def uci_module(openwrt_container):  # pylint: disable=unused-argument
    """
    Salt execution module wired to the real container.

    UbusRpcClient handles transport (test setup); the module's __proxy__
    dunder is injected so that every call goes through the production
    ubus_jsonrpc → ubus_ops code path.
    """
    # pylint: disable-next=import-outside-toplevel
    from saltext.uci_ubus.modules import ubus_jsonrpc as mod

    client = make_rpc_client()

    mod.__opts__ = {"proxy": {"proxytype": "uci_ubus_jsonrpc"}, "id": "openwrt-test-target"}
    mod.__proxy__ = {"uci_ubus_jsonrpc.call": client.call}

    yield mod


@pytest.fixture(scope="module")
def testcorpus_raw(uci_module):
    """Full get() result for testcorpus — fetched once per module."""
    return uci_module.get("testcorpus")


@pytest.fixture(scope="module")
def testcorpus_export(uci_module):
    """config_export() result for testcorpus — fetched once per module."""
    return uci_module.config_export("testcorpus")


# ---------------------------------------------------------------------------
# Package enumeration
# ---------------------------------------------------------------------------


class TestConfigs:
    def test_testcorpus_present(self, uci_module):
        assert "testcorpus" in uci_module.configs()

    def test_testcorpus_deps_present(self, uci_module):
        assert "testcorpus_deps" in uci_module.configs()

    def test_testcorpus_empty_present(self, uci_module):
        assert "testcorpus_empty" in uci_module.configs()

    def test_configs_is_list(self, uci_module):
        assert isinstance(uci_module.configs(), list)


# ---------------------------------------------------------------------------
# Raw get() inventory — named sections
# ---------------------------------------------------------------------------


class TestGetNamedSections:
    NAMED_SECTIONS = [
        "heckle_cam",
        "overhead_cam",
        "face_cam",
        "aj_lav",
        "heckle_hydrophone",
        "hecklefish",
        "obs_box",
        "raid_shadow_legends",
    ]

    def test_all_named_sections_present(self, testcorpus_raw):
        for name in self.NAMED_SECTIONS:
            assert name in testcorpus_raw, f"expected named section '{name}'"

    def test_named_section_not_anonymous(self, testcorpus_raw):
        assert testcorpus_raw["heckle_cam"]["_anonymous"] is False

    def test_named_section_type(self, testcorpus_raw):
        assert testcorpus_raw["heckle_cam"]["_type"] == "camera"

    def test_scalar_option(self, testcorpus_raw):
        assert testcorpus_raw["heckle_cam"]["bitrate"] == "6000"

    def test_space_embedded_scalar_preserved(self, testcorpus_raw):
        # resolution contains a space — must survive the round-trip
        assert testcorpus_raw["overhead_cam"]["resolution"] == "3840 2160"

    def test_list_option_returned_as_list(self, testcorpus_raw):
        # face_cam uses 'list mac' so mac must be a Python list
        assert isinstance(testcorpus_raw["face_cam"]["mac"], list)

    def test_tag_list_preserved(self, testcorpus_raw):
        assert testcorpus_raw["heckle_cam"]["tag"] == ["fishtank", "wide"]

    def test_empty_named_section_present(self, testcorpus_raw):
        # raid_shadow_legends is a named section with no options
        assert "raid_shadow_legends" in testcorpus_raw
        s = testcorpus_raw["raid_shadow_legends"]
        assert s["_type"] == "sponsor"
        assert s["_anonymous"] is False

    def test_hecklefish_named_section(self, testcorpus_raw):
        # hecklefish is a named section of type 'fish' (mixed with anonymous fish)
        assert testcorpus_raw["hecklefish"]["_type"] == "fish"
        assert testcorpus_raw["hecklefish"]["_anonymous"] is False


# ---------------------------------------------------------------------------
# Raw get() inventory — anonymous sections
# ---------------------------------------------------------------------------


class TestGetAnonymousSections:
    def test_anonymous_sections_present(self, testcorpus_raw):
        anon = [s for s in testcorpus_raw.values() if s.get("_anonymous") is True]
        assert len(anon) > 0

    def test_studio_singleton_anonymous(self, testcorpus_raw):
        studios = [s for s in testcorpus_raw.values() if s.get("_type") == "studio"]
        assert len(studios) == 1
        assert studios[0]["_anonymous"] is True
        assert studios[0]["name"] == "The Basement"

    def test_three_anonymous_light_sections(self, testcorpus_raw):
        lights = [s for s in testcorpus_raw.values() if s.get("_type") == "light"]
        assert len(lights) == 3

    def test_anonymous_and_named_fish_coexist(self, testcorpus_raw):
        all_fish = [s for s in testcorpus_raw.values() if s.get("_type") == "fish"]
        named = [f for f in all_fish if not f.get("_anonymous")]
        anon = [f for f in all_fish if f.get("_anonymous")]
        assert len(named) == 1  # hecklefish
        assert len(anon) == 2  # Neon tetra + Corydoras panda

    def test_seven_anonymous_host_sections(self, testcorpus_raw):
        hosts = [s for s in testcorpus_raw.values() if s.get("_type") == "host"]
        assert len(hosts) == 7

    def test_five_anonymous_rule_sections(self, testcorpus_raw):
        rules = [s for s in testcorpus_raw.values() if s.get("_type") == "rule"]
        assert len(rules) == 5

    def test_metadata_fields_present(self, testcorpus_raw):
        # Every section must carry _type, _anonymous, _index
        for name, section in testcorpus_raw.items():
            assert "_type" in section, f"section {name!r} missing _type"
            assert "_anonymous" in section, f"section {name!r} missing _anonymous"
            assert "_index" in section, f"section {name!r} missing _index"


# ---------------------------------------------------------------------------
# Normalized config_export() inventory
# ---------------------------------------------------------------------------


class TestConfigExport:
    def test_named_sections_emitted_directly(self, testcorpus_export):
        assert "heckle_cam" in testcorpus_export
        assert "obs_box" in testcorpus_export

    def test_singleton_anonymous_keyed_by_type(self, testcorpus_export):
        # studio is a singleton anonymous → _studio
        assert "_studio" in testcorpus_export

    def test_singleton_scalar_preserved(self, testcorpus_export):
        assert testcorpus_export["_studio"]["name"] == "The Basement"

    def test_multi_instance_anonymous_grouped(self, testcorpus_export):
        # 3 anonymous light sections → _lights with _items
        assert "_lights" in testcorpus_export
        lights = testcorpus_export["_lights"]
        assert "_items" in lights
        assert len(lights["_items"]) == 3

    def test_export_is_deterministic(self, uci_module):
        first = uci_module.config_export("testcorpus")
        second = uci_module.config_export("testcorpus")
        assert first == second


# ---------------------------------------------------------------------------
# Pending changes — inventory must not leave staged mutations
# ---------------------------------------------------------------------------


class TestPendingChanges:
    def test_no_pending_changes_before_inventory(self, uci_module):
        assert uci_module.changes("testcorpus") == []

    def test_no_pending_changes_after_inventory(  # pylint: disable=unused-argument
        self, uci_module, testcorpus_raw, testcorpus_export
    ):
        # Trigger inventory calls, then verify nothing was staged
        uci_module.get("testcorpus")
        uci_module.configs()
        uci_module.config_export("testcorpus")
        assert uci_module.changes("testcorpus") == []


# ---------------------------------------------------------------------------
# Immutability — /etc/config/testcorpus must be byte-for-byte unchanged
# ---------------------------------------------------------------------------


class TestConfigEvidence:
    def test_top_level_schema(self, uci_module):
        result = uci_module.config_evidence("testcorpus")
        assert set(result) >= {
            "evidence_type",
            "source_type",
            "source_device",
            "scope",
            "collected_at",
            "payload",
            "provenance",
        }

    def test_evidence_type(self, uci_module):
        assert uci_module.config_evidence("testcorpus")["evidence_type"] == "configured_state"

    def test_source_type(self, uci_module):
        assert uci_module.config_evidence("testcorpus")["source_type"] == "uci"

    def test_scope(self, uci_module):
        assert uci_module.config_evidence("testcorpus")["scope"] == {"config": "testcorpus"}

    def test_source_device(self, uci_module):
        assert uci_module.config_evidence("testcorpus")["source_device"] == "openwrt-test-target"

    def test_collected_at_is_utc_iso8601(self, uci_module):
        ts = uci_module.config_evidence("testcorpus")["collected_at"]
        dt = datetime.datetime.fromisoformat(ts)
        assert dt.tzinfo is not None

    def test_payload_has_sensitivity_metadata(self, uci_module):
        payload = uci_module.config_evidence("testcorpus")["payload"]
        for name, sec in payload.items():
            if isinstance(sec, dict):
                assert "_sensitivity" in sec, f"section {name!r} missing _sensitivity in evidence payload"

    def test_transport(self, uci_module):
        prov = uci_module.config_evidence("testcorpus")["provenance"]
        assert prov["transport"] == "ubus-jsonrpc"

    def test_collector_name(self, uci_module):
        prov = uci_module.config_evidence("testcorpus")["provenance"]
        assert prov["collector"] == "saltext-uci-ubus"

    def test_collector_version_present(self, uci_module):
        prov = uci_module.config_evidence("testcorpus")["provenance"]
        assert isinstance(prov["collector_version"], str)
        assert prov["collector_version"] != ""

    def test_no_pending_changes_after_evidence(self, uci_module):
        uci_module.config_evidence("testcorpus")
        assert uci_module.changes("testcorpus") == []

    def test_config_file_unchanged(self, uci_module):
        before = read_container_config(CONTAINER_NAME, "testcorpus")
        uci_module.config_evidence("testcorpus")
        after = read_container_config(CONTAINER_NAME, "testcorpus")
        assert before == after


class TestImmutability:
    def test_get_does_not_mutate_config(self, uci_module):
        before = read_container_config(CONTAINER_NAME, "testcorpus")
        uci_module.get("testcorpus")
        after = read_container_config(CONTAINER_NAME, "testcorpus")
        assert before == after

    def test_configs_does_not_mutate_config(self, uci_module):
        before = read_container_config(CONTAINER_NAME, "testcorpus")
        uci_module.configs()
        after = read_container_config(CONTAINER_NAME, "testcorpus")
        assert before == after

    def test_config_export_does_not_mutate_config(self, uci_module):
        before = read_container_config(CONTAINER_NAME, "testcorpus")
        uci_module.config_export("testcorpus")
        after = read_container_config(CONTAINER_NAME, "testcorpus")
        assert before == after

    def test_full_inventory_leaves_file_unchanged(self, uci_module):
        before = read_container_config(CONTAINER_NAME, "testcorpus")
        uci_module.configs()
        uci_module.get("testcorpus")
        uci_module.config_export("testcorpus")
        uci_module.changes("testcorpus")
        after = read_container_config(CONTAINER_NAME, "testcorpus")
        assert before == after
