"""Događaji — what happened (derived from status changes + own commands)."""
from datetime import datetime
from typing import Tuple

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QLineEdit,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from . import icons
from .controller import Controller
from .theme import c
from .widgets import Card, button, label

TONE_TEXT = {"success": "OK", "warning": "PAŽNJA", "danger": "GREŠKA", "info": "INFO", "idle": "INFO"}


class EventsPage(QWidget):
    def __init__(self, ctl: Controller) -> None:
        super().__init__()
        self.ctl = ctl
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 26, 32, 22)
        root.setSpacing(16)

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label("Događaji", "PageTitle"))
        titles.addWidget(label("Šta se dešavalo od pokretanja aplikacije.", "PageSubtitle"))
        head.addLayout(titles)
        head.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Pretraži događaje…")
        self.search.addAction(icons.icon("search", c("muted"), 18), QLineEdit.LeadingPosition)
        self.search.setMinimumWidth(300)
        self.search.textChanged.connect(self._filter)
        head.addWidget(self.search)
        head.addWidget(button("Izvezi .txt", "file-export", "outline", on_click=self._export))
        head.addWidget(button("Očisti", "trash", on_click=self._clear))
        root.addLayout(head)

        card = Card()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(8, 8, 8, 8)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Vreme", "Tip", "Događaj"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setShowGrid(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        cl.addWidget(self.table)
        root.addWidget(card, 1)

        for ev in ctl.events:
            self._add(ev)
        ctl.event_added.connect(self._add)

    def _add(self, ev: Tuple[datetime, str, str]) -> None:
        when, tone, text = ev
        self.table.insertRow(0)
        t = QTableWidgetItem(when.strftime("%d.%m. %H:%M:%S"))
        k = QTableWidgetItem(TONE_TEXT.get(tone, "INFO"))
        k.setForeground(QColor(c(tone)))
        k.setIcon(icons.icon("circle-check" if tone == "success" else
                             "alert-triangle" if tone == "warning" else
                             "alert-circle" if tone == "danger" else "info-circle", c(tone), 16))
        e = QTableWidgetItem(text)
        for col, item in enumerate((t, k, e)):
            self.table.setItem(0, col, item)
        self.table.setRowHidden(0, not self._match(text))

    def _match(self, text: str) -> bool:
        q = self.search.text().strip().lower()
        return not q or q in text.lower()

    def _filter(self) -> None:
        for r in range(self.table.rowCount()):
            self.table.setRowHidden(r, not self._match(self.table.item(r, 2).text()))

    def _clear(self) -> None:
        self.ctl.events.clear()
        self.table.setRowCount(0)

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Izvezi događaje",
                                              f"blastgate_dogadjaji_{datetime.now():%Y%m%d_%H%M}.txt",
                                              "Tekst (*.txt)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            for when, tone, text in self.ctl.events:
                f.write(f"{when:%Y-%m-%d %H:%M:%S}\t{TONE_TEXT.get(tone, 'INFO')}\t{text}\n")
