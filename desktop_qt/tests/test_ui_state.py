"""Tests for pure UI display logic (blastgate.ui.state)."""
from datetime import datetime

import pytest

from blastgate.ui import state


def test_status_offline_beats_everything():
    assert state.node_status({"online": 0, "active": 1, "err": 1}) == ("OFFLINE", "danger")


def test_status_error_bits_warn_but_calibrating_does_not():
    assert state.node_status({"online": 1, "err": 1}) == ("UPOZORENJE", "warning")
    assert state.node_status({"online": 1, "err": 8, "active": 0}) == ("MIRUJE", "idle")


def test_status_running_and_idle():
    assert state.node_status({"online": 1, "active": 1}) == ("RADI", "success")
    assert state.node_status({"online": 1, "active": 0}) == ("MIRUJE", "idle")


def test_gate_open_prefers_gatestate_then_gateopen_then_override():
    assert state.gate_open({"gateState": 2, "gateOpen": 0}) is True
    assert state.gate_open({"gateOpen": 1, "override": 2}) is True
    assert state.gate_open({"override": 1}) is True
    assert state.gate_open({"override": 0}) is False


def test_gate_text_countdown_and_old_firmware():
    assert state.gate_text({"online": 1, "gateOpen": 1, "closeInMs": 3400}) == "Zatvara za 3 s"
    assert state.gate_text({"online": 1, "gateState": 3}) == "Zatvara se"
    assert state.gate_text({"online": 1, "gateOpen": 0}) == "Zatvoren"
    assert state.gate_text({"online": 0}) == "—"


def test_signal_bars():
    assert state.signal_bars(None) == 0
    assert state.signal_bars(-55) == 4
    assert state.signal_bars(-65) == 3
    assert state.signal_bars(-75) == 2
    assert state.signal_bars(-85) == 1
    assert state.signal_bars(-95) == 0


def test_signal_text_old_firmware_has_no_rssi():
    assert state.signal_text({"online": 1}) == "—"
    assert state.signal_text({"online": 1, "rssi": -62}) == "-62 dBm"


def test_hold_conversion_roundtrip():
    assert state.hold_ms_to_s(5000) == 5.0
    assert state.hold_s_to_ms(2.5) == 2500


def test_err_texts():
    assert len(state.err_texts(1 | 4)) == 2
    assert state.err_texts(0) == []


def test_bar_max_keeps_threshold_in_middle():
    assert state.bar_max(10, 40) == 80
    assert state.bar_max(200, 40) == pytest.approx(220)


def test_diff_events():
    t = datetime(2026, 9, 29, 10, 0, 0)
    prev = {"relayState": 0, "nodes": [{"id": "BG-1", "name": "Cirkular", "online": 1, "active": 0, "gateOpen": 0}]}
    cur = {"relayState": 1, "nodes": [{"id": "BG-1", "name": "Cirkular", "online": 1, "active": 1, "gateOpen": 1}]}
    texts = [e[2] for e in state.diff_events(prev, cur, t)]
    assert "Usisivač uključen" in texts
    assert "Cirkular: mašina krenula" in texts
    assert "Cirkular: zatvarač otvoren" in texts


def test_diff_events_hub_lost():
    assert state.diff_events({"nodes": []}, {})[0][2] == "Veza sa hubom izgubljena"
