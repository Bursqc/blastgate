"""Demo hub must follow the same rules as the hub firmware, through the real client."""
import pytest

from blastgate.exceptions import HubCommandError
from blastgate.fake_hub import FakeHub, FakeHubClient
from blastgate.models.config import AppConfig


@pytest.fixture
def client():
    hub = FakeHub()
    for n in hub.nodes:          # deterministic: every machine idle
        n["running"] = False
        n["next_toggle"] = float("inf")
        n["value"] = 3.0
    c = FakeHubClient(AppConfig(), hub)
    c.pick_best_ip()
    yield c
    c.close()


def _node(client, idx=0):
    return client.get_status_fast().nodes[idx]


def test_status_parses_with_new_fields(client):
    st = client.get_status_fast().model_dump()
    assert len(st["nodes"]) == 6
    assert "gateState" in st["nodes"][0] and "rssi" in st["nodes"][0]


def test_relay_on_blocked_without_open_gate(client):
    with pytest.raises(HubCommandError, match="no gate open"):
        client.set_relay("on")


def test_manual_open_then_relay_on(client):
    nid = _node(client).id
    client.set_node_mode(nid, "manual")
    client.set_node_gate(nid, "open")
    assert _node(client).is_gate_open
    client.set_relay("on")
    st = client.get_status_fast()
    assert st.relayState == 1 and st.relayMode == 1


def test_overdrive_locks_refresh_but_allows_node_commands(client):
    client.hub.toggle_overdrive()
    st = client.get_status_fast()   # STATUS is always allowed
    assert st.manualOverdrive == 1
    assert all(n.override == 2 for n in st.nodes)
    assert client._send_cmd("x", b"REFRESH").startswith("{")
    assert client._send_cmd("x", b"WIFI_SET ssid=a pass=b") == "OK WIFI_SET (restarting)"


def test_config_roundtrip_and_rename(client):
    nid = _node(client).id
    client.set_node_config(nid, {"threshold_on": 77.5, "gate_hold_ms": 1200})
    cfg = client.get_node_config(nid)
    assert cfg["threshold_on"] == 77.5 and cfg["gate_hold_ms"] == 1200
    client.set_node_name(nid, "Stona testera")
    assert _node(client).name == "Stona testera"


def test_lost_hub_returns_nothing(client):
    client.hub.set_lost(True)
    assert client._send_cmd("x", b"PING") is None
