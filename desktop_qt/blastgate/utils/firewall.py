"""
Windows Firewall helper - checks and fixes UDP 8888 rule for Blastgate.
Called once on startup if hub is not found.
"""
import ctypes
import logging
import platform
import subprocess
import sys

logger = logging.getLogger(__name__)

RULE_NAME = "Blastgate UDP 8888"
UDP_PORT  = 8888


def _is_windows() -> bool:
    return platform.system() == "Windows"


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def firewall_rule_exists() -> bool:
    """Return True if our inbound UDP rule already exists."""
    if not _is_windows():
        return True  # non-Windows: assume OK
    try:
        result = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule", f"name={RULE_NAME}"],
            capture_output=True, text=True, timeout=5
        )
        return "No rules match" not in result.stdout and result.returncode == 0
    except Exception as e:
        logger.debug("Firewall rule check failed: %s", e)
        return False


def _add_rule_direct() -> bool:
    """Add firewall rule (already running as admin)."""
    try:
        r = subprocess.run([
            "netsh", "advfirewall", "firewall", "add", "rule",
            f"name={RULE_NAME}",
            "protocol=UDP",
            "dir=in",
            f"localport={UDP_PORT}",
            "action=allow",
            "enable=yes",
        ], capture_output=True, text=True, timeout=10)
        ok = r.returncode == 0
        logger.info("Firewall rule add: %s", "OK" if ok else r.stdout.strip())
        return ok
    except Exception as e:
        logger.warning("Firewall rule add failed: %s", e)
        return False


def _add_rule_elevated() -> None:
    """Re-run just the netsh command with UAC elevation (ShellExecuteW runas)."""
    cmd = (
        f'advfirewall firewall add rule name="{RULE_NAME}" '
        f"protocol=UDP dir=in localport={UDP_PORT} action=allow enable=yes"
    )
    try:
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", "netsh", cmd, None, 1  # 1 = SW_SHOWNORMAL
        )
        logger.info("Firewall elevation requested")
    except Exception as e:
        logger.warning("Firewall elevation failed: %s", e)


def ensure_firewall_rule() -> bool:
    """
    Check if inbound UDP 8888 rule exists.
    If not:
      - If already admin: add directly.
      - If not admin:     elevate and add (UAC prompt).
    Returns True if rule already existed or was added successfully.
    """
    if not _is_windows():
        return True

    if firewall_rule_exists():
        logger.debug("Firewall rule already present")
        return True

    logger.info("Firewall rule missing - adding...")
    if _is_admin():
        return _add_rule_direct()
    else:
        _add_rule_elevated()
        return False  # can't verify immediately (runs in separate process)
