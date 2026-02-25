import pytest

pytestmark = [
    pytest.mark.requires_salt_modules("saltext_uci.example_function"),
]


@pytest.fixture
def saltext_uci(modules):
    return modules.saltext_uci


def test_replace_this_this_with_something_meaningful(saltext_uci):
    echo_str = "Echoed!"
    res = saltext_uci.example_function(echo_str)
    assert res == echo_str
