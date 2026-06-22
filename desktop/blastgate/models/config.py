"""
Pydantic models for application configuration
"""
from typing import Dict, Optional, Any
from pydantic import BaseModel, Field, field_validator, ConfigDict
import ipaddress


class NodeConfig(BaseModel):
    """Per-node configuration stored in config file"""
    model_config = ConfigDict(validate_assignment=True, extra='allow')

    threshold: float = 40.0
    hyst: float = 2.0
    hold_ms: int = 5000
    servo_delay_ms: int = 0
    debounce_ms: int = 150
    hbridge_open_ms: int = 2000   # H-bridge motor open run time (ms)
    hbridge_close_ms: int = 2000  # H-bridge motor close run time (ms)
    name: Optional[str] = None  # Local override for display name

    @field_validator('threshold', 'hyst')
    @classmethod
    def positive_float(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Must be positive")
        return v

    @field_validator('hold_ms', 'servo_delay_ms', 'debounce_ms', 'hbridge_open_ms', 'hbridge_close_ms')
    @classmethod
    def non_negative_int(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Must be non-negative")
        return v


class AppConfig(BaseModel):
    """Application configuration (blastgate_gui_config.json)"""
    model_config = ConfigDict(validate_assignment=True, extra='ignore')

    hub_lan_ip: str = "192.168.1.116"
    hub_ap_ip: str = "192.168.4.1"
    udp_port: int = Field(default=8888, ge=1, le=65535)

    poll_ms: int = Field(default=650, ge=100)
    timeout_s: float = Field(default=1.2, ge=0.1, le=10.0)
    discovery_timeout_s: float = Field(default=2.0, ge=0.3, le=30.0)

    theme: str = "darkly"
    preferred_hub_ip: str = ""
    auto_ap_detect: bool = True
    ui_scale: float = Field(default=1.30, ge=0.5, le=3.0)

    # OTA — where to look for new firmware. Default = GitHub Releases manifest.
    # Change this if you self-host releases.
    ota_manifest_url: str = "https://raw.githubusercontent.com/Bursqc/blastgate/main/releases/manifest.json"
    ota_token: str = "blastgate-change-me"     # must match hub's stored token
    ota_auto_check_s: int = Field(default=3600, ge=0)  # 0 = disable auto-check

    nodes: Dict[str, Any] = Field(default_factory=dict)

    @field_validator('hub_lan_ip', 'hub_ap_ip')
    @classmethod
    def validate_ip(cls, v: str) -> str:
        if v:  # Allow empty string
            try:
                ipaddress.IPv4Address(v)
            except ValueError:
                raise ValueError(f"Invalid IPv4 address: {v}")
        return v

    @field_validator('preferred_hub_ip')
    @classmethod
    def validate_preferred_ip(cls, v: str) -> str:
        if v and v.strip():
            try:
                ipaddress.IPv4Address(v.strip())
            except ValueError:
                raise ValueError(f"Invalid IPv4 address: {v}")
        return v.strip() if v else ""

    def get_node_config(self, node_id: str) -> NodeConfig:
        """
        Get configuration for specific node with defaults

        Args:
            node_id: Node identifier

        Returns:
            NodeConfig instance with node-specific or default values
        """
        node_data = self.nodes.get(node_id, {})
        if isinstance(node_data, dict):
            return NodeConfig(**node_data)
        return NodeConfig()

    def set_node_config(self, node_id: str, config: NodeConfig) -> None:
        """
        Set configuration for specific node

        Args:
            node_id: Node identifier
            config: NodeConfig instance
        """
        self.nodes[node_id] = config.model_dump()

    def update_node_config(self, node_id: str, **kwargs: Any) -> None:
        """
        Update specific fields of node configuration

        Args:
            node_id: Node identifier
            **kwargs: Fields to update
        """
        current = self.get_node_config(node_id)
        updated = current.model_copy(update=kwargs)
        self.set_node_config(node_id, updated)
