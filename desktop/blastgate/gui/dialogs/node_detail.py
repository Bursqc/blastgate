"""
Node detail configuration dialog for Blastgate
"""
import logging
import time
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Dict, Any, TYPE_CHECKING

import ttkbootstrap as tb
from ttkbootstrap.constants import *

from blastgate.gui.utils import apply_ui_scale, smart_center, show_user_error
from blastgate.gui.components.animated_toggle import TwoStateToggle
from blastgate.utils.helpers import to_float, to_int, safe_node_id

if TYPE_CHECKING:
    from blastgate.gui.app import App
    from .calibration import CalibrationWizard

logger = logging.getLogger(__name__)


class NodeDetail(tb.Toplevel):
    """Node detail and configuration dialog"""

    def __init__(self, master, app: "App", node_id: str):
        super().__init__(master)
        self.app = app
        self.net = app.net
        self.cfg = app.cfg
        self.node_id = node_id
        self._stop = False
        self._current_mode = 0  # 0=AUTO, 1=MANUAL (from hub status)
        self._current_override = 0  # 0=AUTO, 1=OPEN, 2=CLOSE
        self._updating_ui = False  # Flag to prevent feedback loops
        self._first_tick = True  # For initial visibility setup
        self._settings_loaded = False  # For loading settings only once
        self._user_action_until = 0  # Timestamp until which to ignore hub updates (prevents flicker)

        apply_ui_scale(self, self.cfg.ui_scale)
        self.title(f"Blastgate • {self.node_id}")
        smart_center(self, 720, 560, scale=self.cfg.ui_scale)
        self.minsize(int(620 * self.cfg.ui_scale), int(460 * self.cfg.ui_scale))
        self.resizable(True, True)

        logger.info("NodeDetail opened for node: %s", node_id)

        # Main container
        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True)

        # Header
        header = ttk.Frame(outer, padding=18)
        header.pack(fill="x")
        self.var_name = tb.StringVar(value="(loading)")
        self.var_status = tb.StringVar(value="…")
        ttk.Label(header, textvariable=self.var_name, font=("Segoe UI", 18, "bold")).pack(side="left")

        right = ttk.Frame(header)
        right.pack(side="right")
        ttk.Label(right, textvariable=self.var_status, bootstyle=INFO).pack(side="left", padx=(0, 12))
        ttk.Button(right, text="Rename…", bootstyle=SECONDARY, command=self._rename).pack(side="left")

        # Notebook for tabs
        self.notebook = ttk.Notebook(outer)
        self.notebook.pack(fill="both", expand=True, padx=18, pady=(0, 18))

        # Tab 1: Control
        self.tab_control = ttk.Frame(self.notebook, padding=14)
        self.notebook.add(self.tab_control, text="Control")
        self._build_control_tab()

        # Tab 2: Settings
        self.tab_settings = ttk.Frame(self.notebook, padding=14)
        self.notebook.add(self.tab_settings, text="Settings")
        self._build_settings_tab()

        # Bottom status message
        bottom = ttk.Frame(outer, padding=(18, 0, 18, 12))
        bottom.pack(fill="x")
        self.var_msg = tb.StringVar(value="")
        ttk.Label(bottom, textvariable=self.var_msg, bootstyle=INFO).pack(anchor="w")

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(200, self._tick_ui)

    def _build_control_tab(self):
        """Build the Control tab"""
        # Status info
        info = ttk.Labelframe(self.tab_control, text="Status", padding=14)
        info.pack(fill="x")

        self.var_gate = tb.StringVar(value="-")
        self.var_value = tb.StringVar(value="-")
        self.var_sensor = tb.StringVar(value="")  # Shows "ACTIVE" only when above threshold
        self.var_relay = tb.StringVar(value="-")

        ttk.Label(info, textvariable=self.var_gate, font=("Segoe UI", 12)).pack(anchor="w")
        ttk.Label(info, textvariable=self.var_value).pack(anchor="w", pady=(6, 0))
        self.lbl_sensor = ttk.Label(info, textvariable=self.var_sensor, font=("Segoe UI", 11, "bold"), bootstyle=SUCCESS)
        self.lbl_sensor.pack(anchor="w", pady=(6, 0))
        ttk.Label(info, textvariable=self.var_relay).pack(anchor="w", pady=(6, 0))

        # Mode control (AUTO/MANUAL)
        mode_frame = ttk.Labelframe(self.tab_control, text="Mode", padding=14)
        mode_frame.pack(fill="x", pady=(16, 0))

        mode_row = ttk.Frame(mode_frame)
        mode_row.pack(fill="x")
        self.mode_toggle = TwoStateToggle(
            mode_row,
            width=180,
            height=38,
            left_color="#2a9fd6",    # Blue for AUTO
            right_color="#f0ad4e",   # Orange for MANUAL
            inactive_color="#3a3a3a",
            on_change=self._on_mode_toggle,
            initial_state="left",
            labels=("AUTO", "MANUAL"),
        )
        self.mode_toggle.pack(side="left", pady=4)

        self.var_mode_hint = tb.StringVar(value="AUTO: senzor kontroliše gate")
        ttk.Label(mode_frame, textvariable=self.var_mode_hint, bootstyle=SECONDARY).pack(anchor="w", pady=(10, 0))

        # Manual controls container (hidden when AUTO)
        self.manual_container = ttk.Frame(self.tab_control)
        # Will be packed/unpacked based on mode

        # Gate control (OPEN/CLOSE buttons)
        gate_frame = ttk.Labelframe(self.manual_container, text="Gate Control", padding=14)
        gate_frame.pack(fill="x", pady=(16, 0))

        gate_row = ttk.Frame(gate_frame)
        gate_row.pack(fill="x")

        self.btn_close = ttk.Button(
            gate_row, text="CLOSE", bootstyle=DANGER, width=12,
            command=lambda: self._set_gate("close")
        )
        self.btn_close.pack(side="left", padx=(0, 12))

        self.btn_open = ttk.Button(
            gate_row, text="OPEN", bootstyle=SUCCESS, width=12,
            command=lambda: self._set_gate("open")
        )
        self.btn_open.pack(side="left")

        # Relay control container (hidden when gate is CLOSED)
        self.relay_container = ttk.Labelframe(self.manual_container, text="Relay Control", padding=14)
        # Will be packed/unpacked based on gate state

        relay_row = ttk.Frame(self.relay_container)
        relay_row.pack(fill="x")

        self.btn_relay_off = ttk.Button(
            relay_row, text="OFF", bootstyle=DANGER, width=10,
            command=lambda: self._set_relay("off")
        )
        self.btn_relay_off.pack(side="left", padx=(0, 12))

        self.btn_relay_on = ttk.Button(
            relay_row, text="ON", bootstyle=SUCCESS, width=10,
            command=lambda: self._set_relay("on")
        )
        self.btn_relay_on.pack(side="left")

    def _build_settings_tab(self):
        """Build the Settings tab"""
        # Settings form
        form = ttk.Frame(self.tab_settings)
        form.pack(fill="x")

        self.v_thr = tb.StringVar(value="40.0")
        self.v_hyst = tb.StringVar(value="2.0")
        self.v_hold = tb.StringVar(value="5000")
        self.v_hb_open = tb.StringVar(value="2000")
        self.v_hb_close = tb.StringVar(value="2000")

        # Store entry widgets for Enter key binding
        self._settings_entries = []

        def row_entry(r, label, var, hint):
            ttk.Label(form, text=label, width=20).grid(row=r, column=0, sticky="w", pady=10)
            entry = ttk.Entry(form, textvariable=var, width=15)
            entry.grid(row=r, column=1, sticky="w", padx=12, pady=10)
            entry.bind("<Return>", lambda e: self._apply_settings())
            self._settings_entries.append(entry)
            ttk.Label(form, text=hint, bootstyle=SECONDARY).grid(row=r, column=2, sticky="w", padx=12, pady=10)

        row_entry(0, "Threshold", self.v_thr, "Prag aktivacije (npr 40.0)")
        row_entry(1, "Hysteresis", self.v_hyst, "Sprečava treperenje (npr 2.0)")
        row_entry(2, "Gate hold (ms)", self.v_hold, "Gate ostaje OPEN nakon inactive")
        row_entry(3, "H-bridge open (ms)", self.v_hb_open, "Motor trči pri otvaranju (npr 2000)")
        row_entry(4, "H-bridge close (ms)", self.v_hb_close, "Motor trči pri zatvaranju (npr 2000)")

        form.grid_columnconfigure(2, weight=1)

        # Buttons row
        btn_frame = ttk.Frame(self.tab_settings)
        btn_frame.pack(fill="x", pady=(20, 0))

        ttk.Button(
            btn_frame, text="🔧 Auto-Calibrate", bootstyle=SUCCESS,
            command=self._open_calibration_wizard
        ).pack(side="left", padx=(0, 12))

        ttk.Button(
            btn_frame, text="Refresh from Hub", bootstyle=SECONDARY,
            command=self._refresh_from_hub
        ).pack(side="left", padx=(0, 12))

        ttk.Button(
            btn_frame, text="Apply to HUB", bootstyle=PRIMARY,
            command=self._apply_settings
        ).pack(side="left")

        self.var_settings_msg = tb.StringVar(value="")
        ttk.Label(btn_frame, textvariable=self.var_settings_msg, bootstyle=INFO).pack(side="left", padx=(16, 0))

        # Bind tab change to auto-refresh when entering Settings tab
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def _rename(self):
        """Rename node"""
        self.app.rename_node(self.node_id, parent=self)

    def _open_calibration_wizard(self):
        """Open auto-calibration wizard"""
        # Import here to avoid circular dependency
        from .calibration import CalibrationWizard

        try:
            wizard = CalibrationWizard(self, self.app, self.node_id)
            wizard.grab_set()  # Make dialog modal
            logger.info("Opened calibration wizard for %s", self.node_id)
        except Exception as e:
            logger.error("Failed to open calibration wizard: %s", e, exc_info=True)
            messagebox.showerror(
                "Error",
                f"Failed to open calibration wizard:\n{e}",
                parent=self
            )

    def _on_tab_changed(self, event):
        """Handle tab change - refresh settings when entering Settings tab"""
        try:
            current_tab = self.notebook.index(self.notebook.select())
            if current_tab == 1:  # Settings tab
                self._refresh_from_hub()
        except Exception as e:
            logger.debug("Tab change handler error: %s", e)

    def _refresh_from_hub(self):
        """Refresh settings from hub (pull current values via NODECFG_GET)"""
        self.var_settings_msg.set("Refreshing...")
        logger.info("Refreshing settings from hub for node %s (using NODECFG_GET)", self.node_id)

        def on_config_received(cfg_data):
            # cfg_data is the JSON response from NODECFG_GET
            if cfg_data:
                thr = cfg_data.get("threshold_on", 40.0)
                hold = cfg_data.get("gate_hold_ms", 5000)
                hb_open = cfg_data.get("hbridge_open_ms", 2000)
                hb_close = cfg_data.get("hbridge_close_ms", 2000)

                self.v_thr.set(str(thr))
                self.v_hold.set(str(hold))
                self.v_hb_open.set(str(hb_open))
                self.v_hb_close.set(str(hb_close))

                self.var_settings_msg.set(f"Loaded: thr={thr}, hold={hold}ms, hb={hb_open}/{hb_close}ms")
                logger.info("Settings refreshed from hub: thr=%.1f, hold=%d, hb_open=%d, hb_close=%d",
                            thr, hold, hb_open, hb_close)
            else:
                self.var_settings_msg.set("No config from hub")
                logger.warning("Empty config received from hub")

        def on_config_err(e):
            self.var_settings_msg.set(f"Refresh failed: {e}")
            logger.error("Settings refresh failed: %s", e)

        # Use NODECFG_GET to get actual config values from hub
        self.net.send("nodecfg_get", self.node_id, on_ok=on_config_received, on_err=on_config_err)

    def _load_settings_from_hub_and_local(self, hub_node: Dict[str, Any]):
        """
        Load settings from hub and local config (one-time on window open).
        Priority: local config > hub values > defaults
        """
        # Get local config for this node
        local = self.app._get_local_node(self.node_id)

        # Threshold: prefer local, fallback to hub, then default
        if local.get("threshold") is not None:
            thr = local.get("threshold")
        elif "threshold_on" in hub_node:
            thr = hub_node.get("threshold_on", 40.0)
        else:
            thr = 40.0

        # Hysteresis: only from local config (hub doesn't have this)
        hyst = local.get("hyst", 2.0)

        # Hold time: prefer local, fallback to hub, then default
        if local.get("hold_ms") is not None:
            hold = local.get("hold_ms")
        elif "gate_hold_ms" in hub_node:
            hold = hub_node.get("gate_hold_ms", 5000)
        else:
            hold = 5000

        # Set values in UI
        self.v_thr.set(str(thr))
        self.v_hyst.set(str(hyst))
        self.v_hold.set(str(hold))

        logger.info("Settings loaded for %s: thr=%.1f, hyst=%.1f, hold=%d (local=%s)",
                   self.node_id, float(thr), float(hyst), int(hold),
                   "yes" if local else "no")

    def _on_mode_toggle(self, state: str):
        """Handle mode toggle (AUTO/MANUAL)"""
        if self._updating_ui:
            return

        if self.app.lockout:
            messagebox.showwarning("Locked", "HUB overdrive active.", parent=self)
            self.mode_toggle.set_state("left" if self._current_mode == 0 else "right", animate=True)
            return

        new_mode = "manual" if state == "right" else "auto"
        new_mode_int = 1 if state == "right" else 0
        self.var_msg.set(f"Setting mode -> {new_mode.upper()} ...")
        logger.info("Setting mode for node %s: %s", self.node_id, new_mode)

        # Set long cooldown to prevent _tick_ui from overwriting our change
        # Hub has 300ms status cache, plus network delay, so 3 seconds should be safe
        self._user_action_until = time.time() + 3.0

        # Immediately update local state and visibility (optimistic update)
        self._current_mode = new_mode_int
        # Reset override when switching to AUTO
        if new_mode_int == 0:
            self._current_override = 0  # AUTO override
        # Notify App's AUTO controller about local mode change
        self.app.set_local_node_mode(self.node_id, new_mode_int)
        self._update_controls_visibility()

        if new_mode_int == 0:
            # Switching to AUTO: send mode command, then reset gate override to auto
            def mode_ok():
                logger.info("Mode set to AUTO, now resetting gate override")
                self.var_msg.set("Mode -> AUTO [OK], resetting gate...")
                # Reset gate override to AUTO
                self._reset_gate_to_auto()

            def mode_err(e):
                logger.error("Mode set failed: %s -> auto: %s", self.node_id, e)
                self.var_msg.set(f"Mode error: {e}")
                self._user_action_until = 0
                self._current_mode = 1
                self.app.set_local_node_mode(self.node_id, 1)
                self.mode_toggle.set_state("right", animate=True)
                self._update_controls_visibility()

            self.net.send("mode", self.node_id, "auto", on_ok=mode_ok, on_err=mode_err)
        else:
            # Switching to MANUAL: just send mode command
            def ok():
                self.var_msg.set(f"Mode -> MANUAL [OK]")
                logger.info("Mode set successfully: %s -> manual", self.node_id)
                self._user_action_until = time.time() + 1.5

            def err(e):
                logger.error("Mode set failed: %s -> manual: %s", self.node_id, e)
                self.var_msg.set(f"Mode error: {e}")
                self._user_action_until = 0
                self._current_mode = 0
                self.app.set_local_node_mode(self.node_id, 0)
                self.mode_toggle.set_state("left", animate=True)
                self._update_controls_visibility()

            self.net.send("mode", self.node_id, "manual", on_ok=ok, on_err=err)

    def _reset_gate_to_auto(self):
        """Reset gate override to AUTO (called when switching to AUTO mode)"""
        def ok():
            self.var_msg.set("Mode -> AUTO [OK]")
            logger.info("Gate reset to AUTO for %s", self.node_id)
            self._user_action_until = time.time() + 1.5

        def err(e):
            logger.warning("Gate reset failed: %s: %s", self.node_id, e)
            self.var_msg.set(f"Mode -> AUTO [OK] (gate reset failed: {e})")
            self._user_action_until = time.time() + 1.5

        self.net.send("gate", self.node_id, "auto", on_ok=ok, on_err=err)

    def _set_gate(self, gate: str):
        """Set gate state (open/close)"""
        if self.app.lockout:
            messagebox.showwarning("Locked", "HUB overdrive active.", parent=self)
            return

        logger.info("Setting gate for node %s: %s", self.node_id, gate)

        # Set long cooldown to prevent _tick_ui from overwriting our change
        self._user_action_until = time.time() + 5.0

        # Optimistic update: set local override state
        new_override = 1 if gate == "open" else 2  # 1=OPEN, 2=CLOSE
        self._current_override = new_override
        self._update_controls_visibility()

        if gate == "close":
            # CLOSE sequence: relay OFF first, then gate close after delay
            self.var_msg.set("Relay OFF -> Gate CLOSE ...")
            logger.info("CLOSE sequence: relay OFF first, then gate close")

            def relay_ok():
                self.var_msg.set("Relay OFF [OK], closing gate...")
                logger.info("Relay OFF success, now closing gate")
                # Now send gate close command
                self._send_gate_close()

            def relay_err(e):
                logger.warning("Relay OFF failed: %s, closing gate anyway", e)
                self.var_msg.set(f"Relay OFF failed: {e}, closing gate...")
                # Still try to close gate even if relay failed
                self._send_gate_close()

            self.net.send("relay", "off", on_ok=relay_ok, on_err=relay_err)
        else:
            # OPEN: just send gate open command
            self.var_msg.set(f"Setting gate -> OPEN ...")

            def ok():
                self.var_msg.set("Gate -> OPEN [OK]")
                logger.info("Gate set successfully: %s -> open", self.node_id)
                self._user_action_until = time.time() + 1.5

            def err(e):
                logger.error("Gate set failed: %s -> open: %s", self.node_id, e)
                self.var_msg.set("Gate command failed")
                self._current_override = 0  # Reset to AUTO on error
                self._update_controls_visibility()
                self._user_action_until = 0
                # Show user-friendly error dialog
                show_user_error(self, e, f"Failed to open gate for {self.node_id}")

            self.net.send("gate", self.node_id, "open", on_ok=ok, on_err=err)

    def _send_gate_close(self):
        """Send gate close command (called after relay OFF)"""
        def ok():
            self.var_msg.set("Gate -> CLOSE [OK]")
            logger.info("Gate set successfully: %s -> close", self.node_id)
            self._user_action_until = time.time() + 1.5

        def err(e):
            logger.error("Gate set failed: %s -> close: %s", self.node_id, e)
            self.var_msg.set("Gate command failed")
            self._current_override = 0  # Reset to AUTO on error
            self._update_controls_visibility()
            self._user_action_until = 0
            # Show user-friendly error dialog
            show_user_error(self, e, f"Failed to close gate for {self.node_id}")

        self.net.send("gate", self.node_id, "close", on_ok=ok, on_err=err)

    def _set_relay(self, relay: str):
        """Set relay state (on/off)"""
        if self.app.lockout:
            messagebox.showwarning("Locked", "HUB overdrive active.", parent=self)
            return

        self.var_msg.set(f"Setting relay -> {relay.upper()} ...")
        logger.info("Setting relay: %s", relay)

        self.app.relay_manual(relay)

    def _apply_settings(self):
        """Apply settings to hub"""
        try:
            thr = to_float(self.v_thr.get(), 40.0)
            hyst = max(0.0, to_float(self.v_hyst.get(), 2.0))
            hold = max(0, to_int(self.v_hold.get(), 5000))
            hb_open = max(100, to_int(self.v_hb_open.get(), 2000))
            hb_close = max(100, to_int(self.v_hb_close.get(), 2000))
        except Exception as e:
            self.var_settings_msg.set(f"Invalid input: {e}")
            return

        payload = {
            "threshold_on": thr,
            "relay_hold_ms": hold,
            "gate_hold_ms": hold,
            "hbridge_open_ms": hb_open,
            "hbridge_close_ms": hb_close,
        }

        self.var_settings_msg.set("Applying to HUB...")
        logger.info("Applying settings to hub: %s - %s", self.node_id, payload)

        def ok():
            self.var_settings_msg.set("Applied [OK]")
            # Also save locally for Python AUTO controller
            self.app.set_local_node(self.node_id, {
                "threshold": thr,
                "hyst": hyst,
                "hold_ms": hold,
                "hbridge_open_ms": hb_open,
                "hbridge_close_ms": hb_close,
            })
            logger.info("Settings applied successfully: %s", self.node_id)

        def err(e):
            logger.error("Failed to apply settings: %s - %s", self.node_id, e)
            self.var_settings_msg.set("Configuration failed")
            # Show user-friendly error dialog
            show_user_error(self, e, f"Failed to save configuration for {self.node_id}")

        self.net.send("cfg", self.node_id, payload, on_ok=ok, on_err=err)

    def _update_controls_visibility(self):
        """Show/hide controls based on mode and gate state"""
        logger.debug("Updating controls visibility: mode=%d, override=%d",
                     self._current_mode, self._current_override)

        try:
            if self._current_mode == 1:  # MANUAL
                # First unpack, then pack to ensure correct positioning
                try:
                    self.manual_container.pack_forget()
                except tk.TclError:
                    pass
                self.manual_container.pack(fill="x", pady=(16, 0))
                self.var_mode_hint.set("MANUAL: ručna kontrola gate-a")

                # Show relay controls only if gate is OPEN
                if self._current_override == 1:  # OPEN
                    try:
                        self.relay_container.pack_forget()
                    except tk.TclError:
                        pass
                    self.relay_container.pack(fill="x", pady=(16, 0))
                else:
                    try:
                        self.relay_container.pack_forget()
                    except tk.TclError:
                        pass
            else:  # AUTO
                try:
                    self.relay_container.pack_forget()
                except tk.TclError:
                    pass
                try:
                    self.manual_container.pack_forget()
                except tk.TclError:
                    pass
                self.var_mode_hint.set("AUTO: senzor kontroliše gate")
        except Exception as e:
            logger.debug("Error updating controls visibility: %s", e)

    def _tick_ui(self):
        """Update UI with current status"""
        if self._stop:
            return

        try:
            self._updating_ui = True

            st, state = self.app.get_status_cached()
            self.var_status.set(state if st else "OFFLINE")

            rs = int(st.get("relayState", 0)) if st and "relayState" in st else None
            self.var_relay.set(f"Relay: {'ON' if rs else 'OFF'}" if rs is not None else "Relay: -")

            # Find this node in status
            hit = None
            for n in (st.get("nodes", []) or []):
                if safe_node_id(n) == self.node_id:
                    hit = n
                    break

            if hit:
                # Check if node is online
                node_online = int(hit.get("online", 0)) == 1
                if not node_online:
                    logger.info("Node %s went offline, closing window", self.node_id)
                    self._on_close()
                    return

                hub_name = (hit.get("name") or "").strip() or "(unassigned)"
                name = self.app.get_display_name(self.node_id, hub_name)
                self.var_name.set(name)

                # Get mode and override from hub
                node_mode = int(hit.get("mode", 0))  # 0=AUTO, 1=MANUAL
                override = int(hit.get("override", 0))  # 0=AUTO, 1=OPEN, 2=CLOSE
                gate_open = int(hit.get("gateOpen", 0)) == 1 if "gateOpen" in hit else (override == 1)
                active = int(hit.get("active", 0)) == 1

                # Simple status display
                self.var_gate.set(f"Gate: {'OPEN' if gate_open else 'CLOSED'}")

                # Show sensor value
                val = hit.get("value", None)
                self.var_value.set(f"Value: {val}" if val is not None else "Value: -")

                # Show "ACTIVE" only when sensor is above threshold
                if active:
                    self.var_sensor.set("ACTIVE")
                    self.lbl_sensor.configure(bootstyle=SUCCESS)
                else:
                    self.var_sensor.set("")  # Hide when not active

                # Load settings only once (first time we have hub data)
                if not self._settings_loaded:
                    self._settings_loaded = True
                    self._load_settings_from_hub_and_local(hit)

                # Only sync override from hub, NOT mode (mode is controlled locally)
                # Hub's mode field is unreliable - it gets reset by NODE_PING
                override_changed = (override != self._current_override)

                # Check if we're in cooldown for override changes
                in_cooldown = time.time() < self._user_action_until

                if not in_cooldown:
                    # Sync override from hub (but not mode!)
                    if override_changed:
                        logger.info("Hub override sync: %d -> %d", self._current_override, override)
                        self._current_override = override

                # Mode is controlled LOCALLY - do NOT sync from hub (hub mode is unreliable)
                # Exception: detect when hub auto-resets MANUAL to AUTO (sensor crossed threshold)
                if self._first_tick:
                    self._first_tick = False
                    self._current_mode = node_mode
                    self.app.set_local_node_mode(self.node_id, node_mode)
                    expected_mode_state = "right" if self._current_mode == 1 else "left"
                    self.mode_toggle.set_state(expected_mode_state, animate=False)
                    self._update_controls_visibility()
                    logger.info("Initial mode from hub: %d", node_mode)
                elif not in_cooldown:
                    # Detect hub auto-reset: we're in MANUAL, hub says AUTO with active sensor
                    # This means hub auto-reset due to threshold crossing
                    if self._current_mode == 1 and node_mode == 0 and active:
                        logger.info("Hub auto-reset detected: MANUAL -> AUTO (sensor active)")
                        self._current_mode = 0
                        self.app.set_local_node_mode(self.node_id, 0)
                        self.mode_toggle.set_state("left", animate=True)
                        self._update_controls_visibility()
                    elif override_changed:
                        self._update_controls_visibility()
            else:
                # Node not found in status - if hub is online, node disappeared
                if st and state not in ("OFFLINE", "CONNECTING"):
                    logger.info("Node %s not found in status, closing window", self.node_id)
                    self._updating_ui = False
                    self._on_close()
                    return

            self._updating_ui = False

        except Exception as e:
            self._updating_ui = False
            logger.debug("Failed to update NodeDetail UI: %s", e)

        self.after(250, self._tick_ui)

    def _on_close(self):
        """Close window and cleanup"""
        self._stop = True
        try:
            self.app._node_windows.pop(self.node_id, None)
        except (AttributeError, KeyError, tk.TclError) as e:
            logger.debug("Failed to cleanup node window reference: %s", e)

        try:
            self.destroy()
        except tk.TclError as e:
            logger.debug("Failed to destroy NodeDetail window: %s", e)
