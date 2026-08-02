"""
Integration tests for uci UCI operations against a live container.

Each testcorpus case exercises a distinct UCI data model pattern:
    before.uci  →  ubus call uci.*  →  after.uci

The tests call ubus directly (not through Salt) to validate the transport
and UCI layer in isolation. Salt state module tests are a future layer on top.

Prerequisite:
    docker compose -f infra/openwrt-test/compose.yaml up -d
"""

import pytest
import yaml

from tests.integration.openwrt.conftest import TESTCORPUS_TESTS, read_container_config

# (case_name, expect_changed)
TESTCORPUS_CASES = [
    ("01_set_scalar_named", True),
    ("02_set_scalar_with_spaces", True),
    ("03_replace_list", True),
    ("04_set_anon_singleton", True),
    ("05_toggle_boolean", True),
    ("06_populate_empty_section", True),
    ("07_idempotent_no_change", False),
    ("08_multi_section_update", True),
]


class TestRpcTransport:
    """Verify the JSON-RPC session and basic ubus connectivity."""

    def test_login_succeeds(self, ubus_client):
        assert ubus_client.session is not None
        assert len(ubus_client.session) == 32

    def test_uci_configs_lists_testcorpus(self, ubus_client):
        result = ubus_client.call("uci", "configs")
        assert "testcorpus" in result.get("configs", [])

    def test_system_board_returns_hostname(self, ubus_client):
        result = ubus_client.call("system", "board")
        assert "hostname" in result

    def test_uci_get_testcorpus(self, ubus_client, openwrt_container):  # pylint: disable=unused-argument
        result = ubus_client.call("uci", "get", {"config": "testcorpus"})
        assert "values" in result


class TestUciScalarMutation:
    """Named scalar set — testcorpus case 01."""

    @pytest.fixture(autouse=True)
    def _reset(self, testcorpus_case):
        pass

    @pytest.mark.parametrize("testcorpus_case", ["01_set_scalar_named"], indirect=True)
    def test_set_scalar_changes_option(self, ubus_client, testcorpus_case, openwrt_container):
        delta = yaml.safe_load((TESTCORPUS_TESTS / testcorpus_case / "delta.yaml").read_text())
        after_expected = (TESTCORPUS_TESTS / testcorpus_case / "after.uci").read_text()

        kwargs = delta["kwargs"]
        sections = kwargs["sections"]
        config = kwargs["config"]

        # Apply each section change via uci set.
        for section_name, values in sections.items():
            values_without_type = {k: v for k, v in values.items() if k != "_type"}
            for option, value in values_without_type.items():
                ubus_client.call(
                    "uci",
                    "set",
                    {
                        "config": config,
                        "section": section_name,
                        "values": {option: value},
                    },
                )
        ubus_client.call("uci", "commit", {"config": config})

        actual = read_container_config(openwrt_container, config)
        assert actual.strip() == after_expected.strip()

    @pytest.mark.parametrize("testcorpus_case", ["07_idempotent_no_change"], indirect=True)
    def test_idempotent_no_mutation(self, ubus_client, testcorpus_case, openwrt_container):
        """Applying the current value must leave /etc/config unchanged."""
        delta = yaml.safe_load((TESTCORPUS_TESTS / testcorpus_case / "delta.yaml").read_text())
        after_expected = (TESTCORPUS_TESTS / testcorpus_case / "after.uci").read_text()

        kwargs = delta["kwargs"]
        sections = kwargs["sections"]
        config = kwargs["config"]

        ubus_client.call("uci", "changes", {"config": config})

        for section_name, values in sections.items():
            values_without_type = {k: v for k, v in values.items() if k != "_type"}
            for option, value in values_without_type.items():
                ubus_client.call(
                    "uci",
                    "set",
                    {
                        "config": config,
                        "section": section_name,
                        "values": {option: value},
                    },
                )

        changes_after = ubus_client.call("uci", "changes", {"config": config})
        # Idempotent: no pending changes after setting the same value.
        assert changes_after.get("changes", []) == []

        actual = read_container_config(openwrt_container, config)
        assert actual.strip() == after_expected.strip()
