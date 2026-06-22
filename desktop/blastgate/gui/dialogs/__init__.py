"""
GUI dialogs for Blastgate
"""
from .connect import ConnectWindow
from .wifi import WifiWindow
from .node_detail import NodeDetail
from .settings import SettingsWindow
from .calibration import CalibrationWizard
from .setup_wizard import SetupWizard
from .ota import OtaWindow

__all__ = [
    "ConnectWindow",
    "WifiWindow",
    "NodeDetail",
    "SettingsWindow",
    "CalibrationWizard",
    "SetupWizard",
    "OtaWindow",
]