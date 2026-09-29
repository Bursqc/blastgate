"""
Color tokens + QSS for the Blastgate UI.

Semantic colors (open/closed/warning/error) are the same in every theme;
only surfaces and text change between dark and light.
"""
from typing import Dict

DARK: Dict[str, str] = {
    "bg": "#0c161e",
    "sidebar": "#0e1a23",
    "card": "#122029",
    "card_hi": "#16272f",
    "border": "#1f3340",
    "text": "#e6edf3",
    "muted": "#8aa0b2",
    "track": "#23343f",
    "accent": "#22d3ee",
    "accent_text": "#062a33",
    "nav_active": "#113845",
}

LIGHT: Dict[str, str] = {
    "bg": "#eef2f5",
    "sidebar": "#e3e9ee",
    "card": "#ffffff",
    "card_hi": "#f5f8fa",
    "border": "#d3dce3",
    "text": "#0f1a22",
    "muted": "#5a6c7a",
    "track": "#dde5eb",
    "accent": "#0891b2",
    "accent_text": "#ffffff",
    "nav_active": "#cfeaf1",
}

SEMANTIC: Dict[str, str] = {
    "success": "#22c55e",   # gate open / machine running / suction on
    "warning": "#fbbf24",   # moving / manual / warning
    "danger": "#ef4444",    # error / offline / gate closed command
    "info": "#38bdf8",      # AUTO
    "idle": "#8aa0b2",      # idle / unknown
}

THEMES = {"dark": DARK, "light": LIGHT}

_current: Dict[str, str] = {}


def palette(name: str) -> Dict[str, str]:
    p = dict(THEMES.get(name, DARK))
    p.update(SEMANTIC)
    return p


def set_current(p: Dict[str, str]) -> None:
    _current.clear()
    _current.update(p)


def c(key: str) -> str:
    """Color of the active theme (custom-painted widgets read colors here)."""
    return _current.get(key) or palette("dark")[key]


def qss(p: Dict[str, str], scale: float = 1.0) -> str:
    """Application stylesheet. Widgets pick variants via dynamic properties."""
    def px(v: float) -> str:
        return f"{max(1, round(v * scale))}px"

    return f"""
* {{ font-family: "Segoe UI"; color: {p['text']}; }}
QWidget {{ background: transparent; font-size: {px(14)}; }}
QMainWindow, QDialog, #Root {{ background: {p['bg']}; }}
QToolTip {{ background: {p['card_hi']}; color: {p['text']}; border: 1px solid {p['border']}; padding: 4px; }}

#Sidebar {{ background: {p['sidebar']}; border-right: 1px solid {p['border']}; }}
#AppTitle {{ font-size: {px(17)}; font-weight: 700; letter-spacing: 0.5px; }}
QPushButton#NavButton {{
    text-align: left; padding: {px(12)} {px(18)}; border: none; border-radius: 0;
    font-size: {px(16)}; color: {p['muted']}; background: transparent;
    border-left: 3px solid transparent;
}}
QPushButton#NavButton:hover {{ color: {p['text']}; background: {p['card']}; }}
QPushButton#NavButton:checked {{ color: {p['accent']}; background: {p['nav_active']}; border-left: 3px solid {p['accent']}; }}

#PageTitle {{ font-size: {px(30)}; font-weight: 600; }}
#PageSubtitle {{ color: {p['muted']}; font-size: {px(14)}; }}
#SectionTitle {{ font-size: {px(19)}; font-weight: 600; }}
#Muted {{ color: {p['muted']}; }}
#Small {{ color: {p['muted']}; font-size: {px(12)}; }}
#BigValue {{ font-size: {px(40)}; font-weight: 700; }}
#MidValue {{ font-size: {px(18)}; font-weight: 600; }}
#TileTitle {{ font-size: {px(19)}; font-weight: 600; }}

QFrame#Card {{ background: {p['card']}; border: 1px solid {p['border']}; border-radius: 10px; }}
QFrame#Card:hover[clickable="true"] {{ border: 1px solid {p['accent']}; }}
QFrame#Inset {{ background: {p['card_hi']}; border: 1px solid {p['border']}; border-radius: 8px; }}
QFrame#Divider {{ background: {p['border']}; max-height: 1px; min-height: 1px; }}
QFrame#VDivider {{ background: {p['border']}; max-width: 1px; min-width: 1px; }}

QFrame#Banner[tone="warning"] {{ background: rgba(251,191,36,0.12); border: 1px solid {p['warning']}; border-radius: 8px; }}
QFrame#Banner[tone="danger"]  {{ background: rgba(239,68,68,0.12);  border: 1px solid {p['danger']};  border-radius: 8px; }}
QFrame#Banner[tone="success"] {{ background: rgba(34,197,94,0.12);  border: 1px solid {p['success']}; border-radius: 8px; }}
QFrame#Banner[tone="info"]    {{ background: rgba(56,189,248,0.12); border: 1px solid {p['info']};    border-radius: 8px; }}

QPushButton {{
    background: transparent; border: 1px solid {p['border']}; border-radius: 7px;
    padding: {px(8)} {px(16)}; font-size: {px(14)};
}}
QPushButton:hover {{ border-color: {p['muted']}; background: {p['card_hi']}; }}
QPushButton:disabled {{ color: {p['muted']}; border-color: {p['border']}; background: transparent; }}
QPushButton[variant="primary"] {{ background: {p['accent']}; color: {p['accent_text']}; border: 1px solid {p['accent']}; font-weight: 600; }}
QPushButton[variant="primary"]:hover {{ background: {p['accent']}; border-color: {p['text']}; }}
QPushButton[variant="primary"]:disabled {{ background: {p['track']}; color: {p['muted']}; border-color: {p['track']}; }}
QPushButton[variant="outline"] {{ border: 1px solid {p['accent']}; color: {p['accent']}; }}
QPushButton[variant="danger"]  {{ border: 1px solid {p['danger']};  color: {p['danger']}; }}
QPushButton[variant="ghost"] {{ border: none; padding: {px(4)} {px(8)}; color: {p['muted']}; font-size: {px(18)}; }}
QPushButton[variant="ghost"]:hover {{ color: {p['text']}; background: {p['card_hi']}; }}

/* Segmented choice buttons (AUTO / MANUAL, OPEN / CLOSE, relay) */
QPushButton[seg="true"] {{ padding: {px(9)} {px(14)}; font-weight: 600; color: {p['muted']}; }}
QPushButton[seg="true"][tone="info"]:checked    {{ color: {p['info']};    border: 1px solid {p['info']};    background: rgba(56,189,248,0.10); }}
QPushButton[seg="true"][tone="warning"]:checked {{ color: {p['warning']}; border: 1px solid {p['warning']}; background: rgba(251,191,36,0.10); }}
QPushButton[seg="true"][tone="success"]:checked {{ color: {p['success']}; border: 1px solid {p['success']}; background: rgba(34,197,94,0.10); }}
QPushButton[seg="true"][tone="danger"]:checked  {{ color: {p['danger']};  border: 1px solid {p['danger']};  background: rgba(239,68,68,0.10); }}
QPushButton[seg="true"][pending="true"] {{ border-style: dashed; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {p['bg']}; border: 1px solid {p['border']}; border-radius: 6px;
    padding: {px(6)} {px(10)}; selection-background-color: {p['accent']};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border: 1px solid {p['accent']}; }}
QComboBox QAbstractItemView {{ background: {p['card']}; border: 1px solid {p['border']}; selection-background-color: {p['nav_active']}; }}
QCheckBox {{ spacing: {px(8)}; }}
QCheckBox::indicator {{ width: {px(18)}; height: {px(18)}; border: 1px solid {p['border']}; border-radius: 4px; background: {p['bg']}; }}
QCheckBox::indicator:checked {{ background: {p['accent']}; border-color: {p['accent']}; }}
QSlider::groove:horizontal {{ height: {px(8)}; background: {p['track']}; border-radius: 4px; }}
QSlider::sub-page:horizontal {{ background: {p['warning']}; border-radius: 4px; }}
QSlider::handle:horizontal {{ width: {px(6)}; margin: -{px(6)} 0; background: {p['text']}; border-radius: 2px; }}
QProgressBar {{ background: {p['track']}; border: none; border-radius: 4px; height: {px(8)}; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {p['accent']}; border-radius: 4px; }}

QTabBar::tab {{ padding: {px(8)} {px(18)}; color: {p['muted']}; border: none; border-bottom: 2px solid transparent; font-size: {px(15)}; }}
QTabBar::tab:selected {{ color: {p['accent']}; border-bottom: 2px solid {p['accent']}; }}
QTabWidget::pane {{ border: none; }}

QTableWidget {{ background: transparent; border: none; gridline-color: {p['border']}; }}
QTableWidget::item {{ padding: {px(6)}; border-bottom: 1px solid {p['border']}; }}
QTableWidget::item:selected {{ background: {p['nav_active']}; color: {p['text']}; }}
QHeaderView::section {{ background: transparent; color: {p['muted']}; border: none; border-bottom: 1px solid {p['border']}; padding: {px(8)}; font-size: {px(13)}; }}

QScrollArea {{ border: none; }}
QScrollBar:vertical {{ background: transparent; width: {px(10)}; }}
QScrollBar::handle:vertical {{ background: {p['track']}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QMenu {{ background: {p['card']}; border: 1px solid {p['border']}; padding: 4px; }}
QMenu::item {{ padding: {px(6)} {px(18)}; border-radius: 4px; }}
QMenu::item:selected {{ background: {p['nav_active']}; }}
QTextEdit, QPlainTextEdit {{ background: {p['bg']}; border: 1px solid {p['border']}; border-radius: 6px; }}
"""
