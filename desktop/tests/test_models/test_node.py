"""
Tests for NodeStatus model
"""
import pytest
from pydantic import ValidationError
from blastgate.models.node import NodeStatus


def test_node_status_basic():
    node = NodeStatus(id="BG-1F8A3C", online=1, active=0, override=0)
    assert node.id == "BG-1F8A3C"
    assert node.online == 1
    assert node.active == 0
    assert node.override == 0
    assert node.name is None
    assert node.value is None
    assert node.gateOpen is None


def test_node_is_online():
    online = NodeStatus(id="BG-001", online=1, active=0, override=0)
    offline = NodeStatus(id="BG-002", online=0, active=0, override=0)
    assert online.is_online is True
    assert offline.is_online is False


def test_node_is_active():
    active = NodeStatus(id="BG-001", online=1, active=1, override=0)
    inactive = NodeStatus(id="BG-002", online=1, active=0, override=0)
    assert active.is_active is True
    assert inactive.is_active is False


def test_node_gate_state_from_gate_open():
    """gateOpen field takes priority"""
    node_open = NodeStatus(id="BG-001", online=1, active=0, override=0, gateOpen=1)
    node_closed = NodeStatus(id="BG-002", online=1, active=0, override=0, gateOpen=0)
    assert node_open.is_gate_open is True
    assert node_closed.is_gate_open is False


def test_node_gate_state_fallback_to_override():
    """When gateOpen is None, falls back to override==1"""
    node_override_open = NodeStatus(id="BG-001", online=1, active=0, override=1)
    node_override_close = NodeStatus(id="BG-002", online=1, active=0, override=2)
    node_override_auto = NodeStatus(id="BG-003", online=1, active=0, override=0)
    assert node_override_open.is_gate_open is True
    assert node_override_close.is_gate_open is False
    assert node_override_auto.is_gate_open is False


def test_node_gate_state_str():
    node_open = NodeStatus(id="BG-001", online=1, active=0, override=0, gateOpen=1)
    node_closed = NodeStatus(id="BG-002", online=1, active=0, override=0, gateOpen=0)
    assert node_open.gate_state_str == "OPEN"
    assert node_closed.gate_state_str == "CLOSED"


def test_node_override_command_str():
    auto = NodeStatus(id="BG-001", online=1, active=0, override=0)
    open_cmd = NodeStatus(id="BG-002", online=1, active=0, override=1)
    close_cmd = NodeStatus(id="BG-003", online=1, active=0, override=2)
    assert auto.override_command_str == "AUTO"
    assert open_cmd.override_command_str == "OPEN"
    assert close_cmd.override_command_str == "CLOSE"


def test_node_with_name_and_value():
    node = NodeStatus(id="BG-ABC", online=1, active=1, override=0, name="Front Gate", value=55.5)
    assert node.name == "Front Gate"
    assert node.value == 55.5


def test_node_validation_online_out_of_range():
    with pytest.raises(ValidationError):
        NodeStatus(id="BG-001", online=2, active=0, override=0)


def test_node_validation_active_out_of_range():
    with pytest.raises(ValidationError):
        NodeStatus(id="BG-001", online=0, active=5, override=0)


def test_node_validation_override_out_of_range():
    with pytest.raises(ValidationError):
        NodeStatus(id="BG-001", online=0, active=0, override=3)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
