import pytest
import salt.modules.test as testmod

import saltext.saltext_uci.modules.saltext_uci_mod as saltext_uci_module
import saltext.saltext_uci.states.saltext_uci_mod as saltext_uci_state


@pytest.fixture
def configure_loader_modules():
    return {
        saltext_uci_module: {
            "__salt__": {
                "test.echo": testmod.echo,
            },
        },
        saltext_uci_state: {
            "__salt__": {
                "saltext_uci.example_function": saltext_uci_module.example_function,
            },
        },
    }


def test_replace_this_this_with_something_meaningful():
    echo_str = "Echoed!"
    expected = {
        "name": echo_str,
        "changes": {},
        "result": True,
        "comment": f"The 'saltext_uci.example_function' returned: '{echo_str}'",
    }
    assert saltext_uci_state.exampled(echo_str) == expected
