"""„Nova verzija" strips shown above the machines on Pregled."""
from typing import Callable

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

from . import icons
from .theme import c
from .updater import AppUpdater
from .widgets import button, repolish


class UpdateStrip(QFrame):
    def __init__(self, on_action: Callable[[], None], on_later: Callable[[], None]) -> None:
        super().__init__()
        self.setObjectName("Banner")
        self.setProperty("tone", "info")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 10, 8)
        lay.setSpacing(12)
        self.ic = QLabel()
        self.lbl = QLabel()
        self.btn = button("", "download", "primary", on_click=on_action)
        later = button("Kasnije", variant="ghost", on_click=on_later)
        later.setStyleSheet("font-size: 13px;")
        lay.addWidget(self.ic)
        lay.addWidget(self.lbl, 1)
        lay.addWidget(self.btn)
        lay.addWidget(later)
        self.hide()

    def show_state(self, text: str, action: str = "") -> None:
        """[action] is the button text; empty hides the button (e.g. while downloading)."""
        repolish(self)
        self.ic.setPixmap(icons.pixmap("download", c("info"), 22))
        self.lbl.setText(text)
        self.lbl.setStyleSheet(f"color: {c('text')}; font-weight: 600;")
        self.btn.setText(action)
        self.btn.setVisible(bool(action))
        self.show()


def app_strip_state(up: AppUpdater) -> tuple:
    """(visible, text, button text) of the desktop-app strip."""
    if not (up.self_update and up.app_update and not up.app_hidden):
        return False, "", ""
    v = up.release.version
    if up.setup:
        return True, f"Nova verzija aplikacije {v} je spremna.", "Instaliraj i pokreni ponovo"
    if up.downloading:
        return True, f"Preuzimam novu verziju aplikacije {v}… {up.progress} %", ""
    return True, f"Nova verzija aplikacije {v}.", "Preuzmi"


def hub_strip_state(up: AppUpdater) -> tuple:
    """(visible, text, button text) of the hub-firmware strip."""
    if not (up.hub_update and not up.hub_hidden):
        return False, "", ""
    return True, f"Novi firmware za hub {up.firmware.version} (sada {up.hub_version}).", "Ažuriraj hub"
