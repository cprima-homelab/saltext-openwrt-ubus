"""
Tests for saltext.openwrt_ubus.utils.ubus_ops
"""

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
