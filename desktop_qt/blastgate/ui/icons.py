"""
SVG icons (Tabler Icons, MIT — see icons/LICENSE) recolored at runtime.
gate-open.svg / gate-closed.svg are drawn for this project in the same style.
"""
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, QSize
from PySide6.QtGui import QIcon, QPainter, QPixmap, QGuiApplication
from PySide6.QtSvg import QSvgRenderer

_DIR = Path(__file__).parent / "icons"


@lru_cache(maxsize=None)
def _svg(name: str) -> str:
    return (_DIR / f"{name}.svg").read_text(encoding="utf-8")


@lru_cache(maxsize=512)
def pixmap(name: str, color: str, size: int = 20, stroke: float = 2.0) -> QPixmap:
    src = _svg(name).replace("currentColor", color)
    if stroke != 2.0:
        src = src.replace('stroke-width="2"', f'stroke-width="{stroke}"')
    renderer = QSvgRenderer(QByteArray(src.encode("utf-8")))
    app = QGuiApplication.instance()
    dpr = app.devicePixelRatio() if app else 1.0
    pm = QPixmap(round(size * dpr), round(size * dpr))
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    renderer.render(painter)
    painter.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, color: str, size: int = 20) -> QIcon:
    return QIcon(pixmap(name, color, size))


def qsize(size: int) -> QSize:
    return QSize(size, size)
