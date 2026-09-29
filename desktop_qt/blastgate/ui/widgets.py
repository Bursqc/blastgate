"""Reusable widgets in the look of the Blastgate mockups."""
import time
from typing import Callable, List, Optional, Sequence, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

from . import icons
from .theme import c


def label(text: str = "", obj: str = "", wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if obj:
        lb.setObjectName(obj)
    lb.setWordWrap(wrap)
    return lb


def repolish(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)


def button(text: str, icon_name: str = "", variant: str = "", tone_color: str = "",
           on_click: Optional[Callable] = None) -> QPushButton:
    b = QPushButton(text)
    if variant:
        b.setProperty("variant", variant)
    if icon_name:
        col = tone_color or (c("accent_text") if variant == "primary" else
                             c("danger") if variant == "danger" else
                             c("accent") if variant == "outline" else c("text"))
        b.setIcon(icons.icon(icon_name, col, 18))
        b.setIconSize(icons.qsize(18))
    if on_click:
        b.clicked.connect(on_click)
    b.setCursor(Qt.PointingHandCursor)
    return b


class Card(QFrame):
    clicked = Signal()

    def __init__(self, clickable: bool = False, obj: str = "Card") -> None:
        super().__init__()
        self.setObjectName(obj)
        self.setProperty("clickable", "true" if clickable else "false")
        if clickable:
            self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if self.property("clickable") == "true" and e.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(e)


def divider(vertical: bool = False) -> QFrame:
    f = QFrame()
    f.setObjectName("VDivider" if vertical else "Divider")
    return f


class Dot(QWidget):
    def __init__(self, tone: str = "idle", size: int = 11) -> None:
        super().__init__()
        self._tone = tone
        self.setFixedSize(size, size)

    def set_tone(self, tone: str) -> None:
        if tone != self._tone:
            self._tone = tone
            self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(c(self._tone)))
        p.drawEllipse(self.rect().adjusted(1, 1, -1, -1))


class StatusLabel(QWidget):
    """Colored dot + uppercase status text (AKTIVAN / UPOZORENJE / NEDOSTUPAN look)."""

    def __init__(self, text: str = "", tone: str = "idle", size: int = 13) -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.dot = Dot(tone, 11)
        self.lbl = QLabel(text)
        self._size = size
        lay.addWidget(self.dot)
        lay.addWidget(self.lbl)
        self.set(text, tone)

    def set(self, text: str, tone: str) -> None:
        self.dot.set_tone(tone)
        self.lbl.setText(text)
        self.lbl.setStyleSheet(f"color: {c(tone)}; font-size: {self._size}px; font-weight: 600;")


class ValueBar(QWidget):
    """Horizontal bar with a threshold marker and its caption under it."""

    def __init__(self, height: int = 12) -> None:
        super().__init__()
        self._value: Optional[float] = None
        self._thr: Optional[float] = None
        self._max = 100.0
        self._bar_h = height
        self.setMinimumHeight(height + 22)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_values(self, value: Optional[float], threshold: Optional[float], vmax: float) -> None:
        self._value, self._thr, self._max = value, threshold, max(vmax, 1.0)
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        top = 4
        r = self._bar_h / 2
        track = QRectF(0, top, w, self._bar_h)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(c("track")))
        p.drawRoundedRect(track, r, r)

        if self._value is not None and self._value > 0:
            frac = min(1.0, self._value / self._max)
            above = self._thr is not None and self._value >= self._thr
            p.setBrush(QColor(c("success") if above else c("accent")))
            p.drawRoundedRect(QRectF(0, top, max(self._bar_h, w * frac), self._bar_h), r, r)

        if self._thr:
            x = min(w - 2, max(2, w * self._thr / self._max))
            p.setPen(QPen(QColor(c("text")), 2))
            p.drawLine(QPointF(x, top - 3), QPointF(x, top + self._bar_h + 3))
            f = QFont(self.font())
            f.setPointSizeF(max(7.5, f.pointSizeF() * 0.8))
            p.setFont(f)
            p.setPen(QColor(c("muted")))
            txt = f"prag {self._thr:g}"
            tw = p.fontMetrics().horizontalAdvance(txt)
            p.drawText(QPointF(min(max(0, x - tw / 2), w - tw), top + self._bar_h + 17), txt)
        p.end()


class Segmented(QWidget):
    """Row of exclusive buttons, e.g. AUTO | MANUAL. Emits the chosen key."""
    chosen = Signal(str)

    def __init__(self, options: Sequence[Tuple[str, str, str, str]], compact: bool = False) -> None:
        """options: (key, text, icon, tone)"""
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.buttons = {}
        self._tones = {}
        for key, text, icon_name, tone in options:
            b = QPushButton(text)
            b.setProperty("seg", "true")
            b.setProperty("tone", tone)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setIconSize(icons.qsize(18 if compact else 22))
            b.clicked.connect(lambda _=False, k=key: self._click(k))
            if compact:
                b.setMinimumHeight(34)
            else:
                b.setMinimumHeight(46)
            lay.addWidget(b)
            self.buttons[key] = b
            self._tones[key] = (icon_name, tone)
        self._current = None
        self._pending: Optional[Tuple[str, float]] = None
        self._refresh_icons()

    PENDING_S = 3.0

    def _click(self, key: str) -> None:
        # The checked button always shows what the HUB says; a click is shown
        # as "pending" (dashed) until the hub status confirms it or 3 s pass.
        self._pending = (key, time.monotonic())
        self._apply()
        self.chosen.emit(key)

    def set_current(self, key: Optional[str]) -> None:
        """Called with the hub's state on every status update."""
        self._current = key
        if self._pending and (self._pending[0] == key or
                              time.monotonic() - self._pending[1] > self.PENDING_S):
            self._pending = None
        self._apply()

    def clear_pending(self) -> None:
        self._pending = None
        self._apply()

    def _apply(self) -> None:
        pend = self._pending[0] if self._pending else None
        for k, b in self.buttons.items():
            b.setChecked(k == self._current)
            want = "true" if k == pend else "false"
            if b.property("pending") != want:
                b.setProperty("pending", want)
                repolish(b)
        self._refresh_icons()

    def set_enabled_keys(self, keys: Optional[List[str]]) -> None:
        for k, b in self.buttons.items():
            b.setEnabled(keys is None or k in keys)
        self._refresh_icons()

    def _refresh_icons(self) -> None:
        for k, b in self.buttons.items():
            icon_name, tone = self._tones[k]
            if icon_name:
                col = c(tone) if (b.isChecked() or b.property("pending") == "true") and b.isEnabled() else c("muted")
                b.setIcon(icons.icon(icon_name, col, 22))


class IconValue(QWidget):
    """Icon + small caption + value (Temperatura/Signal style row element)."""

    def __init__(self, icon_name: str, caption: str) -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self.ic = QLabel()
        self._icon = icon_name
        self.ic.setPixmap(icons.pixmap(icon_name, c("muted"), 26, 1.6))
        col = QVBoxLayout()
        col.setSpacing(0)
        self.cap = label(caption, "Small")
        self.val = label("—", "MidValue")
        col.addWidget(self.cap)
        col.addWidget(self.val)
        lay.addWidget(self.ic)
        lay.addLayout(col)
        lay.addStretch(1)

    def set(self, value: str, icon_name: Optional[str] = None, tone: str = "muted") -> None:
        self.val.setText(value)
        self.ic.setPixmap(icons.pixmap(icon_name or self._icon, c(tone), 26, 1.6))


class Badge(QFrame):
    """Outlined pill with icon + text (AUTO / MANUAL / OTVOREN / ZATVOREN on tiles)."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Badge")
        self.setObjectName("Badge")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 14, 6)
        lay.setSpacing(8)
        self.ic = QLabel()
        self.lbl = QLabel()
        lay.addStretch(1)
        lay.addWidget(self.ic)
        lay.addWidget(self.lbl)
        lay.addStretch(1)
        self.setMinimumWidth(132)
        self._key = None

    def set(self, text: str, icon_name: str, tone: str) -> None:
        key = (text, icon_name, tone, c(tone))
        if key == self._key:
            return
        self._key = key
        col = c(tone)
        self.setStyleSheet(f"QFrame#Badge {{ border: 1px solid {col}; border-radius: 7px; }}")
        self.ic.setPixmap(icons.pixmap(icon_name, col, 20))
        self.lbl.setText(text)
        self.lbl.setStyleSheet(f"color: {col}; font-weight: 600; border: none;")


class Banner(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Banner")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(12)
        self.ic = QLabel()
        self.lbl = QLabel()
        self.lbl.setWordWrap(True)
        lay.addWidget(self.ic)
        lay.addWidget(self.lbl, 1)
        self.hide()

    def show_msg(self, text: str, tone: str = "info", icon_name: str = "info-circle") -> None:
        self.setProperty("tone", tone)
        repolish(self)
        self.ic.setPixmap(icons.pixmap(icon_name, c(tone), 22))
        self.lbl.setText(text)
        self.lbl.setStyleSheet(f"color: {c(tone)};")
        self.show()


class TileGrid(QWidget):
    """Grid that reflows its tiles into as many columns as fit."""

    def __init__(self, min_tile_w: int = 380) -> None:
        super().__init__()
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(18)
        self.min_tile_w = min_tile_w
        self._tiles: List[QWidget] = []
        self._cols = 0

    def set_tiles(self, tiles: List[QWidget]) -> None:
        self._tiles = tiles
        self._cols = 0
        self._reflow()

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._reflow()

    def _reflow(self) -> None:
        cols = max(1, min(4, self.width() // self.min_tile_w)) if self.width() > 0 else 3
        if cols == self._cols and all(self.grid.indexOf(t) >= 0 for t in self._tiles) \
                and self.grid.count() == len(self._tiles):
            return
        self._cols = cols
        while self.grid.count():
            self.grid.takeAt(0)
        for i, t in enumerate(self._tiles):
            self.grid.addWidget(t, i // cols, i % cols)
        for col in range(4):
            self.grid.setColumnStretch(col, 1 if col < cols else 0)
