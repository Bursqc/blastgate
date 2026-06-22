"""
Main Blastgate application GUI
"""
import logging
import threading
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
from typing import Dict, Any, Optional, Tuple, List

import ttkbootstrap as tb
from ttkbootstrap.constants import *

from blastgate.config import load_config, save_config
from blastgate.gui.utils import apply_ui_scale, smart_center
from blastgate.gui.components.rounded_tile import RoundedTile
# animated_toggle imports removed - controls moved to NodeDetail
from blastgate.gui.components.dropdown_menu import AnimatedDropdown
from blastgate.gui.components import StatusIndicator
from blastgate.gui.dialogs import ConnectWindow, WifiWindow, NodeDetail, SettingsWindow, OtaWindow
from blastgate.network.client import HubClientUDP
from blastgate.network.engine import NetEngine
from blastgate.utils.helpers import to_float, to_int, now_ms, safe_node_id

logger = logging.getLogger(__name__)


class App(tb.Window):
    """Main Blastgate application window"""

    def __init__(self):
        # Load config
        self.cfg = load_config()
        if self.cfg.theme not in tb.themes.standard.STANDARD_THEMES:
            self.cfg.theme = "darkly"
            logger.warning("Invalid theme, using 'darkly'")

        super().__init__(themename=self.cfg.theme)
        apply_ui_scale(self, self.cfg.ui_scale)

        self.title("Blastgate")
        smart_center(self, 860, 540, scale=self.cfg.ui_scale)
        self.minsize(int(740 * self.cfg.ui_scale), int(460 * self.cfg.ui_scale))
        self.resizable(True, True)

        logger.info("Initializing Blastgate application")

        # Network client
        self.client = HubClientUDP(self.cfg)
        if self.cfg.preferred_hub_ip.strip():
            self.client.selected_ip = self.cfg.preferred_hub_ip.strip()
            logger.info("Using preferred hub IP: %s", self.cfg.preferred_hub_ip)

        # Network engine (background thread)
        self.net = NetEngine(self.client, self.cfg, self.after)
        self.net.set_status_callback(self._on_status_from_net)
        self.net.start()

        self._stop = threading.Event()

        # App state
        self.lockout: bool = False  # Hub manual overdrive active

        # Tiles management
        self._tiles: Dict[str, Dict[str, Any]] = {}
        self._last_nodes: Dict[str, Dict[str, Any]] = {}

        # Local mode tracking (user-set mode per node, used by NodeDetail UI)
        self._local_node_mode: Dict[str, int] = {}

        self._last_keep_set = set()
        self._refresh_busy = False

        # Windows management
        self._win_connect: Optional[ConnectWindow] = None
        self._win_wifi: Optional[WifiWindow] = None
        self._win_settings: Optional[SettingsWindow] = None
        self._win_ota: Optional[OtaWindow] = None
        self._node_windows: Dict[str, NodeDetail] = {}

        # Dropdown menu
        self._dropdown: Optional[AnimatedDropdown] = None

        # Cached status (from network thread)
        self._cached_status: Dict[str, Any] = {}
        self._cached_state: str = "OFFLINE"

        # Build UI
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<Configure>", lambda _e: self.after(140, self._reflow_tiles))

        # Auto-discover hub on startup (runs after 1s, non-blocking)
        self.after(1000, self._auto_discover_on_start)

        # Firewall check - after 5s, if hub still offline, check/fix UDP 8888 rule
        self.after(5000, self._check_firewall_once)

        logger.info("Blastgate application initialized successfully")

    def get_status_cached(self) -> Tuple[Dict[str, Any], str]:
        """Get cached status (thread-safe)"""
        return self._cached_status or {}, self._cached_state

    def _on_status_from_net(self, st: Dict[str, Any], state: str):
        """Status callback from network thread (called in UI thread via after())"""
        self._cached_status = st or {}
        self._cached_state = state or "OFFLINE"

        # Check for hub lockout (manual overdrive on hub)
        was_locked = self.lockout
        self.lockout = bool(int((st or {}).get("manualOverdrive", 0))) if st else False

        if self.lockout and not was_locked:
            logger.warning("Hub lockout detected (manualOverdrive=1)")
        elif not self.lockout and was_locked:
            logger.info("Hub lockout released")

        # Extract nodes
        nodes = (st.get("nodes", []) or []) if st else []
        nodes_online = [n for n in nodes if int(n.get("online", 0)) == 1]
        self._last_nodes = {safe_node_id(n): n for n in nodes if safe_node_id(n)}

        logger.debug("Status update: %d nodes online, state=%s, lockout=%s",
                    len(nodes_online), state, self.lockout)

        # Update UI
        self._apply_header_locking()
        self.var_status.set(state if st else "OFFLINE")

        # Update status indicator
        if state == "SEARCHING":
            self.status_indicator.set_status("searching")
        elif state == "OFFLINE" or not st:
            self.status_indicator.set_status("offline")
        elif state in ("LAN", "AP"):
            has_active = any(int(n.get("active", 0)) == 1 for n in nodes_online)
            if has_active:
                self.status_indicator.set_status("active")
            else:
                self.status_indicator.set_status("online")
        else:
            self.status_indicator.set_status("unknown")

        self._apply_nodes(nodes_online)

    # ---- Local config helpers ----
    def _get_local_node(self, node_id: str) -> Dict[str, Any]:
        """Get local node configuration"""
        if self.cfg.nodes is None:
            self.cfg.nodes = {}
        return self.cfg.nodes.get(node_id, {}) or {}

    def set_local_node(self, node_id: str, data: Dict[str, Any]):
        """Set local node configuration"""
        if self.cfg.nodes is None:
            self.cfg.nodes = {}
        cur = self.cfg.nodes.get(node_id, {}) or {}
        cur.update(data or {})
        self.cfg.nodes[node_id] = cur
        save_config(self.cfg)
        logger.info("Node config saved: %s", node_id)

    def set_local_node_mode(self, node_id: str, mode: int):
        """Set local mode for node (0=AUTO, 1=MANUAL) - used by NodeDetail"""
        self._local_node_mode[node_id] = mode
        logger.info("Local mode set: %s -> %s", node_id, "MANUAL" if mode == 1 else "AUTO")

    def get_local_node_mode(self, node_id: str) -> Optional[int]:
        """Get local mode for node, or None if not set"""
        return self._local_node_mode.get(node_id)

    def get_display_name(self, node_id: str, hub_name: str) -> str:
        """Get display name for node (local override or hub name)"""
        local = self._get_local_node(node_id)
        override = (local.get("name") or "").strip()
        return override if override else hub_name

    def rename_node(self, node_id: str, parent=None):
        """Rename node dialog"""
        parent = parent or self
        current = self.get_display_name(node_id, "(unassigned)")
        new_name = simpledialog.askstring(
            "Rename blastgate",
            f"New name for {node_id}:",
            initialvalue=current,
            parent=parent
        )

        if not new_name:
            return

        new_name = new_name.strip()
        if not new_name:
            return

        self.set_local_node(node_id, {"name": new_name})
        logger.info("Node renamed: %s -> %s", node_id, new_name)

        def ok():
            self._set_diag(f"Renamed on HUB [OK] ({node_id})")
            logger.info("Hub rename successful: %s", node_id)

        def err(e):
            logger.error("Hub rename failed: %s - %s", node_id, e)
            self._set_diag(f"Saved local [OK] | HUB rename error: {e}")

        self.net.send("rename", node_id, new_name, on_ok=ok, on_err=err)

    # ---- UI building ----
    def _build_ui(self):
        """Build main UI"""
        # Top bar
        self.top = ttk.Frame(self, padding=12)
        self.top.pack(fill="x")

        # Menu button (hamburger)
        self.btn_menu = ttk.Button(
            self.top,
            text="☰",
            width=3,
            bootstyle=SECONDARY,
            command=self._toggle_dropdown
        )
        self.btn_menu.pack(side="left")

        # Show offline nodes variable (used by settings)
        self.var_show_offline = tb.BooleanVar(value=False)

        ttk.Label(self.top, text="Blastgate", font=("Segoe UI", 18, "bold")).pack(side="left", padx=12)

        # Right side - status and lockout indicator
        self.right_box = ttk.Frame(self.top)
        self.right_box.pack(side="right")

        # Lockout indicator (shows when manual overdrive is active on hub)
        self.var_lockout = tb.StringVar(value="")
        self.lbl_lockout = ttk.Label(self.right_box, textvariable=self.var_lockout, bootstyle=DANGER, font=("Segoe UI", 11, "bold"))
        self.lbl_lockout.pack(side="right", padx=(10, 0))

        # Connection status indicator (colored dot)
        self.status_indicator = StatusIndicator(self.right_box, status="offline", size=12)
        self.status_indicator.pack(side="right", padx=(10, 0))

        self.var_status = tb.StringVar(value="OFFLINE")
        self.lbl_status = ttk.Label(self.right_box, textvariable=self.var_status, bootstyle=INFO)
        self.lbl_status.pack(side="right", padx=(5, 0))

        # Body (tiles area)
        self.body = ttk.Frame(self, padding=18)
        self.body.pack(fill="both", expand=True)

        # Hint (shown when no nodes)
        self.hint = ttk.Label(
            self.body,
            text="No online nodes.\n\n☰ → Settings → Connect Hub",
            justify="center",
            bootstyle=SECONDARY,
            font=("Segoe UI", 13),
        )
        self.hint.pack(expand=True)

        # Grid wrapper for tiles
        self.gridwrap = ttk.Frame(self.body)

        # Bottom status bar
        bottom = ttk.Frame(self, padding=(12, 0, 12, 12))
        bottom.pack(fill="x")
        self.var_diag = tb.StringVar(value="")
        ttk.Label(bottom, textvariable=self.var_diag, bootstyle=SECONDARY).pack(anchor="w")

        self._apply_header_locking()

    def _toggle_dropdown(self):
        """Toggle animated dropdown menu."""
        if self._dropdown is None:
            # Create dropdown on first use
            self._dropdown = AnimatedDropdown(
                self,
                items=[
                    ("Refresh", lambda: self.refresh_now(full=True)),
                    ("WiFi Setup", self.open_wifi),
                    ("Firmware Update", self.open_ota),
                    ("Settings", self.open_settings),
                    ("Setup Wizard", self.open_setup_wizard),
                    ("Exit", self.on_close),
                ],
                width=180,
                item_height=48,
            )

        # Get button position
        try:
            x = self.btn_menu.winfo_rootx()
            y = self.btn_menu.winfo_rooty() + self.btn_menu.winfo_height()
            self._dropdown.toggle(x, y)
        except tk.TclError as e:
            logger.debug("Failed to toggle dropdown: %s", e)

    def open_settings(self):
        """Open settings dialog."""
        if self._win_settings and self._win_settings.winfo_exists():
            self._win_settings.deiconify()
            self._win_settings.lift()
            self._win_settings.focus_force()
            return
        self._win_settings = SettingsWindow(self, self)
        logger.info("Opened settings window")

    def open_ota(self):
        """Open firmware update dialog."""
        if self._win_ota and self._win_ota.winfo_exists():
            self._win_ota.deiconify()
            self._win_ota.lift()
            self._win_ota.focus_force()
            return
        self._win_ota = OtaWindow(self, self)
        logger.info("Opened OTA window")

    def open_setup_wizard(self):
        """Open setup wizard."""
        from blastgate.gui.dialogs import SetupWizard
        try:
            wizard = SetupWizard(self, self)
            wizard.grab_set()  # Make modal
            logger.info("Opened setup wizard")
        except Exception as e:
            logger.error("Failed to open setup wizard: %s", e, exc_info=True)
            messagebox.showerror(
                "Error",
                f"Failed to open setup wizard:\n{e}",
                parent=self
            )

    def open_connect(self):
        """Open connection settings dialog"""
        if self._win_connect and self._win_connect.winfo_exists():
            self._win_connect.deiconify()
            self._win_connect.lift()
            self._win_connect.focus_force()
            return
        self._win_connect = ConnectWindow(self, self)
        logger.info("Opened connection window")

    def open_wifi(self):
        """Open WiFi settings dialog"""
        if self._win_wifi and self._win_wifi.winfo_exists():
            self._win_wifi.deiconify()
            self._win_wifi.lift()
            self._win_wifi.focus_force()
            return
        self._win_wifi = WifiWindow(self, self)
        logger.info("Opened WiFi window")

    def _open_node(self, node_id: str):
        """Open node detail dialog"""
        node_id = (node_id or "").strip()
        if not node_id:
            messagebox.showerror("Open", "Node nema ID (prazan).")
            return

        w = self._node_windows.get(node_id)
        if w and w.winfo_exists():
            w.deiconify()
            w.lift()
            w.focus_force()
            return

        w = NodeDetail(self, self, node_id)
        self._node_windows[node_id] = w
        logger.info("Opened node detail: %s", node_id)

    def _set_diag(self, txt: str):
        """Set diagnostic message"""
        self.var_diag.set((txt or "")[:220])

    def _apply_header_locking(self):
        """Apply UI locking based on lockout state"""
        if self.lockout:
            self.top.configure(bootstyle=DANGER)
            self.lbl_status.configure(bootstyle=DANGER)
            self.var_lockout.set("OVERDRIVE")
        else:
            self.top.configure(bootstyle=DEFAULT)
            self.lbl_status.configure(bootstyle=INFO)
            self.var_lockout.set("")

    def refresh_now(self, full: bool = False):
        """Trigger manual refresh"""
        if self._refresh_busy:
            return

        self._refresh_busy = True
        self._set_diag("Refreshing...")
        logger.info("Manual refresh triggered (full=%s)", full)

        def ok():
            self._set_diag("Refresh [OK]" if not full else "Refresh Full [OK]")
            self._refresh_busy = False
            logger.info("Refresh completed successfully")

        def err(e):
            self._set_diag(f"Refresh error: {e}")
            self._refresh_busy = False
            logger.error("Refresh failed: %s", e)

        self.net.send("refresh", full=full, on_ok=ok, on_err=err)

    # ---- Tiles layout ----
    def _calc_cols(self) -> int:
        """Calculate number of tile columns based on window width"""
        width = self.winfo_width()
        if width >= 1700:
            return 4
        if width >= 1350:
            return 3
        return 2

    def _create_tile(self, node_id: str) -> Dict[str, Any]:
        """Create new tile widget"""
        tile = RoundedTile(
            self.gridwrap,
            node_id=node_id,
            on_open=lambda nid=node_id: self._open_node(nid),
            on_rename=lambda nid=node_id: self.rename_node(nid, parent=self),
        )
        obj = {"tile": tile, "appeared": False}
        self._tiles[node_id] = obj
        logger.debug("Tile created: %s", node_id)
        return obj

    def _tile_colors(self, online: bool, gate_open: bool) -> Tuple[str, str, str]:
        """
        Calculate tile colors based on state.

        Colors:
        - Offline: dark gray
        - Gate OPEN: green
        - Gate CLOSED: red
        """
        if not online:
            # Offline - dark gray
            return ("#141414", "#1a1a1a", "#333333")

        if gate_open:
            # Gate OPEN = GREEN
            return ("#0f1d12", "#163a22", "#2f6a42")

        # Gate CLOSED = RED
        return ("#1d0f0f", "#3a1616", "#6a2f2f")

    def _update_tile(self, node: Dict[str, Any]):
        """Update tile with node data"""
        nid = safe_node_id(node)
        if not nid:
            return

        obj = self._tiles.get(nid) or self._create_tile(nid)
        tile: RoundedTile = obj["tile"]

        hub_name = (node.get("name") or "").strip() or "(unassigned)"
        name = self.get_display_name(nid, hub_name)

        online = int(node.get("online", 0)) == 1
        override = int(node.get("override", 0))
        cmd = {0: "AUTO", 1: "OPEN", 2: "CLOSE"}.get(override, str(override))
        active_flag = "ACTIVE" if int(node.get("active", 0)) == 1 else "IDLE"

        val = node.get("value", None)
        vtxt = "-"
        if val is not None:
            try:
                vtxt = f"{float(val):.3f}"
            except (ValueError, TypeError) as e:
                logger.debug("Failed to format node value: %s", e)
                vtxt = str(val)

        gate_open = int(node.get("gateOpen", 0)) == 1 if "gateOpen" in node else (override == 1)
        gate_state_txt = "OPEN" if gate_open else "CLOSED"

        tile.set_text(
            title=name,
            subtitle=nid,
            meta=f"{active_flag} • Gate: {gate_state_txt} • Cmd: {cmd} • Value: {vtxt}"
        )

        c1, c2, outline = self._tile_colors(online=online, gate_open=gate_open)
        tile.set_tile_style(c1, c2, outline=outline)

        if not obj["appeared"]:
            obj["appeared"] = True
            tile.fade_in(ms_total=220, steps=10)

    def _remove_missing_tiles(self, keep_ids: set):
        """Remove tiles for offline nodes"""
        dead = [nid for nid in list(self._tiles.keys()) if nid not in keep_ids]
        for nid in dead:
            try:
                self._tiles[nid]["tile"].destroy()
                logger.debug("Tile removed: %s", nid)
            except (tk.TclError, KeyError) as e:
                logger.debug("Failed to destroy tile: %s - %s", nid, e)
            self._tiles.pop(nid, None)


    def _reflow_tiles(self):
        """Re-layout tiles in grid"""
        if not self._tiles:
            return

        cols = self._calc_cols()
        i = 0
        for nid, obj in sorted(self._tiles.items(), key=lambda kv: kv[0]):
            r = i // cols
            c = i % cols
            try:
                obj["tile"].grid(row=r, column=c, sticky="nsew", padx=14, pady=14)
                self.gridwrap.grid_columnconfigure(c, weight=1)
            except tk.TclError as e:
                logger.debug("Failed to grid tile: %s - %s", nid, e)
            i += 1

    def _apply_nodes(self, online_nodes: List[Dict[str, Any]]):
        """Apply node updates to UI"""
        if not online_nodes:
            self.gridwrap.pack_forget()
            self.hint.pack(expand=True)
            self._remove_missing_tiles(set())
            self._last_keep_set = set()
            return

        self.hint.pack_forget()
        self.gridwrap.pack(fill="both", expand=True)

        keep = set()
        for n in online_nodes:
            nid = safe_node_id(n)
            if not nid:
                continue
            keep.add(nid)
            self._update_tile(n)

        self._remove_missing_tiles(keep)

        if keep != self._last_keep_set:
            self._last_keep_set = set(keep)
            self._reflow_tiles()

    # ---- Relay manual controls with safety ----
    def any_gate_open(self) -> bool:
        """Check if any gate is currently open"""
        for n in self._last_nodes.values():
            try:
                if int(n.get("online", 0)) != 1:
                    continue
                if "gateOpen" in n and int(n.get("gateOpen", 0)) == 1:
                    return True
                if int(n.get("override", 0)) == 1:
                    return True
            except (ValueError, TypeError, KeyError) as e:
                logger.debug("Failed to check gate state: %s", e)
        return False

    def relay_manual(self, mode: str):
        """Manual relay control with safety checks"""
        mode = (mode or "").strip().lower()

        if self.lockout:
            self._set_diag("LOCKED: HUB overdrive active")
            logger.warning("Relay command blocked: hub lockout active")
            return

        if mode == "on" and (not self.any_gate_open()):
            self._set_diag("Safety: RELAY ON blocked (no gate OPEN)")
            logger.warning("Relay ON blocked: no gates open (safety)")
            return

        self._set_diag(f"Relay -> {mode.upper()} (sending...)")
        logger.info("Relay command: %s", mode)

        def ok():
            self._set_diag(f"Relay -> {mode.upper()} [OK]")
            logger.info("Relay command successful: %s", mode)

        def err(e):
            self._set_diag(f"Relay error: {e}")
            logger.error("Relay command failed: %s - %s", mode, e)

        self.net.send("relay", mode, on_ok=ok, on_err=err)

    def _auto_discover_on_start(self) -> None:
        """Auto-discover hub on startup in background thread. If exactly one hub is found
        and no preferred IP is configured, auto-select it."""
        if self._cached_state not in ("OFFLINE", "SEARCHING"):
            return  # Already connected, skip

        def worker():
            try:
                hubs = self.client.discover_hubs()
                if not hubs:
                    logger.info("[AUTO-DISC] No hubs found on startup scan")
                    return
                if len(hubs) == 1:
                    ip = hubs[0]["ip"]
                    logger.info("[AUTO-DISC] Auto-selected hub: %s", ip)
                    self.cfg.preferred_hub_ip = ip
                    self.client.selected_ip = ip
                    self.client.best_ip = None
                    save_config(self.cfg)
                    self.after(0, lambda: self._set_diag(f"Hub found: {ip}"))
                else:
                    ips = ", ".join(h["ip"] for h in hubs)
                    logger.info("[AUTO-DISC] Multiple hubs found: %s — open Connection to select", ips)
                    self.after(0, lambda: self._set_diag(f"Multiple hubs found: {ips} — select in Connection"))
            except Exception as e:
                logger.debug("[AUTO-DISC] Discovery error: %s", e)

        threading.Thread(target=worker, daemon=True).start()

    def _check_firewall_once(self) -> None:
        """
        One-time startup check: if hub not found after 5s and firewall rule is missing,
        offer to add it automatically (UAC prompt on Windows).
        """
        from blastgate.utils.firewall import firewall_rule_exists, ensure_firewall_rule
        import platform

        if platform.system() != "Windows":
            return

        # Only bother if hub is still offline
        if self._cached_state not in ("OFFLINE", "SEARCHING"):
            return

        if firewall_rule_exists():
            return  # Rule OK, different problem

        logger.warning("Firewall rule missing and hub offline - prompting user")

        answer = messagebox.askyesno(
            "Windows Firewall",
            "Hub nije pronađen.\n\n"
            "Windows Firewall verovatno blokira UDP port 8888.\n\n"
            "Dodati izuzetak automatski? (traži Admin prava)\n\n"
            "Klikni DA → pojaviće se UAC prozor → klikni Da.",
            parent=self
        )
        if answer:
            ensure_firewall_rule()
            messagebox.showinfo(
                "Firewall",
                "Pravilo dodato.\n\nProgram će naći hub za nekoliko sekundi.",
                parent=self
            )

    def on_close(self):
        """Application shutdown"""
        logger.info("Shutting down application...")
        self._stop.set()

        try:
            self.net.stop()
            logger.info("Network engine stopped")
        except Exception as e:
            logger.error("Failed to stop network engine: %s", e)

        try:
            self.client.close()
            logger.info("Network client closed")
        except Exception as e:
            logger.error("Failed to close network client: %s", e)

        # Close all windows
        try:
            if self._win_connect and self._win_connect.winfo_exists():
                self._win_connect.destroy()
        except (AttributeError, tk.TclError) as e:
            logger.debug("Failed to destroy connect window: %s", e)

        try:
            if self._win_wifi and self._win_wifi.winfo_exists():
                self._win_wifi.destroy()
        except (AttributeError, tk.TclError) as e:
            logger.debug("Failed to destroy wifi window: %s", e)

        try:
            if self._win_settings and self._win_settings.winfo_exists():
                self._win_settings.destroy()
        except (AttributeError, tk.TclError) as e:
            logger.debug("Failed to destroy settings window: %s", e)

        try:
            for w in list(self._node_windows.values()):
                if w and w.winfo_exists():
                    w.destroy()
        except (AttributeError, tk.TclError) as e:
            logger.debug("Failed to destroy node windows: %s", e)

        try:
            self.destroy()
            logger.info("Application destroyed")
        except tk.TclError as e:
            logger.debug("Failed to destroy main window: %s", e)
