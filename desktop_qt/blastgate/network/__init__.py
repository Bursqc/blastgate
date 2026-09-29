"""
Network communication layer for Blastgate

This package provides UDP communication with ESP32 hubs:
- HubClientUDP: Direct UDP communication
- NetEngine: Background thread for non-blocking operations
- protocol: Command builders and response parsers
- discovery: Hub discovery via broadcast

Example:
    >>> from blastgate.network import HubClientUDP, NetEngine
    >>> from blastgate.config import load_config
    >>>
    >>> config = load_config()
    >>> client = HubClientUDP(config)
    >>> engine = NetEngine(client, config, app.after)
    >>> engine.start()
"""

from .client import HubClientUDP
from .engine import NetEngine
from .discovery import discover_hubs, discover_single
from . import protocol

__all__ = [
    "HubClientUDP",
    "NetEngine",
    "discover_hubs",
    "discover_single",
    "protocol",
]
