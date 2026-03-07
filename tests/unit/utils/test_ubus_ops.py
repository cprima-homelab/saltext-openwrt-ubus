"""
Tests for saltext.openwrt_ubus.utils.ubus_ops
"""

import pytest

from saltext.openwrt_ubus.utils import ubus_ops


class TestTransformSection:
    def test_dot_to_underscore(self):
        data = {".type": "interface", ".name": "lan", ".anonymous": False, "proto": "static"}
        result = ubus_ops.transform_section(data)
        assert result == {
            "_type": "interface",
            "_name": "lan",
            "_anonymous": False,
            "proto": "static",
        }
        assert ".type" not in result


# --- Pillar generation tests ---

NETWORK_STATE = {
    "lan": {
        "_type": "interface",
        "_name": "lan",
        "_anonymous": False,
        "_index": 1,
        "proto": "static",
        "ipaddr": "10.35.24.1",
    },
    "wan": {
        "_type": "interface",
        "_name": "wan",
        "_anonymous": False,
        "_index": 2,
        "proto": "dhcp",
        "password": "s3cret",
    },
}

SYSTEM_STATE = {
    "cfg01e48a": {
        "_type": "system",
        "_name": "cfg01e48a",
        "_anonymous": True,
        "_index": 0,
        "hostname": "austru",
        "zonename": "Europe/Berlin",
    },
}

DHCP_STATE = {
    "cfg0a": {
        "_type": "host",
        "_name": "cfg0a",
        "_anonymous": True,
        "_index": 0,
        "name": "cam1",
        "mac": "AA:BB:CC:DD:00:01",
        "ip": "10.0.0.10",
    },
    "cfg0b": {
        "_type": "host",
        "_name": "cfg0b",
        "_anonymous": True,
        "_index": 1,
        "name": "cam2",
        "mac": "AA:BB:CC:DD:00:02",
        "ip": "10.0.0.11",
    },
    "lan": {
        "_type": "dhcp",
        "_name": "lan",
        "_anonymous": False,
        "_index": 2,
        "interface": "lan",
    },
}

FORWARDING_STATE = {
    "cfg01": {
        "_type": "forwarding",
        "_name": "cfg01",
        "_anonymous": True,
        "_index": 0,
        "src": "lan",
        "dest": "wan",
    },
    "cfg02": {
        "_type": "forwarding",
        "_name": "cfg02",
        "_anonymous": True,
        "_index": 1,
        "src": "guest",
        "dest": "wan",
    },
    "cfg03": {
        "_type": "forwarding",
        "_name": "cfg03",
        "_anonymous": True,
        "_index": 2,
        "src": "lan",
        "dest": "vpn",
    },
}

NO_UNIQUE_KEY_STATE = {
    "cfg01": {
        "_type": "rule",
        "_name": "cfg01",
        "_anonymous": True,
        "_index": 0,
        "src": "wan",
        "target": "ACCEPT",
    },
    "cfg02": {
        "_type": "rule",
        "_name": "cfg02",
        "_anonymous": True,
        "_index": 1,
        "src": "wan",
        "target": "ACCEPT",
    },
}


class TestStripMetadata:
    def test_removes_name_anonymous_index(self):
        data = {
            "_type": "interface",
            "_name": "lan",
            "_anonymous": False,
            "_index": 1,
            "proto": "static",
        }
        result = ubus_ops._strip_metadata(data)
        assert result == {"_type": "interface", "proto": "static"}

    def test_keeps_type(self):
        data = {"_type": "system", "_name": "cfg01", "_anonymous": True, "_index": 0}
        result = ubus_ops._strip_metadata(data)
        assert "_type" in result
        assert result["_type"] == "system"

    def test_keeps_options(self):
        data = {"_type": "host", "_name": "cfg0a", "_anonymous": True, "_index": 0, "ip": "1.2.3.4"}
        result = ubus_ops._strip_metadata(data)
        assert result == {"_type": "host", "ip": "1.2.3.4"}


class TestIsSensitive:
    @pytest.mark.parametrize("name", ["password", "key", "psk", "secret", "token", "passphrase"])
    def test_exact_matches(self, name):
        assert ubus_ops._is_sensitive(name) is True

    @pytest.mark.parametrize("name", ["wpa_psk", "auth_key", "private_key", "pptp_password"])
    def test_suffix_matches(self, name):
        assert ubus_ops._is_sensitive(name) is True

    @pytest.mark.parametrize("name", ["proto", "ipaddr", "device", "name", "hostname", "interface"])
    def test_non_sensitive(self, name):
        assert ubus_ops._is_sensitive(name) is False

    def test_case_insensitive(self):
        assert ubus_ops._is_sensitive("Password") is True
        assert ubus_ops._is_sensitive("KEY") is True


class TestDetectMatchKey:
    def test_prefers_name(self):
        sections = [
            {"_type": "host", "name": "a", "ip": "1.1.1.1"},
            {"_type": "host", "name": "b", "ip": "2.2.2.2"},
        ]
        assert ubus_ops._detect_match_key(sections) == "name"

    def test_falls_back_to_first_alpha(self):
        sections = [
            {"_type": "host", "ip": "1.1.1.1", "mac": "AA"},
            {"_type": "host", "ip": "2.2.2.2", "mac": "BB"},
        ]
        assert ubus_ops._detect_match_key(sections) == "ip"

    def test_skips_list_values(self):
        sections = [
            {"_type": "x", "tags": ["a"], "id": "1"},
            {"_type": "x", "tags": ["b"], "id": "2"},
        ]
        assert ubus_ops._detect_match_key(sections) == "id"

    def test_composite_key(self):
        sections = [
            {"_type": "forwarding", "src": "lan", "dest": "wan"},
            {"_type": "forwarding", "src": "guest", "dest": "wan"},
            {"_type": "forwarding", "src": "lan", "dest": "vpn"},
        ]
        result = ubus_ops._detect_match_key(sections)
        assert isinstance(result, list)
        assert set(result) == {"src", "dest"}

    def test_returns_none_when_no_key(self):
        sections = [
            {"_type": "rule", "src": "wan", "target": "ACCEPT"},
            {"_type": "rule", "src": "wan", "target": "ACCEPT"},
        ]
        assert ubus_ops._detect_match_key(sections) is None

    def test_single_section_returns_none(self):
        sections = [{"_type": "host", "name": "a"}]
        assert ubus_ops._detect_match_key(sections) is None


class TestDump:
    @staticmethod
    def _mock_call(state):
        def call(_obj, method, _params=None):
            if method == "get":
                return {
                    "values": {
                        n: {f".{k[1:]}" if k.startswith("_") else k: v for k, v in s.items()}
                        for n, s in state.items()
                    }
                }
            return {}

        return call

    def test_named_sections(self):
        result = ubus_ops.dump(self._mock_call(NETWORK_STATE), "network", redact=False)
        assert "lan" in result
        assert "wan" in result
        assert result["lan"] == {"_type": "interface", "proto": "static", "ipaddr": "10.35.24.1"}
        assert "_name" not in result["lan"]
        assert "_anonymous" not in result["lan"]
        assert "_index" not in result["lan"]

    def test_singleton_anonymous(self):
        result = ubus_ops.dump(self._mock_call(SYSTEM_STATE), "system", redact=False)
        assert "_system" in result
        assert result["_system"]["_type"] == "system"
        assert result["_system"]["hostname"] == "austru"

    def test_multi_instance_anonymous(self):
        result = ubus_ops.dump(self._mock_call(DHCP_STATE), "dhcp", redact=False)
        assert "_hosts" in result
        assert result["_hosts"]["_type"] == "host"
        assert result["_hosts"]["_match"] == "name"
        assert len(result["_hosts"]["_items"]) == 2
        assert result["_hosts"]["_items"][0]["name"] == "cam1"
        assert result["_hosts"]["_items"][1]["name"] == "cam2"

    def test_mixed_named_and_anonymous(self):
        result = ubus_ops.dump(self._mock_call(DHCP_STATE), "dhcp", redact=False)
        assert "lan" in result
        assert "_hosts" in result

    def test_redact_sensitive_options(self):
        result = ubus_ops.dump(self._mock_call(NETWORK_STATE), "network", redact=True)
        assert "pillar.get" in result["wan"]["password"]
        assert "s3cret" not in result["wan"]["password"]

    def test_redact_false_preserves_values(self):
        result = ubus_ops.dump(self._mock_call(NETWORK_STATE), "network", redact=False)
        assert result["wan"]["password"] == "s3cret"

    def test_empty_config(self):
        result = ubus_ops.dump(self._mock_call({}), "empty", redact=False)
        assert not result

    def test_no_viable_match_key_emits_comment(self):
        result = ubus_ops.dump(self._mock_call(NO_UNIQUE_KEY_STATE), "firewall", redact=False)
        assert "_rules" in result
        assert "_comment" in result["_rules"]
        assert "_match" not in result["_rules"]

    def test_composite_match_key(self):
        result = ubus_ops.dump(self._mock_call(FORWARDING_STATE), "firewall", redact=False)
        assert "_forwardings" in result
        match = result["_forwardings"]["_match"]
        assert isinstance(match, list)
        assert set(match) == {"src", "dest"}

    def test_items_exclude_type(self):
        result = ubus_ops.dump(self._mock_call(DHCP_STATE), "dhcp", redact=False)
        for item in result["_hosts"]["_items"]:
            assert "_type" not in item


class TestDumpAll:
    def test_iterates_all_configs(self):
        configs = ["network", "system"]
        states = {
            "network": NETWORK_STATE,
            "system": SYSTEM_STATE,
        }

        def call(_obj, method, params=None):
            if method == "configs":
                return {"configs": configs}
            if method == "get":
                config = params["config"]
                state = states[config]
                return {
                    "values": {
                        n: {f".{k[1:]}" if k.startswith("_") else k: v for k, v in s.items()}
                        for n, s in state.items()
                    }
                }
            return {}

        result = ubus_ops.dump_all(call, redact=False)
        assert "network" in result
        assert "system" in result
        assert "lan" in result["network"]
        assert "_system" in result["system"]

    def test_handles_read_failure(self):
        def call(_obj, method, params=None):
            if method == "configs":
                return {"configs": ["good", "bad"]}
            if method == "get":
                if params["config"] == "bad":
                    raise RuntimeError("read failed")
                return {"values": {}}
            return {}

        result = ubus_ops.dump_all(call, redact=False)
        assert result["good"] == {}
        assert "_error" in result["bad"]
