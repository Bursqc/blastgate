"""
Pydantic models for hub status responses
"""
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict
from .node import NodeStatus


class HubStatus(BaseModel):
    """Complete hub status response"""
    model_config = ConfigDict(extra='ignore')  # tolerate unknown fields from newer firmware

    # Identity / health (added in proto 1.0)
    protoVer: str = "1.0"
    version: Optional[str] = None
    build: Optional[str] = None
    uptime: Optional[int] = None     # seconds since boot
    freeHeap: Optional[int] = None   # bytes

    # Networking
    apIp: Optional[str] = None
    staIp: Optional[str] = None
    sta: int = Field(default=0, ge=0, le=1)
    ethLink: int = Field(default=0, ge=0, le=1)
    ethIp: Optional[str] = None

    # Control state
    manualOverdrive: int = Field(default=0, ge=0, le=1)
    relayState: int = Field(default=0, ge=0, le=1)
    relayMode: int = Field(default=2, ge=0, le=2)  # 0=force_off, 1=force_on, 2=auto

    nodes: List[NodeStatus] = Field(default_factory=list)

    @property
    def is_locked(self) -> bool:
        """MODE 3: Hub manual override active"""
        return self.manualOverdrive == 1

    @property
    def is_relay_on(self) -> bool:
        """Check if relay is on"""
        return self.relayState == 1

    @property
    def online_nodes(self) -> List[NodeStatus]:
        """Get list of online nodes only"""
        return [n for n in self.nodes if n.is_online]

    @property
    def active_nodes(self) -> List[NodeStatus]:
        """Get list of active nodes (online and above threshold)"""
        return [n for n in self.nodes if n.is_online and n.is_active]

    def get_node_by_id(self, node_id: str) -> Optional[NodeStatus]:
        """
        Find node by ID

        Args:
            node_id: Node identifier

        Returns:
            NodeStatus if found, None otherwise
        """
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None


class WifiInfo(BaseModel):
    """WiFi connection information from WIFI_GET response"""
    STA: str = "?"  # Connected status
    SSID: str = ""
    IP: str = ""
    RSSI: str = ""
    PROV: str = "?"  # Provisioning active
    raw: str = ""  # Raw response for debugging

    @property
    def is_connected(self) -> bool:
        """Check if STA is connected"""
        return self.STA.lower() in ("1", "true", "yes", "connected")

    @property
    def is_provisioning(self) -> bool:
        """Check if BLE provisioning is active"""
        return self.PROV.lower() in ("1", "true", "yes", "active")
