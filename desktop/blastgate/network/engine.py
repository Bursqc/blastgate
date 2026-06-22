"""
Network Engine - Background thread for non-blocking network operations

The NetEngine runs in a separate thread and handles:
- Periodic status polling from hub
- Command queue execution (gate, relay, config, etc.)
- Command deduplication (prevents click spam)
- Result callbacks to UI thread
- HUB_UPDATE broadcast listener for real-time sync

Threading Model:
- NetEngine runs in daemon background thread
- All UI callbacks executed via ui_after() in UI thread
- Command queue is thread-safe (Queue)
- Status updates posted to UI via callback
"""
import logging
import socket
import time
import threading
from typing import Callable, Optional, Tuple, Dict, Any
from queue import Queue, Empty

from ..models.config import AppConfig
from ..models.status import HubStatus
from ..exceptions import HubOfflineError, HubCommandError, NetworkError
from .client import HubClientUDP

logger = logging.getLogger(__name__)


def now_ms() -> int:
    """Get current time in milliseconds"""
    return int(time.time() * 1000)


class NetEngine:
    """
    Background network engine for non-blocking hub communication.

    Features:
    - Runs in separate daemon thread
    - Executes commands from queue
    - Periodic status polling
    - Command deduplication (250ms window)
    - Periodic IP selection refresh
    - Thread-safe UI callbacks

    Example:
        >>> engine = NetEngine(client, config, app.after)
        >>> engine.set_status_callback(on_status_update)
        >>> engine.start()
        >>> engine.send("gate", "BG-123", "open", on_ok=success_cb, on_err=error_cb)
    """

    def __init__(self, client: HubClientUDP, cfg: AppConfig, ui_after: Callable[[int, Callable], None]):
        """
        Initialize network engine

        Args:
            client: HubClientUDP instance
            cfg: Application configuration
            ui_after: UI thread scheduler function (e.g., tk.after)
        """
        self.client = client
        self.cfg = cfg
        self.ui_after = ui_after

        # Command queue: (kind, args, kwargs, on_ok_callback, on_err_callback)
        self._cmd_q: "Queue[Tuple[str, Tuple, Dict, Optional[Callable], Optional[Callable]]]" = Queue()
        self._stop = threading.Event()

        # Cached status (thread-safe read from UI)
        self._last_status: Dict[str, Any] = {}
        self._last_state_str: str = "OFFLINE"
        self._last_ip: Optional[str] = None

        # Command deduplication
        self._last_cmd_key: Optional[str] = None
        self._last_cmd_ms: int = 0
        self.dedup_window_ms = 250

        # Status update callback
        self._on_status: Optional[Callable[[Dict[str, Any], str], None]] = None

        # HUB_UPDATE broadcast listener socket
        self._broadcast_sock: Optional[socket.socket] = None
        self._force_poll = threading.Event()  # Trigger immediate poll

        # Auto-discovery when offline
        self._last_discovery_t: float = 0.0
        self.DISCOVERY_EVERY_S: float = 10.0

        logger.info("NetEngine initialized (poll_ms=%d, dedup_ms=%d)",
                   cfg.poll_ms, self.dedup_window_ms)

    def set_status_callback(self, cb: Callable[[Dict[str, Any], str], None]) -> None:
        """
        Set callback for status updates

        Args:
            cb: Callback function(status_dict, state_string)
        """
        self._on_status = cb
        logger.debug("Status callback registered")

    def get_cached_status(self) -> Tuple[Dict[str, Any], str]:
        """
        Get cached status (thread-safe, no network call)

        Returns:
            Tuple of (status_dict, state_string)
        """
        return self._last_status or {}, self._last_state_str

    def send(self, kind: str, *args, on_ok: Optional[Callable] = None,
             on_err: Optional[Callable] = None, **kwargs) -> None:
        """
        Queue command for execution (non-blocking)

        Args:
            kind: Command type ("gate", "relay", "rename", "cfg", "refresh",
                  "wifi_get", "wifi_set", "wifi_disconnect", "wifi_forget", "wifi_prov")
            *args: Command arguments
            on_ok: Success callback (executed in UI thread)
            on_err: Error callback (executed in UI thread)
            **kwargs: Additional keyword arguments

        Example:
            >>> engine.send("gate", "BG-123", "open",
            ...            on_ok=lambda: print("OK"),
            ...            on_err=lambda e: print(f"Error: {e}"))
        """
        self._cmd_q.put((kind, args, kwargs, on_ok, on_err))
        logger.debug("Queued command: %s (queue size: %d)", kind, self._cmd_q.qsize())

    def start(self) -> None:
        """Start network engine thread"""
        # Setup broadcast listener for HUB_UPDATE
        self._setup_broadcast_listener()

        thread = threading.Thread(target=self._run, daemon=True, name="NetEngine")
        thread.start()
        logger.info("NetEngine thread started")

    def _setup_broadcast_listener(self) -> None:
        """Setup UDP socket to listen for HUB_UPDATE broadcasts"""
        try:
            self._broadcast_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._broadcast_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._broadcast_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self._broadcast_sock.setblocking(False)  # Non-blocking
            self._broadcast_sock.bind(("", self.cfg.udp_port))
            logger.info("Broadcast listener ready on port %d", self.cfg.udp_port)
        except OSError as e:
            logger.warning("Failed to setup broadcast listener: %s (real-time sync disabled)", e)
            self._broadcast_sock = None

    def _check_broadcast(self) -> bool:
        """
        Check for HUB_UPDATE/HUB_HELLO/HUB_READY broadcasts (non-blocking)

        When we receive any hub broadcast, update the client's best_ip
        so STATUS polling uses the correct address.

        Returns:
            True if HUB_UPDATE was received (triggers immediate poll)
        """
        if not self._broadcast_sock:
            return False

        try:
            data, addr = self._broadcast_sock.recvfrom(256)
            msg = data.decode("utf-8", errors="ignore").strip()
            sender_ip = addr[0]

            # Any hub broadcast tells us the hub's IP
            if msg.startswith("HUB_") or msg.startswith("BLASTGATE_HUB"):
                # Update client's known IP from broadcast source
                if sender_ip != "0.0.0.0" and sender_ip != "255.255.255.255":
                    if self.client.best_ip != sender_ip:
                        logger.info("Hub IP discovered via broadcast: %s (was %s)",
                                   sender_ip, self.client.best_ip)
                        self.client.best_ip = sender_ip
                        self.client.last_ok_ip = sender_ip

            if msg == "HUB_UPDATE":
                logger.info("HUB_UPDATE from %s - triggering refresh", sender_ip)
                return True

        except BlockingIOError:
            pass  # No data available (expected in non-blocking mode)
        except OSError as e:
            logger.debug("Broadcast recv error: %s", e)

        return False

    def stop(self) -> None:
        """Stop network engine thread"""
        self._stop.set()

        # Close broadcast listener
        if self._broadcast_sock:
            try:
                self._broadcast_sock.close()
            except OSError:
                pass
            self._broadcast_sock = None

        logger.info("NetEngine stop requested")

    def _dedup_ok(self, key: str) -> bool:
        """
        Check if command should be executed (deduplication)

        Args:
            key: Command deduplication key

        Returns:
            True if command should execute, False if duplicate
        """
        ms = now_ms()
        if self._last_cmd_key == key and (ms - self._last_cmd_ms) < self.dedup_window_ms:
            logger.debug("Deduped command: %s (within %dms window)", key, self.dedup_window_ms)
            return False

        self._last_cmd_key = key
        self._last_cmd_ms = ms
        return True

    def _ui(self, fn: Callable) -> None:
        """
        Schedule callback in UI thread (best-effort)

        Args:
            fn: Callback function to execute in UI thread
        """
        try:
            self.ui_after(0, fn)
        except Exception as e:
            logger.warning("Failed to schedule UI callback: %s", e)

    def _execute_command(self, kind: str, args: Tuple, kwargs: Dict,
                        on_ok: Optional[Callable], on_err: Optional[Callable]) -> None:
        """
        Execute single command

        Args:
            kind: Command type
            args: Command arguments
            kwargs: Keyword arguments
            on_ok: Success callback
            on_err: Error callback
        """
        try:
            if kind == "gate":
                node_id, gate = args
                key = f"gate:{node_id}:{gate}"
                if self._dedup_ok(key):
                    self.client.set_node_gate(node_id, gate)
                    logger.info("Command executed: set_gate %s -> %s", node_id, gate)
                    if on_ok:
                        self._ui(on_ok)

            elif kind == "relay":
                mode = args[0]
                key = f"relay:{mode}"
                if self._dedup_ok(key):
                    self.client.set_relay(mode)
                    logger.info("Command executed: set_relay -> %s", mode)
                    if on_ok:
                        self._ui(on_ok)

            elif kind == "mode":
                node_id, mode = args
                key = f"mode:{node_id}:{mode}"
                if self._dedup_ok(key):
                    self.client.set_node_mode(node_id, mode)
                    logger.info("Command executed: set_mode %s -> %s", node_id, mode)
                    if on_ok:
                        self._ui(on_ok)

            elif kind == "rename":
                node_id, name = args
                key = f"rename:{node_id}:{name}"
                if self._dedup_ok(key):
                    self.client.set_node_name(node_id, name)
                    logger.info("Command executed: rename %s -> %s", node_id, name)
                    if on_ok:
                        self._ui(on_ok)

            elif kind == "cfg":
                node_id, payload = args
                key = f"cfg:{node_id}"
                if self._dedup_ok(key):
                    self.client.set_node_config(node_id, payload)
                    logger.info("Command executed: set_config %s", node_id)
                    if on_ok:
                        self._ui(on_ok)

            elif kind == "nodecfg_get":
                node_id = args[0]
                cfg_data = self.client.get_node_config(node_id)
                logger.info("Command executed: get_node_config %s", node_id)
                if on_ok:
                    # Pass config data to callback
                    self._ui(lambda data=cfg_data: on_ok(data))

            elif kind == "refresh":
                full = bool(kwargs.get("full", False))
                key = f"refresh:{int(full)}"
                if self._dedup_ok(key):
                    st = self.client.refresh_status(full=full)
                    logger.info("Command executed: refresh (full=%s)", full)
                    # Update cached status
                    self._last_status = st.model_dump()
                    if on_ok:
                        self._ui(on_ok)

            elif kind == "wifi_get":
                wifi_info = self.client.wifi_get()
                logger.info("Command executed: wifi_get")
                if on_ok:
                    # Pass wifi_info to callback
                    self._ui(lambda info=wifi_info: on_ok(info.model_dump()))

            elif kind == "wifi_set":
                ssid, pw = args
                self.client.wifi_set(ssid, pw)
                logger.info("Command executed: wifi_set (SSID=%s)", ssid)
                if on_ok:
                    self._ui(on_ok)

            elif kind == "wifi_disconnect":
                self.client.wifi_disconnect()
                logger.info("Command executed: wifi_disconnect")
                if on_ok:
                    self._ui(on_ok)

            elif kind == "wifi_forget":
                self.client.wifi_forget()
                logger.info("Command executed: wifi_forget")
                if on_ok:
                    self._ui(on_ok)

            elif kind == "wifi_prov":
                self.client.wifi_prov()
                logger.info("Command executed: wifi_prov")
                if on_ok:
                    self._ui(on_ok)

            else:
                logger.warning("Unknown command type: %s", kind)

        except (HubOfflineError, HubCommandError, NetworkError) as e:
            logger.error("Command failed (%s): %s", kind, e)
            if on_err:
                self._ui(lambda err=e: on_err(err))

        except Exception as e:
            logger.error("Unexpected error executing command (%s): %s", kind, e, exc_info=True)
            if on_err:
                self._ui(lambda err=e: on_err(err))

    def _run_discovery(self) -> None:
        """
        Run UDP broadcast discovery to find hub when offline.
        Called from background thread - blocking for discovery_timeout_s seconds.
        """
        from .discovery import discover_hubs

        logger.info("Auto-discovery: searching for hub...")

        # Notify UI: searching
        if self._on_status:
            self._ui(lambda: self._on_status({}, "SEARCHING"))

        try:
            # Use a short timeout (2s) for auto-discovery
            quick_cfg = self.cfg.model_copy(update={"discovery_timeout_s": 2.0})
            hubs = discover_hubs(quick_cfg, selected_ip=self.client.selected_ip)

            if hubs:
                ip = hubs[0]["ip"]
                logger.info("Auto-discovery: found hub at %s", ip)
                self.client.best_ip = ip
                self.client.last_ok_ip = ip
            else:
                logger.info("Auto-discovery: no hub found")

        except Exception as e:
            logger.warning("Auto-discovery failed: %s", e)

    def _run(self) -> None:
        """
        Main engine loop (runs in background thread)

        Loop performs:
        1. Check for HUB_UPDATE broadcasts (real-time sync)
        2. Execute all pending commands from queue
        3. Periodic best IP refresh (every 4s)
        4. Auto-discovery when offline (every 10s)
        5. Periodic status polling (configurable interval)
        """
        last_pick = 0.0
        last_poll = 0.0

        logger.info("NetEngine loop started")

        while not self._stop.is_set():
            # 0) Check for HUB_UPDATE broadcasts (real-time sync from other clients)
            if self._check_broadcast():
                # Force immediate poll on next iteration
                last_poll = 0.0
                logger.debug("HUB_UPDATE received - forcing immediate poll")

            # 1) Execute all available commands quickly
            try:
                kind, args, kwargs, on_ok, on_err = self._cmd_q.get_nowait()
                self._execute_command(kind, args, kwargs, on_ok, on_err)
            except Empty:
                pass  # No commands in queue

            # 2) Periodic best IP selection
            # Fast (4s) when offline so we reconnect quickly,
            # slow (30s) when already connected to avoid AP ping timeouts.
            now = time.time()
            pick_interval = 4.0 if not self.client.best_ip else 30.0
            if (now - last_pick) > pick_interval:
                try:
                    ip, state = self.client.pick_best_ip()
                    self._last_ip = ip
                    self._last_state_str = state if ip else "OFFLINE"
                    logger.debug("IP selection: %s (%s)", ip or "none", state)
                except Exception as e:
                    logger.warning("IP selection failed: %s", e)
                    self._last_ip = None
                    self._last_state_str = "OFFLINE"

                last_pick = now

            # 3) Auto-discovery when offline (every 10s)
            if self._last_state_str == "OFFLINE":
                if (now - self._last_discovery_t) >= self.DISCOVERY_EVERY_S:
                    self._last_discovery_t = now
                    self._run_discovery()

            # 4) Periodic status polling
            poll_every = max(0.25, float(self.cfg.poll_ms) / 1000.0)
            if (now - last_poll) >= poll_every:
                last_poll = now

                try:
                    # Ensure we have an IP before polling
                    if not (self.client.best_ip or self.client.last_ok_ip):
                        ip, state = self.client.pick_best_ip()
                        self._last_ip = ip
                        self._last_state_str = state if ip else "OFFLINE"

                    # Poll status if we have IP
                    if self.client.best_ip or self.client.last_ok_ip:
                        st = self.client.get_status_fast()
                        self._last_status = st.model_dump()

                        # Auto-save hub IP if it changed (DHCP can change IP)
                        current_ip = self.client.best_ip or self.client.last_ok_ip
                        if current_ip and current_ip != self.cfg.preferred_hub_ip:
                            logger.info("Hub IP changed: %s -> %s (saving to config)",
                                        self.cfg.preferred_hub_ip, current_ip)
                            self.cfg.preferred_hub_ip = current_ip
                            self.cfg.hub_lan_ip = current_ip
                            self.client.selected_ip = current_ip
                            try:
                                from ..config import save_config
                                save_config(self.cfg)
                            except Exception as e:
                                logger.warning("Failed to save updated hub IP: %s", e)

                        # Notify UI callback
                        if self._on_status:
                            state_str = self._last_state_str
                            self._ui(lambda st=st.model_dump(), s=state_str: self._on_status(st, s))

                except HubOfflineError:
                    logger.debug("Hub offline during status poll")
                    self._last_state_str = "OFFLINE"
                    self._last_status = {}
                    if self._on_status:
                        self._ui(lambda: self._on_status({}, "OFFLINE"))

                except Exception as e:
                    logger.warning("Status poll failed: %s", e)
                    self._last_state_str = "OFFLINE"
                    self._last_status = {}
                    if self._on_status:
                        self._ui(lambda: self._on_status({}, "OFFLINE"))

            # Small sleep to prevent busy-waiting
            time.sleep(0.01)

        logger.info("NetEngine loop stopped")
