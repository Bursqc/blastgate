"""
Auto-calibration wizard for finding optimal threshold values
"""
import logging
import time
import tkinter as tk
from tkinter import ttk, messagebox
from typing import TYPE_CHECKING, Optional, List

import ttkbootstrap as tb
from ttkbootstrap.constants import *

from blastgate.gui.utils import apply_ui_scale, smart_center
from blastgate.gui.components import ProgressBar, LoadingSpinner
from blastgate.utils.helpers import to_float, to_int

if TYPE_CHECKING:
    from blastgate.gui.app import App

logger = logging.getLogger(__name__)


class CalibrationWizard(tb.Toplevel):
    """
    Auto-calibration wizard for finding optimal sensor threshold.

    Steps:
    1. Start: User prepares to turn on machine
    2. Sampling ON: Collect sensor readings while machine runs
    3. Turn OFF: User turns off machine
    4. Sampling OFF: Verify readings drop below threshold
    5. Complete: Save calibrated threshold
    """

    # Calibration states
    STATE_START = 0
    STATE_WAIT_ON = 1
    STATE_SAMPLE_ON = 2
    STATE_WAIT_OFF = 3
    STATE_SAMPLE_OFF = 4
    STATE_COMPLETE = 5

    def __init__(self, master, app: "App", node_id: str):
        super().__init__(master)

        self.app = app
        self.node_id = node_id
        self.net = app.net

        # Calibration state
        self._state = self.STATE_START
        self._samples_on: List[float] = []
        self._samples_off: List[float] = []
        self._baseline_samples: List[float] = []
        self._baseline_avg: float = 0.0
        self._recommended_threshold: Optional[float] = None
        self._stop = False
        self._last_sensor_value: Optional[float] = None  # Dedup cached readings

        # UI setup
        self.title(f"Auto-Calibration - {node_id}")
        smart_center(self, 500, 420, scale=app.cfg.ui_scale)
        self.minsize(int(440 * app.cfg.ui_scale), int(360 * app.cfg.ui_scale))
        self.resizable(True, True)

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._close)

        logger.info("Calibration wizard started for %s", node_id)

    def _build_ui(self):
        """Build wizard UI"""
        wrap = ttk.Frame(self, padding=14)
        wrap.pack(fill="both", expand=True)

        # Header
        ttk.Label(wrap, text="Auto-Calibration", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(wrap, text=f"Node: {self.node_id}", bootstyle=SECONDARY).pack(anchor="w", pady=(2, 10))

        # Instructions area
        self.instructions_frame = ttk.Labelframe(wrap, text="Instructions", padding=8)
        self.instructions_frame.pack(fill="both", expand=True, pady=(0, 8))

        self.var_instructions = tb.StringVar(value=self._get_instructions())
        self.lbl_instructions = ttk.Label(
            self.instructions_frame,
            textvariable=self.var_instructions,
            wraplength=360,
            justify="left"
        )
        self.lbl_instructions.pack(fill="both", expand=True)

        # Update wraplength when window is resized
        self.instructions_frame.bind("<Configure>", self._on_frame_resize)

        # Status area
        status_frame = ttk.Labelframe(wrap, text="Status", padding=8)
        status_frame.pack(fill="x", pady=(0, 8))

        # Progress bar
        self.progress = ProgressBar(status_frame, width=200, height=6)
        self.progress.pack(fill="x", expand=True, pady=(0, 6))

        # Status text with spinner
        status_row = ttk.Frame(status_frame)
        status_row.pack(fill="x")

        self.spinner = LoadingSpinner(status_row, size=16)
        self.spinner.pack(side="left", padx=(0, 6))
        self.spinner.pack_forget()

        self.var_status = tb.StringVar(value="Ready to start")
        ttk.Label(status_row, textvariable=self.var_status, bootstyle=INFO).pack(side="left")

        # Current reading + samples on same row
        info_row = ttk.Frame(status_frame)
        info_row.pack(fill="x", pady=(6, 0))

        ttk.Label(info_row, text="Reading:").pack(side="left")
        self.var_reading = tb.StringVar(value="--")
        ttk.Label(info_row, textvariable=self.var_reading, font=("Consolas", 10, "bold")).pack(side="left", padx=(4, 16))

        ttk.Label(info_row, text="Samples:").pack(side="left")
        self.var_samples = tb.StringVar(value="0")
        ttk.Label(info_row, textvariable=self.var_samples).pack(side="left", padx=(4, 0))

        # Buttons
        btn_frame = ttk.Frame(wrap)
        btn_frame.pack(fill="x", pady=(8, 0))

        self.btn_action = ttk.Button(
            btn_frame,
            text="Start Calibration",
            bootstyle=SUCCESS,
            command=self._on_action
        )
        self.btn_action.pack(side="left")

        self.btn_cancel = ttk.Button(
            btn_frame,
            text="Cancel",
            bootstyle=SECONDARY,
            command=self._close
        )
        self.btn_cancel.pack(side="left", padx=(12, 0))

    def _on_frame_resize(self, event):
        """Update wraplength when instructions frame resizes"""
        try:
            new_width = event.width - 20  # Account for padding
            if new_width > 100:
                self.lbl_instructions.configure(wraplength=new_width)
        except (tk.TclError, AttributeError):
            pass

    def _get_instructions(self) -> str:
        """Get instructions for current state"""
        if self._state == self.STATE_START:
            return (
                "Find the optimal threshold for your machine.\n\n"
                "1. Make sure the machine is OFF\n"
                "2. Click 'Start Calibration'\n"
                "3. Turn ON when prompted\n"
                "4. Turn OFF when prompted\n\n"
                "Threshold will be calculated automatically."
            )
        elif self._state == self.STATE_WAIT_ON:
            return (
                "📍 Step 1: Turn ON the machine\n\n"
                "Please turn on your machine now and wait for it to reach normal operating speed.\n\n"
                "The wizard will automatically detect when the machine is running and start collecting samples."
            )
        elif self._state == self.STATE_SAMPLE_ON:
            return (
                "⏱️ Step 2: Sampling while ON\n\n"
                "Keep the machine running...\n\n"
                "The wizard is collecting sensor readings to determine the threshold. "
                "This will take about 5-10 seconds."
            )
        elif self._state == self.STATE_WAIT_OFF:
            return (
                "📍 Step 3: Turn OFF the machine\n\n"
                "Please turn off your machine now.\n\n"
                "The wizard will verify that sensor readings drop below the calculated threshold."
            )
        elif self._state == self.STATE_SAMPLE_OFF:
            return (
                "⏱️ Step 4: Verifying OFF state\n\n"
                "Machine should be OFF...\n\n"
                "The wizard is verifying that sensor readings are below the threshold."
            )
        elif self._state == self.STATE_COMPLETE:
            if self._recommended_threshold is not None:
                avg_on = sum(self._samples_on) / len(self._samples_on) if self._samples_on else 0
                avg_off = sum(self._samples_off) / len(self._samples_off) if self._samples_off else 0
                return (
                    f"Calibration Complete!\n\n"
                    f"Recommended threshold: {self._recommended_threshold:.1f}\n\n"
                    f"Samples collected:\n"
                    f"  Machine ON: {len(self._samples_on)} samples (avg: {avg_on:.1f})\n"
                    f"  Machine OFF: {len(self._samples_off)} samples (avg: {avg_off:.1f})\n\n"
                    f"Click 'Apply' to save this threshold to the node."
                )
            else:
                return "Calibration failed. Please try again."
        return ""

    def _on_action(self):
        """Handle action button click"""
        if self._state == self.STATE_START:
            self._start_calibration()
        elif self._state == self.STATE_COMPLETE:
            self._apply_threshold()

    def _start_calibration(self):
        """Start calibration process"""
        self._state = self.STATE_WAIT_ON
        self._samples_on = []
        self._samples_off = []
        self._baseline_samples = []
        self._baseline_avg = 0.0
        self._last_sensor_value = None

        self.var_instructions.set(self._get_instructions())
        self.var_status.set("Waiting for machine to turn ON...")
        self.btn_action.configure(state="disabled")

        # Start monitoring loop
        self.spinner.pack(side="left", padx=(0, 8))
        self.spinner.start()
        self.after(500, self._monitor_loop)

        logger.info("Calibration started: waiting for machine ON")

    def _monitor_loop(self):
        """Monitor sensor readings and advance calibration steps"""
        if self._stop:
            return

        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return

        # Get current node status
        status, _ = self.app.get_status_cached()
        nodes = status.get("nodes", [])
        node = next((n for n in nodes if n.get("id") == self.node_id), None)

        if not node:
            self.var_status.set("Error: Node not found")
            logger.error("Node %s not found during calibration", self.node_id)
            self._stop = True
            return

        # Get sensor reading - field is "value" in NodeStatus model
        raw_sensor = node.get("value")
        if raw_sensor is None:
            # No reading yet, skip this cycle
            self.var_reading.set("--")
            self.var_status.set("Waiting for sensor data...")
            self.after(500, self._monitor_loop)
            return

        sensor = to_float(raw_sensor, 0.0)
        self.var_reading.set(f"{sensor:.1f}")

        # Dedup: skip if same cached value (hub polls every ~650ms, we poll faster)
        is_new_reading = (self._last_sensor_value is None or
                          abs(sensor - self._last_sensor_value) > 0.01)
        self._last_sensor_value = sensor

        # State machine
        if self._state == self.STATE_WAIT_ON:
            # Collect baseline samples (only count distinct readings)
            if len(self._baseline_samples) < 5:
                if is_new_reading:
                    self._baseline_samples.append(sensor)
                self.var_status.set(f"Measuring baseline... ({len(self._baseline_samples)}/5)")
            else:
                # Calculate baseline and detect machine ON
                baseline_avg = sum(self._baseline_samples) / len(self._baseline_samples)
                # Machine is ON if reading is significantly above baseline
                detect_threshold = max(baseline_avg * 1.5, baseline_avg + 8.0)

                if sensor > detect_threshold:
                    self._baseline_avg = baseline_avg
                    self._state = self.STATE_SAMPLE_ON
                    self.var_instructions.set(self._get_instructions())
                    self.var_status.set(f"Machine detected ON (baseline: {baseline_avg:.1f})")
                    self.progress.set_progress(0.0)
                    logger.info("Machine detected ON (baseline=%.1f, current=%.1f)", baseline_avg, sensor)
                else:
                    self.var_status.set(f"Waiting for machine... (baseline: {baseline_avg:.1f}, current: {sensor:.1f})")

        elif self._state == self.STATE_SAMPLE_ON:
            # Collect samples while machine is ON (only distinct readings)
            if is_new_reading:
                self._samples_on.append(sensor)
                self.var_samples.set(f"{len(self._samples_on)}")
            progress = min(1.0, len(self._samples_on) / 15.0)  # 15 unique samples target
            self.progress.set_progress(progress)

            # Need at least 10 unique samples
            if len(self._samples_on) >= 10:
                # Calculate recommended threshold
                avg_on = sum(self._samples_on) / len(self._samples_on)
                min_on = min(self._samples_on)
                baseline = self._baseline_avg

                # Threshold = midpoint between baseline and minimum ON reading
                self._recommended_threshold = round((baseline + min_on) / 2.0, 1)

                # Ensure threshold is at least slightly above baseline
                if self._recommended_threshold <= baseline:
                    self._recommended_threshold = round(baseline + (min_on - baseline) * 0.3, 1)

                self._state = self.STATE_WAIT_OFF
                self.var_instructions.set(self._get_instructions())
                self.var_status.set(f"Threshold: {self._recommended_threshold:.1f} (baseline={baseline:.1f}, min_on={min_on:.1f})")
                self.progress.set_progress(1.0)
                logger.info("Sampling complete: threshold=%.1f (baseline=%.1f, avg=%.1f, min=%.1f)",
                          self._recommended_threshold, baseline, avg_on, min_on)

        elif self._state == self.STATE_WAIT_OFF:
            # Wait for sensor to drop below threshold (machine turned off)
            if self._recommended_threshold and sensor < self._recommended_threshold:
                self._state = self.STATE_SAMPLE_OFF
                self._samples_off = []  # Clear for fresh verification
                self.var_instructions.set(self._get_instructions())
                self.var_status.set("Verifying OFF readings...")
                self.progress.set_progress(0.0)
                logger.info("Machine detected OFF, verifying")

        elif self._state == self.STATE_SAMPLE_OFF:
            # Verify readings stay below threshold (only distinct readings)
            if is_new_reading:
                self._samples_off.append(sensor)
                self.var_samples.set(f"{len(self._samples_off)}")
            progress = min(1.0, len(self._samples_off) / 5.0)  # 5 unique samples target
            self.progress.set_progress(progress)

            # Need at least 5 unique samples below threshold
            if len(self._samples_off) >= 5:
                max_off = max(self._samples_off)
                if max_off < self._recommended_threshold:
                    # Success!
                    self._state = self.STATE_COMPLETE
                    self.var_instructions.set(self._get_instructions())
                    self.var_status.set("Calibration successful!")
                    self.progress.set_progress(1.0)
                    self.btn_action.configure(text="Apply Threshold", state="normal")
                    self.spinner.stop()
                    self.spinner.pack_forget()
                    logger.info("Calibration complete: threshold=%.1f", self._recommended_threshold)
                    return
                else:
                    # Failed - readings still above threshold, allow retry
                    self.var_status.set(f"Verification failed (max_off={max_off:.1f} >= threshold)")
                    logger.warning("Calibration failed: max_off=%.1f >= threshold=%.1f",
                                 max_off, self._recommended_threshold)
                    self.spinner.stop()
                    self.spinner.pack_forget()
                    self.btn_action.configure(text="Retry Calibration", state="normal")
                    self._state = self.STATE_START
                    return

        # Continue monitoring (poll slightly faster than hub update rate)
        try:
            self.after(400, self._monitor_loop)
        except tk.TclError:
            pass  # Widget destroyed

    def _apply_threshold(self):
        """Apply calibrated threshold to node"""
        if not self._recommended_threshold:
            return

        # Get current node config
        status, _ = self.app.get_status_cached()
        nodes = status.get("nodes", [])
        node = next((n for n in nodes if n.get("id") == self.node_id), None)

        if not node:
            messagebox.showerror("Error", "Node not found", parent=self)
            return

        # Build config payload with new threshold (dict format)
        relay_hold = to_int(node.get("relay_hold_ms", 5000))
        gate_hold = to_int(node.get("gate_hold_ms", 0))

        payload = {
            "threshold_on": self._recommended_threshold,
            "relay_hold_ms": relay_hold,
            "gate_hold_ms": gate_hold,
        }

        def on_ok():
            self.var_status.set("Threshold applied successfully!")
            logger.info("Threshold applied: %s -> %.1f", self.node_id, self._recommended_threshold)
            messagebox.showinfo(
                "Success",
                f"Threshold {self._recommended_threshold:.1f} has been applied to {self.node_id}",
                parent=self
            )
            self.after(1000, self._close)

        def on_err(e):
            self.var_status.set("Failed to apply threshold")
            logger.error("Failed to apply threshold: %s", e)
            messagebox.showerror("Error", f"Failed to apply threshold:\n{e}", parent=self)

        self.net.send("cfg", self.node_id, payload, on_ok=on_ok, on_err=on_err)

        # Also save to local config
        self.app.set_local_node(self.node_id, {"threshold": self._recommended_threshold})

    def _close(self):
        """Close wizard"""
        self._stop = True
        try:
            self.spinner.stop()
        except (tk.TclError, AttributeError):
            pass

        try:
            self.destroy()
        except tk.TclError as e:
            logger.debug("Failed to destroy CalibrationWizard: %s", e)

        logger.info("Calibration wizard closed")
