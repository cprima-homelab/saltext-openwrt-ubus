import pytest

pytestmark = [
    pytest.mark.requires_salt_states("saltext_uci.exampled"),
]


@pytest.fixture
def saltext_uci(states):
    return states.saltext_uci


def test_replace_this_this_with_something_meaningful(saltext_uci):
    echo_str = "Echoed!"
    ret = saltext_uci.exampled(echo_str)
    assert ret.result
    assert not ret.changes
    assert echo_str in ret.comment
