"""
User-friendly error messages and troubleshooting
"""
from typing import Dict, List, Optional


class ErrorInfo:
    """Information about an error with user-friendly message and solutions"""
    def __init__(self, title: str, message: str, solutions: List[str], help_url: Optional[str] = None):
        self.title = title
        self.message = message
        self.solutions = solutions
        self.help_url = help_url


# Error database with user-friendly messages
ERROR_DATABASE: Dict[str, ErrorInfo] = {
    # Connection errors
    "hub_offline": ErrorInfo(
        title="Hub Not Responding",
        message="Cannot connect to the Blastgate hub",
        solutions=[
            "Check if hub is powered on",
            "Verify network connection (WiFi/Ethernet)",
            "Try connecting to hub's AP: BLASTGATE_HUB",
            "Check hub IP address (default: 192.168.4.1)",
            "Restart the hub and try again"
        ]
    ),

    "connection_timeout": ErrorInfo(
        title="Connection Timeout",
        message="Hub is not responding to requests",
        solutions=[
            "Check network connection",
            "Verify hub IP address",
            "Check if firewall is blocking UDP port 8888",
            "Restart the hub",
            "Try manual IP: 192.168.4.1"
        ]
    ),

    "discovery_failed": ErrorInfo(
        title="Hub Discovery Failed",
        message="Cannot find any Blastgate hubs on the network",
        solutions=[
            "Make sure hub is powered on",
            "Check WiFi connection (connect to BLASTGATE_HUB)",
            "Verify you're on the same network as hub",
            "Try manual connection with IP: 192.168.4.1",
            "Restart hub and try discovery again"
        ]
    ),

    # Node errors
    "node_offline": ErrorInfo(
        title="Node Offline",
        message="The node has stopped responding",
        solutions=[
            "Check node power supply",
            "Verify node is within WiFi range",
            "Check WiFi signal strength",
            "Reset the node (power cycle)",
            "Check sensor connections"
        ]
    ),

    "node_timeout": ErrorInfo(
        title="Node Communication Error",
        message="Node is not responding to commands",
        solutions=[
            "Check WiFi signal strength (-70 dBm or better)",
            "Move node closer to hub or WiFi access point",
            "Reset the node",
            "Check for interference (other 2.4GHz devices)",
            "Verify node firmware is up to date"
        ]
    ),

    "node_active_override": ErrorInfo(
        title="Cannot Override Active Node",
        message="Cannot manually control gate while sensor is active",
        solutions=[
            "Turn off the machine first",
            "Wait for sensor reading to drop below threshold",
            "Override will be applied when machine turns off",
            "This is a safety feature to prevent gate closing on running machine"
        ]
    ),

    # Configuration errors
    "config_error": ErrorInfo(
        title="Configuration Error",
        message="Invalid configuration values",
        solutions=[
            "Check threshold value (typical: 30-50)",
            "Verify hold time is reasonable (3000-10000 ms)",
            "Use 'Auto-Calibrate' to find correct threshold",
            "Reset to default values if unsure"
        ]
    ),

    "invalid_threshold": ErrorInfo(
        title="Invalid Threshold Value",
        message="Threshold value is out of acceptable range",
        solutions=[
            "Threshold should be between 5 and 200",
            "Use 'Auto-Calibrate' to find optimal value",
            "Typical values: 30-50 for most machines",
            "Check sensor installation if readings are unusual"
        ]
    ),

    # WiFi errors
    "wifi_error": ErrorInfo(
        title="WiFi Connection Error",
        message="Cannot connect hub to WiFi network",
        solutions=[
            "Verify WiFi password is correct",
            "Check if network is 2.4GHz (5GHz not supported)",
            "Make sure network is within range",
            "Try BLE provisioning from mobile app",
            "Check if MAC filtering is enabled on router"
        ]
    ),

    "wifi_weak_signal": ErrorInfo(
        title="Weak WiFi Signal",
        message="WiFi signal strength is poor",
        solutions=[
            "Move hub/node closer to WiFi router",
            "Remove obstacles between device and router",
            "Check antenna connection (if external)",
            "Consider using Ethernet connection (hub only)",
            "Add WiFi extender if needed"
        ]
    ),

    # System errors
    "low_memory": ErrorInfo(
        title="Low Memory Warning",
        message="Device is running low on free memory",
        solutions=[
            "Restart the device to free memory",
            "Reduce number of active nodes if possible",
            "This may indicate a memory leak - report to developer",
            "Consider firmware update if available"
        ]
    ),

    "crash_detected": ErrorInfo(
        title="Device Crash Detected",
        message="Device has restarted unexpectedly",
        solutions=[
            "Check power supply (stable 5V required)",
            "Verify all connections are secure",
            "Check for overheating",
            "Review crash logs if available",
            "Contact support if crashes persist"
        ]
    ),

    # Sensor errors
    "sensor_error": ErrorInfo(
        title="Sensor Reading Error",
        message="Sensor is providing invalid or erratic readings",
        solutions=[
            "Check SCT-013 sensor connection",
            "Verify sensor is clamped around single wire",
            "Check for loose connections at GPIO 34",
            "Ensure wire is properly centered in sensor clamp",
            "Try sensor calibration or offset adjustment"
        ]
    ),

    "sensor_spike": ErrorInfo(
        title="Sensor Spike Detected",
        message="Sensor reading jumped unexpectedly",
        solutions=[
            "This is usually caused by servo motor current draw",
            "Spike detection is active - reading ignored",
            "If persistent, check sensor installation",
            "Ensure servo and sensor have separate power if possible",
            "Contact support if issue persists"
        ]
    ),

    # General errors
    "unknown_error": ErrorInfo(
        title="Unknown Error",
        message="An unexpected error occurred",
        solutions=[
            "Try the operation again",
            "Restart the application",
            "Check application logs for details",
            "Contact support with error details"
        ]
    ),

    "permission_denied": ErrorInfo(
        title="Operation Blocked",
        message="Operation not allowed in current state",
        solutions=[
            "Check if manual overdrive is active on hub",
            "Verify hub is not in lockout mode",
            "Ensure node is in correct mode (AUTO/MANUAL)",
            "Wait a moment and try again"
        ]
    ),
}


def get_error_info(error_key: str) -> ErrorInfo:
    """Get error information by key, returns unknown_error if not found"""
    return ERROR_DATABASE.get(error_key, ERROR_DATABASE["unknown_error"])


def format_error_message(error_key: str, details: Optional[str] = None) -> str:
    """Format a complete error message with solutions"""
    info = get_error_info(error_key)

    msg = f"❌ {info.title}\n\n"
    msg += f"{info.message}\n\n"

    if details:
        msg += f"Details: {details}\n\n"

    msg += "Troubleshooting:\n"
    for i, solution in enumerate(info.solutions, 1):
        msg += f"  {i}. {solution}\n"

    return msg


def parse_hub_error(error_str: str) -> str:
    """Parse hub error response and return appropriate error key"""
    error_lower = error_str.lower()

    # Map hub error strings to error keys
    if "unknown id" in error_lower or "no slots" in error_lower:
        return "node_offline"
    elif "manual_overdrive" in error_lower or "lockout" in error_lower:
        return "permission_denied"
    elif "node_active" in error_lower:
        return "node_active_override"
    elif "wifi" in error_lower:
        return "wifi_error"
    elif "timeout" in error_lower:
        return "connection_timeout"
    elif "blocked" in error_lower:
        return "permission_denied"
    else:
        return "unknown_error"
