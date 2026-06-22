"""
Tests for helper utility functions
"""
import time
import pytest
from blastgate.utils.helpers import to_float, to_int, now_ms, safe_node_id


# ─── to_float ─────────────────────────────────────────────────────────────────

def test_to_float_standard():
    assert to_float("3.14") == 3.14
    assert to_float("0.0") == 0.0
    assert to_float("100") == 100.0


def test_to_float_comma_decimal():
    assert to_float("2,5") == 2.5
    assert to_float("10,0") == 10.0
    assert to_float("99,99") == 99.99


def test_to_float_strips_whitespace():
    assert to_float("  3.14  ") == 3.14
    assert to_float(" 42 ") == 42.0


def test_to_float_invalid_returns_default():
    assert to_float("invalid", 0.0) == 0.0
    assert to_float("abc", 99.0) == 99.0
    assert to_float("", 5.0) == 5.0
    assert to_float("1.2.3", 0.0) == 0.0


def test_to_float_default_is_zero():
    assert to_float("bad") == 0.0


def test_to_float_negative():
    assert to_float("-5.5") == -5.5
    assert to_float("-0") == 0.0


# ─── to_int ───────────────────────────────────────────────────────────────────

def test_to_int_standard():
    assert to_int("42") == 42
    assert to_int("0") == 0
    assert to_int("1000") == 1000


def test_to_int_truncates_float():
    assert to_int("3.7") == 3
    assert to_int("9.9") == 9
    assert to_int("2.0") == 2


def test_to_int_comma_decimal():
    assert to_int("5,5") == 5
    assert to_int("10,9") == 10


def test_to_int_strips_whitespace():
    assert to_int("  7  ") == 7


def test_to_int_invalid_returns_default():
    assert to_int("invalid", 0) == 0
    assert to_int("abc", 100) == 100
    assert to_int("", 0) == 0


def test_to_int_default_is_zero():
    assert to_int("bad") == 0


def test_to_int_negative():
    assert to_int("-10") == -10


# ─── now_ms ───────────────────────────────────────────────────────────────────

def test_now_ms_is_integer():
    ts = now_ms()
    assert isinstance(ts, int)


def test_now_ms_is_positive():
    assert now_ms() > 0


def test_now_ms_increases():
    t1 = now_ms()
    time.sleep(0.05)
    t2 = now_ms()
    assert t2 > t1


def test_now_ms_reasonable_range():
    """Should be roughly current epoch time in ms (after year 2020)"""
    ts = now_ms()
    assert ts > 1_577_836_800_000  # Jan 1 2020 in ms


# ─── safe_node_id ─────────────────────────────────────────────────────────────

def test_safe_node_id_normal():
    assert safe_node_id({"id": "BG-123ABC"}) == "BG-123ABC"


def test_safe_node_id_strips_whitespace():
    assert safe_node_id({"id": "  BG-001  "}) == "BG-001"


def test_safe_node_id_missing_key():
    assert safe_node_id({"name": "Test"}) == ""
    assert safe_node_id({}) == ""


def test_safe_node_id_none_value():
    assert safe_node_id({"id": None}) == ""


def test_safe_node_id_empty_string():
    assert safe_node_id({"id": ""}) == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
