"""Main window: sidebar + pages (Pregled / Sistem / Događaji / Podešavanja)."""
import logging
import platform
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QButtonGroup, QHBoxLayout, QInputDialog, QMainWindow,
                               QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from ..config import save_config
from . import icons
from .controller import Controller
from .events_page import EventsPage
from .node_dialog import NodeDialog
from .overview_page import OverviewPage
from .theme import c, palette, qss, set_current
from .updater import AppUpdater
from .widgets import label

logger = logging.getLogger(__name__)

NAV = [("Pregled", "home"), ("Sistem", "list-details"), ("Događaji", "bell"), ("Podešavanja", "settings")]


def apply_theme(app: QApplication, cfg) -> None:
    name = "light" if cfg.theme == "light" else "dark"
    p = palette(name)
    set_current(p)
    app.setStyleSheet(qss(p, cfg.ui_zoom))


class MainWindow(QMainWindow):
    def __init__(self, ctl: Controller) -> None:
        super().__init__()
        self.ctl = ctl
        self._dialogs: Dict[str, NodeDialog] = {}
        self.setWindowTitle("Blastgate — nadzor zatvarača" + ("  [DEMO]" if ctl.demo_hub else ""))
        self.setWindowIcon(icons.icon("gate-open", "#22d3ee", 64))
        self.resize(1600, 940)

        root = QWidget()
        root.setObjectName("Root")
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.setCentralWidget(root)

        side = QWidget()
        side.setObjectName("Sidebar")
        side.setFixedWidth(236)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 18, 0, 18)
        sl.setSpacing(4)
        brand = QHBoxLayout()
        brand.setContentsMargins(22, 0, 0, 18)
        self.brand_icon = label()
        brand.addWidget(self.brand_icon)
        brand.addWidget(label("BLASTGATE", "AppTitle"))
        brand.addStretch(1)
        sl.addLayout(brand)

        self.updater = AppUpdater(ctl)
        self.stack = QStackedWidget()
        self.overview = OverviewPage(ctl, self.updater)
        self.overview.open_node.connect(self.open_node)
        self.overview.node_action.connect(self._node_action)
        self.overview.open_hub_update.connect(self._open_hub_update)
        self.system = self._lazy_system()
        self.pages: List[QWidget] = [self.overview, self.system, EventsPage(ctl), self._lazy_settings()]
        for p in self.pages:
            self.stack.addWidget(p)

        self.nav_group = QButtonGroup(self)
        self.nav_buttons: List[QPushButton] = []
        for i, (text, icon_name) in enumerate(NAV):
            b = QPushButton(f"  {text}")
            b.setObjectName("NavButton")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setIconSize(icons.qsize(24))
            b.clicked.connect(lambda _=False, idx=i: self.show_page(idx))
            self.nav_group.addButton(b, i)
            self.nav_buttons.append(b)
            sl.addWidget(b)
        sl.addStretch(1)

        if ctl.demo_hub:
            sl.addWidget(label("  DEMO — lažni hub", "Small"))
            for text, fn in (("Ručni režim huba", ctl.demo_hub.toggle_overdrive),
                             ("Prekini / vrati vezu", lambda: ctl.demo_hub.set_lost(not ctl.demo_hub.lost))):
                b = QPushButton(text)
                b.setObjectName("NavButton")
                b.setStyleSheet("font-size: 13px; padding: 8px 18px;")
                b.clicked.connect(fn)
                sl.addWidget(b)

        lay.addWidget(side)
        lay.addWidget(self.stack, 1)
        self.refresh_icons()
        self.show_page(0)

        ctl.start()
        self.updater.start()
        if not ctl.demo_hub:
            QTimer.singleShot(1000, self._auto_discover_on_start)
            QTimer.singleShot(5000, self._check_firewall_once)

    # the Sistem / Podešavanja pages import lazily to keep startup simple
    def _lazy_system(self) -> QWidget:
        from .system_page import SystemPage
        return SystemPage(self.ctl, self.updater)

    def _lazy_settings(self) -> QWidget:
        from .settings_page import SettingsPage
        page = SettingsPage(self.ctl)
        page.appearance_changed.connect(self.reapply_theme)
        return page

    def refresh_icons(self) -> None:
        self.brand_icon.setPixmap(icons.pixmap("layout-grid", c("accent"), 26))
        for i, b in enumerate(self.nav_buttons):
            b.setIcon(icons.icon(NAV[i][1], c("accent") if b.isChecked() else c("muted"), 24))

    def _open_hub_update(self) -> None:
        self.show_page(1)
        self.system.show_updates()

    def show_page(self, idx: int) -> None:
        self.stack.setCurrentIndex(idx)
        self.nav_buttons[idx].setChecked(True)
        self.refresh_icons()

    def reapply_theme(self) -> None:
        apply_theme(QApplication.instance(), self.ctl.cfg)
        self.refresh_icons()
        self.ctl.status_changed.emit(self.ctl.status, self.ctl.state)   # repaint custom colors

    # ------------------------------------------------------------- nodes
    def open_node(self, node_id: str) -> Optional[NodeDialog]:
        dlg = self._dialogs.get(node_id)
        if dlg and dlg.isVisible():
            dlg.raise_()
            dlg.activateWindow()
            return dlg
        dlg = NodeDialog(self.ctl, node_id, self)
        dlg.finished.connect(lambda _r, nid=node_id: self._dialogs.pop(nid, None))
        self._dialogs[node_id] = dlg
        dlg.show()
        return dlg

    def _node_action(self, action: str, node_id: str) -> None:
        if action == "rename":
            n = self.ctl.node(node_id) or {}
            name, ok = QInputDialog.getText(self, "Preimenuj mašinu", f"Novo ime za {node_id}:",
                                            text=(n.get("name") or "").strip())
            if ok and name.strip():
                self.ctl.send("rename", node_id, name.strip(), log=f"{node_id}: novo ime „{name.strip()}”",
                              on_err=lambda e: QMessageBox.warning(self, "Preimenovanje", str(e)))
        elif action == "calibrate":
            dlg = self.open_node(node_id)
            if dlg:
                dlg._calibrate()

    # ----------------------------------------------------- startup helpers
    def _auto_discover_on_start(self) -> None:
        """Same as the old app: if exactly one hub answers and none is configured, use it."""
        if self.ctl.status:
            return

        def found(hubs) -> None:
            if len(hubs) == 1 and not self.ctl.cfg.preferred_hub_ip.strip():
                ip = hubs[0]["ip"]
                self.ctl.cfg.preferred_hub_ip = ip
                self.ctl.client.selected_ip = ip
                self.ctl.client.best_ip = None
                save_config(self.ctl.cfg)
                self.ctl.add_event("success", f"Hub pronađen: {ip}")
            elif len(hubs) > 1:
                self.ctl.add_event("warning", "Pronađeno više hubova: " + ", ".join(h["ip"] for h in hubs)
                                   + " — izaberi u Podešavanjima")
        self.ctl.run_bg(self.ctl.client.discover_hubs, found)

    def _check_firewall_once(self) -> None:
        if platform.system() != "Windows" or self.ctl.status:
            return
        from ..utils.firewall import ensure_firewall_rule, firewall_rule_exists
        if firewall_rule_exists():
            return
        if QMessageBox.question(self, "Windows Firewall",
                                "Hub nije pronađen.\n\nWindows Firewall verovatno blokira UDP port 8888.\n\n"
                                "Dodati izuzetak automatski? (traži Admin prava — pojaviće se UAC prozor)"
                                ) == QMessageBox.Yes:
            ensure_firewall_rule()
            QMessageBox.information(self, "Firewall", "Pravilo dodato. Program će naći hub za nekoliko sekundi.")

    def closeEvent(self, e) -> None:  # noqa: N802
        self.ctl.stop()
        super().closeEvent(e)
