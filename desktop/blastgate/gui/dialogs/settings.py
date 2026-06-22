"""
Settings dialog with tabbed sidebar for Blastgate

A modern settings dialog with:
- Left sidebar with tab buttons (Connect Hub, WiFi, General)
- Right content area that changes based on selected tab
- Smooth transitions between tabs
"""
import logging
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import TYPE_CHECKING, Optional, Tuple

import ttkbootstrap as tb
from ttkbootstrap.constants import *

from blastgate.gui.utils import apply_ui_scale, smart_center, show_user_error
from blastgate.network.client import HubClientUDP
from blastgate.config import save_config
from blastgate.utils.validators import is_valid_ipv4
from blastgate.utils.helpers import to_int, to_float

if TYPE_CHECKING:
    from blastgate.gui.app import App

logger = logging.getLogger(__name__)


class SidebarTab(tk.Canvas):
    """
    Sidebar tab button with rounded corners and hover effects.
    """

    def __init__(
        self,
        master: tk.Widget,
        text: str,
        width: int = 180,
        height: int = 48,
        active: bool = False,
        on_click: Optional[callable] = None,
        bg_color: str = "#2a2d32",
        active_color: str = "#3a7bd5",
        hover_color: str = "#3a3d42",
        text_color: str = "#ffffff",
    ):
        super().__init__(
            master,
            width=width,
            height=height,
            highlightthickness=0,
            bg=bg_color,
        )

        self.text = text
        self.width = width
        self.height = height
        self.active = active
        self.on_click = on_click
        self.bg_color = bg_color
        self.active_color = active_color
        self.hover_color = hover_color
        self.text_color = text_color

        self._hovering = False

        self._draw()

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    def _draw(self):
        """Draw the tab button."""
        self.delete("all")

        # Determine background color
        if self.active:
            bg = self.active_color
        elif self._hovering:
            bg = self.hover_color
        else:
            bg = self.bg_color

        # Draw pill shape (rounded on left and right)
        r = self.height // 2
        self._draw_pill(4, 4, self.width - 4, self.height - 4, r - 4, bg)

        # Draw text
        self.create_text(
            self.width // 2,
            self.height // 2,
            text=self.text,
            fill=self.text_color,
            font=("Segoe UI", 11, "bold" if self.active else "normal"),
            anchor="center",
        )

    def _draw_pill(self, x1: int, y1: int, x2: int, y2: int, r: int, fill: str):
        """Draw a pill-shaped rectangle."""
        points = [
            x1 + r, y1,
            x2 - r, y1,
            x2, y1,
            x2, y1 + r,
            x2, y2 - r,
            x2, y2,
            x2 - r, y2,
            x1 + r, y2,
            x1, y2,
            x1, y2 - r,
            x1, y1 + r,
            x1, y1,
            x1 + r, y1,
        ]
        self.create_polygon(points, smooth=True, fill=fill, outline="")

    def _on_enter(self, event):
        self._hovering = True
        self.configure(cursor="hand2")
        self._draw()

    def _on_leave(self, event):
        self._hovering = False
        self.configure(cursor="")
        self._draw()

    def _on_click(self, event):
        if callable(self.on_click):
            self.on_click()

    def set_active(self, active: bool):
        """Set tab active state."""
        self.active = active
        self._draw()


class SettingsWindow(tb.Toplevel):
    """
    Settings dialog with tabbed sidebar.

    Tabs:
    - Connect Hub: Hub connection settings and discovery
    - WiFi: WiFi network configuration
    - General: General app settings (show offline nodes, etc.)
    """

    def __init__(self, master, app: "App"):
        super().__init__(master)
        self.app = app
        self.cfg = app.cfg
        self.client = app.client
        self.net = app.net

        apply_ui_scale(self, self.cfg.ui_scale)
        self.title("Settings")
        smart_center(self, 880, 580, scale=self.cfg.ui_scale)
        self.minsize(int(750 * self.cfg.ui_scale), int(480 * self.cfg.ui_scale))
        self.resizable(True, True)

        logger.info("SettingsWindow opened")

        # Main container
        self.container = ttk.Frame(self)
        self.container.pack(fill="both", expand=True)

        # Left sidebar
        self.sidebar = ttk.Frame(self.container, width=200)
        self.sidebar.pack(side="left", fill="y", padx=(0, 0))
        self.sidebar.pack_propagate(False)

        # Sidebar header
        sidebar_header = ttk.Frame(self.sidebar)
        sidebar_header.pack(fill="x", pady=(20, 10), padx=10)
        ttk.Label(
            sidebar_header,
            text="Settings",
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w")

        # Sidebar tabs
        self.tabs_frame = ttk.Frame(self.sidebar)
        self.tabs_frame.pack(fill="x", pady=10, padx=10)

        self.tab_buttons = {}
        self._current_tab = "connect"

        # Create tab buttons
        for tab_id, tab_name in [
            ("connect", "Connect Hub"),
            ("wifi", "WiFi"),
            ("general", "General"),
        ]:
            btn = SidebarTab(
                self.tabs_frame,
                text=tab_name,
                width=180,
                height=48,
                active=(tab_id == self._current_tab),
                on_click=lambda t=tab_id: self._switch_tab(t),
            )
            btn.pack(pady=4)
            self.tab_buttons[tab_id] = btn

        # Right content area
        self.content = ttk.Frame(self.container, padding=20)
        self.content.pack(side="right", fill="both", expand=True)

        # Message label and Close button (create BEFORE tabs so they're available)
        self.var_msg = tb.StringVar(value="")
        self.msg_frame = ttk.Frame(self.content)
        self.msg_frame.pack(side="bottom", fill="x", pady=(10, 0))
        ttk.Label(self.msg_frame, textvariable=self.var_msg, bootstyle=INFO).pack(side="left")
        ttk.Button(self.msg_frame, text="Close", bootstyle=SECONDARY, command=self._close).pack(side="right")

        # Content area for tabs (above message frame)
        self.tab_content = ttk.Frame(self.content)
        self.tab_content.pack(side="top", fill="both", expand=True)

        # Content frames for each tab
        self.content_frames = {}
        self._build_connect_tab()
        self._build_wifi_tab()
        self._build_general_tab()

        # Show initial tab
        self._show_tab("connect")

        self._scan_busy = False
        self.protocol("WM_DELETE_WINDOW", self._close)

        # Bring window to front
        self.lift()
        self.focus_force()

    def _switch_tab(self, tab_id: str):
        """Switch to specified tab."""
        if tab_id == self._current_tab:
            return

        # Update tab button states
        for tid, btn in self.tab_buttons.items():
            btn.set_active(tid == tab_id)

        self._current_tab = tab_id
        self._show_tab(tab_id)

        # Clear message when switching tabs
        self.var_msg.set("")

        # Load WiFi status when first switching to WiFi tab
        if tab_id == "wifi" and not self._wifi_loaded:
            self._wifi_loaded = True
            self.after(200, self.refresh_wifi)

        logger.debug("Switched to tab: %s", tab_id)

    def _show_tab(self, tab_id: str):
        """Show content for specified tab."""
        # Hide all content frames
        for frame in self.content_frames.values():
            frame.pack_forget()

        # Show selected frame in tab_content area
        if tab_id in self.content_frames:
            self.content_frames[tab_id].pack(in_=self.tab_content, fill="both", expand=True)

    # ========== CONNECT TAB ==========
    def _build_connect_tab(self):
        """Build Connect Hub tab content."""
        frame = ttk.Frame(self.tab_content)
        self.content_frames["connect"] = frame

        # Header
        ttk.Label(frame, text="Connect Hub", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Configure hub connection settings", bootstyle=SECONDARY).pack(anchor="w", pady=(4, 16))

        # AUTO/MANUAL toggle for connect mode
        from blastgate.gui.components.animated_toggle import TwoStateToggle
        mode_frame = ttk.Frame(frame)
        mode_frame.pack(fill="x", pady=(0, 12))
        ttk.Label(mode_frame, text="Mode:", bootstyle=SECONDARY).pack(side="left", padx=(0, 12))
        self.connect_mode_toggle = TwoStateToggle(
            mode_frame,
            width=160,
            height=32,
            left_color="#2a9fd6",
            right_color="#f0ad4e",
            inactive_color="#3a3a3a",
            on_change=self._on_connect_mode_change,
            initial_state="left",
            labels=("AUTO", "MANUAL"),
        )
        self.connect_mode_toggle.pack(side="left")

        # AUTO mode frame (scan/detect)
        self.connect_auto_frame = ttk.Frame(frame)
        self._build_connect_auto_ui()

        # MANUAL mode frame (detailed settings)
        self.connect_manual_frame = ttk.Frame(frame)
        self._build_connect_manual_ui()

        # Start in AUTO mode
        self._show_connect_auto_mode()

    def _build_connect_auto_ui(self):
        """Build AUTO mode UI for Connect tab."""
        frame = self.connect_auto_frame

        ttk.Label(frame, text="Automatic hub detection", bootstyle=SECONDARY).pack(anchor="w", pady=(0, 12))

        # Scan results
        results = ttk.Labelframe(frame, text="Detected Hubs", padding=12)
        results.pack(fill="both", expand=True)
        self.connect_listbox = tk.Listbox(results, height=8)
        self.connect_listbox.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(results, orient="vertical", command=self.connect_listbox.yview)
        sb.pack(side="right", fill="y")
        self.connect_listbox.configure(yscrollcommand=sb.set)

        # Buttons
        btn_row = ttk.Frame(frame)
        btn_row.pack(fill="x", pady=(12, 0))
        self.btn_scan = ttk.Button(btn_row, text="Scan", bootstyle=PRIMARY, command=self.on_scan)
        self.btn_scan.pack(side="left")
        self.btn_use = ttk.Button(btn_row, text="Use selected", bootstyle=SUCCESS, command=self.on_use_selected)
        self.btn_use.pack(side="left", padx=12)
        self.btn_test_auto = ttk.Button(btn_row, text="Test", bootstyle=SECONDARY, command=self.on_test)
        self.btn_test_auto.pack(side="left")

    def _build_connect_manual_ui(self):
        """Build MANUAL mode UI for Connect tab."""
        frame = self.connect_manual_frame

        ttk.Label(frame, text="Manual configuration", bootstyle=SECONDARY).pack(anchor="w", pady=(0, 12))

        form = ttk.Labelframe(frame, text="Connection Settings", padding=14)
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
                ttk.Checkbutton(form, variable=var, bootstyle="round-toggle").grid(row=r, column=1, sticky="w", padx=12, pady=6)
            ttk.Label(form, text=hint, bootstyle=SECONDARY).grid(row=r, column=2, sticky="w", padx=8, pady=6)

        row(0, "Preferred HUB IP", self.v_pref, "Priority IP")
        row(1, "LAN IP", self.v_lan, "Router IP")
        row(2, "AP IP", self.v_ap, "AP mode IP")
        row(3, "UDP Port", self.v_port, "Default 8888")
        row(4, "Timeout (s)", self.v_timeout, "UDP timeout")
        row(5, "Discovery (s)", self.v_disc, "Scan timeout")
        row(6, "Auto-detect AP", self.v_autoap, "", entry=False)
        form.grid_columnconfigure(2, weight=1)

        # Buttons
        btn_row = ttk.Frame(frame)
        btn_row.pack(fill="x", pady=(12, 0))
        ttk.Button(btn_row, text="Save", bootstyle=SUCCESS, command=self.on_save).pack(side="left")
        ttk.Button(btn_row, text="Test", bootstyle=PRIMARY, command=self.on_test).pack(side="left", padx=12)

    def _on_connect_mode_change(self, state: str):
        """Handle connect mode toggle change."""
        if state == "left":
            self._show_connect_auto_mode()
        else:
            self._show_connect_manual_mode()

    def _show_connect_auto_mode(self):
        """Show AUTO mode UI for Connect tab."""
        self.connect_manual_frame.pack_forget()
        self.connect_auto_frame.pack(fill="both", expand=True, pady=(16, 0))
        logger.debug("Connect: switched to AUTO mode")

    def _show_connect_manual_mode(self):
        """Show MANUAL mode UI for Connect tab."""
        self.connect_auto_frame.pack_forget()
        self.connect_manual_frame.pack(fill="both", expand=True, pady=(16, 0))
        logger.debug("Connect: switched to MANUAL mode")

    # ========== WIFI TAB ==========
    def _build_wifi_tab(self):
        """Build WiFi tab content."""
        frame = ttk.Frame(self.tab_content)
        self.content_frames["wifi"] = frame

        # Header
        ttk.Label(frame, text="WiFi Configuration", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Configure hub WiFi connection", bootstyle=SECONDARY).pack(anchor="w", pady=(4, 16))

        # WiFi credentials form
        frm = ttk.Labelframe(frame, text="WiFi Network", padding=14)
        frm.pack(fill="x")

        self.v_ssid = tb.StringVar(value="")
        self.v_pass = tb.StringVar(value="")

        r0 = ttk.Frame(frm)
        r0.pack(fill="x", pady=6)
        ttk.Label(r0, text="SSID:", width=10).pack(side="left")
        ttk.Entry(r0, textvariable=self.v_ssid).pack(side="left", fill="x", expand=True)

        r1 = ttk.Frame(frm)
        r1.pack(fill="x", pady=6)
        ttk.Label(r1, text="Password:", width=10).pack(side="left")
        ttk.Entry(r1, textvariable=self.v_pass, show="*").pack(side="left", fill="x", expand=True)

        # Buttons
        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(16, 0))
        self.btn_wifi_set = ttk.Button(btns, text="Save & Connect", bootstyle=SUCCESS, command=self.on_wifi_set)
        self.btn_wifi_forget = ttk.Button(btns, text="Forget", bootstyle=DANGER, command=self.on_wifi_forget)
        self.btn_wifi_reset = ttk.Button(btns, text="Reset WiFi", bootstyle=WARNING, command=self.on_wifi_reset)
        self.btn_wifi_set.pack(side="left")
        self.btn_wifi_forget.pack(side="left", padx=16)
        self.btn_wifi_reset.pack(side="left")

        # Status display
        stat = ttk.Labelframe(frame, text="Status", padding=14)
        stat.pack(fill="both", expand=True, pady=(16, 0))
        self.wifi_txt = tk.Text(stat, height=8, wrap="word")
        self.wifi_txt.pack(fill="both", expand=True)

        # WiFi status will be loaded when tab is selected
        self._wifi_loaded = False

    # ========== GENERAL TAB ==========
    def _build_general_tab(self):
        """Build General tab content."""
        frame = ttk.Frame(self.tab_content)
        self.content_frames["general"] = frame

        # Header
        ttk.Label(frame, text="General Settings", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Application preferences", bootstyle=SECONDARY).pack(anchor="w", pady=(4, 16))

        # Settings form
        settings_frame = ttk.Labelframe(frame, text="Display Options", padding=14)
        settings_frame.pack(fill="x")

        # Show offline nodes
        row1 = ttk.Frame(settings_frame)
        row1.pack(fill="x", pady=8)
        self.v_show_offline = tb.BooleanVar(value=self.app.var_show_offline.get())
        ttk.Checkbutton(
            row1,
            text="Show offline nodes",
            variable=self.v_show_offline,
            bootstyle="round-toggle",
            command=self._on_show_offline_change,
        ).pack(side="left")
        ttk.Label(row1, text="Display nodes that are offline", bootstyle=SECONDARY).pack(side="left", padx=12)

        # UI Scale (read-only display for now)
        row2 = ttk.Frame(settings_frame)
        row2.pack(fill="x", pady=8)
        ttk.Label(row2, text=f"UI Scale: {self.cfg.ui_scale:.2f}").pack(side="left")
        ttk.Label(row2, text="(Edit config file to change)", bootstyle=SECONDARY).pack(side="left", padx=12)

        # Theme selector
        row3 = ttk.Frame(settings_frame)
        row3.pack(fill="x", pady=8)
        ttk.Label(row3, text="Theme:", width=12).pack(side="left")

        # Available themes (light and dark options)
        self.themes = {
            "🌙 Darkly (Dark)": "darkly",
            "🌙 Cyborg (Dark)": "cyborg",
            "🌙 Vapor (Dark)": "vapor",
            "🌙 Superhero (Dark)": "superhero",
            "☀️ Flatly (Light)": "flatly",
            "☀️ Litera (Light)": "litera",
            "☀️ Minty (Light)": "minty",
            "☀️ Cosmo (Light)": "cosmo",
        }

        # Find current theme display name
        current_display = next(
            (k for k, v in self.themes.items() if v == self.cfg.theme),
            "🌙 Darkly (Dark)"
        )

        self.v_theme = tb.StringVar(value=current_display)
        theme_combo = ttk.Combobox(
            row3,
            textvariable=self.v_theme,
            values=list(self.themes.keys()),
            state="readonly",
            width=25
        )
        theme_combo.pack(side="left", padx=(0, 12))
        theme_combo.bind("<<ComboboxSelected>>", self._on_theme_change)

        ttk.Label(row3, text="(Restart required)", bootstyle=SECONDARY).pack(side="left")

        # Backup/Restore section
        backup_frame = ttk.Labelframe(frame, text="Backup & Restore", padding=14)
        backup_frame.pack(fill="x", pady=(16, 0))

        ttk.Label(
            backup_frame,
            text="Save or restore all node configurations and settings",
            bootstyle=SECONDARY
        ).pack(anchor="w", pady=(0, 12))

        btn_row = ttk.Frame(backup_frame)
        btn_row.pack(fill="x")

        ttk.Button(
            btn_row,
            text="📥 Backup Configuration",
            bootstyle=SUCCESS,
            command=self._backup_config
        ).pack(side="left", padx=(0, 12))

        ttk.Button(
            btn_row,
            text="📤 Restore from Backup",
            bootstyle=INFO,
            command=self._restore_config
        ).pack(side="left")

    def _on_show_offline_change(self):
        """Handle show offline nodes checkbox change."""
        show = self.v_show_offline.get()
        self.app.var_show_offline.set(show)
        logger.info("Show offline nodes: %s", show)

    def _on_theme_change(self, event=None):
        """Handle theme selection change."""
        display_name = self.v_theme.get()
        theme = self.themes.get(display_name, "darkly")

        # Save to config
        self.cfg.theme = theme
        save_config(self.cfg)

        logger.info("Theme changed to: %s (restart required)", theme)
        self.var_msg.set("Theme saved - restart application to apply")

        # Show info messagebox
        messagebox.showinfo(
            "Theme Changed",
            f"Theme '{display_name}' has been saved.\n\n"
            "Please restart the application to apply the new theme.",
            parent=self
        )

    def _backup_config(self):
        """Backup all configuration to file"""
        from tkinter import filedialog
        import json
        from datetime import datetime

        # Ask for save location
        default_name = f"blastgate_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = filedialog.asksaveasfilename(
            parent=self,
            title="Save Configuration Backup",
            defaultextension=".json",
            initialfile=default_name,
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )

        if not filepath:
            return

        try:
            # Collect all configuration
            backup_data = {
                "version": "1.0",
                "timestamp": datetime.now().isoformat(),
                "app_config": self.cfg.model_dump(),
                "nodes": {}
            }

            # Get all node configurations
            status, _ = self.app.get_status_cached()
            nodes = status.get("nodes", [])

            for node in nodes:
                node_id = node.get("id", "")
                if node_id:
                    backup_data["nodes"][node_id] = {
                        "name": node.get("name", ""),
                        "threshold": node.get("threshold_on", 40.0),
                        "relay_hold_ms": node.get("relay_hold_ms", 5000),
                        "gate_hold_ms": node.get("gate_hold_ms", 0),
                    }

            # Save to file
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(backup_data, f, indent=2, ensure_ascii=False)

            logger.info("Configuration backed up to: %s", filepath)
            self.var_msg.set("Backup saved successfully")

            messagebox.showinfo(
                "Backup Complete",
                f"Configuration has been backed up to:\n{filepath}\n\n"
                f"Backed up {len(backup_data['nodes'])} node(s)",
                parent=self
            )

        except Exception as e:
            logger.error("Backup failed: %s", e, exc_info=True)
            messagebox.showerror(
                "Backup Failed",
                f"Failed to create backup:\n{e}",
                parent=self
            )

    def _restore_config(self):
        """Restore configuration from backup file"""
        from tkinter import filedialog
        import json

        # Ask for backup file
        filepath = filedialog.askopenfilename(
            parent=self,
            title="Open Configuration Backup",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )

        if not filepath:
            return

        try:
            # Load backup file
            with open(filepath, 'r', encoding='utf-8') as f:
                backup_data = json.load(f)

            # Validate backup format
            if "version" not in backup_data or "app_config" not in backup_data:
                raise ValueError("Invalid backup file format")

            # Confirm restore
            node_count = len(backup_data.get("nodes", {}))
            if not messagebox.askyesno(
                "Confirm Restore",
                f"This will restore configuration from:\n{filepath}\n\n"
                f"Nodes in backup: {node_count}\n\n"
                "Current configuration will be overwritten.\n\n"
                "Continue?",
                parent=self
            ):
                return

            # Restore app config (selective - only safe settings)
            app_config = backup_data.get("app_config", {})
            if "ui_scale" in app_config:
                self.cfg.ui_scale = app_config["ui_scale"]
            if "theme" in app_config:
                self.cfg.theme = app_config["theme"]
            if "poll_ms" in app_config:
                self.cfg.poll_ms = app_config["poll_ms"]
            if "timeout_s" in app_config:
                self.cfg.timeout_s = app_config["timeout_s"]

            # Save app config
            save_config(self.cfg)

            # Restore node configurations
            nodes = backup_data.get("nodes", {})
            restored_count = 0

            for node_id, node_config in nodes.items():
                # Save to local config
                self.app.set_local_node(node_id, {
                    "name": node_config.get("name", ""),
                    "threshold": node_config.get("threshold", 40.0),
                })

                # Try to apply to hub if node is online
                threshold = node_config.get("threshold", 40.0)
                relay_hold = node_config.get("relay_hold_ms", 5000)
                gate_hold = node_config.get("gate_hold_ms", 0)

                payload = {
                    "threshold_on": threshold,
                    "relay_hold_ms": relay_hold,
                    "gate_hold_ms": gate_hold,
                }

                # Send to hub (fire and forget)
                self.net.send("cfg", node_id, payload)
                restored_count += 1

            logger.info("Configuration restored from: %s (%d nodes)", filepath, restored_count)
            self.var_msg.set(f"Restored {restored_count} node(s)")

            messagebox.showinfo(
                "Restore Complete",
                f"Configuration has been restored from:\n{filepath}\n\n"
                f"Restored {restored_count} node configuration(s)\n\n"
                "Application settings updated (restart may be required)",
                parent=self
            )

        except FileNotFoundError:
            logger.error("Backup file not found: %s", filepath)
            messagebox.showerror(
                "File Not Found",
                f"Backup file not found:\n{filepath}",
                parent=self
            )
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON in backup file: %s", e)
            messagebox.showerror(
                "Invalid Backup",
                f"Failed to parse backup file:\n{e}",
                parent=self
            )
        except Exception as e:
            logger.error("Restore failed: %s", e, exc_info=True)
            messagebox.showerror(
                "Restore Failed",
                f"Failed to restore configuration:\n{e}",
                parent=self
            )

    # ========== CONNECT ACTIONS ==========
    def _apply_to_cfg(self) -> Tuple[bool, str]:
        """Validate and apply connection settings to config."""
        pref = self.v_pref.get().strip()
        lan = self.v_lan.get().strip()
        ap = self.v_ap.get().strip()
        port = self.v_port.get().strip()
        tout = self.v_timeout.get().strip()
        disc = self.v_disc.get().strip()

        # Validate IPs
        if pref and not is_valid_ipv4(pref):
            logger.warning("Invalid preferred IP: %s", pref)
            return False, "Preferred HUB IP is not valid IPv4."
        if lan and not is_valid_ipv4(lan):
            logger.warning("Invalid LAN IP: %s", lan)
            return False, "LAN IP is not valid IPv4."
        if ap and not is_valid_ipv4(ap):
            logger.warning("Invalid AP IP: %s", ap)
            return False, "AP IP is not valid IPv4."

        # Validate port
        p = to_int(port, self.cfg.udp_port)
        if p <= 0 or p > 65535:
            logger.warning("Invalid UDP port: %s", port)
            return False, "UDP port must be 1..65535."

        # Validate timeouts
        t = to_float(tout, self.cfg.timeout_s)
        if t <= 0.05:
            logger.warning("Timeout too small: %s", tout)
            return False, "Timeout is too small."

        d = to_float(disc, self.cfg.discovery_timeout_s)
        if d < 0.3:
            logger.warning("Discovery timeout too small: %s", disc)
            return False, "Discovery timeout is too small."

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
        """Save connection settings."""
        ok, msg = self._apply_to_cfg()
        self.var_msg.set(msg)
        if ok:
            self.app._set_diag("Connection settings saved [OK]")

    def on_test(self):
        """Test connection."""
        # In manual mode, apply settings first
        if self.connect_mode_toggle.get_state() == "right":
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
        """Scan for hubs."""
        if self._scan_busy:
            logger.debug("Scan already in progress")
            return

        self._scan_busy = True
        self.var_msg.set("Scanning...")
        self.connect_listbox.delete(0, tk.END)
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
                        self.connect_listbox.insert(tk.END, f'{h["ip"]}   |   {h.get("raw", "")}')
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
        """Use selected hub from scan results."""
        sel = self.connect_listbox.curselection()
        if not sel:
            self.var_msg.set("Select a hub from the list.")
            return

        line = self.connect_listbox.get(sel[0])
        ip = (line.split("|")[0] or "").strip()

        if not is_valid_ipv4(ip):
            logger.warning("Invalid IP selected: %s", ip)
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

    # ========== WIFI ACTIONS ==========
    def _wifi_busy(self, on: bool):
        """Enable/disable WiFi buttons during operation."""
        st = "disabled" if on else "normal"
        for b in (self.btn_wifi_set, self.btn_wifi_forget, self.btn_wifi_reset):
            try:
                b.configure(state=st)
            except tk.TclError as e:
                logger.debug("Failed to set button state: %s", e)

    def _wifi_write(self, s: str):
        """Write text to WiFi status display."""
        try:
            self.wifi_txt.delete("1.0", tk.END)
            self.wifi_txt.insert(tk.END, s)
        except tk.TclError as e:
            logger.debug("Failed to update status text: %s", e)

    def refresh_wifi(self):
        """Refresh WiFi status from hub."""
        self._wifi_busy(True)
        self.var_msg.set("Reading WiFi status...")
        logger.info("Refreshing WiFi status...")

        def ok(d):
            try:
                st, state = self.net.get_cached_status()
                ip = self.app.client.best_ip or self.app.client.last_ok_ip or "?"
                txt = (
                    f"HUB: {ip} ({state})\n\n"
                    f"STA connected: {d.get('STA', '?')}\n"
                    f"SSID: {d.get('SSID', '')}\n"
                    f"IP: {d.get('IP', '')}\n"
                    f"RSSI: {d.get('RSSI', '')}\n"
                )
                self.var_msg.set("OK")
                self._wifi_write(txt)
                logger.info("WiFi status refreshed: STA=%s, SSID=%s", d.get('STA'), d.get('SSID'))
            except Exception as e:
                logger.error("Failed to process WiFi status: %s", e, exc_info=True)
                self.var_msg.set(f"Error: {e}")
            finally:
                self._wifi_busy(False)

        def err(e):
            logger.error("WiFi status request failed: %s", e)
            self.var_msg.set(f"Error: {e}")
            self._wifi_write(str(e))
            self._wifi_busy(False)

        self.net.send("wifi_get", on_ok=ok, on_err=err)

    def on_wifi_set(self):
        """WiFi connect/set credentials."""
        ssid = self.v_ssid.get().strip()
        pw = self.v_pass.get()

        if not ssid:
            messagebox.showwarning("SSID", "Enter SSID.", parent=self)
            return

        self._wifi_busy(True)
        self.var_msg.set("Connecting...")
        logger.info("Setting WiFi credentials: SSID=%s", ssid)

        def ok():
            self.var_msg.set("Connected [OK]")
            logger.info("WiFi credentials set successfully")
            self._wifi_busy(False)
            self.after(900, self.refresh_wifi)

        def err(e):
            logger.error("WiFi SET failed: %s", e)
            self.var_msg.set("Connection failed")
            self._wifi_busy(False)
            # Show user-friendly error dialog
            show_user_error(self, e, f"Failed to connect to WiFi network: {ssid}")

        self.net.send("wifi_set", ssid, pw, on_ok=ok, on_err=err)

    def on_wifi_forget(self):
        """Forget WiFi credentials."""
        if not messagebox.askyesno("Forget", "Forget WiFi credentials?", parent=self):
            return

        self._wifi_busy(True)
        self.var_msg.set("Forgetting...")
        logger.info("Forgetting WiFi credentials...")

        def ok():
            self.var_msg.set("Forgot [OK]")
            logger.info("WiFi credentials forgotten successfully")
            self._wifi_busy(False)
            self.after(500, self.refresh_wifi)

        def err(e):
            logger.error("WiFi forget failed: %s", e)
            self.var_msg.set("Failed to forget WiFi")
            self._wifi_busy(False)
            # Show user-friendly error dialog
            show_user_error(self, e, "Failed to forget WiFi credentials")

        self.net.send("wifi_forget", on_ok=ok, on_err=err)

    def on_wifi_reset(self):
        """Disconnect and reconnect WiFi (reset connection)."""
        if not messagebox.askyesno("Reset WiFi", "Disconnect and reconnect WiFi?", parent=self):
            return

        self._wifi_busy(True)
        self.var_msg.set("Resetting WiFi...")
        logger.info("Resetting WiFi connection...")

        def ok():
            self.var_msg.set("WiFi reset [OK]")
            logger.info("WiFi reset successfully")
            self._wifi_busy(False)
            self.after(1500, self.refresh_wifi)

        def err(e):
            logger.error("WiFi reset failed: %s", e)
            self.var_msg.set("Reset failed")
            self._wifi_busy(False)
            show_user_error(self, e, "Failed to reset WiFi connection")

        self.net.send("wifi_disconnect", on_ok=ok, on_err=err)

    def _close(self):
        """Close window and cleanup."""
        try:
            self.app._win_settings = None
        except (AttributeError, tk.TclError) as e:
            logger.debug("Failed to cleanup settings window reference: %s", e)

        try:
            self.destroy()
        except tk.TclError as e:
            logger.debug("Failed to destroy SettingsWindow: %s", e)
