"""
Helper utility functions for Blastgate

Generic helper functions:
- Type conversions (to_float, to_int)
- Time utilities (now_ms)
- Data extraction (safe_node_id)
"""
import logging
import time
from typing import Any, Dict

logger = logging.getLogger(__name__)


def to_float(s: str, default: float = 0.0) -> float:
    """
    Convert string to float with fallback.

    Handles comma decimal separators and strips whitespace.

    Args:
        s: String to convert
        default: Default value if conversion fails

    Returns:
        Converted float or default value

    Example:
        >>> to_float("3.14", 0.0)
        3.14
        >>> to_float("2,5", 0.0)
        2.5
        >>> to_float("invalid", 10.0)
        10.0
    """
    try:
        return float(str(s).replace(",", ".").strip())
    except (ValueError, AttributeError) as e:
        logger.debug("Failed to convert '%s' to float: %s (using default %.2f)", s, e, default)
        return default


def to_int(s: str, default: int = 0) -> int:
    """
    Convert string to int with fallback.

    Handles comma decimal separators, strips whitespace, and converts via float first.

    Args:
        s: String to convert
        default: Default value if conversion fails

    Returns:
        Converted int or default value

    Example:
        >>> to_int("42", 0)
        42
        >>> to_int("3.7", 0)
        3
        >>> to_int("invalid", 100)
        100
    """
    try:
        return int(float(str(s).replace(",", ".").strip()))
    except (ValueError, AttributeError) as e:
        logger.debug("Failed to convert '%s' to int: %s (using default %d)", s, e, default)
        return default


def now_ms() -> int:
    """
    Get current time in milliseconds since epoch.

    Returns:
        Current timestamp in milliseconds

    Example:
        >>> ts = now_ms()
        >>> print(f"Current time: {ts}ms")
    """
    return int(time.time() * 1000)


def safe_node_id(node: Dict[str, Any]) -> str:
    """
    Extract node ID from node dict with fallback.

    Args:
        node: Node dictionary (expects "id" key)

    Returns:
        Node ID string (stripped), empty string if not found

    Example:
        >>> safe_node_id({"id": "BG-123ABC"})
        'BG-123ABC'
        >>> safe_node_id({"name": "Test"})
        ''
    """
    return (node.get("id") or "").strip()
