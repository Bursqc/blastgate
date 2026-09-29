"""
UDP protocol command builders and response parsers

This module provides functions to build UDP command strings and parse responses
from the Blastgate ESP32 Hub. The wire protocol uses simple text-based commands.
"""
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


# Command builders
def build_discover_command() -> bytes:
    """Build DISCOVER broadcast command"""
    return b"DISCOVER"


def build_ping_command() -> bytes:
    """Build PING command"""
    return b"PING"


def build_status_command() -> bytes:
    """Build STATUS command"""
    return b"STATUS"


def build_refresh_command(full: bool = False) -> bytes:
    """
    Build REFRESH command

    Args:
        full: If True, builds REFRESH_FULL command

    Returns:
        Command bytes
    """
    return b"REFRESH_FULL" if full else b"REFRESH"


def build_node_command(node_id: str, gate: str) -> bytes:
    """
    Build NODECMD command for gate control

    Args:
        node_id: Node identifier (e.g., "BG-1F8A3C")
        gate: Gate command ("auto", "open", "close")

    Returns:
        Command bytes

    Example:
        >>> build_node_command("BG-1F8A3C", "open")
        b'NODECMD id=BG-1F8A3C gate=open'
    """
    cmd = f"NODECMD id={node_id} gate={gate}"
    return cmd.encode("utf-8")


def build_relay_command(mode: str) -> bytes:
    """
    Build RELAY command

    Args:
        mode: Relay mode ("on", "off", "auto")

    Returns:
        Command bytes

    Example:
        >>> build_relay_command("on")
        b'RELAY on'
    """
    cmd = f"RELAY {mode}"
    return cmd.encode("utf-8")


def build_node_mode_command(node_id: str, mode: str) -> bytes:
    """
    Build NODEMODE command to set node mode

    Args:
        node_id: Node identifier (e.g., "BG-1F8A3C")
        mode: Mode ("auto", "manual")

    Returns:
        Command bytes

    Example:
        >>> build_node_mode_command("BG-1F8A3C", "manual")
        b'NODEMODE id=BG-1F8A3C mode=manual'
    """
    cmd = f"NODEMODE id={node_id} mode={mode}"
    return cmd.encode("utf-8")


def build_assign_command(node_id: str, name: str) -> bytes:
    """
    Build ASSIGN command for node naming

    Args:
        node_id: Node identifier
        name: New name (spaces will be replaced with underscores)

    Returns:
        Command bytes

    Example:
        >>> build_assign_command("BG-1F8A3C", "Main Gate")
        b'ASSIGN id=BG-1F8A3C name=Main_Gate'
    """
    # Sanitize name
    safe_name = name.strip().replace('"', "'").replace(" ", "_")
    if not safe_name:
        raise ValueError("Name cannot be empty")

    cmd = f"ASSIGN id={node_id} name={safe_name}"
    return cmd.encode("utf-8")


def build_node_config_command(
    node_id: str,
    threshold_on: Optional[float] = None,
    relay_hold_ms: Optional[int] = None,
    gate_hold_ms: Optional[int] = None,
    hbridge_open_ms: Optional[int] = None,
    hbridge_close_ms: Optional[int] = None,
) -> bytes:
    """
    Build NODECFG_SET command for node configuration

    Args:
        node_id: Node identifier
        threshold_on: Threshold value (optional)
        relay_hold_ms: Relay hold time in milliseconds (optional)
        gate_hold_ms: Gate hold time in milliseconds (optional)
        hbridge_open_ms: H-bridge motor open run time in ms (optional)
        hbridge_close_ms: H-bridge motor close run time in ms (optional)

    Returns:
        Command bytes
    """
    parts = [f"NODECFG_SET id={node_id}"]

    if threshold_on is not None:
        parts.append(f"threshold_on={threshold_on}")

    if relay_hold_ms is not None:
        parts.append(f"relay_hold_ms={int(relay_hold_ms)}")

    if gate_hold_ms is not None:
        parts.append(f"gate_hold_ms={int(gate_hold_ms)}")

    if hbridge_open_ms is not None:
        parts.append(f"hbridge_open_ms={int(hbridge_open_ms)}")

    if hbridge_close_ms is not None:
        parts.append(f"hbridge_close_ms={int(hbridge_close_ms)}")

    cmd = " ".join(parts)
    return cmd.encode("utf-8")


def build_node_config_get_command(node_id: str) -> bytes:
    """
    Build NODECFG_GET command to retrieve node configuration

    Args:
        node_id: Node identifier (e.g., "BG-1F8A3C")

    Returns:
        Command bytes

    Example:
        >>> build_node_config_get_command("BG-1F8A3C")
        b'NODECFG_GET id=BG-1F8A3C'
    """
    cmd = f"NODECFG_GET id={node_id}"
    return cmd.encode("utf-8")


def build_wifi_get_command() -> bytes:
    """Build WIFI_GET command"""
    return b"WIFI_GET"


def build_wifi_set_command(ssid: str, password: str) -> bytes:
    """
    Build WIFI_SET command

    Args:
        ssid: WiFi SSID (spaces will be replaced with underscores)
        password: WiFi password (spaces will be replaced with underscores)

    Returns:
        Command bytes

    Raises:
        ValueError: If SSID is empty

    Example:
        >>> build_wifi_set_command("My Network", "password123")
        b'WIFI_SET ssid=My_Network pass=password123'
    """
    ssid = ssid.strip()
    if not ssid:
        raise ValueError("SSID cannot be empty")

    # Sanitize
    ssid_safe = ssid.replace(" ", "_")
    pass_safe = password.replace(" ", "_")

    cmd = f"WIFI_SET ssid={ssid_safe} pass={pass_safe}"
    return cmd.encode("utf-8")


def build_wifi_disconnect_command() -> bytes:
    """Build WIFI_DISCONNECT command"""
    return b"WIFI_DISCONNECT"


def build_wifi_forget_command() -> bytes:
    """Build WIFI_FORGET command"""
    return b"WIFI_FORGET"


def build_wifi_prov_command() -> bytes:
    """Build WIFI_PROV command (start BLE provisioning)"""
    return b"WIFI_PROV"


# Response parsers
def parse_wifi_response(raw: str) -> Dict[str, str]:
    """
    Parse WIFI_GET response

    Args:
        raw: Raw response string

    Returns:
        Dict with WiFi information

    Example:
        >>> parse_wifi_response("WIFI;STA=1;SSID=MyNet;IP=192.168.1.50;RSSI=-45;PROV=0")
        {'raw': '...', 'STA': '1', 'SSID': 'MyNet', 'IP': '192.168.1.50', ...}
    """
    result: Dict[str, str] = {"raw": raw}

    if raw.startswith("WIFI;"):
        parts = raw.split(";")
        for part in parts[1:]:
            if "=" in part:
                key, value = part.split("=", 1)
                result[key.strip()] = value.strip()

    logger.debug("Parsed WiFi response: %s", result)
    return result


def is_error_response(response: str) -> bool:
    """
    Check if response is an error

    Args:
        response: Response string

    Returns:
        True if response starts with "ERR"
    """
    return response.startswith("ERR")


def is_pong_response(response: str) -> bool:
    """
    Check if response is PONG

    Args:
        response: Response string

    Returns:
        True if response is "PONG"
    """
    return response == "PONG"


def is_hub_discover_response(response: str) -> bool:
    """
    Check if response is hub discovery response

    Args:
        response: Response string

    Returns:
        True if response starts with "BLASTGATE_HUB"
    """
    return response.startswith("BLASTGATE_HUB")
