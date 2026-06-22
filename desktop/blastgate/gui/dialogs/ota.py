"""
OTA firmware update dialog.

UX flow:
  1. Open → spinner while we fetch /version (hub) and manifest.json (server) in parallel
  2. Show table: current vs available + changelog
  3. If newer available → enable [Update] button
  4. On click: download (progress bar) → SHA256 verify → upload (progress bar) → wait reboot
  5. On success: dialog shows new version, button changes to [Close]

Errors are surfaced inline in the status label, not as popups.
"""
from __future__ import annotations

import logging
import threading
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from tempfile import gettempdir
from typing import TYPE_CHECKING, Optional

import ttkbootstrap as tb
from ttkbootstrap.constants import *

from blastgate.gui.utils import apply_ui_scale, smart_center
from blastgate.network.ota import (
    HubVersion,
    OtaManifest,
    check_and_get_update,
    download_firmware,
    is_newer,
    upload_to_hub,
    wait_for_reboot,
)

if TYPE_CHECKING:
    from blastgate.gui.app import App

logger = logging.getLogger(__name__)


class OtaWindow(tb.Toplevel):
    """Firmware update dialog — fetches hub version + remote manifest, then drives the update."""

    def __init__(self, master, app: "App"):
        super().__init__(master)
        self.app = app
        self.cfg = app.cfg
        self._busy = False
        self._closed = False

        # State populated by the background check thread
        self._hub_ver: Optional[HubVersion] = None
        self._manifest: Optional[OtaManifest] = None

        apply_ui_scale(self, self.cfg.ui_scale)
        self.title("Firmware Update")
        smart_center(self, 560, 480, scale=self.cfg.ui_scale)
        self.minsize(int(480 * self.cfg.ui_scale), int(420 * self.cfg.ui_scale))
        self.resizable(True, True)

        self._build_ui()
        self._start_check()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        logger.info("OtaWindow opened")

    # ────────────────────────────────────────────────────────────── UI build ──
    def _build_ui(self) -> None:
        pad = 14
        outer = ttk.Frame(self, padding=pad)
        outer.pack(fill="both", expand=True)

        # Header
        hdr = ttk.Frame(outer)
        hdr.pack(fill="x")
        ttk.Label(hdr, text="Blastgate Hub Firmware Update", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(hdr, text="Hub firmware is fetched from the configured release server.",
                  font=("Segoe UI", 9), bootstyle="secondary").pack(anchor="w", pady=(2, 8))

        ttk.Separator(outer).pack(fill="x", pady=(0, 10))

        # Version comparison grid
        grid = ttk.Frame(outer)
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)

        def _row(r: int, label: str) -> tb.StringVar:
            var = tb.StringVar(value="—")
            ttk.Label(grid, text=label, anchor="w").grid(row=r, column=0, sticky="w", padx=(0, 12), pady=2)
            ttk.Label(grid, textvariable=var, anchor="w").grid(row=r, column=1, sticky="ew", pady=2)
            return var

        self.var_hub_ver  = _row(0, "Hub version:")
        self.var_hub_build = _row(1, "Hub build:")
        self.var_hub_uptime = _row(2, "Hub uptime:")
        self.var_hub_heap = _row(3, "Hub free heap:")
        self.var_remote_ver = _row(4, "Latest version:")
        self.var_proto = _row(5, "Protocol:")

        ttk.Separator(outer).pack(fill="x", pady=10)

        # Changelog
        ttk.Label(outer, text="Changelog", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.txt_changelog = tk.Text(outer, height=6, wrap="word", relief="flat",
                                      borderwidth=1, padx=8, pady=6)
        self.txt_changelog.pack(fill="both", expand=True, pady=(4, 10))
        self.txt_changelog.configure(state="disabled")

        # Status row + progress bar
        status_row = ttk.Frame(outer)
        status_row.pack(fill="x", pady=(0, 6))
        self.var_status = tb.StringVar(value="Checking for updates…")
        ttk.Label(status_row, textvariable=self.var_status, anchor="w").pack(side="left")

        self.progress = ttk.Progressbar(outer, mode="determinate", maximum=100, value=0)
        self.progress.pack(fill="x", pady=(0, 10))

        # Buttons
        btns = ttk.Frame(outer)
        btns.pack(fill="x")
        self.btn_update = ttk.Button(btns, text="Update", bootstyle="success",
                                      state="disabled", command=self._on_update_click)
        self.btn_update.pack(side="right", padx=(8, 0))
        self.btn_close = ttk.Button(btns, text="Close", bootstyle="secondary",
                                     command=self._on_close)
        self.btn_close.pack(side="right")

    # ─────────────────────────────────────────────────────────── Check phase ──
    def _start_check(self) -> None:
        """Fetch hub /version and remote manifest in a background thread."""
        threading.Thread(target=self._do_check, daemon=True, name="OtaCheck").start()

    def _do_check(self) -> None:
        hub_ip = self._resolve_hub_ip()
        if not hub_ip:
            self._ui(lambda: self._set_status("No hub IP available — connect first.", error=True))
            return
        try:
            hub_ver, manifest = check_and_get_update(hub_ip, self.cfg.ota_manifest_url)
        except Exception as e:
            logger.exception("OTA check failed")
            self._ui(lambda err=e: self._set_status(f"Hub unreachable: {err}", error=True))
            return

        self._hub_ver = hub_ver
        self._manifest = manifest
        self._ui(self._render_versions)

    def _render_versions(self) -> None:
        hv = self._hub_ver
        m = self._manifest

        if hv:
            self.var_hub_ver.set(hv.version)
            self.var_hub_build.set(hv.build or "—")
            self.var_hub_uptime.set(f"{hv.uptime // 60} min" if hv.uptime else "—")
            self.var_hub_heap.set(f"{hv.free_heap / 1024:.1f} KB" if hv.free_heap else "—")
            self.var_proto.set(hv.proto_ver)

        if m is None:
            self.var_remote_ver.set("(server unreachable)")
            self._set_status("Could not reach release server.", error=True)
            return

        self.var_remote_ver.set(m.version)
        self._set_changelog(m.changelog or "(no changelog provided)")

        if hv and is_newer(m.version, hv.version):
            self._set_status(f"Update available: {hv.version} → {m.version}", error=False)
            self.btn_update.configure(state="normal")
        else:
            self._set_status("Hub is up to date.", error=False)

    # ────────────────────────────────────────────────────────── Update phase ──
    def _on_update_click(self) -> None:
        if self._busy:
            return
        if not (self._hub_ver and self._manifest):
            return
        self._busy = True
        self.btn_update.configure(state="disabled")
        self.btn_close.configure(state="disabled")
        threading.Thread(target=self._do_update, daemon=True, name="OtaUpdate").start()

    def _do_update(self) -> None:
        hub_ip = self._resolve_hub_ip()
        if not hub_ip or not self._manifest:
            self._ui(lambda: self._set_status("Lost hub connection.", error=True))
            self._ui(self._unlock_buttons)
            return

        manifest = self._manifest
        token = self.cfg.ota_token
        tmp_path = Path(gettempdir()) / f"blastgate_hub_{manifest.version}.bin"

        # Step 1: download
        try:
            self._ui(lambda: self._set_status(f"Downloading {manifest.version}…"))
            self._ui(lambda: self._set_progress(0, 100))

            def dl_progress(done: int, total: int) -> None:
                pct = int((done / total) * 60) if total else 0  # download = 0..60%
                self._ui(lambda p=pct: self._set_progress(p, 100))

            download_firmware(manifest, tmp_path, progress_cb=dl_progress)
        except Exception as e:
            logger.exception("OTA download failed")
            self._ui(lambda err=e: self._set_status(f"Download failed: {err}", error=True))
            self._ui(self._unlock_buttons)
            return

        # Step 2: upload to hub
        try:
            self._ui(lambda: self._set_status("Uploading to hub…"))
            self._ui(lambda: self._set_progress(60, 100))

            def up_progress(done: int, total: int) -> None:
                pct = 60 + int((done / total) * 30) if total else 60  # upload = 60..90%
                self._ui(lambda p=pct: self._set_progress(p, 100))

            resp = upload_to_hub(hub_ip, tmp_path, token, progress_cb=up_progress)
            if not resp.get("ok"):
                err = resp.get("error", "unknown")
                self._ui(lambda e=err: self._set_status(f"Hub rejected upload: {e}", error=True))
                self._ui(self._unlock_buttons)
                return
        except Exception as e:
            logger.exception("OTA upload failed")
            self._ui(lambda err=e: self._set_status(f"Upload failed: {err}", error=True))
            self._ui(self._unlock_buttons)
            return

        # Step 3: wait for reboot
        self._ui(lambda: self._set_status("Hub rebooting…"))
        self._ui(lambda: self._set_progress(90, 100))
        ok = wait_for_reboot(hub_ip, manifest.version, timeout_s=60.0)
        if ok:
            self._ui(lambda: self._set_progress(100, 100))
            self._ui(lambda: self._set_status(f"Update complete → {manifest.version}", error=False))
            self._ui(lambda: self.var_hub_ver.set(manifest.version))
        else:
            self._ui(lambda: self._set_status("Timed out waiting for hub reboot.", error=True))

        self._ui(self._unlock_buttons)
        # Clean up downloaded firmware
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass

    # ───────────────────────────────────────────────────────────── Helpers ──
    def _resolve_hub_ip(self) -> Optional[str]:
        """Return current best hub IP, or None if offline."""
        ip = (self.app.client.best_ip
              or self.app.client.last_ok_ip
              or self.cfg.preferred_hub_ip.strip()
              or None)
        return ip

    def _set_status(self, text: str, error: bool = False) -> None:
        self.var_status.set(text)

    def _set_progress(self, value: int, maximum: int) -> None:
        self.progress.configure(maximum=maximum, value=value)

    def _set_changelog(self, text: str) -> None:
        self.txt_changelog.configure(state="normal")
        self.txt_changelog.delete("1.0", "end")
        self.txt_changelog.insert("1.0", text)
        self.txt_changelog.configure(state="disabled")

    def _unlock_buttons(self) -> None:
        self._busy = False
        self.btn_close.configure(state="normal")
        # Don't re-enable Update after a successful run — version is now current

    def _ui(self, fn) -> None:
        """Schedule a callable on the tk main loop, ignoring if window closed."""
        if self._closed:
            return
        try:
            self.after(0, fn)
        except tk.TclError:
            pass

    def _on_close(self) -> None:
        if self._busy:
            # Don't allow close during upload — interrupting flash can brick the hub
            return
        self._closed = True
        try:
            self.destroy()
        except tk.TclError:
            pass
