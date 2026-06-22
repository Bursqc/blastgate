"""
Input validation utilities for Blastgate

Validators for:
- IP addresses (IPv4)
- Port numbers
- String sanitization
"""
import logging
import ipaddress
from typing import Optional

logger = logging.getLogger(__name__)


def is_valid_ipv4(ip: str) -> bool:
    """
    Check if string is valid IPv4 address.

    Args:
        ip: IP address string to validate

    Returns:
        True if valid IPv4 address, False otherwise

    Example:
        >>> is_valid_ipv4("192.168.1.1")
        True
        >>> is_valid_ipv4("256.1.1.1")
        False
        >>> is_valid_ipv4("not an ip")
        False
    """
    try:
        ipaddress.IPv4Address(ip)
        return True
    except (ValueError, ipaddress.AddressValueError) as e:
        logger.debug("Invalid IPv4 address '%s': %s", ip, e)
        return False


def is_valid_port(port: int) -> bool:
    """
    Check if port number is valid (1-65535).

    Args:
        port: Port number to validate

    Returns:
        True if valid port number, False otherwise

    Example:
        >>> is_valid_port(8888)
        True
        >>> is_valid_port(0)
        False
        >>> is_valid_port(70000)
        False
    """
    valid = 1 <= port <= 65535
    if not valid:
        logger.debug("Invalid port number: %d (must be 1-65535)", port)
    return valid


def sanitize_node_name(name: str) -> Optional[str]:
    """
    Sanitize node name for protocol compliance.

    Removes/replaces characters that would break UDP protocol:
    - Strips leading/trailing whitespace
    - Replaces spaces with underscores
    - Replaces double quotes with single quotes
    - Returns None if result is empty

    Args:
        name: Node name to sanitize

    Returns:
        Sanitized name string, or None if empty after sanitization

    Example:
        >>> sanitize_node_name("Front Gate")
        'Front_Gate'
        >>> sanitize_node_name('Test "Node"')
        "Test 'Node'"
        >>> sanitize_node_name("   ")
        None
    """
    if not isinstance(name, str):
        logger.warning("sanitize_node_name received non-string: %s", type(name))
        return None

    sanitized = name.strip()

    if not sanitized:
        logger.debug("Node name is empty after strip")
        return None

    # Replace problematic characters
    sanitized = sanitized.replace('"', "'")  # Protocol uses quotes for delimiters
    sanitized = sanitized.replace(" ", "_")  # Spaces break protocol parsing

    if not sanitized:
        logger.debug("Node name is empty after sanitization")
        return None

    logger.debug("Sanitized node name: '%s' -> '%s'", name, sanitized)
    return sanitized
