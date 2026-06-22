"""
First-time setup wizard for Blastgate
"""
import logging
import tkinter as tk
from tkinter import ttk, messagebox
from typing import TYPE_CHECKING, Optional, List, Dict, Any

import ttkbootstrap as tb
from ttkbootstrap.constants import *

from blastgate.gui.utils import apply_ui_scale, smart_center
from blastgate.gui.components import LoadingSpinner, ProgressBar
from blastgate.network.discovery import discover_hubs
from blastgate.config import save_config

if TYPE_CHECKING:
    from blastgate.gui.app import App

logger = logging.getLogger(__name__)


class SetupWizard(tb.Toplevel):
    """
    First-time setup wizard for new users.

    Steps:
    1. Welcome
    2. Hub discovery
    3. WiFi configuration (optional)
    4. Node detection
    5. Complete
    """

    # Wizard steps
    STEP_WELCOME = 0
    STEP_HUB = 1
    STEP_WIFI = 2
    STEP_NODES = 3
    STEP_COMPLETE = 4

    def __init__(self, master, app: "App"):
        super().__init__(master)

        self.app = app
        self.cfg = app.cfg
        self.net = app.net

        # Wizard state
        self._current_step = self.STEP_WELCOME
        self._discovered_hubs: List[Dict[str, str]] = []
        self._selected_hub_ip: Optional[str] = None
        self._skip_wifi = False
        self._discovered_nodes: List[Dict[str, Any]] = []
        self._stop = False

        # UI setup
        self.title("Blastgate Setup Wizard")
        apply_ui_scale(self, app.cfg.ui_scale)
        smart_center(self, 620, 520, scale=app.cfg.ui_scale)
        self.minsize(int(540 * app.cfg.ui_scale), int(440 * app.cfg.ui_scale))
        self.resizable(True, True)

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._close)

        logger.info("Setup wizard started")

    def _build_ui(self):
        """Build wizard UI"""
        wrap = ttk.Frame(self, padding=24)
        wrap.pack(fill="both", expand=True)

        # Header with progress
        header = ttk.Frame(wrap)
        header.pack(fill="x", pady=(0, 24))

        ttk.Label(header, text="🚀 Blastgate Setup", font=("Segoe UI", 20, "bold")).pack(anchor="w")

        # Progress bar
        self.progress = ProgressBar(header, width=200, height=6)
        self.progress.pack(fill="x", expand=True, pady=(12, 0))

        # Content frame (changes per step)
        self.content_frame = ttk.Frame(wrap)
        self.content_frame.pack(fill="both", expand=True)

        # Bottom navigation
        nav = ttk.Frame(wrap)
        nav.pack(fill="x", pady=(24, 0))

        self.btn_back = ttk.Button(
            nav, text="← Back", bootstyle=SECONDARY,
            command=self._go_back, state="disabled"
        )
        self.btn_back.pack(side="left")

        self.var_status = tb.StringVar(value="")
        ttk.Label(nav, textvariable=self.var_status, bootstyle=INFO).pack(side="left", padx=(16, 0))

        self.btn_next = ttk.Button(
            nav, text="Next →", bootstyle=SUCCESS,
            command=self._go_next
        )
        self.btn_next.pack(side="right")

        self.btn_cancel = ttk.Button(
            nav, text="Cancel", bootstyle=SECONDARY,
            command=self._close
        )
        self.btn_cancel.pack(side="right", padx=(0, 12))

        # Show first step
        self._show_step(self.STEP_WELCOME)

    def _clear_content(self):
        """Clear content frame"""
        for widget in self.content_frame.winfo_children():
            widget.destroy()

    def _show_step(self, step: int):
        """Show specific wizard step"""
        self._current_step = step
        self._clear_content()

        # Update progress bar
        progress = step / 4.0
        self.progress.set_progress(progress)

        # Update navigation buttons
        self.btn_back.configure(state="normal" if step > 0 else "disabled")

        if step == self.STEP_WELCOME:
            self._show_welcome()
        elif step == self.STEP_HUB:
            self._show_hub_discovery()
        elif step == self.STEP_WIFI:
            self._show_wifi_setup()
        elif step == self.STEP_NODES:
            self._show_node_detection()
        elif step == self.STEP_COMPLETE:
            self._show_complete()

    def _show_welcome(self):
        """Show welcome screen"""
        ttk.Label(
            self.content_frame,
            text="Welcome to Blastgate! 👋",
            font=("Segoe UI", 16, "bold")
        ).pack(anchor="w", pady=(0, 16))

        ttk.Label(
            self.content_frame,
            text="This wizard will help you set up your Blastgate dust collection system.",
            wraplength=450,
            justify="left"
        ).pack(anchor="w", pady=(0, 24))

        # What we'll do
        steps_frame = ttk.Labelframe(self.content_frame, text="Setup Steps", padding=16)
        steps_frame.pack(fill="x", pady=(0, 24))

        steps = [
            "1️⃣  Find and connect to your Blastgate hub",
            "2️⃣  Configure WiFi connection (optional)",
            "3️⃣  Detect and configure nodes",
            "4️⃣  You're ready to go!"
        ]

        for step in steps:
            ttk.Label(steps_frame, text=step, font=("Segoe UI", 11)).pack(anchor="w", pady=4)

        # Requirements
        req_frame = ttk.Labelframe(self.content_frame, text="Before You Start", padding=16)
        req_frame.pack(fill="x")

        requirements = [
            "✓  Blastgate hub is powered on",
            "✓  Hub is connected to your network (Ethernet or WiFi)",
            "✓  At least one node is powered on and connected",
        ]

        for req in requirements:
            ttk.Label(req_frame, text=req, bootstyle=SECONDARY).pack(anchor="w", pady=4)

        self.btn_next.configure(text="Get Started →")
        self.var_status.set("Ready to begin")

    def _show_hub_discovery(self):
        """Show hub discovery screen"""
        ttk.Label(
            self.content_frame,
            text="Step 1: Find Your Hub 🔍",
            font=("Segoe UI", 16, "bold")
        ).pack(anchor="w", pady=(0, 16))

        ttk.Label(
            self.content_frame,
            text="Searching for Blastgate hubs on your network...",
            wraplength=550
        ).pack(anchor="w", pady=(0, 16))

        # Discovered hubs list
        list_frame = ttk.Labelframe(self.content_frame, text="Discovered Hubs", padding=14)
        list_frame.pack(fill="both", expand=True, pady=(0, 16))

        # Scrollable list
        scroll_frame = ttk.Frame(list_frame)
        scroll_frame.pack(fill="both", expand=True)

        scrollbar = ttk.Scrollbar(scroll_frame)
        scrollbar.pack(side="right", fill="y")

        self.hub_listbox = tk.Listbox(
            scroll_frame,
            height=6,
            yscrollcommand=scrollbar.set,
            font=("Consolas", 10)
        )
        self.hub_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.configure(command=self.hub_listbox.yview)

        # Spinner
        spinner_row = ttk.Frame(self.content_frame)
        spinner_row.pack(fill="x")

        self.hub_spinner = LoadingSpinner(spinner_row, size=20)
        self.hub_spinner.pack(side="left", padx=(0, 8))

        self.var_hub_status = tb.StringVar(value="Scanning...")
        ttk.Label(spinner_row, textvariable=self.var_hub_status, bootstyle=INFO).pack(side="left")

        # Manual IP entry
        manual_frame = ttk.Frame(self.content_frame)
        manual_frame.pack(fill="x", pady=(16, 0))

        ttk.Label(manual_frame, text="Or enter IP manually:").pack(side="left", padx=(0, 8))
        self.v_manual_ip = tb.StringVar(value="")
        ttk.Entry(manual_frame, textvariable=self.v_manual_ip, width=20).pack(side="left")

        self.btn_next.configure(text="Connect →", state="disabled")
        self.var_status.set("Searching for hubs...")

        # Start discovery
        self.after(500, self._start_hub_discovery)

    def _start_hub_discovery(self):
        """Start hub discovery in background"""
        self.hub_spinner.start()

        def discovery_thread():
            try:
                self._discovered_hubs = discover_hubs(self.cfg)
                self.after(100, self._update_hub_list)
            except Exception as e:
                logger.error("Hub discovery failed: %s", e)
                self.after(100, lambda: self._hub_discovery_failed(e))

        import threading
        thread = threading.Thread(target=discovery_thread, daemon=True)
        thread.start()

    def _update_hub_list(self):
        """Update hub list with discovered hubs"""
        self.hub_spinner.stop()
        self.hub_spinner.pack_forget()

        if self._discovered_hubs:
            self.hub_listbox.delete(0, tk.END)
            for hub in self._discovered_hubs:
                ip = hub.get("ip", "")
                raw = hub.get("raw", "")
                self.hub_listbox.insert(tk.END, f"{ip}  {raw[:30]}")

            self.hub_listbox.selection_set(0)
            self.var_hub_status.set(f"Found {len(self._discovered_hubs)} hub(s)")
            self.btn_next.configure(state="normal")
            logger.info("Found %d hub(s)", len(self._discovered_hubs))
        else:
            self.var_hub_status.set("No hubs found - enter IP manually")
            self.btn_next.configure(state="normal")

    def _hub_discovery_failed(self, error):
        """Handle hub discovery failure"""
        self.hub_spinner.stop()
        self.hub_spinner.pack_forget()
        self.var_hub_status.set("Discovery failed - enter IP manually")
        self.btn_next.configure(state="normal")
        logger.error("Hub discovery failed: %s", error)

    def _show_wifi_setup(self):
        """Show WiFi setup screen (optional)"""
        ttk.Label(
            self.content_frame,
            text="Step 2: WiFi Setup (Optional) 📶",
            font=("Segoe UI", 16, "bold")
        ).pack(anchor="w", pady=(0, 16))

        ttk.Label(
            self.content_frame,
            text="Configure WiFi for your hub to connect to your network wirelessly.",
            wraplength=550
        ).pack(anchor="w", pady=(0, 16))

        # Skip option
        skip_frame = ttk.Frame(self.content_frame)
        skip_frame.pack(fill="x", pady=(0, 24))

        self.v_skip_wifi = tb.BooleanVar(value=True)
        ttk.Checkbutton(
            skip_frame,
            text="Skip WiFi setup (hub is already connected via Ethernet)",
            variable=self.v_skip_wifi,
            bootstyle="round-toggle",
            command=self._on_skip_wifi_toggle
        ).pack(side="left")

        # WiFi form (disabled by default)
        self.wifi_form = ttk.Labelframe(self.content_frame, text="WiFi Credentials", padding=14)
        self.wifi_form.pack(fill="x", pady=(0, 16))

        row1 = ttk.Frame(self.wifi_form)
        row1.pack(fill="x", pady=6)
        ttk.Label(row1, text="SSID:", width=12).pack(side="left")
        self.v_ssid = tb.StringVar(value="")
        self.e_ssid = ttk.Entry(row1, textvariable=self.v_ssid)
        self.e_ssid.pack(side="left", fill="x", expand=True)

        row2 = ttk.Frame(self.wifi_form)
        row2.pack(fill="x", pady=6)
        ttk.Label(row2, text="Password:", width=12).pack(side="left")
        self.v_wifi_pass = tb.StringVar(value="")
        self.e_wifi_pass = ttk.Entry(row2, textvariable=self.v_wifi_pass, show="•")
        self.e_wifi_pass.pack(side="left", fill="x", expand=True)

        # Initially disable WiFi form
        self._on_skip_wifi_toggle()

        self.btn_next.configure(text="Continue →")
        self.var_status.set("WiFi setup is optional")

    def _on_skip_wifi_toggle(self):
        """Handle skip WiFi toggle"""
        skip = self.v_skip_wifi.get()
        state = "disabled" if skip else "normal"

        try:
            self.e_ssid.configure(state=state)
            self.e_wifi_pass.configure(state=state)
        except (tk.TclError, AttributeError):
            pass

    def _show_node_detection(self):
        """Show node detection screen"""
        ttk.Label(
            self.content_frame,
            text="Step 3: Detect Nodes 🔌",
            font=("Segoe UI", 16, "bold")
        ).pack(anchor="w", pady=(0, 16))

        ttk.Label(
            self.content_frame,
            text="Looking for connected nodes...",
            wraplength=550
        ).pack(anchor="w", pady=(0, 16))

        # Nodes list
        list_frame = ttk.Labelframe(self.content_frame, text="Detected Nodes", padding=14)
        list_frame.pack(fill="both", expand=True, pady=(0, 16))

        # Scrollable list
        scroll_frame = ttk.Frame(list_frame)
        scroll_frame.pack(fill="both", expand=True)

        scrollbar = ttk.Scrollbar(scroll_frame)
        scrollbar.pack(side="right", fill="y")

        self.node_listbox = tk.Listbox(
            scroll_frame,
            height=6,
            yscrollcommand=scrollbar.set,
            font=("Consolas", 10)
        )
        self.node_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.configure(command=self.node_listbox.yview)

        # Status
        status_row = ttk.Frame(self.content_frame)
        status_row.pack(fill="x")

        self.node_spinner = LoadingSpinner(status_row, size=20)
        self.node_spinner.pack(side="left", padx=(0, 8))
        self.node_spinner.start()

        self.var_node_status = tb.StringVar(value="Scanning for nodes...")
        ttk.Label(status_row, textvariable=self.var_node_status, bootstyle=INFO).pack(side="left")

        self.btn_next.configure(text="Finish Setup →", state="disabled")
        self.var_status.set("Detecting nodes...")

        # Start node detection
        self.after(1000, self._detect_nodes)

    def _detect_nodes(self):
        """Detect nodes from hub status"""
        try:
            status, _ = self.app.get_status_cached()
            nodes = status.get("nodes", [])
            self._discovered_nodes = [n for n in nodes if int(n.get("online", 0)) == 1]

            self.node_spinner.stop()
            self.node_spinner.pack_forget()

            if self._discovered_nodes:
                self.node_listbox.delete(0, tk.END)
                for node in self._discovered_nodes:
                    node_id = node.get("id", "")
                    name = node.get("name", "Unnamed")
                    self.node_listbox.insert(tk.END, f"{node_id} - {name}")

                self.var_node_status.set(f"Found {len(self._discovered_nodes)} node(s)")
                self.btn_next.configure(state="normal")
                logger.info("Found %d node(s)", len(self._discovered_nodes))
            else:
                self.var_node_status.set("No nodes found - check connections")
                self.btn_next.configure(state="normal")

        except Exception as e:
            logger.error("Node detection failed: %s", e)
            self.node_spinner.stop()
            self.node_spinner.pack_forget()
            self.var_node_status.set("Detection failed")
            self.btn_next.configure(state="normal")

    def _show_complete(self):
        """Show completion screen"""
        ttk.Label(
            self.content_frame,
            text="✅ Setup Complete!",
            font=("Segoe UI", 18, "bold")
        ).pack(anchor="w", pady=(0, 24))

        ttk.Label(
            self.content_frame,
            text="Your Blastgate system is ready to use!",
            font=("Segoe UI", 12),
            wraplength=550
        ).pack(anchor="w", pady=(0, 24))

        # Summary
        summary_frame = ttk.Labelframe(self.content_frame, text="Setup Summary", padding=16)
        summary_frame.pack(fill="x", pady=(0, 24))

        hub_ip = self._selected_hub_ip or "Not configured"
        ttk.Label(summary_frame, text=f"Hub IP: {hub_ip}").pack(anchor="w", pady=4)
        ttk.Label(summary_frame, text=f"Nodes found: {len(self._discovered_nodes)}").pack(anchor="w", pady=4)

        # Next steps
        next_frame = ttk.Labelframe(self.content_frame, text="Next Steps", padding=16)
        next_frame.pack(fill="x")

        steps = [
            "• Click on node tiles to configure threshold and settings",
            "• Use Auto-Calibrate to find the optimal threshold",
            "• Test by turning your machines on and off",
            "• Use Settings menu for WiFi, backup, and more",
        ]

        for step in steps:
            ttk.Label(next_frame, text=step, bootstyle=SECONDARY).pack(anchor="w", pady=4)

        self.btn_next.configure(text="Close Wizard")
        self.btn_back.configure(state="disabled")
        self.var_status.set("Setup complete!")

    def _go_back(self):
        """Go to previous step"""
        if self._current_step > 0:
            self._show_step(self._current_step - 1)

    def _go_next(self):
        """Go to next step"""
        if self._current_step == self.STEP_WELCOME:
            self._show_step(self.STEP_HUB)

        elif self._current_step == self.STEP_HUB:
            # Get selected hub or manual IP
            selected_idx = self.hub_listbox.curselection()
            if selected_idx:
                hub = self._discovered_hubs[selected_idx[0]]
                self._selected_hub_ip = hub.get("ip", "")
            else:
                self._selected_hub_ip = self.v_manual_ip.get().strip()

            if not self._selected_hub_ip:
                messagebox.showwarning(
                    "No Hub Selected",
                    "Please select a hub or enter an IP address manually.",
                    parent=self
                )
                return

            # Save hub IP to config
            self.cfg.preferred_hub_ip = self._selected_hub_ip
            save_config(self.cfg)
            self.app.client.selected_ip = self._selected_hub_ip

            logger.info("Selected hub IP: %s", self._selected_hub_ip)
            self._show_step(self.STEP_WIFI)

        elif self._current_step == self.STEP_WIFI:
            # Configure WiFi if not skipped
            if not self.v_skip_wifi.get():
                ssid = self.v_ssid.get().strip()
                password = self.v_wifi_pass.get()

                if not ssid:
                    messagebox.showwarning("SSID Required", "Please enter WiFi SSID.", parent=self)
                    return

                # Send WiFi credentials to hub
                self.var_status.set("Configuring WiFi...")
                self.btn_next.configure(state="disabled")

                def on_ok():
                    self.var_status.set("WiFi configured")
                    logger.info("WiFi configured successfully")
                    self.after(500, lambda: self._show_step(self.STEP_NODES))

                def on_err(e):
                    self.var_status.set("WiFi configuration failed")
                    logger.error("WiFi configuration failed: %s", e)
                    messagebox.showerror("WiFi Error", f"Failed to configure WiFi:\n{e}", parent=self)
                    self.btn_next.configure(state="normal")

                self.net.send("wifi_set", ssid, password, on_ok=on_ok, on_err=on_err)
            else:
                # Skip WiFi
                self._show_step(self.STEP_NODES)

        elif self._current_step == self.STEP_NODES:
            self._show_step(self.STEP_COMPLETE)

        elif self._current_step == self.STEP_COMPLETE:
            self._close()

    def _close(self):
        """Close wizard"""
        self._stop = True
        try:
            self.destroy()
        except tk.TclError as e:
            logger.debug("Failed to destroy SetupWizard: %s", e)

        logger.info("Setup wizard closed")
