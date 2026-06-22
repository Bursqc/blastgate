"""
Tests for input validation utilities
"""
import pytest
from blastgate.utils.validators import is_valid_ipv4, is_valid_port, sanitize_node_name


# ─── is_valid_ipv4 ────────────────────────────────────────────────────────────

def test_valid_ipv4_standard():
    assert is_valid_ipv4("192.168.1.1") is True
    assert is_valid_ipv4("10.0.0.1") is True
    assert is_valid_ipv4("255.255.255.255") is True
    assert is_valid_ipv4("0.0.0.0") is True


def test_valid_ipv4_edge_cases():
    assert is_valid_ipv4("192.168.4.1") is True    # AP default
    assert is_valid_ipv4("169.254.5.1") is True    # link-local
    assert is_valid_ipv4("127.0.0.1") is True      # loopback


def test_invalid_ipv4_out_of_range():
    assert is_valid_ipv4("256.1.1.1") is False
    assert is_valid_ipv4("192.168.1.999") is False
    assert is_valid_ipv4("999.999.999.999") is False


def test_invalid_ipv4_wrong_format():
    assert is_valid_ipv4("not.an.ip") is False
    assert is_valid_ipv4("192.168.1") is False       # only 3 octets
    assert is_valid_ipv4("192.168.1.1.1") is False   # 5 octets
    assert is_valid_ipv4("invalid") is False
    assert is_valid_ipv4("") is False
    assert is_valid_ipv4("192.168.1. 1") is False    # space inside


# ─── is_valid_port ────────────────────────────────────────────────────────────

def test_valid_ports():
    assert is_valid_port(1) is True
    assert is_valid_port(80) is True
    assert is_valid_port(8888) is True
    assert is_valid_port(65535) is True


def test_invalid_port_zero():
    assert is_valid_port(0) is False


def test_invalid_port_too_large():
    assert is_valid_port(65536) is False
    assert is_valid_port(99999) is False


def test_invalid_port_negative():
    assert is_valid_port(-1) is False


# ─── sanitize_node_name ───────────────────────────────────────────────────────

def test_sanitize_spaces_to_underscores():
    assert sanitize_node_name("Front Gate") == "Front_Gate"
    assert sanitize_node_name("Node 1 Test") == "Node_1_Test"


def test_sanitize_strips_whitespace():
    assert sanitize_node_name("  Main Gate  ") == "Main_Gate"
    assert sanitize_node_name("  Gate  ") == "Gate"


def test_sanitize_replaces_double_quotes():
    # spaces → underscores AND double quotes → single quotes
    assert sanitize_node_name('Test "Node"') == "Test_'Node'"


def test_sanitize_empty_returns_none():
    assert sanitize_node_name("") is None
    assert sanitize_node_name("   ") is None


def test_sanitize_no_change_needed():
    assert sanitize_node_name("Gate1") == "Gate1"
    assert sanitize_node_name("BG-1F8A3C") == "BG-1F8A3C"


def test_sanitize_non_string_returns_none():
    assert sanitize_node_name(None) is None  # type: ignore
    assert sanitize_node_name(123) is None   # type: ignore


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
