import pytest

pytestmark = [
    pytest.mark.requires_salt_modules("saltext_uci.get"),
]


@pytest.fixture
def saltext_uci(modules):
    return modules.saltext_uci


def test_get_returns_none_for_missing_key(saltext_uci):
    res = saltext_uci.get("nonexistent.package.option")
    assert res is None
