from saltext.saltext_uci.utils.uci_parser import parse_show
from saltext.saltext_uci.utils.uci_parser import to_pillar

# --- Captured from austru: ssh austru "uci show network" ---

AUSTRU_NETWORK = """\
network.loopback=interface
network.loopback.device='lo'
network.loopback.proto='static'
network.loopback.ipaddr='127.0.0.1'
network.loopback.netmask='255.0.0.0'
network.globals=globals
network.wan=interface
network.wan.device='eth1'
network.wan.proto='static'
network.wan.ipaddr='192.168.16.99'
network.wan.netmask='255.255.255.0'
network.wan.gateway='192.168.16.254'
network.wan.dns='1.1.1.1' '1.0.0.1'
network.@device[0]=device
network.@device[0].name='br-lan'
network.@device[0].type='bridge'
network.@device[0].ports='eth0'
network.@device[1]=device
network.@device[1].name='eth0'
network.@device[1].macaddr='22:4e:7f:5b:26:9a'
network.lan=interface
network.lan.device='br-lan'
network.lan.proto='static'
network.lan.ipaddr='10.35.24.1'
network.lan.netmask='255.255.255.0'
network.@switch[0]=switch
network.@switch[0].name='switch0'
network.@switch[0].reset='1'
network.@switch[0].enable_vlan='1'
network.@switch[0].blinkrate='2'
network.@switch_vlan[0]=switch_vlan
network.@switch_vlan[0].device='switch0'
network.@switch_vlan[0].vlan='1'
network.@switch_vlan[0].ports='0 1 2 3 5'
network.vpn=interface
network.vpn.proto='none'
network.vpn.device='tun0'
"""


class TestParseShow:
    def test_named_section_scalar(self):
        result = parse_show(AUSTRU_NETWORK)
        assert result["network"]["lan"]["ipaddr"] == "10.35.24.1"
        assert result["network"]["lan"]["_type"] == "interface"

    def test_named_section_list(self):
        result = parse_show(AUSTRU_NETWORK)
        assert result["network"]["wan"]["dns"] == ["1.1.1.1", "1.0.0.1"]

    def test_empty_section(self):
        result = parse_show(AUSTRU_NETWORK)
        assert result["network"]["globals"]["_type"] == "globals"

    def test_anonymous_sections(self):
        result = parse_show(AUSTRU_NETWORK)
        anon = result["network"]["_anonymous"]
        devices = [e for e in anon if e["_type"] == "device"]
        assert len(devices) == 2
        assert devices[0]["name"] == "br-lan"
        assert devices[1]["macaddr"] == "22:4e:7f:5b:26:9a"

    def test_anonymous_switch(self):
        result = parse_show(AUSTRU_NETWORK)
        anon = result["network"]["_anonymous"]
        switches = [e for e in anon if e["_type"] == "switch"]
        assert len(switches) == 1
        assert switches[0]["name"] == "switch0"

    def test_all_named_sections_present(self):
        result = parse_show(AUSTRU_NETWORK)
        named = {k for k in result["network"] if not k.startswith("_")}
        assert named == {"loopback", "globals", "wan", "lan", "vpn"}

    def test_single_section(self):
        text = "network.lan=interface\nnetwork.lan.proto='static'"
        result = parse_show(text)
        assert result == {"network": {"lan": {"_type": "interface", "proto": "static"}}}

    def test_empty_input(self):
        assert not parse_show("")

    def test_multi_package(self):
        text = (
            "network.lan=interface\n"
            "network.lan.proto='static'\n"
            "system.@system[0]=system\n"
            "system.@system[0].hostname='austru'\n"
        )
        result = parse_show(text)
        assert "network" in result
        assert "system" in result
        assert result["system"]["_anonymous"][0]["hostname"] == "austru"


class TestToPillar:
    def test_wraps_under_uci_key(self):
        config = parse_show("network.lan=interface\nnetwork.lan.proto='static'")
        pillar = to_pillar(config)
        assert pillar == {"uci": {"network": {"lan": {"_type": "interface", "proto": "static"}}}}
