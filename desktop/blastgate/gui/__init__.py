"""
GUI components for Blastgate application

This package provides the tkinter-based graphical interface:
- utils: UI scaling, window centering, color manipulation, canvas drawing
- components: Reusable widgets (RoundedTile)
- dialogs: Toplevel windows (Connect, WiFi, NodeDetail)
- app: Main application window

Example:
    >>> from blastgate.gui import App
    >>> app = App()
    >>> app.mainloop()
"""

from .app import App
from . import utils
from . import components
from . import dialogs

__all__ = [
    "App",
    "utils",
    "components",
    "dialogs",
]
