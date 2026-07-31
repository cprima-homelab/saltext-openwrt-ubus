"""
Tests for the data-handling manifest generator and DataContract enforcement.

The CI enforcement test (test_required_functions_have_contracts) fails if any
function in the required set lacks a @data_contract annotation. When adding a
new data-handling function, add it to _REQUIRED_CONTRACTS and annotate it.
"""

import pytest

from saltext.openwrt_ubus.data_manifest import build_manifest
from saltext.openwrt_ubus.data_manifest import check_manifest
from saltext.openwrt_ubus.data_manifest import collect_contracts
from saltext.openwrt_ubus.data_manifest import derive_crossings

# Functions that handle classified data and must be annotated.
# CI fails if any of these lacks a @data_contract.
_REQUIRED_CONTRACTS = frozenset(
    {
        "classify_export",
        "evidence_projection",
        "grains_projection",
        "diff_projection",
        "config_evidence",
        "runtime_evidence",
        "config_diff",
    }
)


class TestContractEnforcement:
    def test_required_functions_have_contracts(self):
        contracts = collect_contracts()
        missing = _REQUIRED_CONTRACTS - set(contracts.keys())
        assert not missing, f"Missing @data_contract on: {sorted(missing)}"

    def test_classify_export_handles_secrets(self):
        contracts = collect_contracts()
        assert contracts["classify_export"]["handles_secrets"] is True

    def test_classify_export_emits_secrets(self):
        # classify_export output (uci.classified) still contains secret values
        contracts = collect_contracts()
        assert contracts["classify_export"]["emits_secrets"] is True

    def test_projection_functions_do_not_emit_secrets(self):
        contracts = collect_contracts()
        for fn in ("evidence_projection", "grains_projection", "diff_projection"):
            assert contracts[fn]["emits_secrets"] is False, fn

    def test_config_evidence_does_not_emit_secrets(self):
        contracts = collect_contracts()
        assert contracts["config_evidence"]["emits_secrets"] is False

    def test_config_diff_does_not_emit_secrets(self):
        contracts = collect_contracts()
        assert contracts["config_diff"]["emits_secrets"] is False

    def test_runtime_evidence_handles_secrets_unknown(self):
        # runtime_evidence has no classification layer; both fields must be None
        contracts = collect_contracts()
        c = contracts["runtime_evidence"]
        assert c["handles_secrets"] is None
        assert c["emits_secrets"] is None

    def test_config_evidence_guards_projections(self):
        contracts = collect_contracts()
        guards = contracts["config_evidence"]["guards"]
        assert "classify_export" in guards
        assert "evidence_projection" in guards

    def test_config_diff_guards_diff_projection(self):
        contracts = collect_contracts()
        assert "diff_projection" in contracts["config_diff"]["guards"]


class TestContractSchema:
    def test_classify_export_io(self):
        contracts = collect_contracts()
        c = contracts["classify_export"]
        assert "uci.raw" in c["inputs"]
        assert "uci.classified" in c["outputs"]

    def test_evidence_projection_io(self):
        contracts = collect_contracts()
        c = contracts["evidence_projection"]
        assert "uci.classified" in c["inputs"]
        assert "evidence.configured_state" in c["outputs"]
        assert "evidence" in c["surfaces"]

    def test_grains_projection_io(self):
        contracts = collect_contracts()
        c = contracts["grains_projection"]
        assert "uci.classified" in c["inputs"]
        assert "grains.configured_state" in c["outputs"]
        assert "grains" in c["surfaces"]

    def test_config_evidence_module(self):
        contracts = collect_contracts()
        assert contracts["config_evidence"]["module"] == "saltext.openwrt_ubus.utils.ubus_ops"

    def test_runtime_evidence_inputs(self):
        contracts = collect_contracts()
        assert "ubus.runtime" in contracts["runtime_evidence"]["inputs"]


class TestManifest:
    @pytest.fixture(scope="class")
    def manifest(self):
        return build_manifest()

    def test_manifest_has_data_types(self, manifest):
        assert "data_types" in manifest
        dt = manifest["data_types"]
        assert "uci.raw" in dt
        assert "uci.classified" in dt
        assert "grains.configured_state" in dt

    def test_data_types_uci_raw_secret_capable(self, manifest):
        assert manifest["data_types"]["uci.raw"]["secret_capable"] is True

    def test_data_types_grains_not_secret_capable(self, manifest):
        assert manifest["data_types"]["grains.configured_state"]["secret_capable"] is False

    def test_data_types_observed_state_unknown(self, manifest):
        assert manifest["data_types"]["evidence.observed_state"]["secret_capable"] is None

    def test_data_types_have_boundary(self, manifest):
        for name, dt in manifest["data_types"].items():
            assert "boundary" in dt, f"{name} missing boundary field"

    def test_internal_data_types_stay_internal(self, manifest):
        for name in ("uci.raw", "uci.classified", "uci.diff", "pillar.sections", "ubus.runtime"):
            assert manifest["data_types"][name]["boundary"] == "internal", name

    def test_grains_boundary_is_salt_master(self, manifest):
        assert manifest["data_types"]["grains.configured_state"]["boundary"] == "salt-master"

    def test_evidence_boundary_is_persistent_store(self, manifest):
        for name in (
            "evidence.configured_state",
            "evidence.config_diff",
            "evidence.observed_state",
        ):
            assert manifest["data_types"][name]["boundary"] == "persistent-store", name

    def test_pillar_sections_has_provenance_boundary(self, manifest):
        dt = manifest["data_types"]["pillar.sections"]
        assert dt["boundary"] == "internal"
        assert dt.get("provenance_boundary") == "salt-master"

    def test_manifest_has_crossings(self, manifest):
        assert "crossings" in manifest
        assert len(manifest["crossings"]) > 0

    def test_manifest_has_functions_and_profile(self, manifest):
        assert "functions" in manifest
        assert "sensitivity_profile" in manifest

    def test_profile_name_and_version(self, manifest):
        profile = manifest["sensitivity_profile"]
        assert profile["name"] == "saltext-openwrt-ubus/default"
        assert profile["version"] == "2"

    def test_profile_has_policy_table(self, manifest):
        policies = manifest["sensitivity_profile"]["policies"]
        assert set(policies.keys()) >= {"secret", "internal", "unknown", "sensitive", "public"}
        assert policies["secret"]["grains"] == "deny"
        assert policies["internal"]["evidence"] == "allow"

    def test_profile_has_classified_fields(self, manifest):
        fields = manifest["sensitivity_profile"]["classified_fields"]
        assert len(fields) > 0
        secret_options = [
            opt
            for entry in fields
            if entry["classification"] == "secret"
            for opt in entry.get("options", [])
        ]
        assert "private_key" in secret_options

    def test_all_required_functions_in_manifest(self, manifest):
        missing = _REQUIRED_CONTRACTS - set(manifest["functions"].keys())
        assert not missing


class TestCrossings:
    @pytest.fixture(scope="class")
    def manifest(self):
        return build_manifest()

    @pytest.fixture(scope="class")
    def crossings(self, manifest):
        return manifest["crossings"]

    def _via(self, crossings, fn_name):
        return [c for c in crossings if c["via"] == fn_name]

    def test_crossings_have_required_fields(self, crossings):
        for c in crossings:
            assert "from" in c
            assert "to" in c
            assert "via" in c
            assert "guards" in c
            assert "result" in c

    def test_crossing_results_are_valid_values(self, crossings):
        valid = {"safe", "unknown", "fail"}
        for c in crossings:
            assert c["result"] in valid, f"{c['via']}: unexpected result {c['result']!r}"

    def test_grains_projection_crossing(self, crossings):
        cs = self._via(crossings, "grains_projection")
        assert len(cs) == 1
        c = cs[0]
        assert c["from"] == "internal"
        assert c["to"] == "salt-master"
        assert c["result"] == "safe"
        assert "grains_projection" in c["guards"]

    def test_evidence_projection_crossing(self, crossings):
        cs = self._via(crossings, "evidence_projection")
        assert len(cs) == 1
        c = cs[0]
        assert c["from"] == "internal"
        assert c["to"] == "persistent-store"
        assert c["result"] == "safe"

    def test_diff_projection_crossing(self, crossings):
        cs = self._via(crossings, "diff_projection")
        assert len(cs) == 1
        c = cs[0]
        assert c["to"] == "persistent-store"
        assert c["result"] == "safe"

    def test_config_evidence_crossing(self, crossings):
        cs = self._via(crossings, "config_evidence")
        assert len(cs) == 1
        c = cs[0]
        assert c["to"] == "persistent-store"
        assert c["result"] == "safe"
        assert "classify_export" in c["guards"]
        assert "evidence_projection" in c["guards"]

    def test_config_diff_crossing(self, crossings):
        cs = self._via(crossings, "config_diff")
        assert len(cs) == 1
        c = cs[0]
        assert c["to"] == "persistent-store"
        assert c["result"] == "safe"
        assert "diff_projection" in c["guards"]

    def test_runtime_evidence_crossing_is_unknown(self, crossings):
        cs = self._via(crossings, "runtime_evidence")
        assert len(cs) == 1
        c = cs[0]
        assert c["to"] == "persistent-store"
        assert c["result"] == "unknown"
        assert c["guards"] == []

    def test_no_crossings_stay_internal(self, crossings):
        # Every crossing must involve a boundary change; no internal→internal entries
        for c in crossings:
            assert c["from"] != c["to"], f"{c['via']}: from==to in crossings list"

    def test_classify_export_not_in_crossings(self, crossings):
        # classify_export outputs to uci.classified (internal → internal); no crossing
        cs = self._via(crossings, "classify_export")
        assert cs == [], "classify_export should produce no boundary crossing"

    def test_no_fail_crossings(self, crossings):
        fails = [c for c in crossings if c["result"] == "fail"]
        assert not fails, f"Unexpected fail crossings: {fails}"

    def test_synthetic_fail_crossing(self):
        """derive_crossings emits result=fail when emits_secrets=true reaches external boundary."""
        manifest = {
            "data_types": {
                "uci.raw": {"secret_capable": True, "boundary": "internal"},
                "evidence.leak": {"secret_capable": True, "boundary": "persistent-store"},
            },
            "functions": {
                "leaky_fn": {
                    "inputs": ["uci.raw"],
                    "outputs": ["evidence.leak"],
                    "handles_secrets": True,
                    "emits_secrets": True,
                    "guards": [],
                }
            },
        }
        crossings = derive_crossings(manifest)
        assert len(crossings) == 1
        assert crossings[0]["result"] == "fail"
        assert crossings[0]["guards"] == []

    def test_dedup_multiple_inputs_same_boundary(self):
        """A function with two inputs at the same boundary produces one crossing."""
        manifest = {
            "data_types": {
                "uci.raw": {"boundary": "internal"},
                "uci.diff": {"boundary": "internal"},
                "evidence.out": {"boundary": "persistent-store"},
            },
            "functions": {
                "multi_input": {
                    "inputs": ["uci.raw", "uci.diff"],
                    "outputs": ["evidence.out"],
                    "handles_secrets": True,
                    "emits_secrets": False,
                    "guards": ["some_guard"],
                }
            },
        }
        crossings = derive_crossings(manifest)
        assert len(crossings) == 1
        assert crossings[0]["via"] == "multi_input"


class TestCheckMode:
    @pytest.fixture(scope="class")
    def check_results(self):
        manifest = build_manifest()
        return check_manifest(manifest)

    def _find(self, results, fn_name):
        return next((r for r in results if r[1] == fn_name), None)

    def test_evidence_projection_passes(self, check_results):
        r = self._find(check_results, "evidence_projection")
        assert r is not None
        assert r[0] == "PASS"

    def test_grains_projection_passes(self, check_results):
        r = self._find(check_results, "grains_projection")
        assert r is not None
        assert r[0] == "PASS"

    def test_diff_projection_passes(self, check_results):
        r = self._find(check_results, "diff_projection")
        assert r is not None
        assert r[0] == "PASS"

    def test_runtime_evidence_warns(self, check_results):
        r = self._find(check_results, "runtime_evidence")
        assert r is not None
        assert r[0] == "WARN"
        assert "uncharted" in r[2] or "null" in r[2].lower() or "unknown" in r[2].lower()

    def test_config_evidence_passes_with_guards(self, check_results):
        r = self._find(check_results, "config_evidence")
        assert r is not None
        assert r[0] == "PASS"
        assert "guarded" in r[2].lower()

    def test_config_diff_passes_with_guards(self, check_results):
        r = self._find(check_results, "config_diff")
        assert r is not None
        assert r[0] == "PASS"
        assert "guarded" in r[2].lower()

    def test_no_fail_results(self, check_results):
        fails = [r for r in check_results if r[0] == "FAIL"]
        assert not fails, f"Unexpected FAIL: {fails}"

    def test_fail_on_secret_leak_to_external_boundary(self):
        """check_manifest emits FAIL when a crossing has result=fail."""
        manifest = {
            "data_types": {
                "uci.raw": {"secret_capable": True, "boundary": "internal"},
                "evidence.leak": {"secret_capable": True, "boundary": "persistent-store"},
            },
            "functions": {
                "leaky_fn": {
                    "inputs": ["uci.raw"],
                    "outputs": ["evidence.leak"],
                    "handles_secrets": True,
                    "emits_secrets": True,
                    "guards": [],
                }
            },
        }
        results = check_manifest(manifest)
        assert any(r[0] == "FAIL" for r in results)
        fail = next(r for r in results if r[0] == "FAIL")
        assert "external boundary" in fail[2]
