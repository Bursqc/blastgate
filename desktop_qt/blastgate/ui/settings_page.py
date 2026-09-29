"""Podešavanja — connection, polling, appearance, OTA, backup/restore (app settings only)."""
import json
from datetime import datetime

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QGridLayout, QHBoxLayout,
                               QLineEdit, QMessageBox, QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from ..config import save_config
from ..models.config import AppConfig
from . import icons
from .controller import Controller
from .theme import c
from .widgets import Banner, Card, StatusLabel, button, label


def _card(title: str) -> (Card, QVBoxLayout):
    card = Card()
    lay = QVBoxLayout(card)
    lay.setContentsMargins(20, 14, 20, 16)
    lay.setSpacing(10)
    head = QHBoxLayout()
    head.addWidget(label(title, "SectionTitle"))
    head.addStretch(1)
    lay.addLayout(head)
    return card, lay


class SettingsPage(QWidget):
    appearance_changed = Signal()

    def __init__(self, ctl: Controller) -> None:
        super().__init__()
        self.ctl = ctl
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 26, 32, 18)
        root.setSpacing(14)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label("Podešavanja", "PageTitle"))
        titles.addWidget(label("Veza sa hubom, osvežavanje i izgled aplikacije. "
                               "Podešavanja mašina su u prozoru svake mašine.", "PageSubtitle"))
        root.addLayout(titles)

        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(0, 0, 6, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)

        # --- connection -------------------------------------------------------
        card, cl = _card("Veza sa hubom")
        self.conn_state = StatusLabel()
        cl.itemAt(0).layout().addWidget(self.conn_state)
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        self.ed_ip = QLineEdit()
        self.ed_ip.setPlaceholderText("npr. 192.168.1.50 (prazno = automatski)")
        self.ed_ap = QLineEdit()
        self.sp_port = QSpinBox()
        self.sp_port.setRange(1, 65535)
        self.chk_ap = QCheckBox("Automatski prepoznaj WiFi huba (BLASTGATE_HUB)")
        g.addWidget(label("IP adresa huba", "Muted"), 0, 0)
        g.addWidget(self.ed_ip, 0, 1)
        g.addWidget(label("UDP port", "Muted"), 0, 2)
        g.addWidget(self.sp_port, 0, 3)
        g.addWidget(label("IP huba na njegovom WiFi-ju", "Muted"), 1, 0)
        g.addWidget(self.ed_ap, 1, 1)
        g.addWidget(self.chk_ap, 2, 0, 1, 4)
        g.setColumnStretch(1, 1)
        cl.addLayout(g)
        row = QHBoxLayout()
        row.addWidget(button("Testiraj vezu", "link", "outline", on_click=self._test))
        row.addWidget(button("Pronađi hubove", "search", on_click=self._scan))
        self.cb_found = QComboBox()
        self.cb_found.setMinimumWidth(170)
        self.cb_found.setPlaceholderText("pronađeni hubovi")
        row.addWidget(self.cb_found)
        row.addWidget(button("Koristi", on_click=self._use_found))
        row.addStretch(1)
        cl.addLayout(row)
        self.conn_msg = Banner()
        cl.addWidget(self.conn_msg)
        grid.addWidget(card, 0, 0)

        # --- polling ----------------------------------------------------------
        card, cl = _card("Osvežavanje")
        g = QGridLayout()
        self.sp_poll = QSpinBox()
        self.sp_poll.setRange(100, 10000)
        self.sp_poll.setSingleStep(50)
        self.sp_poll.setSuffix(" ms")
        self.sp_timeout = QDoubleSpinBox()
        self.sp_timeout.setRange(0.1, 10.0)
        self.sp_timeout.setSingleStep(0.1)
        self.sp_timeout.setSuffix(" s")
        g.addWidget(label("Interval osvežavanja", "Muted"), 0, 0)
        g.addWidget(self.sp_poll, 0, 1)
        g.addWidget(label("Čekanje odgovora", "Muted"), 1, 0)
        g.addWidget(self.sp_timeout, 1, 1)
        g.setColumnStretch(2, 1)
        cl.addLayout(g)
        cl.addWidget(label("Hub keš statusa je 300 ms; kraće od toga nema smisla. "
                           "Na HUB_UPDATE poruku aplikacija osvežava odmah.", "Small", wrap=True))
        cl.addStretch(1)
        grid.addWidget(card, 0, 1)

        # --- appearance -------------------------------------------------------
        card, cl = _card("Interfejs")
        g = QGridLayout()
        self.cb_theme = QComboBox()
        self.cb_theme.addItems(["Tamna", "Svetla"])
        self.cb_zoom = QComboBox()
        self.zooms = [0.9, 1.0, 1.1, 1.25, 1.4]
        self.cb_zoom.addItems([f"{int(z * 100)} %" for z in self.zooms])
        self.chk_offline = QCheckBox("Prikaži mašine koje su van mreže")
        g.addWidget(label("Tema", "Muted"), 0, 0)
        g.addWidget(self.cb_theme, 0, 1)
        g.addWidget(label("Veličina teksta", "Muted"), 0, 2)
        g.addWidget(self.cb_zoom, 0, 3)
        g.addWidget(self.chk_offline, 1, 0, 1, 4)
        g.setColumnStretch(4, 1)
        cl.addLayout(g)
        grid.addWidget(card, 1, 0)

        # --- OTA --------------------------------------------------------------
        card, cl = _card("Firmware (OTA)")
        g = QGridLayout()
        self.ed_manifest = QLineEdit()
        self.ed_token = QLineEdit()
        self.ed_token.setEchoMode(QLineEdit.Password)
        g.addWidget(label("Manifest URL", "Muted"), 0, 0)
        g.addWidget(self.ed_manifest, 0, 1)
        g.addWidget(label("OTA token huba", "Muted"), 1, 0)
        g.addWidget(self.ed_token, 1, 1)
        g.setColumnStretch(1, 1)
        cl.addLayout(g)
        cl.addWidget(label("Proverava se ručno u Sistem → Firmware huba.", "Small"))
        grid.addWidget(card, 1, 1)

        # --- backup -----------------------------------------------------------
        card, cl = _card("Rezervna kopija")
        cl.addWidget(label("Čuva imena, pragove i vremena svih mašina sa huba + podešavanja aplikacije. "
                           "Vraćanje šalje sačuvane vrednosti nazad hubu.", "Muted", wrap=True))
        row = QHBoxLayout()
        row.addWidget(button("Sačuvaj kopiju", "download", "outline", on_click=self._backup))
        row.addWidget(button("Vrati iz kopije", "upload", on_click=self._restore))
        row.addStretch(1)
        cl.addLayout(row)
        grid.addWidget(card, 2, 0, 1, 2)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        grid.setRowStretch(3, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        foot = Card()
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(18, 10, 18, 10)
        self.dirty_icon = label()
        self.dirty_lbl = label("")
        fl.addWidget(self.dirty_icon)
        fl.addWidget(self.dirty_lbl)
        fl.addStretch(1)
        fl.addWidget(button("Vrati podrazumevano", "rotate-clockwise", on_click=self._defaults))
        fl.addWidget(button("Otkaži", on_click=self._load))
        fl.addWidget(button("Sačuvaj podešavanja", "device-floppy", "primary", on_click=self._save))
        root.addWidget(foot)

        self._load()
        for w in (self.ed_ip, self.ed_ap, self.ed_manifest, self.ed_token):
            w.textChanged.connect(self._mark_dirty)
        for w in (self.sp_port, self.sp_poll):
            w.valueChanged.connect(self._mark_dirty)
        self.sp_timeout.valueChanged.connect(self._mark_dirty)
        for w in (self.chk_ap, self.chk_offline):
            w.toggled.connect(self._mark_dirty)
        for w in (self.cb_theme, self.cb_zoom):
            w.currentIndexChanged.connect(self._mark_dirty)
        ctl.status_changed.connect(self._on_status)
        self._on_status(ctl.status, ctl.state)

    # ------------------------------------------------------------ form <-> cfg
    def _fill(self, cfg: AppConfig) -> None:
        self._loading = True
        self.ed_ip.setText(cfg.preferred_hub_ip)
        self.ed_ap.setText(cfg.hub_ap_ip)
        self.sp_port.setValue(cfg.udp_port)
        self.chk_ap.setChecked(cfg.auto_ap_detect)
        self.sp_poll.setValue(cfg.poll_ms)
        self.sp_timeout.setValue(cfg.timeout_s)
        self.cb_theme.setCurrentIndex(1 if cfg.theme == "light" else 0)
        self.cb_zoom.setCurrentIndex(min(range(len(self.zooms)), key=lambda i: abs(self.zooms[i] - cfg.ui_zoom)))
        self.chk_offline.setChecked(cfg.show_offline)
        self.ed_manifest.setText(cfg.ota_manifest_url)
        self.ed_token.setText(cfg.ota_token)
        self._loading = False
        self._set_dirty(False)

    def _load(self) -> None:
        self._fill(self.ctl.cfg)

    def _defaults(self) -> None:
        d = AppConfig()
        d.ota_token = self.ctl.cfg.ota_token          # never reset the secret silently
        self._fill(d)
        self._set_dirty(True)

    def _save(self) -> None:
        cfg = self.ctl.cfg
        try:
            cfg.preferred_hub_ip = self.ed_ip.text().strip()
            cfg.hub_ap_ip = self.ed_ap.text().strip()
        except ValueError as e:
            QMessageBox.warning(self, "Podešavanja", f"Neispravna IP adresa:\n{e}")
            return
        cfg.udp_port = self.sp_port.value()
        cfg.auto_ap_detect = self.chk_ap.isChecked()
        cfg.poll_ms = self.sp_poll.value()
        cfg.timeout_s = round(self.sp_timeout.value(), 1)
        cfg.ota_manifest_url = self.ed_manifest.text().strip()
        cfg.ota_token = self.ed_token.text()
        appearance = (cfg.theme, cfg.ui_zoom, cfg.show_offline)
        cfg.theme = "light" if self.cb_theme.currentIndex() == 1 else "dark"
        cfg.ui_zoom = self.zooms[self.cb_zoom.currentIndex()]
        cfg.show_offline = self.chk_offline.isChecked()

        # apply to the running client (same as the old app)
        self.ctl.client.selected_ip = cfg.preferred_hub_ip or None
        self.ctl.client.best_ip = None
        self.ctl.client.sock.settimeout(cfg.timeout_s)
        save_config(cfg)
        self._set_dirty(False)
        self.ctl.add_event("info", "Podešavanja aplikacije sačuvana")
        if appearance != (cfg.theme, cfg.ui_zoom, cfg.show_offline):
            self.appearance_changed.emit()

    def _mark_dirty(self, *_a) -> None:
        if not getattr(self, "_loading", False):
            self._set_dirty(True)

    def _set_dirty(self, dirty: bool) -> None:
        self.dirty_icon.setPixmap(icons.pixmap("alert-circle", c("warning"), 22) if dirty else icons.pixmap(
            "circle-check", c("muted"), 22))
        self.dirty_lbl.setText("Postoje nesačuvane izmene" if dirty else "Sve je sačuvano")
        self.dirty_lbl.setStyleSheet(f"color: {c('warning' if dirty else 'muted')};")

    # -------------------------------------------------------------- actions
    def _on_status(self, st, state) -> None:
        if st:
            self.conn_state.set(f"Povezan · {self.ctl.hub_ip()}", "success")
        else:
            self.conn_state.set("Traži hub…" if state == "SEARCHING" else "Nije povezan",
                                "warning" if state == "SEARCHING" else "danger")

    def _test(self) -> None:
        ip = self.ed_ip.text().strip() or self.ctl.hub_ip()
        if not ip:
            self.conn_msg.show_msg("Unesi IP adresu ili klikni „Pronađi hubove”.", "warning", "alert-triangle")
            return
        self.conn_msg.show_msg(f"Testiram {ip}…", "info", "link")
        self.ctl.run_bg(lambda: self.ctl.client._try_http_status(ip) or self.ctl.client._try_ping(ip),
                        lambda ok: self.conn_msg.show_msg(f"Veza sa {ip} je uspešna." if ok else
                                                          f"{ip} ne odgovara.", "success" if ok else "danger",
                                                          "circle-check" if ok else "alert-circle"))

    def _scan(self) -> None:
        self.conn_msg.show_msg("Tražim hubove na mreži (par sekundi)…", "info", "search")

        def done(hubs) -> None:
            self.cb_found.clear()
            self.cb_found.addItems([h["ip"] for h in hubs])
            self.conn_msg.show_msg(f"Pronađeno hubova: {len(hubs)}", "success" if hubs else "warning",
                                   "circle-check" if hubs else "alert-triangle")
        self.ctl.run_bg(self.ctl.client.discover_hubs, done,
                        lambda e: self.conn_msg.show_msg(f"Greška: {e}", "danger", "alert-circle"))

    def _use_found(self) -> None:
        if self.cb_found.currentText():
            self.ed_ip.setText(self.cb_found.currentText())

    def _backup(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Sačuvaj kopiju",
                                              f"blastgate_backup_{datetime.now():%Y%m%d_%H%M}.json", "JSON (*.json)")
        if not path:
            return
        app_cfg = {k: getattr(self.ctl.cfg, k) for k in ("ui_scale", "theme", "poll_ms", "timeout_s")}
        data = {"version": "2.1", "timestamp": datetime.now().isoformat(), "app_config": app_cfg, "nodes": {}}
        for n in self.ctl.status.get("nodes", []) or []:
            data["nodes"][n["id"]] = {"name": n.get("name", ""), "threshold": n.get("threshold_on", 40.0),
                                      "relay_hold_ms": n.get("relay_hold_ms", 5000),
                                      "gate_hold_ms": n.get("gate_hold_ms", 0),
                                      "hbridge_open_ms": n.get("hbridge_open_ms"),
                                      "hbridge_close_ms": n.get("hbridge_close_ms")}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        QMessageBox.information(self, "Rezervna kopija", f"Sačuvano mašina: {len(data['nodes'])}\n{path}")

    def _restore(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Vrati iz kopije", "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if "app_config" not in data:
                raise ValueError("nije Blastgate kopija")
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Rezervna kopija", f"Ne mogu da pročitam fajl:\n{e}")
            return
        nodes = data.get("nodes", {})
        if QMessageBox.question(self, "Vrati iz kopije",
                                f"Poslati hubu podešavanja za {len(nodes)} mašina i vratiti podešavanja "
                                "aplikacije?\nTrenutne vrednosti na hubu biće prepisane.") != QMessageBox.Yes:
            return
        cfg = self.ctl.cfg
        for key in ("poll_ms", "timeout_s"):
            if key in data["app_config"]:
                setattr(cfg, key, data["app_config"][key])
        save_config(cfg)
        for node_id, nc in nodes.items():
            if (nc.get("name") or "").strip():
                self.ctl.send("rename", node_id, nc["name"].strip())
            payload = {"threshold_on": nc.get("threshold", 40.0), "gate_hold_ms": nc.get("gate_hold_ms", 0)}
            for k in ("hbridge_open_ms", "hbridge_close_ms"):
                if nc.get(k):
                    payload[k] = nc[k]
            self.ctl.send("cfg", node_id, payload)
        self.ctl.add_event("info", f"Vraćena kopija ({len(nodes)} mašina)")
        self._load()
