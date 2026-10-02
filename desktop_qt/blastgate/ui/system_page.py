"""Sistem — hub state, node table, WiFi of the hub, updates (app + hub firmware)."""
import json
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from tempfile import gettempdir
from typing import Any, Dict

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QGridLayout,
                               QHBoxLayout, QHeaderView, QLineEdit, QMessageBox, QPlainTextEdit,
                               QProgressBar, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout,
                               QWidget)

from ..constants import APP_VERSION, LOG_PATH
from ..network.ota import check_and_get_update, download_firmware, is_newer, upload_to_hub, wait_for_reboot
from . import icons
from . import state as S
from .controller import Controller
from .theme import c
from .updater import AppUpdater
from .widgets import Banner, Card, StatusLabel, button, divider, label


def _info_card(title: str, icon_name: str) -> tuple:
    card = Card()
    lay = QVBoxLayout(card)
    lay.setContentsMargins(20, 14, 20, 16)
    head = QHBoxLayout()
    head.addWidget(label(title, "SectionTitle"))
    st = StatusLabel()
    head.addSpacing(10)
    head.addWidget(st)
    head.addStretch(1)
    lay.addLayout(head)
    lay.addWidget(divider())
    body = QHBoxLayout()
    ic = label()
    ic.setPixmap(icons.pixmap(icon_name, c("muted"), 54, 1.4))
    body.addWidget(ic)
    body.addSpacing(10)
    body.addWidget(divider(vertical=True))
    grid = QGridLayout()
    grid.setVerticalSpacing(2)
    grid.setHorizontalSpacing(16)
    body.addLayout(grid, 1)
    lay.addLayout(body)
    return card, st, grid, ic


class SystemPage(QWidget):
    COLS = ["Mašina", "ID", "Veza", "Status", "Režim", "Zatvarač", "Signal", "Poslednja poruka"]

    def __init__(self, ctl: Controller, updater: AppUpdater) -> None:
        super().__init__()
        self.ctl = ctl
        self.updater = updater
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 26, 32, 22)
        root.setSpacing(14)

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label("Sistem", "PageTitle"))
        titles.addWidget(label("Stanje huba i mašina, WiFi huba i ažuriranja.", "PageSubtitle"))
        head.addLayout(titles)
        head.addStretch(1)
        self.overall = StatusLabel(size=16)
        head.addWidget(self.overall)
        head.addSpacing(16)
        head.addWidget(button("Osveži status", "refresh", "outline", on_click=self._refresh))
        root.addLayout(head)

        self.tabs = tabs = QTabWidget()
        tabs.addTab(self._build_state_tab(), "Stanje")
        tabs.addTab(self._build_wifi_tab(), "WiFi huba")
        tabs.addTab(self._build_fw_tab(), "Ažuriranja")
        root.addWidget(tabs, 1)
        updater.changed.connect(self._app_update_refresh)
        self._app_update_refresh()

        ctl.status_changed.connect(self._on_status)
        self._on_status(ctl.status, ctl.state)

    # ================================================================ Stanje
    def _build_state_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 14, 0, 0)
        lay.setSpacing(14)

        cards = QHBoxLayout()
        cards.setSpacing(16)
        c1, self.st_hub, g1, _ = _info_card("Hub", "server")
        c2, self.st_radio, g2, _ = _info_card("Radio veza nodova", "access-point")
        c3, self.st_sync, g3, _ = _info_card("Sinhronizacija", "refresh")
        self.kv: Dict[str, Any] = {}
        for grid, rows in ((g1, [("ip", "Adresa"), ("link", "Veza"), ("fw", "Firmware"), ("uptime", "Radi")]),
                           (g2, [("espnow", "ESP-NOW"), ("channel", "Kanal"), ("paired", "Upareno")]),
                           (g3, [("poll", "Osvežavanje"), ("updated", "Poslednji odgovor"), ("heap", "Slobodna mem.")])):
            for r, (key, cap) in enumerate(rows):
                grid.addWidget(label(cap, "Small"), r, 0)
                v = label("—")
                v.setStyleSheet("font-weight: 600;")
                grid.addWidget(v, r, 1)
                self.kv[key] = v
        for card in (c1, c2, c3):
            cards.addWidget(card, 1)
        lay.addLayout(cards)

        table_card = Card()
        tl = QVBoxLayout(table_card)
        tl.setContentsMargins(18, 14, 18, 12)
        th = QHBoxLayout()
        th.addWidget(label("Mašine", "SectionTitle"))
        th.addWidget(label("  lista nodova i njihovo trenutno stanje", "Muted"))
        th.addStretch(1)
        tl.addLayout(th)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        tl.addWidget(self.table)
        lay.addWidget(table_card, 1)

        act = Card()
        al = QHBoxLayout(act)
        al.setContentsMargins(20, 12, 20, 12)
        col = QVBoxLayout()
        col.addWidget(label("Sistemske akcije", "SectionTitle"))
        col.addWidget(label("Održavanje i dijagnostika.", "Muted"))
        al.addLayout(col)
        al.addStretch(1)
        al.addWidget(button("Ponovo poveži", "refresh", "outline", on_click=self._reconnect))
        al.addWidget(button("Pošalji test (PING)", "send", "outline", on_click=self._ping))
        al.addWidget(button("Izvezi dijagnostiku", "download", "outline", on_click=self._export_diag))
        self.action_msg = label("", "Small")
        lay.addWidget(act)
        lay.addWidget(self.action_msg)
        return w

    def _on_status(self, st: Dict[str, Any], state: str) -> None:
        nodes = st.get("nodes", []) or []
        if not st:
            self.overall.set("Hub nije dostupan", "danger")
        elif self.ctl.lockout:
            self.overall.set("Ručni režim na hubu", "warning")
        elif any(S.node_status(n)[1] in ("warning", "danger") for n in nodes):
            self.overall.set("Potrebna pažnja", "warning")
        else:
            self.overall.set("Sve radi normalno", "success")

        self.st_hub.set("POVEZAN" if st else "NEDOSTUPAN", "success" if st else "danger")
        self.kv["ip"].setText(self.ctl.hub_ip() or "—")
        self.kv["link"].setText(S.hub_link_text(st, state))
        self.kv["fw"].setText(st.get("version") or "—")
        up = S.to_int(st.get("uptime"), -1)
        self.kv["uptime"].setText(f"{up // 3600} h {up % 3600 // 60} min" if up >= 0 else "—")

        has_radio = "espnow" in st
        self.st_radio.set(("AKTIVNO" if S.to_int(st.get("espnow")) else "ISKLJUČENO") if has_radio else "STARI FW",
                          ("success" if S.to_int(st.get("espnow")) else "warning") if has_radio else "idle")
        self.kv["espnow"].setText(("da" if S.to_int(st.get("espnow")) else "ne") if has_radio else "— (hub < 1.5.0)")
        self.kv["channel"].setText(str(st.get("channel", "—")))
        self.kv["paired"].setText(str(st.get("pairedCount", "—")))

        self.st_sync.set("AKTIVNO" if st else "ČEKA", "success" if st else "warning")
        self.kv["poll"].setText(f"{self.ctl.cfg.poll_ms} ms")
        self.kv["updated"].setText(f"{self.ctl.updated_at:%H:%M:%S}" if self.ctl.updated_at else "—")
        heap = S.to_int(st.get("freeHeap"), -1)
        self.kv["heap"].setText(f"{heap / 1024:.0f} KB" if heap >= 0 else "—")

        self.table.setRowCount(len(nodes))
        for r, n in enumerate(sorted(nodes, key=lambda x: S.node_name(x).lower())):
            status, tone = S.node_status(n)
            manual = S.to_int(n.get("mode")) == 1
            is_open = S.gate_open(n)
            cells = [
                (S.node_name(n), None, None),
                (n.get("id", ""), None, None),
                ({"espnow": "ESP-NOW", "udp": "WiFi (UDP)"}.get(n.get("transport"), "WiFi (UDP)")
                 if "transport" in n else "WiFi (UDP)", None, None),
                (status, tone, None),
                ("MANUAL" if manual else "AUTO", "warning" if manual else "info",
                 "hand-stop" if manual else "settings"),
                (S.gate_text(n), ("success" if is_open else "danger") if S.to_int(n.get("online")) else "idle",
                 "gate-open" if is_open else "gate-closed"),
                (S.signal_text(n), None, None),
                (S.age_text(n.get("ageMs")), None, None),
            ]
            for col, (txt, tone_, icon_name) in enumerate(cells):
                it = QTableWidgetItem(txt)
                if tone_:
                    it.setForeground(QColor(c(tone_)))
                if icon_name:
                    it.setIcon(icons.icon(icon_name, c(tone_ or "muted"), 18))
                self.table.setItem(r, col, it)

    def _refresh(self) -> None:
        self.ctl.send("refresh", full=True, on_ok=lambda: self._say("Hub osvežen."),
                      on_err=lambda e: self._say(f"Osvežavanje nije uspelo: {e}"))

    def _reconnect(self) -> None:
        self._say("Tražim hub…")
        self.ctl.run_bg(self.ctl.client.pick_best_ip,
                        lambda r: self._say(f"Hub: {r[0]} ({r[1]})" if r[0] else "Hub nije pronađen."),
                        lambda e: self._say(f"Greška: {e}"))

    def _ping(self) -> None:
        ip = self.ctl.hub_ip()
        if not ip:
            self._say("Nema adrese huba.")
            return

        def work():
            t0 = time.perf_counter()
            ok = self.ctl.client._try_ping(ip)
            return ok, (time.perf_counter() - t0) * 1000
        self.ctl.run_bg(work, lambda r: self._say(f"PING {ip}: {'PONG' if r[0] else 'nema odgovora'}"
                                                  f" ({r[1]:.0f} ms)"))

    def _export_diag(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Izvezi dijagnostiku",
                                              f"blastgate_dijagnostika_{datetime.now():%Y%m%d_%H%M}.txt",
                                              "Tekst (*.txt)")
        if not path:
            return
        log_tail = ""
        try:
            log_tail = "\n".join(Path(LOG_PATH).read_text(encoding="utf-8", errors="ignore").splitlines()[-300:])
        except OSError:
            pass
        cfg = self.ctl.cfg.model_dump(mode="json")
        cfg["ota_token"] = "***"
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"Blastgate dijagnostika {datetime.now():%Y-%m-%d %H:%M:%S}\n")
            f.write(f"Hub IP: {self.ctl.hub_ip()}  stanje: {self.ctl.state}\n\n== STATUS ==\n")
            f.write(json.dumps(self.ctl.status, indent=2, ensure_ascii=False))
            f.write("\n\n== CONFIG ==\n" + json.dumps(cfg, indent=2, ensure_ascii=False))
            f.write("\n\n== DOGAĐAJI ==\n")
            f.writelines(f"{w:%H:%M:%S} {t}\n" for w, _, t in self.ctl.events)
            f.write("\n== LOG (poslednjih 300 linija) ==\n" + log_tail)
        self._say(f"Dijagnostika sačuvana: {path}")

    def _say(self, text: str) -> None:
        self.action_msg.setText(text)

    # ============================================================ WiFi huba
    def _build_wifi_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 14, 0, 0)
        lay.setSpacing(14)

        status = Card()
        sl = QVBoxLayout(status)
        sl.setContentsMargins(20, 14, 20, 16)
        h = QHBoxLayout()
        h.addWidget(label("Trenutna WiFi veza huba", "SectionTitle"))
        h.addStretch(1)
        h.addWidget(button("Osveži", "refresh", on_click=self._wifi_refresh))
        sl.addLayout(h)
        self.wifi_state = StatusLabel()
        self.wifi_detail = label("—", "Muted")
        sl.addWidget(self.wifi_state)
        sl.addWidget(self.wifi_detail)
        lay.addWidget(status)

        form = Card()
        fl = QVBoxLayout(form)
        fl.setContentsMargins(20, 14, 20, 16)
        fl.setSpacing(10)
        fl.addWidget(label("Poveži hub na WiFi", "SectionTitle"))
        fl.addWidget(label("Računar mora biti na istoj mreži kao hub ili na WiFi-ju BLASTGATE_HUB "
                           "(lozinka 12345678). Hub se posle slanja restartuje.", "Muted", wrap=True))
        g = QGridLayout()
        self.cb_ssid = QComboBox()
        self.cb_ssid.setEditable(True)
        self.cb_ssid.setMinimumWidth(320)
        self.ed_pass = QLineEdit()
        self.ed_pass.setEchoMode(QLineEdit.Password)
        show = QCheckBox("Prikaži")
        show.toggled.connect(lambda on: self.ed_pass.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        g.addWidget(label("Mreža (SSID)", "Muted"), 0, 0)
        g.addWidget(self.cb_ssid, 0, 1)
        g.addWidget(button("Skeniraj", "search", on_click=self._wifi_scan), 0, 2)
        g.addWidget(label("Lozinka", "Muted"), 1, 0)
        g.addWidget(self.ed_pass, 1, 1)
        g.addWidget(show, 1, 2)
        g.setColumnStretch(3, 1)
        fl.addLayout(g)
        row = QHBoxLayout()
        row.addWidget(button("Pošalji hubu", "send", "primary", on_click=self._wifi_set))
        row.addWidget(button("Otvori stranicu /setup", "world", on_click=self._open_setup))
        row.addStretch(1)
        row.addWidget(button("Prekini WiFi vezu", "wifi-off", on_click=self._wifi_disconnect))
        row.addWidget(button("Zaboravi WiFi", "trash", "danger", on_click=self._wifi_forget))
        fl.addLayout(row)
        self.wifi_msg = Banner()
        fl.addWidget(self.wifi_msg)
        lay.addWidget(form)
        lay.addStretch(1)
        return w

    def _wifi_refresh(self) -> None:
        def ok(d: Dict[str, Any]) -> None:
            connected = str(d.get("STA", "0")) == "1"
            self.wifi_state.set("POVEZAN" if connected else "NIJE POVEZAN", "success" if connected else "warning")
            self.wifi_detail.setText(f"Mreža: {d.get('SSID') or '—'}   IP: {d.get('IP') or '—'}   "
                                     f"Signal: {d.get('RSSI') or '—'} dBm")
        self.ctl.send("wifi_get", on_ok=ok,
                      on_err=lambda e: self.wifi_state.set(f"Greška: {e}", "danger"))

    def _wifi_scan(self) -> None:
        ip = self.ctl.hub_ip()
        if not ip:
            self.wifi_msg.show_msg("Hub nije dostupan.", "danger", "alert-circle")
            return
        self.wifi_msg.show_msg("Skeniram mreže (hub blokira ~2 s)…", "info", "search")

        def done(nets) -> None:
            cur = self.cb_ssid.currentText()
            self.cb_ssid.clear()
            self.cb_ssid.addItems([n["ssid"] for n in nets])
            if cur:
                self.cb_ssid.setEditText(cur)
            self.wifi_msg.show_msg(f"Pronađeno mreža: {len(nets)}", "info", "wifi")
        self.ctl.run_bg(lambda: self.ctl.http.wifi_scan(ip), done,
                        lambda e: self.wifi_msg.show_msg(f"Skeniranje nije uspelo: {e}", "danger", "alert-circle"))

    def _wifi_set(self) -> None:
        ip = self.ctl.hub_ip()
        ssid = self.cb_ssid.currentText().strip()
        if not ssid or not ip:
            self.wifi_msg.show_msg("Unesi mrežu (i proveri da je hub dostupan).", "warning", "alert-triangle")
            return
        if QMessageBox.question(self, "WiFi huba", f"Poslati hubu mrežu „{ssid}”?\nHub će se restartovati."
                                ) != QMessageBox.Yes:
            return
        self.ctl.run_bg(lambda: self.ctl.http.wifi_set(ip, ssid, self.ed_pass.text()),
                        lambda _r: (self.wifi_msg.show_msg("Poslato. Hub se restartuje i povezuje na WiFi.",
                                                           "success", "circle-check"),
                                    self.ctl.add_event("info", f"WiFi huba → {ssid}")),
                        lambda e: self.wifi_msg.show_msg(f"Greška: {e}", "danger", "alert-circle"))

    def _open_setup(self) -> None:
        webbrowser.open(f"http://{self.ctl.hub_ip() or '192.168.4.1'}/setup")

    def _wifi_disconnect(self) -> None:
        if QMessageBox.question(self, "WiFi huba", "Prekinuti WiFi vezu huba (podaci ostaju sačuvani)?\n"
                                "Hub se restartuje.") == QMessageBox.Yes:
            self.ctl.send("wifi_disconnect", on_ok=lambda: self.wifi_msg.show_msg("Hub se restartuje.", "info"),
                          on_err=lambda e: self.wifi_msg.show_msg(f"Greška: {e}", "danger", "alert-circle"))

    def _wifi_forget(self) -> None:
        if QMessageBox.warning(self, "Zaboravi WiFi", "Hub će zaboraviti WiFi mrežu i restartovati se.\n"
                               "Posle toga je dostupan samo preko Etherneta ili BLASTGATE_HUB.\n\nNastaviti?",
                               QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        ip = self.ctl.hub_ip()
        self.ctl.run_bg(lambda: self.ctl.http.wifi_forget(ip),
                        lambda _r: self.wifi_msg.show_msg("WiFi zaboravljen, hub se restartuje.", "info"),
                        lambda e: self.wifi_msg.show_msg(f"Greška: {e}", "danger", "alert-circle"))

    # =========================================================== Ažuriranja
    def show_updates(self) -> None:
        """Open the updates tab and look for new hub firmware (from the strip on Pregled)."""
        self.tabs.setCurrentIndex(2)
        self._fw_check()

    def _build_app_card(self) -> Card:
        card = Card()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 14, 20, 16)
        cl.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(label("Aplikacija na ovom računaru", "SectionTitle"))
        head.addStretch(1)
        self.app_state = StatusLabel()
        head.addWidget(self.app_state)
        cl.addLayout(head)
        g = QGridLayout()
        g.addWidget(label("Instalirana verzija", "Muted"), 0, 0)
        g.addWidget(label(APP_VERSION, "MidValue"), 0, 1)
        g.addWidget(label("Najnovija verzija", "Muted"), 1, 0)
        self.app_latest = label("—", "MidValue")
        g.addWidget(self.app_latest, 1, 1)
        g.setColumnStretch(2, 1)
        cl.addLayout(g)
        self.app_msg = label("", "Muted", wrap=True)
        cl.addWidget(self.app_msg)
        row = QHBoxLayout()
        self.btn_app_check = button("Proveri sada", "refresh", "outline", on_click=self.updater.check)
        row.addWidget(self.btn_app_check)
        self.btn_app_install = button("Instaliraj i pokreni ponovo", "download", "primary",
                                      on_click=self.updater.install)
        row.addWidget(self.btn_app_install)
        row.addStretch(1)
        cl.addLayout(row)
        return card

    def _app_update_refresh(self) -> None:
        up = self.updater
        self.app_latest.setText(up.release.version if up.release else "—")
        self.btn_app_check.setEnabled(not up.checking)
        self.btn_app_install.setVisible(bool(up.setup))
        if up.app_update:
            self.app_state.set("IMA NOVA VERZIJA", "info")
        elif up.release:
            self.app_state.set("AŽURNO", "success")
        else:
            self.app_state.set("NIJE PROVERENO", "idle")

        if up.checking:
            msg = "Proveravam…"
        elif up.failed:
            msg = "Provera nije uspela. Računar nema pristup internetu."
        elif up.app_update and not up.self_update:
            msg = "Ova kopija je pokrenuta iz izvornog koda i ne ažurira se sama."
        elif up.setup:
            msg = "Nova verzija je preuzeta. Instalacija zatvara aplikaciju i sama je ponovo pokreće."
        elif up.downloading:
            msg = f"Preuzimam novu verziju… {up.progress} %"
        elif up.app_update:
            msg = "Preuzimanje nije uspelo. Dodirni „Proveri sada\" da probaš ponovo."
        elif up.checked_at:
            msg = f"Poslednja provera: {up.checked_at:%H:%M:%S}. Aplikacija proverava sama pri pokretanju."
        else:
            msg = "Još nije provereno."
        self.app_msg.setText(msg)

    def _build_fw_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 14, 0, 0)
        lay.setSpacing(14)
        lay.addWidget(self._build_app_card())
        card = Card()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 14, 20, 16)
        cl.setSpacing(10)
        cl.addWidget(label("Ažuriranje firmware-a huba (OTA)", "SectionTitle"))
        cl.addWidget(label("Nova verzija se skida sa servera za izdanja (Podešavanja → OTA), proverava se "
                           "SHA256 i šalje hubu. Hub se posle toga sam restartuje.", "Muted", wrap=True))
        g = QGridLayout()
        self.fw = {}
        for r, (key, cap) in enumerate((("hub", "Verzija na hubu"), ("remote", "Najnovija verzija"),
                                        ("build", "Build huba"))):
            g.addWidget(label(cap, "Muted"), r, 0)
            v = label("—", "MidValue")
            g.addWidget(v, r, 1)
            self.fw[key] = v
        g.setColumnStretch(2, 1)
        cl.addLayout(g)
        cl.addWidget(label("Promene", "Muted"))
        self.changelog = QPlainTextEdit()
        self.changelog.setReadOnly(True)
        self.changelog.setMaximumHeight(170)
        cl.addWidget(self.changelog)
        self.fw_progress = QProgressBar()
        self.fw_progress.setRange(0, 100)
        cl.addWidget(self.fw_progress)
        self.fw_msg = label("", "Muted", wrap=True)
        cl.addWidget(self.fw_msg)
        row = QHBoxLayout()
        row.addWidget(button("Proveri", "refresh", "outline", on_click=self._fw_check))
        self.btn_update = button("Ažuriraj hub", "upload", "primary", on_click=self._fw_update)
        self.btn_update.setEnabled(False)
        row.addWidget(self.btn_update)
        row.addStretch(1)
        cl.addLayout(row)
        lay.addWidget(card)
        lay.addStretch(1)
        self._manifest = None
        self._hub_ver = None
        return w

    def _fw_check(self) -> None:
        ip = self.ctl.hub_ip()
        if not ip:
            self.fw_msg.setText("Hub nije dostupan.")
            return
        self.fw_msg.setText("Proveravam…")
        if self.ctl.demo_hub:
            self.fw["hub"].setText("1.5.0")
            self.fw["remote"].setText("1.5.0")
            self.fw_msg.setText("DEMO: hub je ažuran.")
            return

        def done(r) -> None:
            self._hub_ver, self._manifest = r
            if self._hub_ver:
                self.fw["hub"].setText(self._hub_ver.version)
                self.fw["build"].setText(self._hub_ver.build or "—")
            if not self._manifest:
                self.fw["remote"].setText("(server nedostupan)")
                self.fw_msg.setText("Server za izdanja nije dostupan.")
                return
            self.fw["remote"].setText(self._manifest.version)
            self.changelog.setPlainText(self._manifest.changelog or "(bez opisa promena)")
            newer = self._hub_ver and is_newer(self._manifest.version, self._hub_ver.version)
            self.btn_update.setEnabled(bool(newer))
            self.fw_msg.setText(f"Dostupno ažuriranje: {self._hub_ver.version} → {self._manifest.version}"
                                if newer else "Hub je ažuran.")
        self.ctl.run_bg(lambda: check_and_get_update(ip, self.ctl.cfg.ota_manifest_url), done,
                        lambda e: self.fw_msg.setText(f"Hub nedostupan: {e}"))

    def _fw_update(self) -> None:
        ip, m = self.ctl.hub_ip(), self._manifest
        if not (ip and m):
            return
        if QMessageBox.question(self, "Ažuriranje huba",
                                f"Instalirati {m.version} na hub {ip}?\n\nHub se restartuje; zatvarači se za to "
                                "vreme zatvaraju (failsafe na nodovima).") != QMessageBox.Yes:
            return
        self.btn_update.setEnabled(False)
        prog = lambda p: self.ctl._ui_after(0, lambda: self.fw_progress.setValue(p))  # noqa: E731
        say = lambda t: self.ctl._ui_after(0, lambda: self.fw_msg.setText(t))       # noqa: E731

        def work():
            tmp = Path(gettempdir()) / f"blastgate_hub_{m.version}.bin"
            say(f"Skidam {m.version}…")
            download_firmware(m, tmp, progress_cb=lambda d, t: prog(int(d / t * 60) if t else 0))
            say("Šaljem hubu…")
            resp = upload_to_hub(ip, tmp, self.ctl.cfg.ota_token,
                                 progress_cb=lambda d, t: prog(60 + (int(d / t * 30) if t else 0)))
            if not resp.get("ok"):
                raise RuntimeError(f"hub odbio: {resp.get('error', 'nepoznato')}")
            say("Hub se restartuje…")
            ok = wait_for_reboot(ip, m.version, timeout_s=60.0)
            tmp.unlink(missing_ok=True)
            return ok

        def done(ok: bool) -> None:
            self.fw_progress.setValue(100 if ok else self.fw_progress.value())
            self.fw_msg.setText(f"Gotovo — hub radi na {m.version}." if ok else "Hub se nije javio posle 60 s.")
            self.ctl.add_event("success" if ok else "warning", f"OTA huba → {m.version}: {'OK' if ok else 'nije potvrđeno'}")

        def fail(e: Exception) -> None:
            self.fw_msg.setText(f"Ažuriranje nije uspelo: {e}")
            self.btn_update.setEnabled(True)
        self.ctl.run_bg(work, done, fail)
