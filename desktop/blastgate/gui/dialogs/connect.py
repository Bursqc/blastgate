"""
Connection settings dialog for Blastgate hub discovery and configuration
"""
import logging
import threading
import tkinter as tk
from tkinter import ttk
from typing import Tuple, TYPE_CHECKING

import ttkbootstrap as tb
from ttkbootstrap.constants import *

from blastgate.gui.utils import apply_ui_scale, smart_center
from blastgate.gui.components.animated_toggle import TwoStateToggle
from blastgate.network.client import HubClientUDP
from blastgate.config import save_config
from blastgate.utils.validators import is_valid_ipv4
from blastgate.utils.helpers import to_int, to_float

if TYPE_CHECKING:
    from blastgate.gui.app import App

logger = logging.getLogger(__name__)


class ConnectWindow(tb.Toplevel):
    """Hub connection settings and discovery dialog"""

    def __init__(self, master, app: "App"):
        super().__init__(master)
        self.app = app
        self.cfg = app.cfg
        self.client = app.client

        apply_ui_scale(self, self.cfg.ui_scale)
        self.title("Hub Connection")
        smart_center(self, 680, 540, scale=self.cfg.ui_scale)
        self.minsize(int(580 * self.cfg.ui_scale), int(440 * self.cfg.ui_scale))
        self.resizable(True, True)

        logger.info("ConnectWindow opened")

        self.wrap = ttk.Frame(self, padding=18)
        self.wrap.pack(fill="both", expand=True)

        # Header
        ttk.Label(self.wrap, text="Hub Connection", font=("Segoe UI", 18, "bold")).pack(anchor="w")

        # Mode toggle (AUTO/MANUAL)
        mode_frame = ttk.Frame(self.wrap)
        mode_frame.pack(fill="x", pady=(12, 0))
        ttk.Label(mode_frame, text="Mode:", bootstyle=SECONDARY).pack(side="left", padx=(0, 12))
        self.mode_toggle = TwoStateToggle(
            mode_frame,
            width=160,
            height=32,
            left_color="#2a9fd6",
            right_color="#f0ad4e",
            inactive_color="#3a3a3a",
            on_change=self._on_mode_change,
            initial_state="left",
            labels=("AUTO", "MANUAL"),
        )
        self.mode_toggle.pack(side="left")

        # AUTO mode frame (scan/detect)
        self.auto_frame = ttk.Frame(self.wrap)
        self._build_auto_ui()

        # MANUAL mode frame (detailed settings)
        self.manual_frame = ttk.Frame(self.wrap)
        self._build_manual_ui()

        # Message label
        self.var_msg = tb.StringVar(value="")
        ttk.Label(self.wrap, textvariable=self.var_msg, bootstyle=INFO).pack(anchor="w", pady=(12, 0))

        # Close button
        btn_frame = ttk.Frame(self.wrap)
        btn_frame.pack(fill="x", pady=(12, 0))
        ttk.Button(btn_frame, text="Close", bootstyle=SECONDARY, command=self._close).pack(side="right")

        # Start in AUTO mode
        self._show_auto_mode()

        self._scan_busy = False
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _build_auto_ui(self):
        """Build AUTO mode UI (scan and detect)"""
        ttk.Label(self.auto_frame, text="Automatska detekcija HUB-a", bootstyle=SECONDARY).pack(anchor="w", pady=(0, 12))

        # Scan results
        results = ttk.Labelframe(self.auto_frame, text="Detected Hubs", padding=12)
        results.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(results, height=8)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(results, orient="vertical", command=self.listbox.yview)
        sb.pack(side="right", fill="y")
        self.listbox.configure(yscrollcommand=sb.set)

        # Buttons
        btn_row = ttk.Frame(self.auto_frame)
        btn_row.pack(fill="x", pady=(12, 0))
        self.btn_scan = ttk.Button(btn_row, text="Scan", bootstyle=PRIMARY, command=self.on_scan)
        self.btn_scan.pack(side="left")
        self.btn_use = ttk.Button(btn_row, text="Use selected", bootstyle=SUCCESS, command=self.on_use_selected)
        self.btn_use.pack(side="left", padx=12)
        self.btn_test_auto = ttk.Button(btn_row, text="Test", bootstyle=SECONDARY, command=self.on_test)
        self.btn_test_auto.pack(side="left")

    def _build_manual_ui(self):
        """Build MANUAL mode UI (detailed settings)"""
        ttk.Label(self.manual_frame, text="Ručna konfiguracija", bootstyle=SECONDARY).pack(anchor="w", pady=(0, 12))

        form = ttk.Labelframe(self.manual_frame, text="Settings", padding=14)
        form.pack(fill="x")

        self.v_pref = tb.StringVar(value=self.cfg.preferred_hub_ip or "")
        self.v_lan = tb.StringVar(value=self.cfg.hub_lan_ip)
        self.v_ap = tb.StringVar(value=self.cfg.hub_ap_ip)
        self.v_port = tb.StringVar(value=str(self.cfg.udp_port))
        self.v_timeout = tb.StringVar(value=str(self.cfg.timeout_s))
        self.v_disc = tb.StringVar(value=str(self.cfg.discovery_timeout_s))
        self.v_autoap = tb.BooleanVar(value=bool(self.cfg.auto_ap_detect))

        def row(r, label, var, hint, entry=True):
            ttk.Label(form, text=label).grid(row=r, column=0, sticky="w", pady=6)
            if entry:
                ttk.Entry(form, textvariable=var, width=24).grid(row=r, column=1, sticky="w", padx=12, pady=6)
            else:
                ttk.Checkbutton(form, variable=var, bootstyle="round-toggle")\
                    .grid(row=r, column=1, sticky="w", padx=12, pady=6)
            ttk.Label(form, text=hint, bootstyle=SECONDARY).grid(row=r, column=2, sticky="w", padx=8, pady=6)

        row(0, "Preferred HUB IP", self.v_pref, "Prioritetni IP")
        row(1, "LAN IP", self.v_lan, "IP na ruteru")
        row(2, "AP IP", self.v_ap, "IP na AP modu")
        row(3, "UDP Port", self.v_port, "Default 8888")
        row(4, "Timeout (s)", self.v_timeout, "UDP timeout")
        row(5, "Discovery (s)", self.v_disc, "Scan timeout")
        row(6, "Auto-detect AP", self.v_autoap, "", entry=False)
        form.grid_columnconfigure(2, weight=1)

        # Buttons
        btn_row = ttk.Frame(self.manual_frame)
        btn_row.pack(fill="x", pady=(12, 0))
        ttk.Button(btn_row, text="Save", bootstyle=SUCCESS, command=self.on_save).pack(side="left")
        ttk.Button(btn_row, text="Test", bootstyle=PRIMARY, command=self.on_test).pack(side="left", padx=12)

    def _on_mode_change(self, state: str):
        """Handle mode toggle change"""
        if state == "left":
            self._show_auto_mode()
        else:
            self._show_manual_mode()

    def _show_auto_mode(self):
        """Show AUTO mode UI"""
        self.manual_frame.pack_forget()
        self.auto_frame.pack(fill="both", expand=True, pady=(16, 0))
        logger.debug("Switched to AUTO mode")

    def _show_manual_mode(self):
        """Show MANUAL mode UI"""
        self.auto_frame.pack_forget()
        self.manual_frame.pack(fill="both", expand=True, pady=(16, 0))
        logger.debug("Switched to MANUAL mode")

    def _close(self):
        """Close window and cleanup"""
        try:
            self.app._win_connect = None
        except (AttributeError, tk.TclError) as e:
            logger.debug("Failed to cleanup window reference: %s", e)

        try:
            self.destroy()
        except tk.TclError as e:
            logger.debug("Failed to destroy ConnectWindow: %s", e)

    def _apply_to_cfg(self) -> Tuple[bool, str]:
        """Validate and apply settings to config"""
        pref = self.v_pref.get().strip()
        lan = self.v_lan.get().strip()
        ap = self.v_ap.get().strip()
        port = self.v_port.get().strip()
        tout = self.v_timeout.get().strip()
        disc = self.v_disc.get().strip()

        # Validate IPs
        if pref and not is_valid_ipv4(pref):
            logger.warning("Invalid preferred IP: %s", pref)
            return False, "Preferred HUB IP nije validan IPv4."
        if lan and not is_valid_ipv4(lan):
            logger.warning("Invalid LAN IP: %s", lan)
            return False, "LAN IP nije validan IPv4."
        if ap and not is_valid_ipv4(ap):
            logger.warning("Invalid AP IP: %s", ap)
            return False, "AP IP nije validan IPv4."

        # Validate port
        p = to_int(port, self.cfg.udp_port)
        if p <= 0 or p > 65535:
            logger.warning("Invalid UDP port: %s", port)
            return False, "UDP port mora biti 1..65535."

        # Validate timeouts
        t = to_float(tout, self.cfg.timeout_s)
        if t <= 0.05:
            logger.warning("Timeout too small: %s", tout)
            return False, "Timeout je previše mali."

        d = to_float(disc, self.cfg.discovery_timeout_s)
        if d < 0.3:
            logger.warning("Discovery timeout too small: %s", disc)
            return False, "Discovery timeout je previše mali."

        # Apply to config
        self.cfg.preferred_hub_ip = pref
        self.cfg.hub_lan_ip = lan
        self.cfg.hub_ap_ip = ap
        self.cfg.udp_port = int(p)
        self.cfg.timeout_s = float(t)
        self.cfg.discovery_timeout_s = float(d)
        self.cfg.auto_ap_detect = bool(self.v_autoap.get())

        # Update client
        self.client.cfg = self.cfg
        try:
            self.client.sock.settimeout(self.cfg.timeout_s)
            logger.debug("Updated socket timeout to %s", self.cfg.timeout_s)
        except (OSError, AttributeError) as e:
            logger.debug("Failed to update socket timeout: %s", e)

        self.client.selected_ip = pref if pref else None
        self.client.best_ip = None

        save_config(self.cfg)
        logger.info("Connection settings saved: port=%d, timeout=%s, preferred_ip=%s",
                   self.cfg.udp_port, self.cfg.timeout_s, pref or "none")

        return True, "Saved [OK]"

    def on_save(self):
        """Save button handler"""
        ok, msg = self._apply_to_cfg()
        self.var_msg.set(msg)
        if ok:
            self.app._set_diag("Connection settings saved [OK]")

    def on_test(self):
        """Test connection button handler"""
        # In manual mode, apply settings first
        if self.mode_toggle.get_state() == "right":
            ok, msg = self._apply_to_cfg()
            if not ok:
                self.var_msg.set(msg)
                return

        logger.info("Testing hub connection...")
        self.var_msg.set("Testing...")

        def worker():
            try:
                ip, state = self.client.pick_best_ip()
                result_msg = f"TEST {'OK' if ip else 'FAIL'}  {ip or ''}  ({state})"
                logger.info("Connection test result: %s", result_msg)
                self.after(0, lambda: self.var_msg.set(result_msg))
            except Exception as e:
                logger.error("Connection test failed: %s", e, exc_info=True)
                self.after(0, lambda: self.var_msg.set(f"Test failed: {e}"))

        threading.Thread(target=worker, daemon=True).start()

    def on_scan(self):
        """Scan for hubs button handler"""
        if self._scan_busy:
            logger.debug("Scan already in progress, ignoring")
            return

        self._scan_busy = True
        self.var_msg.set("Scanning...")
        self.listbox.delete(0, tk.END)
        logger.info("Starting hub discovery scan...")

        def worker():
            hubs = []
            try:
                hubs = self.client.discover_hubs()
                logger.info("Discovery found %d hub(s)", len(hubs))
            except Exception as e:
                logger.error("Hub discovery failed: %s", e, exc_info=True)

            def apply():
                if hubs:
                    for h in hubs:
                        self.listbox.insert(tk.END, f'{h["ip"]}   |   {h.get("raw","")}')
                    self.var_msg.set(f"Found {len(hubs)} hub(s) [OK]")
                else:
                    self.var_msg.set("No hub found")
                self._scan_busy = False

            try:
                self.after(0, apply)
            except tk.TclError as e:
                logger.debug("Failed to update scan results: %s", e)

        threading.Thread(target=worker, daemon=True).start()

    def on_use_selected(self):
        """Use selected hub from scan results"""
        sel = self.listbox.curselection()
        if not sel:
            self.var_msg.set("Select a hub from the list.")
            return

        line = self.listbox.get(sel[0])
        ip = (line.split("|")[0] or "").strip()

        if not is_valid_ipv4(ip):
            logger.warning("Invalid IP selected from scan: %s", ip)
            self.var_msg.set("Invalid selection.")
            return

        # Set preferred IP and save
        self.cfg.preferred_hub_ip = ip
        self.client.selected_ip = ip
        self.client.best_ip = None
        save_config(self.cfg)

        self.var_msg.set(f"Selected: {ip} [OK]")
        self.app._set_diag(f"Selected HUB: {ip}")
        logger.info("Hub selected from scan: %s", ip)
