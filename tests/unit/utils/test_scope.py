"""Unit tests for the package scope registry."""

from saltext.openwrt_ubus.utils import scope


class TestTier:
    def test_stable_packages(self):
        assert scope.tier("network") == "stable"
        assert scope.tier("system") == "stable"
        assert scope.tier("dhcp") == "stable"

    def test_experimental_packages(self):
        assert scope.tier("wireless") == "experimental"
        assert scope.tier("firewall") == "experimental"
        assert scope.tier("dropbear") == "experimental"

    def test_unregistered_package(self):
        assert scope.tier("uhttpd") is None
        assert scope.tier("rpcd") is None
        assert scope.tier("nonexistent") is None


class TestIsSupported:
    def test_supported(self):
        assert scope.is_supported("network") is True
        assert scope.is_supported("firewall") is True

    def test_not_supported(self):
        assert scope.is_supported("uhttpd") is False
        assert scope.is_supported("nonexistent") is False


class TestSupported:
    def test_returns_sorted_list(self):
        result = scope.supported()
        assert result == ["dhcp", "dropbear", "firewall", "network", "system", "wireless"]
        assert len(result) == 6
