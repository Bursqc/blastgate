"""
Tests for HubStatus and WifiInfo models
"""
import pytest
from blastgate.models.status import HubStatus, WifiInfo
from blastgate.models.node import NodeStatus


# ─── HubStatus ────────────────────────────────────────────────────────────────

def test_hub_status_defaults():
    hub = HubStatus()
    assert hub.manualOverdrive == 0
    assert hub.relayState == 0
    assert hub.nodes == []


def test_hub_is_locked():
    locked = HubStatus(manualOverdrive=1, relayState=0)
    unlocked = HubStatus(manualOverdrive=0, relayState=0)
    assert locked.is_locked is True
    assert unlocked.is_locked is False


def test_hub_is_relay_on():
    relay_on = HubStatus(manualOverdrive=0, relayState=1)
    relay_off = HubStatus(manualOverdrive=0, relayState=0)
    assert relay_on.is_relay_on is True
    assert relay_off.is_relay_on is False


def _make_node(node_id, online, active):
    return NodeStatus(id=node_id, online=online, active=active, override=0)


def test_hub_online_nodes():
    hub = HubStatus(nodes=[
        _make_node("BG-001", online=1, active=0),
        _make_node("BG-002", online=0, active=0),
        _make_node("BG-003", online=1, active=1),
    ])
    online = hub.online_nodes
    assert len(online) == 2
    assert all(n.is_online for n in online)


def test_hub_active_nodes():
    hub = HubStatus(nodes=[
        _make_node("BG-001", online=1, active=1),
        _make_node("BG-002", online=1, active=0),
        _make_node("BG-003", online=0, active=1),  # offline + active → not counted
    ])
    active = hub.active_nodes
    assert len(active) == 1
    assert active[0].id == "BG-001"


def test_hub_active_nodes_empty():
    hub = HubStatus(nodes=[_make_node("BG-001", online=1, active=0)])
    assert hub.active_nodes == []


def test_hub_get_node_by_id_found():
    hub = HubStatus(nodes=[
        _make_node("BG-AAA", online=1, active=0),
        _make_node("BG-BBB", online=1, active=1),
    ])
    node = hub.get_node_by_id("BG-BBB")
    assert node is not None
    assert node.id == "BG-BBB"


def test_hub_get_node_by_id_not_found():
    hub = HubStatus(nodes=[_make_node("BG-001", online=1, active=0)])
    assert hub.get_node_by_id("BG-MISSING") is None


def test_hub_get_node_by_id_empty():
    hub = HubStatus()
    assert hub.get_node_by_id("BG-001") is None


def test_hub_no_nodes_online():
    hub = HubStatus(nodes=[
        _make_node("BG-001", online=0, active=0),
        _make_node("BG-002", online=0, active=0),
    ])
    assert hub.online_nodes == []


# ─── WifiInfo ─────────────────────────────────────────────────────────────────

def test_wifi_info_defaults():
    wifi = WifiInfo()
    assert wifi.STA == "?"
    assert wifi.SSID == ""
    assert wifi.is_connected is False
    assert wifi.is_provisioning is False


def test_wifi_info_connected():
    wifi = WifiInfo(STA="1", SSID="MyNetwork", IP="192.168.1.50", RSSI="-45", PROV="0")
    assert wifi.is_connected is True
    assert wifi.is_provisioning is False


def test_wifi_info_not_connected():
    wifi = WifiInfo(STA="0", SSID="", IP="")
    assert wifi.is_connected is False


def test_wifi_info_provisioning_active():
    wifi = WifiInfo(STA="0", PROV="1")
    assert wifi.is_provisioning is True


def test_wifi_info_connected_and_provisioning():
    wifi = WifiInfo(STA="1", SSID="Net", PROV="1")
    assert wifi.is_connected is True
    assert wifi.is_provisioning is True


def test_wifi_info_raw_field():
    raw = "WIFI;STA=1;SSID=Test;IP=10.0.0.1;RSSI=-60;PROV=0"
    wifi = WifiInfo(STA="1", SSID="Test", IP="10.0.0.1", RSSI="-60", PROV="0", raw=raw)
    assert wifi.raw == raw


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
