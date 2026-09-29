"""Machine dialog — state, AUTO/MANUAL, manual gate + suction, settings, calibration."""
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QDialog, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLineEdit,
                               QProgressBar, QScrollArea, QSlider, QSpinBox, QVBoxLayout, QWidget)

from . import state as S
from .controller import Controller
from .widgets import (Banner, Card, IconValue, Segmented, StatusLabel, ValueBar, button, divider, label)


def _section(title: str) -> (Card, QVBoxLayout):
    card = Card(obj="Inset")
    lay = QVBoxLayout(card)
    lay.setContentsMargins(16, 12, 16, 14)
    lay.setSpacing(10)
    lay.addWidget(label(title, "SectionTitle"))
    return card, lay


class NodeDialog(QDialog):
    def __init__(self, ctl: Controller, node_id: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.ctl = ctl
        self.node_id = node_id
        self._loaded = False
        self.setWindowTitle("Mašina")
        self.setMinimumSize(640, 720)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 20, 26, 18)
        outer.setSpacing(12)

        head = QHBoxLayout()
        self.title = label("", "PageTitle")
        self.title.setStyleSheet("font-size: 26px;")
        head.addWidget(self.title)
        head.addStretch(1)
        outer.addLayout(head)
        self.status = StatusLabel(size=14)
        self.info = label("", "Small")
        outer.addWidget(self.status)
        outer.addWidget(self.info)

        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(12)

        # --- live value -----------------------------------------------------
        live = Card(obj="Inset")
        ll = QHBoxLayout(live)
        ll.setContentsMargins(18, 14, 18, 14)
        vcol = QVBoxLayout()
        vcol.addWidget(label("Trenutna vrednost senzora", "Muted"))
        self.value = label("—", "BigValue")
        vcol.addWidget(self.value)
        self.bar = ValueBar()
        vcol.addWidget(self.bar)
        ll.addLayout(vcol, 3)
        ll.addWidget(divider(vertical=True))
        self.gate = IconValue("gate-closed", "Zatvarač")
        self.signal = IconValue("antenna-bars-5", "Signal")
        side = QVBoxLayout()
        side.addWidget(self.gate)
        side.addWidget(self.signal)
        ll.addLayout(side, 2)
        lay.addWidget(live)

        self.banner = Banner()
        lay.addWidget(self.banner)

        # --- mode -----------------------------------------------------------
        card, cl = _section("Režim rada")
        self.mode = Segmented([("auto", "AUTO", "settings", "info"),
                               ("manual", "MANUAL", "hand-stop", "warning")])
        self.mode.chosen.connect(self._set_mode)
        cl.addWidget(self.mode)
        cl.addWidget(label("AUTO: hub otvara zatvarač kad mašina radi. MANUAL: ti upravljaš.", "Small", wrap=True))
        lay.addWidget(card)

        # --- manual gate + suction -------------------------------------------
        card, cl = _section("Ručna komanda")
        self.gate_cmd = Segmented([("open", "OTVORI", "gate-open", "success"),
                                   ("close", "ZATVORI", "gate-closed", "danger")])
        self.gate_cmd.chosen.connect(self._set_gate)
        cl.addWidget(self.gate_cmd)
        cl.addWidget(label("Usisivač (ceo sistem, ručno max 30 s pa hub vraća na AUTO)", "Small", wrap=True))
        self.relay = Segmented([("on", "UKLJUČI", "power", "success"),
                                ("off", "ISKLJUČI", "player-stop", "danger")], compact=True)
        self.relay.chosen.connect(self._set_relay)
        cl.addWidget(self.relay)
        self.manual_note = label("Ručne komande su dostupne samo u MANUAL režimu.", "Small", wrap=True)
        cl.addWidget(self.manual_note)
        lay.addWidget(card)

        # --- settings ---------------------------------------------------------
        card, cl = _section("Podešavanja mašine")
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("npr. Cirkular")
        self.sl_thr = QSlider(Qt.Horizontal)
        self.sl_thr.setRange(1, 2500)          # 0.1 steps up to 250
        self.sp_thr = QDoubleSpinBox()
        self.sp_thr.setRange(0.1, 250.0)
        self.sp_thr.setDecimals(1)
        self.sp_thr.setSingleStep(1.0)
        self.sl_thr.valueChanged.connect(lambda v: self.sp_thr.setValue(v / 10))
        self.sp_thr.valueChanged.connect(lambda v: self.sl_thr.setValue(round(v * 10)))
        self.sp_hold = QDoubleSpinBox()
        self.sp_hold.setRange(0.0, 600.0)
        self.sp_hold.setDecimals(1)
        self.sp_hold.setSuffix(" s")
        self.sp_hbo = QSpinBox()
        self.sp_hbc = QSpinBox()
        for sp in (self.sp_hbo, self.sp_hbc):
            sp.setRange(100, 60000)
            sp.setSingleStep(100)
            sp.setSuffix(" ms")
        thr_row = QHBoxLayout()
        thr_row.addWidget(self.sl_thr, 1)
        thr_row.addWidget(self.sp_thr)
        rows = [("Ime", self.ed_name, ""),
                ("Prag", thr_row, "Iznad praga mašina se smatra upaljenom"),
                ("Ostaje otvoren", self.sp_hold, "posle gašenja mašine"),
                ("Motor — otvaranje", self.sp_hbo, "vreme rada H-mosta"),
                ("Motor — zatvaranje", self.sp_hbc, "vreme rada H-mosta")]
        for r, (cap, w, hint) in enumerate(rows):
            grid.addWidget(label(cap, "Muted"), r, 0)
            if isinstance(w, QHBoxLayout):
                grid.addLayout(w, r, 1)
            else:
                grid.addWidget(w, r, 1)
            grid.addWidget(label(hint, "Small"), r, 2)
        grid.setColumnStretch(1, 1)
        cl.addLayout(grid)
        brow = QHBoxLayout()
        brow.addWidget(button("Kalibracija praga", "ruler-measure", "outline", on_click=self._calibrate))
        brow.addWidget(button("Učitaj sa huba", "refresh", on_click=self._reload))
        brow.addStretch(1)
        cl.addLayout(brow)
        lay.addWidget(card)
        lay.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        self.msg = Banner()
        outer.addWidget(self.msg)
        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(button("Zatvori", on_click=self.close))
        self.btn_apply = button("Primeni izmene", "device-floppy", "primary", on_click=self._apply)
        foot.addWidget(self.btn_apply)
        outer.addLayout(foot)

        ctl.status_changed.connect(self._on_status)
        self._on_status(ctl.status, ctl.state)

    # ---------------------------------------------------------------- status
    def _node(self) -> Optional[Dict[str, Any]]:
        return self.ctl.node(self.node_id)

    def _on_status(self, st: Dict[str, Any], _state: str) -> None:
        n = self._node()
        if not n:
            self.status.set("NEPOZNATA" if st else "HUB NEDOSTUPAN", "danger")
            return
        online = S.to_int(n.get("online")) == 1
        self.title.setText(f"{S.node_name(n)} — upravljanje")
        self.setWindowTitle(S.node_name(n))
        self.status.set(*S.node_status(n))
        extra = [self.node_id]
        for key, fmt in (("transport", "veza {}"), ("fw", "FW {}"), ("mac", "{}")):
            if n.get(key):
                extra.append(fmt.format(n[key]))
        self.info.setText("  ·  ".join(extra))

        v = S.to_float(n.get("value"))
        thr = S.to_float(n.get("threshold_on"))
        self.value.setText(f"{v:.1f}" if (v is not None and online) else "—")
        self.bar.set_values(v if online else None, thr, S.bar_max(v, thr))
        is_open = S.gate_open(n)
        self.gate.set(S.gate_text(n), "gate-open" if is_open else "gate-closed",
                      ("success" if is_open else "danger") if online else "muted")
        bars = S.signal_bars(S.to_int(n.get("rssi"), 0) if online else None)
        self.signal.set(S.signal_text(n), f"antenna-bars-{bars + 1}" if n.get("rssi") else "antenna-bars-off")

        manual = S.to_int(n.get("mode")) == 1
        self.mode.set_current("manual" if manual else "auto")
        ov = S.to_int(n.get("override"))
        self.gate_cmd.set_current({1: "open", 2: "close"}.get(ov))
        relay_mode = S.to_int(st.get("relayMode"), 2)
        self.relay.set_current({0: "off", 1: "on"}.get(relay_mode))

        locked = self.ctl.lockout
        can = online and not locked
        self.mode.setEnabled(can)
        self.gate_cmd.setEnabled(can and manual)
        self.relay.setEnabled(can and manual)
        self.manual_note.setVisible(not manual)

        errs = S.err_texts(S.to_int(n.get("err")) & S.ERR_WARNING_MASK)
        if locked:
            self.banner.show_msg("Hub je u ručnom režimu (MANUAL taster) — komande iz aplikacije su zaključane.",
                                 "warning", "lock")
        elif not online:
            self.banner.show_msg("Mašina je van mreže.", "danger", "wifi-off")
        elif errs:
            self.banner.show_msg("\n".join(errs), "warning", "alert-triangle")
        else:
            self.banner.hide()

        if not self._loaded:
            self._loaded = True
            self._fill_settings(n)

    def _fill_settings(self, n: Dict[str, Any]) -> None:
        self.ed_name.setText((n.get("name") or "").strip())
        self.sp_thr.setValue(S.to_float(n.get("threshold_on")) or 40.0)
        self.sp_hold.setValue(S.hold_ms_to_s(n.get("gate_hold_ms", 5000)))
        self.sp_hbo.setValue(S.to_int(n.get("hbridge_open_ms"), 2000))
        self.sp_hbc.setValue(S.to_int(n.get("hbridge_close_ms"), 2000))

    # -------------------------------------------------------------- commands
    def _fail(self, seg: Segmented, what: str):
        def err(e: Exception) -> None:
            seg.clear_pending()
            self.msg.show_msg(f"{what}: {e}", "danger", "alert-circle")
        return err

    def _name(self) -> str:
        n = self._node()
        return S.node_name(n) if n else self.node_id

    def _set_mode(self, mode: str) -> None:
        if mode == "auto":
            # Back to AUTO also clears the manual gate override (same as the old app)
            def reset_gate() -> None:
                self.ctl.send("gate", self.node_id, "auto", on_err=self._fail(self.gate_cmd, "Reset zatvarača"))
            self.ctl.send("mode", self.node_id, "auto", on_ok=reset_gate,
                          on_err=self._fail(self.mode, "Režim"), log=f"{self._name()}: režim → AUTO")
        else:
            self.ctl.send("mode", self.node_id, "manual", on_err=self._fail(self.mode, "Režim"),
                          log=f"{self._name()}: režim → MANUAL")

    def _set_gate(self, gate: str) -> None:
        # Hub decides the relay; never send RELAY off here (it forces suction off for all gates).
        self.ctl.send("gate", self.node_id, gate, on_err=self._fail(self.gate_cmd, "Zatvarač"),
                      log=f"{self._name()}: ručno {'OTVORI' if gate == 'open' else 'ZATVORI'}")

    def _set_relay(self, mode: str) -> None:
        if mode == "on" and not any(S.gate_open(n) for n in self.ctl.status.get("nodes", [])
                                    if S.to_int(n.get("online")) == 1):
            self.relay.clear_pending()
            self.msg.show_msg("Usisivač se ne pali dok nijedan zatvarač nije otvoren.", "warning", "alert-triangle")
            return
        self.ctl.send("relay", mode, on_err=self._fail(self.relay, "Usisivač"),
                      log=f"Usisivač → ručno {'UKLJUČEN' if mode == 'on' else 'ISKLJUČEN'}")

    def _reload(self) -> None:
        def ok(cfg: Dict[str, Any]) -> None:
            n = dict(self._node() or {})
            n.update(cfg or {})
            self._fill_settings(n)
            self.msg.show_msg("Podešavanja učitana sa huba.", "info", "refresh")
        self.ctl.send("nodecfg_get", self.node_id, on_ok=ok,
                      on_err=lambda e: self.msg.show_msg(f"Učitavanje nije uspelo: {e}", "danger", "alert-circle"))

    def _apply(self) -> None:
        payload = {
            "threshold_on": round(self.sp_thr.value(), 1),
            "gate_hold_ms": S.hold_s_to_ms(self.sp_hold.value()),
            "hbridge_open_ms": self.sp_hbo.value(),
            "hbridge_close_ms": self.sp_hbc.value(),
        }
        self.btn_apply.setEnabled(False)
        self.msg.show_msg("Šaljem na hub…", "info", "send")

        def done_ok() -> None:
            self.btn_apply.setEnabled(True)
            self.msg.show_msg("Sačuvano na hubu.", "success", "circle-check")

        def done_err(e: Exception) -> None:
            self.btn_apply.setEnabled(True)
            self.msg.show_msg(f"Čuvanje nije uspelo: {e}", "danger", "alert-circle")

        new_name = self.ed_name.text().strip()
        n = self._node() or {}
        rename = new_name and new_name != (n.get("name") or "").strip()

        def after_cfg() -> None:
            if rename:
                self.ctl.send("rename", self.node_id, new_name, on_ok=done_ok, on_err=done_err,
                              log=f"{self.node_id}: novo ime „{new_name}”")
            else:
                done_ok()
        self.ctl.send("cfg", self.node_id, payload, on_ok=after_cfg, on_err=done_err,
                      log=f"{self._name()}: prag {payload['threshold_on']:g}, "
                          f"ostaje otvoren {payload['gate_hold_ms'] / 1000:g} s")

    def _calibrate(self) -> None:
        dlg = CalibrationDialog(self.ctl, self.node_id, self)
        if not (dlg.exec() and dlg.recommended is not None):
            return
        thr = dlg.recommended
        self.sp_thr.setValue(thr)
        self.ctl.send("cfg", self.node_id, {"threshold_on": thr},
                      on_ok=lambda: self.msg.show_msg(f"Prag {thr:g} upisan na hub.", "success", "circle-check"),
                      on_err=lambda e: self.msg.show_msg(f"Upis praga nije uspeo: {e}", "danger", "alert-circle"),
                      log=f"{self._name()}: kalibrisan prag {thr:g}")

    def closeEvent(self, e) -> None:  # noqa: N802
        try:
            self.ctl.status_changed.disconnect(self._on_status)
        except (RuntimeError, TypeError):
            pass
        super().closeEvent(e)


class CalibrationDialog(QDialog):
    """Same algorithm as the old wizard: baseline -> machine ON samples -> verify OFF."""
    START, WAIT_ON, SAMPLE_ON, WAIT_OFF, SAMPLE_OFF, DONE = range(6)
    STEPS = {
        START: "Mašina mora biti UGAŠENA. Klikni „Počni”.",
        WAIT_ON: "Merim mirovanje… zatim UPALI mašinu.",
        SAMPLE_ON: "Mašina radi — merim…",
        WAIT_OFF: "Sada UGASI mašinu.",
        SAMPLE_OFF: "Proveravam da vrednost pada ispod praga…",
        DONE: "Gotovo.",
    }

    def __init__(self, ctl: Controller, node_id: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.ctl = ctl
        self.node_id = node_id
        self.recommended: Optional[float] = None
        self.setWindowTitle("Kalibracija praga")
        self.setMinimumWidth(520)
        self._state = self.START
        self._baseline: List[float] = []
        self._on: List[float] = []
        self._off: List[float] = []
        self._base_avg = 0.0
        self._last: Optional[float] = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(12)
        lay.addWidget(label("Kalibracija praga", "SectionTitle"))
        self.step = label(self.STEPS[self.START], wrap=True)
        self.step.setStyleSheet("font-size: 16px;")
        lay.addWidget(self.step)
        self.reading = label("Vrednost: —", "MidValue")
        lay.addWidget(self.reading)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        lay.addWidget(self.progress)
        self.detail = label("", "Small", wrap=True)
        lay.addWidget(self.detail)
        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(button("Otkaži", on_click=self.reject))
        self.btn = button("Počni", variant="primary", on_click=self._action)
        foot.addWidget(self.btn)
        lay.addLayout(foot)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

    def _action(self) -> None:
        if self._state == self.DONE and self.recommended is not None:
            self.accept()
            return
        self._state = self.WAIT_ON
        self._baseline, self._on, self._off, self._last = [], [], [], None
        self.btn.setEnabled(False)
        self.btn.setText("Merim…")
        self.timer.start(400)
        self._tick()

    def _tick(self) -> None:
        n = self.ctl.node(self.node_id)
        v = S.to_float(n.get("value")) if n else None
        if v is None:
            self.detail.setText("Čekam podatke sa senzora…")
            return
        self.reading.setText(f"Vrednost: {v:.1f}")
        new = self._last is None or abs(v - self._last) > 0.01   # hub refreshes ~650 ms
        self._last = v

        if self._state == self.WAIT_ON:
            if len(self._baseline) < 5:
                if new:
                    self._baseline.append(v)
                self.progress.setValue(len(self._baseline) * 20)
                self.detail.setText(f"Mirovanje: {len(self._baseline)}/5 merenja")
            else:
                self._base_avg = sum(self._baseline) / len(self._baseline)
                if v > max(self._base_avg * 1.5, self._base_avg + 8.0):
                    self._state = self.SAMPLE_ON
                    self.progress.setValue(0)
                self.detail.setText(f"Mirovanje {self._base_avg:.1f} — čekam da mašina krene")
        elif self._state == self.SAMPLE_ON:
            if new:
                self._on.append(v)
            self.progress.setValue(min(100, len(self._on) * 100 // 15))
            if len(self._on) >= 10:
                min_on = min(self._on)
                thr = round((self._base_avg + min_on) / 2.0, 1)
                if thr <= self._base_avg:
                    thr = round(self._base_avg + (min_on - self._base_avg) * 0.3, 1)
                self.recommended = thr
                self._state = self.WAIT_OFF
                self.detail.setText(f"Predlog praga {thr:g} (mirovanje {self._base_avg:.1f}, min rad {min_on:.1f})")
        elif self._state == self.WAIT_OFF:
            if self.recommended is not None and v < self.recommended:
                self._state = self.SAMPLE_OFF
                self._off = []
                self.progress.setValue(0)
        elif self._state == self.SAMPLE_OFF:
            if new:
                self._off.append(v)
            self.progress.setValue(min(100, len(self._off) * 20))
            if len(self._off) >= 5:
                self.timer.stop()
                self.btn.setEnabled(True)
                if max(self._off) < (self.recommended or 0):
                    self._state = self.DONE
                    self.btn.setText(f"Upiši prag {self.recommended:g}")
                else:
                    self._state = self.START
                    self.recommended = None
                    self.btn.setText("Ponovi")
                    self.detail.setText(f"Provera nije prošla: posle gašenja vrednost je {max(self._off):.1f}, "
                                        "a to je iznad predloga. Pokušaj ponovo.")
        self.step.setText(self.STEPS[self._state])
