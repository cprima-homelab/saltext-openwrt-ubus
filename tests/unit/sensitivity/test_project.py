"""
Unit tests for evidence_projection(), grains_projection(), diff_projection(),
and assert_grains_safe().
"""

import pytest

from saltext.uci_ubus.sensitivity.classify import classify_export
from saltext.uci_ubus.sensitivity.model import SensitivityProfile
from saltext.uci_ubus.sensitivity.project import (
    assert_grains_safe,
    diff_projection,
    evidence_projection,
    grains_projection,
)


@pytest.fixture(scope="module")
def profile():
    return SensitivityProfile.load_builtin()


def _classified_wireless(profile):
    export = {
        "wlan0": {
            "_type": "wifi-iface",
            "device": "radio0",
            "ssid": "MyNetwork",
            "encryption": "psk2",
            "key": "supersecret",
        }
    }
    return classify_export(export, package="wireless", profile=profile)


def _classified_network(profile):
    export = {
        "wg0": {
            "_type": "interface",
            "proto": "wireguard",
            "ipaddr": "10.0.0.1",
            "private_key": "gHcbXXXXXXXXXXXX==",
        },
        "lan": {
            "_type": "interface",
            "proto": "static",
            "ipaddr": "192.168.1.1",
        },
    }
    return classify_export(export, package="network", profile=profile)


def _classified_with_unknown(profile):
    export = {
        "custom": {
            "_type": "custom_type",
            "known_internal": "proto",
            "novel_option": "some_value",
        }
    }
    return classify_export(export, package="custom", profile=profile)


def _classified_multi(profile):
    export = {
        "_rules": {
            "_type": "rule",
            "_match": "name",
            "_items": [
                {"name": "allow-ssh", "src": "wan", "target": "ACCEPT"},
            ],
        }
    }
    return classify_export(export, package="firewall", profile=profile)


class TestEvidenceProjection:
    def test_secret_value_is_null(self, profile):
        classified = _classified_wireless(profile)
        result = evidence_projection(classified)
        assert result["wlan0"]["key"] is None

    def test_secret_key_present(self, profile):
        classified = _classified_wireless(profile)
        result = evidence_projection(classified)
        assert "key" in result["wlan0"]

    def test_internal_value_kept(self, profile):
        classified = _classified_wireless(profile)
        result = evidence_projection(classified)
        assert result["wlan0"]["ssid"] == "MyNetwork"

    def test_unknown_value_is_null(self, profile):
        classified = _classified_with_unknown(profile)
        result = evidence_projection(classified)
        assert result["custom"]["novel_option"] is None

    def test_unknown_key_present(self, profile):
        classified = _classified_with_unknown(profile)
        result = evidence_projection(classified)
        assert "novel_option" in result["custom"]

    def test_taint_in_output(self, profile):
        classified = _classified_wireless(profile)
        result = evidence_projection(classified)
        assert result["wlan0"]["_sensitivity"]["taint"] == "secret"

    def test_sensitivity_fields_compacted(self, profile):
        classified = _classified_wireless(profile)
        result = evidence_projection(classified)
        fields = result["wlan0"]["_sensitivity"]["fields"]
        for cl_str in fields.values():
            assert cl_str not in (
                "public",
                "internal",
            ), f"fields should be compacted; {cl_str!r} should not appear"
        assert "key" in fields
        assert fields["key"] == "secret"

    def test_type_metadata_preserved(self, profile):
        classified = _classified_wireless(profile)
        result = evidence_projection(classified)
        assert result["wlan0"]["_type"] == "wifi-iface"

    def test_multi_instance_items_projected(self, profile):
        classified = _classified_multi(profile)
        result = evidence_projection(classified)
        items = result["_rules"]["_items"]
        assert len(items) == 1
        assert "_sensitivity" in items[0]


class TestGrainsProjection:
    def test_secret_key_absent(self, profile):
        classified = _classified_wireless(profile)
        result = grains_projection(classified)
        assert "key" not in result["wlan0"]

    def test_unknown_key_absent(self, profile):
        classified = _classified_with_unknown(profile)
        result = grains_projection(classified)
        assert "novel_option" not in result["custom"]

    def test_internal_value_present(self, profile):
        classified = _classified_wireless(profile)
        result = grains_projection(classified)
        assert result["wlan0"]["ssid"] == "MyNetwork"
        assert result["wlan0"]["device"] == "radio0"

    def test_sensitivity_metadata_retained(self, profile):
        classified = _classified_wireless(profile)
        result = grains_projection(classified)
        assert "_sensitivity" in result["wlan0"]
        assert result["wlan0"]["_sensitivity"]["taint"] == "secret"

    def test_sensitive_value_is_null_key_present(self, profile):
        export = {
            "router": {
                "_type": "system",
                "hostname": "mywifi",
                "password": "adminpass",
            }
        }
        classified = classify_export(export, package="system", profile=profile)
        result = grains_projection(classified)
        assert "password" in result["router"]
        assert result["router"]["password"] is None

    def test_assert_grains_safe_passes_on_clean_output(self, profile):
        classified = _classified_wireless(profile)
        grains = grains_projection(classified)
        assert_grains_safe(grains)

    def test_assert_grains_safe_fails_on_secret_value(self, profile):
        classified = _classified_wireless(profile)
        grains = grains_projection(classified)
        # Artificially inject a secret value to test the guard
        grains["wlan0"]["key"] = "injected_secret"
        grains["wlan0"]["_sensitivity"]["fields"]["key"] = "secret"
        with pytest.raises(AssertionError, match="Grains invariant violated"):
            assert_grains_safe(grains)

    def test_assert_grains_safe_fails_on_sensitive_value(self, profile):
        export = {
            "router": {
                "_type": "system",
                "hostname": "mywifi",
                "password": "adminpass",
            }
        }
        classified = classify_export(export, package="system", profile=profile)
        grains = grains_projection(classified)
        # password is sensitive → grains_projection sets it to None; inject a non-null value
        grains["router"]["password"] = "leaked_password"
        with pytest.raises(AssertionError, match="Grains invariant violated"):
            assert_grains_safe(grains)

    def test_multi_instance_items_projected(self, profile):
        classified = _classified_multi(profile)
        result = grains_projection(classified)
        items = result["_rules"]["_items"]
        assert len(items) == 1


class TestDiffProjection:
    def test_secret_changed_option_becomes_changed_true(self, profile):
        diff = {
            "changed": {
                "wg0": {
                    "private_key": {"old": "oldkey==", "new": "newkey=="},
                    "proto": {"old": "static", "new": "wireguard"},
                }
            },
            "new": {},
            "removed": {},
            "reordered": {},
            "summary": {
                "changed": 1,
                "new": 0,
                "removed": 0,
                "reordered": 0,
                "total": 1,
                "in_sync": False,
            },
        }
        section_types = {"wg0": "interface"}
        result = diff_projection(diff, package="network", profile=profile, section_types=section_types)
        assert result["changed"]["wg0"]["private_key"] == {"changed": True}
        assert result["changed"]["wg0"]["proto"] == {"old": "static", "new": "wireguard"}

    def test_sensitive_changed_option_becomes_changed_true(self, profile):
        diff = {
            "changed": {"router": {"password": {"old": "old123", "new": "new456"}}},
            "new": {},
            "removed": {},
            "reordered": {},
            "summary": {
                "changed": 1,
                "new": 0,
                "removed": 0,
                "reordered": 0,
                "total": 1,
                "in_sync": False,
            },
        }
        section_types = {"router": "system"}
        result = diff_projection(diff, package="system", profile=profile, section_types=section_types)
        assert result["changed"]["router"]["password"] == {"changed": True}

    def test_unknown_changed_option_becomes_changed_true(self, profile):
        diff = {
            "changed": {"mysec": {"novel_opt": {"old": "a", "new": "b"}}},
            "new": {},
            "removed": {},
            "reordered": {},
            "summary": {
                "changed": 1,
                "new": 0,
                "removed": 0,
                "reordered": 0,
                "total": 1,
                "in_sync": False,
            },
        }
        result = diff_projection(diff, package="custom", profile=profile, section_types={"mysec": "custom_type"})
        assert result["changed"]["mysec"]["novel_opt"] == {"changed": True}

    def test_internal_changed_option_preserves_old_new(self, profile):
        diff = {
            "changed": {"lan": {"ipaddr": {"old": "192.168.1.1", "new": "10.0.0.1"}}},
            "new": {},
            "removed": {},
            "reordered": {},
            "summary": {
                "changed": 1,
                "new": 0,
                "removed": 0,
                "reordered": 0,
                "total": 1,
                "in_sync": False,
            },
        }
        section_types = {"lan": "interface"}
        result = diff_projection(diff, package="network", profile=profile, section_types=section_types)
        assert result["changed"]["lan"]["ipaddr"] == {"old": "192.168.1.1", "new": "10.0.0.1"}

    def test_secret_new_option_never_exposes_value(self, profile):
        diff = {
            "changed": {},
            "new": {
                "wg0": {
                    "private_key": {"old": None, "new": "brandnewsecret=="},
                    "proto": {"old": None, "new": "wireguard"},
                }
            },
            "removed": {},
            "reordered": {},
            "summary": {
                "changed": 0,
                "new": 1,
                "removed": 0,
                "reordered": 0,
                "total": 1,
                "in_sync": False,
            },
        }
        section_types = {"wg0": "interface"}
        result = diff_projection(diff, package="network", profile=profile, section_types=section_types)
        new_wg0 = result["new"]["wg0"]
        assert new_wg0["private_key"] == {"changed": True}
        assert "brandnewsecret" not in str(new_wg0)

    def test_unknown_new_option_never_exposes_value(self, profile):
        diff = {
            "changed": {},
            "new": {"custom": {"novel_option": {"old": None, "new": "secret_value"}}},
            "removed": {},
            "reordered": {},
            "summary": {
                "changed": 0,
                "new": 1,
                "removed": 0,
                "reordered": 0,
                "total": 1,
                "in_sync": False,
            },
        }
        result = diff_projection(diff, package="custom", profile=profile, section_types={"custom": "custom_type"})
        assert result["new"]["custom"]["novel_option"] == {"changed": True}
        assert "secret_value" not in str(result["new"])

    def test_removed_section_with_secret_value_not_exposed(self, profile):
        diff = {
            "changed": {},
            "new": {},
            "removed": {
                "wlan0": {
                    "_type": "wifi-iface",
                    "_anonymous": True,
                    "ssid": "OldNetwork",
                    "key": "oldpassword123",
                }
            },
            "reordered": {},
            "summary": {
                "changed": 0,
                "new": 0,
                "removed": 1,
                "reordered": 0,
                "total": 1,
                "in_sync": False,
            },
        }
        result = diff_projection(diff, package="wireless", profile=profile)
        removed_section = result["removed"]["wlan0"]
        assert removed_section["key"] is None
        assert "oldpassword123" not in str(result["removed"])
        assert removed_section["ssid"] == "OldNetwork"

    def test_removed_anonymous_multi_item_secret_not_exposed(self, profile):
        diff = {
            "changed": {},
            "new": {},
            "removed": {
                "cfg01234": {
                    "_type": "wifi-iface",
                    "_anonymous": True,
                    "ssid": "GuestNet",
                    "encryption": "psk2",
                    "key": "guestsecretpsk",
                }
            },
            "reordered": {},
            "summary": {
                "changed": 0,
                "new": 0,
                "removed": 1,
                "reordered": 0,
                "total": 1,
                "in_sync": False,
            },
        }
        result = diff_projection(diff, package="wireless", profile=profile)
        assert result["removed"]["cfg01234"]["key"] is None
        assert "guestsecretpsk" not in str(result["removed"])

    def test_summary_unchanged(self, profile):
        diff = {
            "changed": {},
            "new": {},
            "removed": {},
            "reordered": {},
            "summary": {
                "changed": 0,
                "new": 0,
                "removed": 0,
                "reordered": 0,
                "total": 0,
                "in_sync": True,
            },
        }
        result = diff_projection(diff, package="network", profile=profile)
        assert result["summary"]["in_sync"] is True
        assert result["summary"]["total"] == 0
