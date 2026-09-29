"""
Glue between the (unchanged) network layer and the Qt UI.

NetEngine calls ui_after(ms, fn) from its worker thread; a queued Qt signal
moves the call onto the GUI thread, exactly like tk.after() did before.
"""
import logging
import threading
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, QTimer, Signal

from ..fake_hub import DEMO_IP, FakeHub, FakeHubClient
from ..hub_http import HubHttp
from ..models.config import AppConfig
from ..network import NetEngine
from ..network.client import HubClientUDP
from .state import diff_events

logger = logging.getLogger(__name__)

MAX_EVENTS = 500


class _Bridge(QObject):
    call = Signal(object)


class Controller(QObject):
    status_changed = Signal(dict, str)   # hub status dict, connection state
    event_added = Signal(object)         # (datetime, tone, text)

    def __init__(self, cfg: AppConfig, demo: bool = False) -> None:
        super().__init__()
        self.cfg = cfg
        self.demo_hub: Optional[FakeHub] = FakeHub() if demo else None
        if self.demo_hub:
            cfg.preferred_hub_ip = DEMO_IP      # in memory only (demo uses a temp config file)
            self.client: HubClientUDP = FakeHubClient(cfg, self.demo_hub)
        else:
            self.client = HubClientUDP(cfg)
        if cfg.preferred_hub_ip.strip():
            self.client.selected_ip = cfg.preferred_hub_ip.strip()
        self.http = HubHttp(self.demo_hub)

        self._bridge = _Bridge()
        self._bridge.call.connect(self._run_on_ui)
        self.net = NetEngine(self.client, cfg, self._ui_after)
        self.net.set_status_callback(self._on_status)

        self.status: Dict[str, Any] = {}
        self.state: str = "OFFLINE"
        self.updated_at: Optional[datetime] = None
        self.events: List[Tuple[datetime, str, str]] = []

    # ---------------------------------------------------------- threading
    def _ui_after(self, ms: int, fn: Callable) -> None:
        self._bridge.call.emit((ms, fn))

    def _run_on_ui(self, item: Tuple[int, Callable]) -> None:
        ms, fn = item
        if ms:
            QTimer.singleShot(ms, fn)
        else:
            fn()

    def run_bg(self, work: Callable[[], Any], on_ok: Optional[Callable[[Any], None]] = None,
               on_err: Optional[Callable[[Exception], None]] = None) -> None:
        """Run blocking work (HTTP, discovery, OTA) off the GUI thread."""
        def worker() -> None:
            try:
                result = work()
                if on_ok:
                    self._ui_after(0, lambda r=result: on_ok(r))
            except Exception as e:  # noqa: BLE001 — surfaced to the user
                logger.warning("Background task failed: %s", e)
                if on_err:
                    self._ui_after(0, lambda err=e: on_err(err))
        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------- status
    def start(self) -> None:
        self.net.start()

    def stop(self) -> None:
        self.net.stop()
        self.client.close()

    def _on_status(self, st: Dict[str, Any], state: str) -> None:
        prev = self.status
        self.status = st or {}
        self.state = state or "OFFLINE"
        if st:
            self.updated_at = datetime.now()
        for ev in diff_events(prev, self.status):
            self.add_event(ev[1], ev[2], ev[0])
        self.status_changed.emit(self.status, self.state)

    def add_event(self, tone: str, text: str, when: Optional[datetime] = None) -> None:
        ev = (when or datetime.now(), tone, text)
        self.events.append(ev)
        del self.events[:-MAX_EVENTS]
        self.event_added.emit(ev)

    @property
    def lockout(self) -> bool:
        return bool(int(self.status.get("manualOverdrive", 0) or 0)) if self.status else False

    def node(self, node_id: str) -> Optional[Dict[str, Any]]:
        return next((n for n in self.status.get("nodes", []) or [] if n.get("id") == node_id), None)

    def hub_ip(self) -> Optional[str]:
        return self.client.best_ip or self.client.last_ok_ip or self.cfg.preferred_hub_ip.strip() or None

    # ----------------------------------------------------------- commands
    def send(self, kind: str, *args, on_ok: Optional[Callable] = None,
             on_err: Optional[Callable] = None, log: str = "", **kwargs) -> None:
        """Queue a hub command; optional log text goes to the event list on success."""
        def ok(*a) -> None:
            if log:
                self.add_event("info", log)
            if on_ok:
                on_ok(*a)
        self.net.send(kind, *args, on_ok=ok, on_err=on_err, **kwargs)
