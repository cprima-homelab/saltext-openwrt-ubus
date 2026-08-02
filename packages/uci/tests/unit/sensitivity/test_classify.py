"""
Unit tests for classify_export().
"""

import pytest

from saltext.uci.sensitivity.classify import classify_export
from saltext.uci.sensitivity.model import Classification, SensitivityProfile, max_taint


@pytest.fixture(scope="module")
def profile():
    return SensitivityProfile.load_builtin()


def _wireless_export_with_secret():
    return {
        "wlan0": {
            "_type": "wifi-iface",
            "device": "radio0",
            "mode": "ap",
            "ssid": "MyNetwork",
            "encryption": "psk2",
            "key": "supersecretpassword",
        }
    }


def _network_export_with_wg():
    return {
        "wg0": {
            "_type": "interface",
            "proto": "wireguard",
            "addresses": ["10.0.0.1/24"],
            "private_key": "gHcb12345678secret==",
        }
    }


def _network_export_clean():
    return {
        "lan": {
            "_type": "interface",
            "proto": "static",
            "ipaddr": "192.168.1.1",
            "netmask": "255.255.255.0",
        }
    }


def _export_with_unknown_option():
    return {
        "custom": {
            "_type": "custom_type",
            "novel_option_xyz": "some value",
        }
    }


def _multi_instance_export():
    return {
        "_rules": {
            "_type": "rule",
            "_match": "name",
            "_items": [
                {"name": "allow-ssh", "src": "wan", "dest_port": "22", "target": "ACCEPT"},
                {"name": "block-telnet", "src": "wan", "dest_port": "23", "target": "DROP"},
            ],
        }
    }


class TestAllOptionsAnnotated:
    def test_all_options_in_fields(self, profile):
        export = _wireless_export_with_secret()
        result = classify_export(export, package="wireless", profile=profile)
        fields = result["wlan0"]["_sensitivity"]["fields"]
        assert set(fields) == {"device", "mode", "ssid", "encryption", "key"}

    def test_no_underscore_keys_in_fields(self, profile):
        export = _wireless_export_with_secret()
        result = classify_export(export, package="wireless", profile=profile)
        fields = result["wlan0"]["_sensitivity"]["fields"]
        for k in fields:
            assert not k.startswith("_"), f"metadata key {k!r} must not appear in fields"


class TestValuesPreserved:
    def test_values_not_modified(self, profile):
        export = _wireless_export_with_secret()
        result = classify_export(export, package="wireless", profile=profile)
        assert result["wlan0"]["key"] == "supersecretpassword"
        assert result["wlan0"]["ssid"] == "MyNetwork"

    def test_list_values_preserved(self, profile):
        export = _network_export_with_wg()
        result = classify_export(export, package="network", profile=profile)
        assert result["wg0"]["addresses"] == ["10.0.0.1/24"]


class TestKnownSecret:
    def test_wifi_key_classified_secret(self, profile):
        export = _wireless_export_with_secret()
        result = classify_export(export, package="wireless", profile=profile)
        assert result["wlan0"]["_sensitivity"]["fields"]["key"] == "secret"

    def test_wireguard_private_key_classified_secret(self, profile):
        export = _network_export_with_wg()
        result = classify_export(export, package="network", profile=profile)
        assert result["wg0"]["_sensitivity"]["fields"]["private_key"] == "secret"


class TestKnownSafe:
    def test_proto_classified_internal(self, profile):
        export = _network_export_clean()
        result = classify_export(export, package="network", profile=profile)
        assert result["lan"]["_sensitivity"]["fields"]["proto"] == "internal"

    def test_ipaddr_classified_internal(self, profile):
        export = _network_export_clean()
        result = classify_export(export, package="network", profile=profile)
        assert result["lan"]["_sensitivity"]["fields"]["ipaddr"] == "internal"


class TestUnknownOption:
    def test_novel_option_is_unknown(self, profile):
        export = _export_with_unknown_option()
        result = classify_export(export, package="custom", profile=profile)
        fields = result["custom"]["_sensitivity"]["fields"]
        assert fields["novel_option_xyz"] == "unknown"


class TestTaint:
    def test_taint_is_secret_when_secret_present(self, profile):
        export = _wireless_export_with_secret()
        result = classify_export(export, package="wireless", profile=profile)
        assert result["wlan0"]["_sensitivity"]["taint"] == "secret"

    def test_taint_is_public_when_all_public_or_internal(self, profile):
        export = _network_export_clean()
        result = classify_export(export, package="network", profile=profile)
        taint = result["lan"]["_sensitivity"]["taint"]
        assert taint in ("public", "internal")

    def test_taint_unknown_beats_internal(self, profile):
        export = _export_with_unknown_option()
        result = classify_export(export, package="custom", profile=profile)
        assert result["custom"]["_sensitivity"]["taint"] == "unknown"

    def test_taint_uses_taint_rank_not_enum_order(self, profile):
        export = {
            "only_unknown": {
                "_type": "custom_type",
                "novel_option_xyz": "value",
            }
        }
        result = classify_export(export, package="custom", profile=profile)
        assert result["only_unknown"]["_sensitivity"]["taint"] == "unknown"


class TestMultiInstance:
    def test_each_item_has_sensitivity(self, profile):
        export = _multi_instance_export()
        result = classify_export(export, package="firewall", profile=profile)
        items = result["_rules"]["_items"]
        assert len(items) == 2
        for item in items:
            assert "_sensitivity" in item

    def test_each_item_fields_annotated(self, profile):
        export = _multi_instance_export()
        result = classify_export(export, package="firewall", profile=profile)
        item = result["_rules"]["_items"][0]
        assert "name" in item["_sensitivity"]["fields"]
        assert "target" in item["_sensitivity"]["fields"]

    def test_container_taint_is_max_of_items(self, profile):
        export = _multi_instance_export()
        result = classify_export(export, package="firewall", profile=profile)
        container_taint = result["_rules"]["_sensitivity"]["taint"]
        item_taints = [item["_sensitivity"]["taint"] for item in result["_rules"]["_items"]]
        expected = max_taint([Classification(t) for t in item_taints]).value
        assert container_taint == expected

    def test_container_metadata_preserved(self, profile):
        export = _multi_instance_export()
        result = classify_export(export, package="firewall", profile=profile)
        assert result["_rules"]["_type"] == "rule"
        assert result["_rules"]["_match"] == "name"
