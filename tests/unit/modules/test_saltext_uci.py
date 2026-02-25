import pytest
import salt.modules.test as testmod

import saltext.saltext_uci.modules.saltext_uci_mod as saltext_uci_module


@pytest.fixture
def configure_loader_modules():
    module_globals = {
        "__salt__": {"test.echo": testmod.echo},
    }
    return {
        saltext_uci_module: module_globals,
    }


def test_replace_this_this_with_something_meaningful():
    echo_str = "Echoed!"
    assert saltext_uci_module.example_function(echo_str) == echo_str
