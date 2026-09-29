"""
Tests for configuration loading and saving
"""
import json
import pytest
from pathlib import Path
from pydantic import ValidationError

from blastgate.models.config import AppConfig, NodeConfig
from blastgate.config import load_config, save_config


def test_appconfig_defaults():
    """Test AppConfig default values"""
    cfg = AppConfig()
    assert cfg.hub_lan_ip == "192.168.1.116"
    assert cfg.hub_ap_ip == "192.168.4.1"
    assert cfg.udp_port == 8888
    assert cfg.poll_ms == 650
    assert cfg.timeout_s == 1.2
    assert cfg.theme == "darkly"
    assert cfg.nodes == {}


def test_appconfig_validation_invalid_port():
    """Test that invalid port raises ValidationError"""
    with pytest.raises(ValidationError):
        AppConfig(udp_port=99999)

    with pytest.raises(ValidationError):
        AppConfig(udp_port=0)


def test_appconfig_validation_invalid_ip():
    """Test that invalid IP raises ValidationError"""
    with pytest.raises(ValidationError):
        AppConfig(hub_lan_ip="999.999.999.999")

    with pytest.raises(ValidationError):
        AppConfig(hub_ap_ip="invalid.ip")


def test_appconfig_validation_timeout():
    """Test timeout validation"""
    with pytest.raises(ValidationError):
        AppConfig(timeout_s=0.01)  # Too small

    with pytest.raises(ValidationError):
        AppConfig(timeout_s=20.0)  # Too large


def test_nodeconfig_defaults():
    """Test NodeConfig default values"""
    cfg = NodeConfig()
    assert cfg.threshold == 40.0
    assert cfg.hyst == 2.0
    assert cfg.hold_ms == 5000
    assert cfg.name is None


def test_nodeconfig_validation():
    """Test NodeConfig validation"""
    with pytest.raises(ValidationError):
        NodeConfig(threshold=-1)  # Negative

    with pytest.raises(ValidationError):
        NodeConfig(hyst=-0.5)  # Negative

    with pytest.raises(ValidationError):
        NodeConfig(hold_ms=-100)  # Negative


def test_config_load_save(tmp_path):
    """Test config save and load cycle"""
    cfg_file = tmp_path / "test_config.json"

    # Create config
    cfg = AppConfig(hub_lan_ip="192.168.1.50", udp_port=9999)

    # Save
    save_config(cfg, cfg_file)
    assert cfg_file.exists()

    # Load
    loaded = load_config(cfg_file)
    assert loaded.hub_lan_ip == "192.168.1.50"
    assert loaded.udp_port == 9999


def test_config_backward_compat(tmp_path):
    """Test loading old format config"""
    cfg_file = tmp_path / "old_config.json"

    # Write old format (missing some fields)
    old_data = {
        "hub_lan_ip": "192.168.1.100",
        "udp_port": 7777
    }
    with open(cfg_file, "w") as f:
        json.dump(old_data, f)

    # Load - should fill in defaults for missing fields
    loaded = load_config(cfg_file)
    assert loaded.hub_lan_ip == "192.168.1.100"
    assert loaded.udp_port == 7777
    assert loaded.theme == "darkly"  # Default value


def test_config_invalid_json(tmp_path):
    """Test handling of invalid JSON"""
    cfg_file = tmp_path / "broken_config.json"
    cfg_file.write_text("{invalid json")

    # Should return defaults and create backup
    loaded = load_config(cfg_file)
    assert loaded.hub_lan_ip == "192.168.1.116"  # Default

    # Check if valid JSON was written
    assert cfg_file.exists()
    with open(cfg_file) as f:
        data = json.load(f)  # Should not raise
    assert data["hub_lan_ip"] == "192.168.1.116"


def test_node_config_operations():
    """Test node config get/set operations"""
    cfg = AppConfig()

    # Get non-existent node - should return defaults
    node_cfg = cfg.get_node_config("node1")
    assert node_cfg.threshold == 40.0

    # Set node config
    new_node_cfg = NodeConfig(threshold=50.0, name="Test Node")
    cfg.set_node_config("node1", new_node_cfg)

    # Get back
    retrieved = cfg.get_node_config("node1")
    assert retrieved.threshold == 50.0
    assert retrieved.name == "Test Node"

    # Update specific fields
    cfg.update_node_config("node1", threshold=60.0)
    updated = cfg.get_node_config("node1")
    assert updated.threshold == 60.0
    assert updated.name == "Test Node"  # Preserved


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
