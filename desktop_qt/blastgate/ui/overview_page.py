"""Pregled — machine tiles + system bar (suction, hub, counts)."""
from typing import Any, Callable, Dict, List

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMenu, QMessageBox, QScrollArea, QVBoxLayout,
                               QWidget)

from . import icons
from . import state as S
from .controller import Controller
from .theme import c
from .widgets import (Badge, Banner, Card, Dot, IconValue, Segmented, StatusLabel, TileGrid, ValueBar,
                      button, divider, label)


class NodeTile(Card):
    open_requested = Signal(str)

    def __init__(self, node_id: str, on_menu: Callable[[str, str], None]) -> None:
        super().__init__(clickable=True)
        self.node_id = node_id
        self.clicked.connect(lambda: self.open_requested.emit(self.node_id))
        self.setMinimumHeight(250)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 14)
        root.setSpacing(8)

        top = QHBoxLayout()
        self.title = label("", "TileTitle")
        self.status = StatusLabel()
        more = button("···", variant="ghost")
        more.setToolTip("Opcije")
        menu = QMenu(self)
        menu.addAction("Detalji i upravljanje", lambda: self.open_requested.emit(self.node_id))
        menu.addAction("Preimenuj…", lambda: on_menu("rename", self.node_id))
        menu.addAction("Kalibracija praga…", lambda: on_menu("calibrate", self.node_id))
        more.setMenu(menu)
        more.setStyleSheet("QPushButton::menu-indicator { image: none; width: 0; }")
        top.addWidget(self.title)
        top.addSpacing(10)
        top.addWidget(self.status)
        top.addStretch(1)
        top.addWidget(more)
        root.addLayout(top)

        mid = QHBoxLayout()
        vals = QVBoxLayout()
        vals.setSpacing(0)
        self.value = label("—", "BigValue")
        vals.addWidget(self.value)
        vals.addWidget(label("Senzor struje", "Muted"))
        mid.addLayout(vals)
        mid.addStretch(1)
        badges = QVBoxLayout()
        badges.setSpacing(8)
        self.badge_mode = Badge()
        self.badge_gate = Badge()
        for b in (self.badge_mode, self.badge_gate):
            badges.addWidget(b)
        badges.addStretch(1)
        mid.addLayout(badges)
        root.addLayout(mid)

        self.bar = ValueBar()
        root.addWidget(self.bar)
        root.addWidget(divider())

        bottom = QHBoxLayout()
        bottom.setSpacing(14)
        self.gate = IconValue("gate-closed", "Zatvarač")
        self.signal = IconValue("antenna-bars-5", "Signal")
        bottom.addWidget(self.gate, 1)
        bottom.addWidget(divider(vertical=True))
        bottom.addWidget(self.signal, 1)
        root.addLayout(bottom)

    def update_node(self, n: Dict[str, Any]) -> None:
        online = S.to_int(n.get("online")) == 1
        self.title.setText(S.node_name(n))
        self.status.set(*S.node_status(n))

        v = S.to_float(n.get("value"))
        thr = S.to_float(n.get("threshold_on"))
        self.value.setText(f"{v:.1f}" if (v is not None and online) else "—")
        self.bar.set_values(v if online else None, thr, S.bar_max(v, thr))

        manual = S.to_int(n.get("mode")) == 1
        if manual:
            self.badge_mode.set("MANUAL", "hand-stop", "warning")
        else:
            self.badge_mode.set("AUTO", "settings", "info")
        is_open = S.gate_open(n)
        self.badge_gate.set("OTVOREN" if is_open else "ZATVOREN", "gate-open" if is_open else "gate-closed",
                            ("success" if is_open else "danger") if online else "idle")

        tone = ("success" if is_open else "danger") if online else "muted"
        self.gate.set(S.gate_text(n), "gate-open" if is_open else "gate-closed", tone)
        bars = S.signal_bars(S.to_int(n.get("rssi"), 0) if online else None)
        self.signal.set(S.signal_text(n), f"antenna-bars-{bars + 1}" if n.get("rssi") else "antenna-bars-off",
                        "muted")
        errs = S.err_texts(S.to_int(n.get("err")) & S.ERR_WARNING_MASK)
        self.setToolTip("\n".join(errs))


class SummaryBar(Card):
    """Bottom bar: overall state | SUCTION (relay) + controls | hub | machines online | updated."""

    def __init__(self, ctl: Controller) -> None:
        super().__init__()
        self.ctl = ctl
        lay = QHBoxLayout(self)
        lay.setContentsMargins(22, 14, 22, 14)
        lay.setSpacing(22)

        self.state_icon = QLabel()
        st_col = QVBoxLayout()
        st_col.setSpacing(2)
        self.state_title = label("", "SectionTitle")
        self.state_sub = label("", "Muted")
        st_col.addWidget(self.state_title)
        st_col.addWidget(self.state_sub)
        lay.addWidget(self.state_icon)
        lay.addLayout(st_col, 2)
        lay.addWidget(divider(vertical=True))

        suction = QVBoxLayout()
        suction.setSpacing(6)
        row = QHBoxLayout()
        self.suction_icon = QLabel()
        self.suction_text = label("", "MidValue")
        self.suction_mode = label("", "Small")
        row.addWidget(self.suction_icon)
        row.addWidget(label("Usisivač", "Small"))
        row.addWidget(self.suction_text)
        row.addWidget(self.suction_mode)
        row.addStretch(1)
        suction.addLayout(row)
        self.relay = Segmented([("auto", "AUTO", "settings-automation", "info"),
                                ("on", "UKLJUČI", "power", "success"),
                                ("off", "ISKLJUČI", "player-stop", "danger")], compact=True)
        self.relay.chosen.connect(self._relay)
        suction.addWidget(self.relay)
        lay.addLayout(suction, 3)
        lay.addWidget(divider(vertical=True))

        self.hub = IconValue("server", "Hub")
        self.online = IconValue("plug-connected", "Mašine online")
        self.online.set("—", "plug-connected")
        self.updated = IconValue("clock", "Ažurirano")
        for w in (self.hub, self.online, self.updated):
            lay.addWidget(w, 1)

    def _relay(self, mode: str) -> None:
        if self.ctl.lockout:
            QMessageBox.warning(self, "Ručni režim na hubu", "Hub je u ručnom režimu (MANUAL taster). "
                                "Usisivačem se upravlja sa huba.")
            self.relay.clear_pending()
            return
        names = {"auto": "AUTO", "on": "ručno UKLJUČEN", "off": "ručno ISKLJUČEN"}

        def err(e: Exception) -> None:
            self.relay.clear_pending()
            msg = str(e)
            if "no gate open" in msg:
                msg = "Hub ne pali usisivač dok nijedan zatvarač nije otvoren."
            QMessageBox.warning(self, "Usisivač", msg)
        self.ctl.send("relay", mode, on_err=err, log=f"Usisivač → {names[mode]}")

    def update_status(self, st: Dict[str, Any], state: str) -> None:
        nodes = st.get("nodes", []) or []
        online = [n for n in nodes if S.to_int(n.get("online")) == 1]
        warn = [n for n in online if S.node_status(n)[1] == "warning"]
        if not st:
            title, sub, tone, ic = "Hub nije dostupan", "Tražim hub na mreži…", "danger", "alert-circle"
        elif self.ctl.lockout:
            title, sub, tone, ic = "Ručni režim na hubu", "Zatvaračima se upravlja tasterima", "warning", "hand-stop"
        elif warn or len(online) < len(nodes):
            title = "Potrebna pažnja"
            sub = f"{len(nodes) - len(online)} van mreže, {len(warn)} upozorenje"
            tone, ic = "warning", "alert-triangle"
        else:
            title, sub, tone, ic = "Sistem radi normalno", "Sve mašine su na vezi", "success", "circle-check"
        self.state_icon.setPixmap(icons.pixmap(ic, c(tone), 52, 2.2))
        self.state_title.setText(title)
        self.state_title.setStyleSheet(f"color: {c(tone)};")
        self.state_sub.setText(sub)

        on = S.to_int(st.get("relayState")) == 1 if st else False
        self.suction_icon.setPixmap(icons.pixmap("wind", c("success" if on else "muted"), 24))
        self.suction_text.setText("RADI" if on else "STOJI" if st else "—")
        self.suction_text.setStyleSheet(f"color: {c('success' if on else 'muted')};")
        self.suction_mode.setText(f"· {S.relay_mode_text(st)}" if st else "")
        mode = {0: "off", 1: "on"}.get(S.to_int(st.get("relayMode"), 2), "auto") if st else None
        self.relay.set_current(mode)
        self.relay.setEnabled(bool(st))

        self.hub.set(S.hub_link_text(st, state), "server", "success" if st else "danger")
        self.online.set(f"{len(online)} / {len(nodes)}" if st else "—", "plug-connected")
        self.updated.set(self.ctl.updated_at.strftime("%H:%M:%S") if self.ctl.updated_at else "—", "clock")


class OverviewPage(QWidget):
    open_node = Signal(str)
    node_action = Signal(str, str)   # action, node_id

    def __init__(self, ctl: Controller) -> None:
        super().__init__()
        self.ctl = ctl
        self.tiles: Dict[str, NodeTile] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 26, 32, 22)
        root.setSpacing(16)

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label("Pregled mašina", "PageTitle"))
        self.subtitle = label("Nadzor i upravljanje zatvaračima u realnom vremenu.", "PageSubtitle")
        titles.addWidget(self.subtitle)
        head.addLayout(titles)
        head.addStretch(1)
        self.hub_state = StatusLabel()
        head.addWidget(label("Hub:", "Muted"))
        head.addWidget(self.hub_state)
        head.addSpacing(18)
        head.addWidget(divider(vertical=True))
        head.addSpacing(18)
        self.count_total = label("", "Muted")
        head.addWidget(self.count_total)
        self.count_dots: List[QLabel] = []
        for tone in ("success", "warning", "danger"):
            head.addSpacing(10)
            head.addWidget(Dot(tone, 11))
            lb = label("0")
            self.count_dots.append(lb)
            head.addWidget(lb)
        root.addLayout(head)

        self.banner = Banner()
        root.addWidget(self.banner)

        self.grid = TileGrid(min_tile_w=390)
        self.empty = label("", "Muted", wrap=True)
        self.empty.setAlignment(Qt.AlignCenter)
        holder = QWidget()
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(0, 0, 4, 0)
        hl.addWidget(self.grid)
        hl.addWidget(self.empty)
        hl.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(holder)
        root.addWidget(scroll, 1)

        self.summary = SummaryBar(ctl)
        root.addWidget(self.summary)

        ctl.status_changed.connect(self.update_status)
        self.update_status({}, "SEARCHING")

    def update_status(self, st: Dict[str, Any], state: str) -> None:
        nodes = st.get("nodes", []) or []
        shown = [n for n in nodes if self.ctl.cfg.show_offline or S.to_int(n.get("online")) == 1]
        shown.sort(key=lambda n: S.node_name(n).lower())

        for n in shown:
            nid = n.get("id")
            if nid not in self.tiles:
                t = NodeTile(nid, lambda a, i: self.node_action.emit(a, i))
                t.open_requested.connect(self.open_node.emit)
                self.tiles[nid] = t
            self.tiles[nid].update_node(n)
        keep = {n.get("id") for n in shown}
        for nid in list(self.tiles):
            if nid not in keep:
                self.tiles.pop(nid).deleteLater()
        self.grid.set_tiles([self.tiles[n.get("id")] for n in shown])

        counts = {"success": 0, "warning": 0, "danger": 0}
        for n in nodes:
            tone = S.node_status(n)[1]
            counts["success" if tone in ("success", "idle") else tone] += 1
        self.count_total.setText(f"{len(nodes)} mašina")
        for lb, key in zip(self.count_dots, ("success", "warning", "danger")):
            lb.setText(str(counts[key]))

        if st:
            self.hub_state.set("POVEZAN", "success")
            self.subtitle.setText(f"Ažurirano {self.ctl.updated_at:%H:%M:%S}" if self.ctl.updated_at else "")
        else:
            self.hub_state.set("TRAŽIM…" if state == "SEARCHING" else "NEDOSTUPAN",
                               "warning" if state == "SEARCHING" else "danger")

        if not st:
            self.banner.show_msg("Veza sa hubom nije uspostavljena. Proveri da li je hub uključen i da li je "
                                 "računar na istoj mreži (ili na WiFi-ju BLASTGATE_HUB). Adresu možeš da "
                                 "podesiš u Podešavanjima.", "danger", "wifi-off")
        elif self.ctl.lockout:
            self.banner.show_msg("Hub je u RUČNOM REŽIMU (MANUAL taster). Svi zatvarači su zatvoreni; "
                                 "otvaraju se tasterima na mašinama. Hub sam izlazi iz ovog režima kad neka "
                                 "mašina krene.", "warning", "hand-stop")
        else:
            self.banner.hide()

        if st and not nodes:
            self.empty.setText("Hub još ne vidi nijednu mašinu.\nUključi nodove — pojaviće se ovde čim se jave.")
            self.empty.show()
        elif not shown and nodes:
            self.empty.setText("Sve mašine su van mreže (prikaz offline mašina je isključen u Podešavanjima).")
            self.empty.show()
        else:
            self.empty.hide()

        self.summary.update_status(st, state)
