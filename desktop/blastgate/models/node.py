"""
Pydantic models for node data
"""
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class NodeStatus(BaseModel):
    """Node status from hub STATUS response"""
    model_config = ConfigDict(extra='ignore')  # tolerate unknown fields from newer firmware

    id: str
    name: Optional[str] = None
    ip: Optional[str] = None
    port: Optional[int] = None
    online: int = Field(ge=0, le=1)
    active: int = Field(ge=0, le=1)
    value: Optional[float] = None
    override: int = Field(default=0, ge=0, le=2)  # 0=AUTO, 1=OPEN, 2=CLOSE
    mode: int = Field(default=0, ge=0, le=1)     # 0=AUTO, 1=MANUAL
    gateOpen: Optional[int] = Field(default=None, ge=0, le=1)

    # Liveness / scheduling (added in proto 1.0)
    ageMs: Optional[int] = None
    closeInMs: Optional[int] = None

    # Per-node config (added in proto 1.0 — hub used to send only in STATUS, now also here)
    threshold_on: Optional[float] = None
    relay_hold_ms: Optional[int] = None
    gate_hold_ms: Optional[int] = None
    hbridge_open_ms: Optional[int] = None
    hbridge_close_ms: Optional[int] = None

    @property
    def is_online(self) -> bool:
        """Check if node is online"""
        return self.online == 1

    @property
    def is_active(self) -> bool:
        """Check if node is active (above threshold)"""
        return self.active == 1

    @property
    def is_gate_open(self) -> bool:
        """Check if gate is open"""
        if self.gateOpen is not None:
            return self.gateOpen == 1
        return self.override == 1  # Fallback to override

    @property
    def gate_state_str(self) -> str:
        """Get human-readable gate state"""
        return "OPEN" if self.is_gate_open else "CLOSED"

    @property
    def override_command_str(self) -> str:
        """Get human-readable override command"""
        return {0: "AUTO", 1: "OPEN", 2: "CLOSE"}.get(self.override, str(self.override))
