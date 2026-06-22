"""
Application constants extracted from esphub.py
"""
import sys
import os
from pathlib import Path

# Application version
APP_VERSION = "2.0.0"

# Application directory — next to the exe when frozen, else gui/ folder
if getattr(sys, 'frozen', False):
    APP_DIR = Path(sys.executable).parent.absolute()
else:
    APP_DIR = Path(__file__).parent.parent.absolute()

# Config file path
CFG_PATH = APP_DIR / "blastgate_gui_config.json"

# Log file path
LOG_PATH = APP_DIR / "logs" / "blastgate.log"

# AP detection interval (seconds) - only re-check AP ping this often
AP_DETECT_INTERVAL_S = 60.0

# Command deduplication window (milliseconds)
DEDUP_WINDOW_MS = 250

# Default poll interval (milliseconds)
DEFAULT_POLL_MS = 650

# Default UDP port
DEFAULT_UDP_PORT = 8888

# Default timeouts
DEFAULT_TIMEOUT_S = 1.2
DEFAULT_DISCOVERY_TIMEOUT_S = 2.0

# Default network settings
DEFAULT_HUB_LAN_IP = "192.168.1.116"
DEFAULT_HUB_AP_IP = "192.168.4.1"

# Default UI settings
DEFAULT_THEME = "darkly"
DEFAULT_UI_SCALE = 1.30

# Default node configuration
DEFAULT_NODE_THRESHOLD = 40.0
DEFAULT_NODE_HYSTERESIS = 2.0
DEFAULT_NODE_HOLD_MS = 5000
DEFAULT_NODE_SERVO_DELAY_MS = 0
DEFAULT_NODE_DEBOUNCE_MS = 150

# App modes
MODE_AUTO = "AUTO"
MODE_MANUAL = "MANUAL"

# Gate commands
GATE_AUTO = "auto"
GATE_OPEN = "open"
GATE_CLOSE = "close"

# Relay commands
RELAY_ON = "on"
RELAY_OFF = "off"
RELAY_AUTO = "auto"

# UDP commands
CMD_DISCOVER = "DISCOVER"
CMD_PING = "PING"
CMD_STATUS = "STATUS"
CMD_REFRESH = "REFRESH"
CMD_REFRESH_FULL = "REFRESH_FULL"
CMD_NODECMD = "NODECMD"
CMD_RELAY = "RELAY"
CMD_ASSIGN = "ASSIGN"
CMD_NODECFG_SET = "NODECFG_SET"
CMD_WIFI_GET = "WIFI_GET"
CMD_WIFI_SET = "WIFI_SET"
CMD_WIFI_DISCONNECT = "WIFI_DISCONNECT"
CMD_WIFI_FORGET = "WIFI_FORGET"
CMD_WIFI_PROV = "WIFI_PROV"

# Response prefixes
RESP_PONG = "PONG"
RESP_BLASTGATE_HUB = "BLASTGATE_HUB"
RESP_ERROR = "ERR"
RESP_WIFI = "WIFI"
