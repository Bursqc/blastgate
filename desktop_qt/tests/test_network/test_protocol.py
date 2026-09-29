"""
Tests for network protocol builders and parsers
"""
import pytest
from blastgate.network import protocol


def test_build_discover_command():
    """Test DISCOVER command builder"""
    cmd = protocol.build_discover_command()
    assert cmd == b"DISCOVER"


def test_build_ping_command():
    """Test PING command builder"""
    cmd = protocol.build_ping_command()
    assert cmd == b"PING"


def test_build_status_command():
    """Test STATUS command builder"""
    cmd = protocol.build_status_command()
    assert cmd == b"STATUS"


def test_build_refresh_command():
    """Test REFRESH command builders"""
    cmd = protocol.build_refresh_command(full=False)
    assert cmd == b"REFRESH"

    cmd_full = protocol.build_refresh_command(full=True)
    assert cmd_full == b"REFRESH_FULL"


def test_build_node_command():
    """Test NODECMD command builder"""
    cmd = protocol.build_node_command("BG-1F8A3C", "open")
    assert cmd == b"NODECMD id=BG-1F8A3C gate=open"

    cmd2 = protocol.build_node_command("BG-123456", "close")
    assert cmd2 == b"NODECMD id=BG-123456 gate=close"


def test_build_relay_command():
    """Test RELAY command builder"""
    cmd = protocol.build_relay_command("on")
    assert cmd == b"RELAY on"

    cmd2 = protocol.build_relay_command("off")
    assert cmd2 == b"RELAY off"

    cmd3 = protocol.build_relay_command("auto")
    assert cmd3 == b"RELAY auto"


def test_build_assign_command():
    """Test ASSIGN command builder"""
    cmd = protocol.build_assign_command("BG-123", "Main Gate")
    assert cmd == b"ASSIGN id=BG-123 name=Main_Gate"

    # Test space replacement
    cmd2 = protocol.build_assign_command("BG-456", "Test Node")
    assert b"Test_Node" in cmd2


def test_build_assign_command_empty_name():
    """Test ASSIGN with empty name raises error"""
    with pytest.raises(ValueError, match="empty"):
        protocol.build_assign_command("BG-123", "")

    with pytest.raises(ValueError, match="empty"):
        protocol.build_assign_command("BG-123", "   ")


def test_build_node_config_command():
    """Test NODECFG_SET command builder"""
    cmd = protocol.build_node_config_command("BG-123", threshold_on=45.0)
    assert b"NODECFG_SET id=BG-123" in cmd
    assert b"threshold_on=45.0" in cmd

    cmd2 = protocol.build_node_config_command("BG-456", relay_hold_ms=3000, gate_hold_ms=4000)
    assert b"relay_hold_ms=3000" in cmd2
    assert b"gate_hold_ms=4000" in cmd2


def test_build_wifi_commands():
    """Test WiFi command builders"""
    # WIFI_GET
    cmd = protocol.build_wifi_get_command()
    assert cmd == b"WIFI_GET"

    # WIFI_SET
    cmd2 = protocol.build_wifi_set_command("MyNetwork", "password123")
    assert cmd2 == b"WIFI_SET ssid=MyNetwork pass=password123"

    # WIFI_DISCONNECT
    cmd3 = protocol.build_wifi_disconnect_command()
    assert cmd3 == b"WIFI_DISCONNECT"

    # WIFI_FORGET
    cmd4 = protocol.build_wifi_forget_command()
    assert cmd4 == b"WIFI_FORGET"

    # WIFI_PROV
    cmd5 = protocol.build_wifi_prov_command()
    assert cmd5 == b"WIFI_PROV"


def test_build_wifi_set_empty_ssid():
    """Test WIFI_SET with empty SSID raises error"""
    with pytest.raises(ValueError, match="empty"):
        protocol.build_wifi_set_command("", "password")


def test_parse_wifi_response():
    """Test WiFi response parsing"""
    raw = "WIFI;STA=1;SSID=MyNetwork;IP=192.168.1.50;RSSI=-45;PROV=0"
    result = protocol.parse_wifi_response(raw)

    assert result["raw"] == raw
    assert result["STA"] == "1"
    assert result["SSID"] == "MyNetwork"
    assert result["IP"] == "192.168.1.50"
    assert result["RSSI"] == "-45"
    assert result["PROV"] == "0"


def test_parse_wifi_response_invalid():
    """Test parsing invalid WiFi response"""
    raw = "INVALID RESPONSE"
    result = protocol.parse_wifi_response(raw)

    assert result["raw"] == raw
    assert len(result) == 1  # Only "raw" key


def test_is_error_response():
    """Test error response detection"""
    assert protocol.is_error_response("ERR: Command failed")
    assert protocol.is_error_response("ERROR")
    assert not protocol.is_error_response("OK")
    assert not protocol.is_error_response("STATUS...")


def test_is_pong_response():
    """Test PONG response detection"""
    assert protocol.is_pong_response("PONG")
    assert not protocol.is_pong_response("PING")
    assert not protocol.is_pong_response("PONG ")


def test_is_hub_discover_response():
    """Test hub discovery response detection"""
    assert protocol.is_hub_discover_response("BLASTGATE_HUB v1.0")
    assert protocol.is_hub_discover_response("BLASTGATE_HUB")
    assert not protocol.is_hub_discover_response("OTHER_DEVICE")
    assert not protocol.is_hub_discover_response("PONG")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
