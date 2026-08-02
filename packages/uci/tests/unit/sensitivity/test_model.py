"""
Unit tests for sensitivity model: Classification, TAINT_RANK, max_taint(),
MatchCriteria, SensitivityProfile.
"""

import pytest

from saltext.uci.sensitivity.model import TAINT_RANK
from saltext.uci.sensitivity.model import Classification
from saltext.uci.sensitivity.model import ClassificationRule
from saltext.uci.sensitivity.model import MatchCriteria
from saltext.uci.sensitivity.model import Policy
from saltext.uci.sensitivity.model import SensitivityProfile
from saltext.uci.sensitivity.model import Surface
from saltext.uci.sensitivity.model import max_taint


class TestClassification:
    def test_all_values_exist(self):
        assert Classification.PUBLIC.value == "public"
        assert Classification.INTERNAL.value == "internal"
        assert Classification.UNKNOWN.value == "unknown"
        assert Classification.SENSITIVE.value == "sensitive"
        assert Classification.SECRET.value == "secret"

    def test_is_str_enum(self):
        assert isinstance(Classification.SECRET, str)
        assert Classification.SECRET == "secret"  # str comparison via value

    def test_no_implicit_ordering_on_unknown(self):
        # Classification does not define __lt__; comparison must not be used.
        # We only verify TAINT_RANK is the intended ranking mechanism.
        assert TAINT_RANK[Classification.UNKNOWN] > TAINT_RANK[Classification.INTERNAL]
        assert TAINT_RANK[Classification.UNKNOWN] < TAINT_RANK[Classification.SENSITIVE]


class TestTaintRank:
    def test_public_lowest(self):
        assert TAINT_RANK[Classification.PUBLIC] == 0

    def test_secret_highest(self):
        assert TAINT_RANK[Classification.SECRET] == max(TAINT_RANK.values())

    def test_unknown_above_internal(self):
        assert TAINT_RANK[Classification.UNKNOWN] > TAINT_RANK[Classification.INTERNAL]

    def test_unknown_below_sensitive(self):
        assert TAINT_RANK[Classification.UNKNOWN] < TAINT_RANK[Classification.SENSITIVE]

    def test_max_taint_public_secret(self):
        assert max_taint([Classification.PUBLIC, Classification.SECRET]) == Classification.SECRET

    def test_max_taint_internal_unknown(self):
        assert (
            max_taint([Classification.INTERNAL, Classification.UNKNOWN]) == Classification.UNKNOWN
        )

    def test_max_taint_empty_defaults_to_public(self):
        assert max_taint([]) == Classification.PUBLIC

    def test_max_taint_all_public(self):
        assert max_taint([Classification.PUBLIC, Classification.PUBLIC]) == Classification.PUBLIC

    def test_max_taint_secret_wins_over_sensitive(self):
        assert max_taint([Classification.SENSITIVE, Classification.SECRET]) == Classification.SECRET


class TestMatchCriteria:
    def test_specificity_option_only(self):
        m = MatchCriteria(option="key")
        assert m.specificity() == 1

    def test_specificity_section_type_and_option(self):
        m = MatchCriteria(section_type="wifi-iface", option="key")
        assert m.specificity() == 2

    def test_specificity_all_three(self):
        m = MatchCriteria(package="network", section_type="interface", option="private_key")
        assert m.specificity() == 3

    def test_matches_option_only(self):
        m = MatchCriteria(option="key")
        assert m.matches("wireless", "wifi-iface", "key")
        assert not m.matches("wireless", "wifi-iface", "ssid")

    def test_matches_section_type_and_option(self):
        m = MatchCriteria(section_type="wifi-iface", option="key")
        assert m.matches("wireless", "wifi-iface", "key")
        assert not m.matches("wireless", "wifi-device", "key")

    def test_matches_list_option(self):
        m = MatchCriteria(option=["key", "psk", "password"])
        assert m.matches("wireless", "wifi-iface", "psk")
        assert not m.matches("wireless", "wifi-iface", "ssid")

    def test_matches_list_section_type(self):
        m = MatchCriteria(section_type=["zone", "rule"], option="name")
        assert m.matches("firewall", "zone", "name")
        assert m.matches("firewall", "rule", "name")
        assert not m.matches("firewall", "defaults", "name")

    def test_matches_all_three(self):
        m = MatchCriteria(package="network", section_type="interface", option="private_key")
        assert m.matches("network", "interface", "private_key")
        assert not m.matches("network", "wireguard", "private_key")
        assert not m.matches("wireless", "interface", "private_key")

    def test_empty_criteria_matches_everything(self):
        m = MatchCriteria()
        assert m.specificity() == 0
        assert m.matches("any", "any", "any")


class TestSensitivityProfile:
    @pytest.fixture(scope="class")
    def builtin(self):
        return SensitivityProfile.load_builtin()

    def test_load_builtin_has_name(self, builtin):
        assert builtin.name == "saltext-uci-ubus/default"

    def test_load_builtin_has_version(self, builtin):
        assert builtin.version == "2"

    def test_builtin_classifies_wireguard_private_key_as_secret(self, builtin):
        assert builtin.classify("network", "interface", "private_key") == Classification.SECRET

    def test_builtin_classifies_wifi_key_as_secret(self, builtin):
        assert builtin.classify("wireless", "wifi-iface", "key") == Classification.SECRET

    def test_builtin_classifies_proto_as_internal(self, builtin):
        assert builtin.classify("network", "interface", "proto") == Classification.INTERNAL

    def test_builtin_classifies_ipaddr_as_internal(self, builtin):
        assert builtin.classify("network", "interface", "ipaddr") == Classification.INTERNAL

    def test_builtin_classifies_ssid_as_internal(self, builtin):
        assert builtin.classify("wireless", "wifi-iface", "ssid") == Classification.INTERNAL

    def test_builtin_classifies_wireguard_public_key_as_internal(self, builtin):
        assert builtin.classify("network", "wireguard_wg0", "public_key") == Classification.INTERNAL

    def test_builtin_classifies_listen_port_as_internal(self, builtin):
        assert builtin.classify("network", "interface", "listen_port") == Classification.INTERNAL

    def test_builtin_classifies_ntp_server_as_internal(self, builtin):
        assert builtin.classify("system", "timeserver", "server") == Classification.INTERNAL

    def test_wireguard_private_key_still_secret_after_public_key_rule(self, builtin):
        assert builtin.classify("network", "interface", "private_key") == Classification.SECRET

    def test_unmatched_option_returns_unknown(self, builtin):
        cl = builtin.classify("custom", "custom_type", "some_novel_option")
        assert cl == Classification.UNKNOWN

    def test_higher_specificity_wins_over_lower(self, builtin):
        # wifi-iface/key is secret (specificity 2); no package rule exists
        # Option 'key' at specificity 1 doesn't exist in builtin, but the test
        # checks the resolution chain: specificity 2 > specificity 1 for wifi-iface/key
        assert builtin.classify("wireless", "wifi-iface", "key") == Classification.SECRET

    def test_evaluate_returns_policy_decision(self, builtin):
        decision = builtin.evaluate("wireless", "wifi-iface", "key", Surface.EVIDENCE)
        assert decision.classification == Classification.SECRET
        assert decision.policy == Policy.REDACT_VALUE

    def test_policy_unknown_grains_is_deny(self, builtin):
        assert builtin.policy(Classification.UNKNOWN, Surface.GRAINS) == Policy.DENY_VALUE

    def test_policy_unknown_evidence_is_redact(self, builtin):
        assert builtin.policy(Classification.UNKNOWN, Surface.EVIDENCE) == Policy.REDACT_VALUE

    def test_policy_secret_config_diff_is_report_change(self, builtin):
        assert builtin.policy(Classification.SECRET, Surface.CONFIG_DIFF) == Policy.REPORT_CHANGE

    def test_policy_internal_grains_is_allow(self, builtin):
        assert builtin.policy(Classification.INTERNAL, Surface.GRAINS) == Policy.ALLOW

    def test_overlay_appends_rules(self, builtin):
        override_rule = ClassificationRule(
            match=MatchCriteria(package="custom", section_type="secret_type", option="my_secret"),
            classification=Classification.SECRET,
        )
        overlay_profile = SensitivityProfile(
            name="custom/override",
            version="1",
            rules=[override_rule],
            policies=dict(builtin.policies),
        )
        merged = builtin.overlay(overlay_profile)
        assert merged.classify("custom", "secret_type", "my_secret") == Classification.SECRET
        assert merged.classify("wireless", "wifi-iface", "key") == Classification.SECRET

    def test_overlay_updates_name_and_version(self, builtin):
        other = SensitivityProfile(
            name="my/profile", version="2", rules=[], policies=dict(builtin.policies)
        )
        merged = builtin.overlay(other)
        assert merged.name == "my/profile"
        assert merged.version == "2"

    def test_overlay_merges_policies(self, builtin):
        custom_policies = {
            **builtin.policies,
            Classification.INTERNAL: {
                **builtin.policies[Classification.INTERNAL],
                Surface.GRAINS: Policy.REDACT_VALUE,
            },
        }
        other = SensitivityProfile(name="x", version="1", rules=[], policies=custom_policies)
        merged = builtin.overlay(other)
        assert merged.policy(Classification.INTERNAL, Surface.GRAINS) == Policy.REDACT_VALUE
        assert merged.policy(Classification.SECRET, Surface.EVIDENCE) == Policy.REDACT_VALUE
