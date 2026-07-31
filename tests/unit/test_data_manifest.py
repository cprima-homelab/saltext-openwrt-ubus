"""
Tests for the data-handling manifest generator and DataContract enforcement.

The CI enforcement test (test_required_functions_have_contracts) fails if any
function in the required set lacks a @data_contract annotation. When adding a
new data-handling function, add it to _REQUIRED_CONTRACTS and annotate it.
"""

import pytest

from saltext.openwrt_ubus.data_manifest import build_manifest
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

    def test_classify_export_may_contain_secrets(self):
        contracts = collect_contracts()
        assert contracts["classify_export"]["may_contain_secrets"] is True

    def test_projection_functions_may_not_contain_secrets(self):
        contracts = collect_contracts()
        for fn in ("evidence_projection", "grains_projection", "diff_projection"):
            assert contracts[fn]["may_contain_secrets"] is False, fn

    def test_evidence_functions_may_not_contain_secrets(self):
        contracts = collect_contracts()
        for fn in ("config_evidence", "runtime_evidence", "config_diff"):
            assert contracts[fn]["may_contain_secrets"] is False, fn


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
