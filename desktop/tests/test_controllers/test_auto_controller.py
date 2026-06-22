"""
Tests for AutoController (AUTO mode dust collection logic)
"""
import pytest
from unittest.mock import MagicMock, call
from blastgate.controllers.auto_controller import AutoController
from blastgate.models.config import AppConfig, NodeConfig


# ─── Fixtures ─────────────────────────────────────────────────────────────────

def make_controller(threshold=40.0, hyst=2.0, hold_ms=0):
    """Helper: create AutoController with mocked net engine and a single node config."""
    cfg = AppConfig()
    cfg.set_node_config("BG-001", NodeConfig(threshold=threshold, hyst=hyst, hold_ms=hold_ms))
    net = MagicMock()
    return AutoController(cfg, net), net


def node(node_id="BG-001", value=0.0, online=True):
    """Helper: create a minimal node dict as the controller receives it."""
    return {"id": node_id, "value": value, "online": 1 if online else 0}


# ─── reset() ──────────────────────────────────────────────────────────────────

def test_reset_clears_state():
    ctrl, net = make_controller()
    # Drive some state in
    ctrl.process([node(value=50.0)], app_mode="AUTO", lockout=False)
    # Reset
    ctrl.reset()
    assert ctrl._above_latched == {}
    assert ctrl._auto_relay_on is False
    assert ctrl._auto_gate_open == {}
    assert ctrl._auto_close_deadline_ms == {}


def test_reset_sends_no_commands():
    ctrl, net = make_controller()
    ctrl.process([node(value=50.0)], app_mode="AUTO", lockout=False)
    net.reset_mock()
    ctrl.reset()
    net.send.assert_not_called()


# ─── Skips when not in AUTO mode ──────────────────────────────────────────────

def test_process_skips_when_manual_mode():
    ctrl, net = make_controller()
    ctrl.process([node(value=50.0)], app_mode="MANUAL", lockout=False)
    net.send.assert_not_called()


def test_process_skips_when_lockout():
    ctrl, net = make_controller()
    ctrl.process([node(value=50.0)], app_mode="AUTO", lockout=True)
    net.send.assert_not_called()


def test_process_skips_empty_node_list():
    ctrl, net = make_controller()
    ctrl.process([], app_mode="AUTO", lockout=False)
    net.send.assert_not_called()


# ─── Threshold & hysteresis logic ─────────────────────────────────────────────

def test_relay_turns_on_when_sensor_crosses_threshold():
    """threshold=40, hyst=2 → ON at >42"""
    ctrl, net = make_controller(threshold=40.0, hyst=2.0, hold_ms=0)
    ctrl.process([node(value=43.0)], app_mode="AUTO", lockout=False)
    net.send.assert_any_call("relay", "on")


def test_gate_opens_when_sensor_above_threshold():
    ctrl, net = make_controller(threshold=40.0, hyst=2.0, hold_ms=0)
    ctrl.process([node(value=43.0)], app_mode="AUTO", lockout=False)
    net.send.assert_any_call("gate", "BG-001", "open")


def test_relay_stays_off_below_threshold():
    """value=41 < on_threshold(42) → no relay on"""
    ctrl, net = make_controller(threshold=40.0, hyst=2.0)
    ctrl.process([node(value=41.0)], app_mode="AUTO", lockout=False)
    # relay should not turn on
    calls = [str(c) for c in net.send.call_args_list]
    assert not any("relay" in c and "on" in c for c in calls)


def test_hysteresis_prevents_premature_off():
    """Once latched ON, stays ON until value drops below threshold-hyst=38"""
    ctrl, net = make_controller(threshold=40.0, hyst=2.0, hold_ms=0)
    # Latch ON
    ctrl.process([node(value=43.0)], app_mode="AUTO", lockout=False)
    net.reset_mock()
    # Value drops to 39 (below 40 but above 38=off_threshold) → stays ON
    ctrl.process([node(value=39.0)], app_mode="AUTO", lockout=False)
    relay_off_calls = [c for c in net.send.call_args_list if c == call("relay", "off")]
    assert len(relay_off_calls) == 0


def test_relay_turns_off_after_sensor_drops_below_off_threshold():
    """Drops below threshold-hyst=38 → relay off (hold_ms=0)"""
    ctrl, net = make_controller(threshold=40.0, hyst=2.0, hold_ms=0)
    ctrl.process([node(value=43.0)], app_mode="AUTO", lockout=False)
    net.reset_mock()
    ctrl.process([node(value=37.0)], app_mode="AUTO", lockout=False)
    net.send.assert_any_call("relay", "off")


def test_gate_closes_immediately_with_zero_hold():
    """hold_ms=0 → gate closes on next poll after sensor drops"""
    ctrl, net = make_controller(threshold=40.0, hyst=2.0, hold_ms=0)
    ctrl.process([node(value=43.0)], app_mode="AUTO", lockout=False)
    net.reset_mock()
    ctrl.process([node(value=37.0)], app_mode="AUTO", lockout=False)
    net.send.assert_any_call("gate", "BG-001", "close")


# ─── Gate open/close not repeated ─────────────────────────────────────────────

def test_gate_open_not_sent_twice():
    """Gate already open → no second open command"""
    ctrl, net = make_controller(threshold=40.0, hyst=2.0, hold_ms=5000)
    ctrl.process([node(value=43.0)], app_mode="AUTO", lockout=False)
    open_count = sum(1 for c in net.send.call_args_list if c == call("gate", "BG-001", "open"))
    net.reset_mock()
    # Still above threshold
    ctrl.process([node(value=50.0)], app_mode="AUTO", lockout=False)
    open_count2 = sum(1 for c in net.send.call_args_list if c == call("gate", "BG-001", "open"))
    assert open_count == 1
    assert open_count2 == 0  # No second open


def test_relay_on_not_sent_twice():
    ctrl, net = make_controller(threshold=40.0, hyst=2.0, hold_ms=5000)
    ctrl.process([node(value=43.0)], app_mode="AUTO", lockout=False)
    relay_on_count = sum(1 for c in net.send.call_args_list if c == call("relay", "on"))
    net.reset_mock()
    ctrl.process([node(value=50.0)], app_mode="AUTO", lockout=False)
    relay_on_count2 = sum(1 for c in net.send.call_args_list if c == call("relay", "on"))
    assert relay_on_count == 1
    assert relay_on_count2 == 0


# ─── None / invalid sensor value ──────────────────────────────────────────────

def test_none_sensor_value_treated_as_below():
    ctrl, net = make_controller(threshold=40.0, hyst=2.0, hold_ms=0)
    ctrl.process([node(value=None)], app_mode="AUTO", lockout=False)
    net.send.assert_not_called()


def test_invalid_sensor_value_treated_as_below():
    ctrl, net = make_controller(threshold=40.0, hyst=2.0, hold_ms=0)
    ctrl.process([{"id": "BG-001", "value": "not_a_number"}], app_mode="AUTO", lockout=False)
    net.send.assert_not_called()


# ─── Multiple nodes ───────────────────────────────────────────────────────────

def test_multiple_nodes_relay_on_if_any_above():
    cfg = AppConfig()
    cfg.set_node_config("BG-001", NodeConfig(threshold=40.0, hyst=2.0, hold_ms=0))
    cfg.set_node_config("BG-002", NodeConfig(threshold=40.0, hyst=2.0, hold_ms=0))
    net = MagicMock()
    ctrl = AutoController(cfg, net)

    ctrl.process(
        [node("BG-001", value=10.0), node("BG-002", value=50.0)],
        app_mode="AUTO",
        lockout=False,
    )
    net.send.assert_any_call("relay", "on")
    net.send.assert_any_call("gate", "BG-002", "open")
    # BG-001 below threshold → no open
    open_001 = [c for c in net.send.call_args_list if c == call("gate", "BG-001", "open")]
    assert len(open_001) == 0


def test_relay_off_only_when_all_nodes_below():
    cfg = AppConfig()
    cfg.set_node_config("BG-001", NodeConfig(threshold=40.0, hyst=2.0, hold_ms=0))
    cfg.set_node_config("BG-002", NodeConfig(threshold=40.0, hyst=2.0, hold_ms=0))
    net = MagicMock()
    ctrl = AutoController(cfg, net)

    # Both above threshold
    ctrl.process(
        [node("BG-001", value=50.0), node("BG-002", value=50.0)],
        app_mode="AUTO", lockout=False,
    )
    net.reset_mock()

    # Only BG-001 drops below off_threshold; BG-002 still above → relay stays ON
    ctrl.process(
        [node("BG-001", value=37.0), node("BG-002", value=50.0)],
        app_mode="AUTO", lockout=False,
    )
    relay_off = [c for c in net.send.call_args_list if c == call("relay", "off")]
    assert len(relay_off) == 0

    net.reset_mock()
    # Both drop below → relay off
    ctrl.process(
        [node("BG-001", value=37.0), node("BG-002", value=37.0)],
        app_mode="AUTO", lockout=False,
    )
    net.send.assert_any_call("relay", "off")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
