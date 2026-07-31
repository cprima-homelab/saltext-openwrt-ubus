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


class TestCheckMode:
    @pytest.fixture(scope="class")
    def check_results(self):
        manifest = build_manifest()
        return check_manifest(manifest)

    def _find(self, results, fn_name):
        return next((r for r in results if r[1] == fn_name), None)

    def test_classify_export_passes(self, check_results):
        # classify_export outputs to uci.classified (internal boundary) → PASS
        r = self._find(check_results, "classify_export")
        assert r is not None
        assert r[0] == "PASS"

    def test_evidence_projection_passes(self, check_results):
        # evidence_projection: secret-capable input → persistent-store, emits_secrets=false
        r = self._find(check_results, "evidence_projection")
        assert r is not None
        assert r[0] == "PASS"

    def test_grains_projection_passes(self, check_results):
        # grains_projection: secret-capable input → salt-master boundary, emits_secrets=false
        r = self._find(check_results, "grains_projection")
        assert r is not None
        assert r[0] == "PASS"

    def test_diff_projection_passes(self, check_results):
        # diff_projection: secret-capable input → persistent-store, emits_secrets=false
        r = self._find(check_results, "diff_projection")
        assert r is not None
        assert r[0] == "PASS"

    def test_runtime_evidence_warns(self, check_results):
        # runtime_evidence: handles_secrets=None → unknown path → WARN
        r = self._find(check_results, "runtime_evidence")
        assert r is not None
        assert r[0] == "WARN"
        assert "null" in r[2].lower() or "unknown" in r[2].lower()

    def test_config_evidence_passes_with_guards(self, check_results):
        # config_evidence: secret-capable input → persistent-store, guarded by projections
        r = self._find(check_results, "config_evidence")
        assert r is not None
        assert r[0] == "PASS"
        assert "guarded" in r[2].lower() or "guard" in r[2].lower()

    def test_config_diff_passes_with_guards(self, check_results):
        # config_diff: secret-capable input → persistent-store, guarded by diff_projection
        r = self._find(check_results, "config_diff")
        assert r is not None
        assert r[0] == "PASS"
        assert "guarded" in r[2].lower() or "guard" in r[2].lower()

    def test_no_fail_results(self, check_results):
        fails = [r for r in check_results if r[0] == "FAIL"]
        assert not fails, f"Unexpected FAIL: {fails}"

    def test_results_cover_all_required(self, check_results):
        found = {r[1] for r in check_results}
        assert _REQUIRED_CONTRACTS <= found

    def test_fail_on_secret_leak_to_external_boundary(self):
        """Synthesize a manifest with a function that leaks secrets to an external boundary."""
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
        assert results[0][0] == "FAIL"
        assert "external boundary" in results[0][2]
