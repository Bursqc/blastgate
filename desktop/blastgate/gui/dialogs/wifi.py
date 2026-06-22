"""
WiFi configuration dialog for Blastgate hub.

Three ways to configure hub WiFi:
  1. Soft AP tab  — connect PC to BLASTGATE_HUB, then POST /wifi_set  (or open browser to /setup)
  2. UDP Set tab  — hub already on LAN, send WIFI_SET via UDP
  3. Status tab   — show current WIFI_GET status
"""
import logging
import threading
import tkinter as tk
import webbrowser
from tkinter import ttk, messagebox
from typing import TYPE_CHECKING

import json as _json
import urllib.request
import urllib.error
import ttkbootstrap as tb
from ttkbootstrap.constants import *

from blastgate.gui.utils import apply_ui_scale, smart_center, show_user_error
from blastgate.gui.components import LoadingSpinner

if TYPE_CHECKING:
    from blastgate.gui.app import App

logger = logging.getLogger(__name__)

HUB_AP_IP   = "192.168.4.1"
HUB_AP_SSID = "BLASTGATE_HUB"
HUB_AP_PASS = "12345678"
# Hub HTTP endpoints (available on AP + LAN + ETH, port 80)
HUB_SETUP_URL    = f"http://{HUB_AP_IP}/setup"
HUB_WIFI_SET_URL = f"http://{HUB_AP_IP}/wifi_set"
HUB_WIFI_SCAN_URL = f"http://{HUB_AP_IP}/wifi_scan"


class WifiWindow(tb.Toplevel):
    """Hub WiFi configuration dialog — tabs: Soft AP | UDP | Status"""

    def __init__(self, master, app: "App"):
        super().__init__(master)
        self.app = app
        self.net = app.net
        self.cfg = app.cfg
        self._stop = False
        self._busy_flag = False

        apply_ui_scale(self, self.cfg.ui_scale)
        self.title("HUB Wi-Fi Setup")
        smart_center(self, 600, 520, scale=self.cfg.ui_scale)
        self.minsize(int(500 * self.cfg.ui_scale), int(420 * self.cfg.ui_scale))
        self.resizable(True, True)

        logger.info("WifiWindow opened")

        # ── Notebook (tabs) ──────────────────────────────────────────────────
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=12, pady=12)

        self._tab_softap = ttk.Frame(nb, padding=16)
        self._tab_udp    = ttk.Frame(nb, padding=16)
        self._tab_status = ttk.Frame(nb, padding=16)

        nb.add(self._tab_softap, text="  Soft AP  ")
        nb.add(self._tab_udp,    text="  UDP Set  ")
        nb.add(self._tab_status, text="  Status   ")

        self._build_softap_tab()
        self._build_udp_tab()
        self._build_status_tab()

        # ── Bottom bar ───────────────────────────────────────────────────────
        btm = ttk.Frame(self, padding=(12, 0, 12, 10))
        btm.pack(fill="x")
        self.spinner = LoadingSpinner(btm, size=20, color="#3498db")
        self.spinner.pack(side="left", padx=(0, 8))
        self.spinner.pack_forget()
        self.var_msg = tb.StringVar(value="")
        ttk.Label(btm, textvariable=self.var_msg, bootstyle=INFO).pack(side="left")
        ttk.Button(btm, text="Close", bootstyle=SECONDARY, command=self._close).pack(side="right")

        self.after(200, self._periodic_refresh)
        self.protocol("WM_DELETE_WINDOW", self._close)

    # ── Soft AP tab ──────────────────────────────────────────────────────────

    def _build_softap_tab(self):
        f = self._tab_softap

        ttk.Label(f, text="Soft AP Provisioning", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(f, text="Konektuj računar na HUB Wi-Fi i pošalji kredencijale.",
                  bootstyle=SECONDARY).pack(anchor="w", pady=(4, 16))

        # Step 1: connect to HUB AP
        step1 = ttk.Labelframe(f, text="Korak 1 — Konektuj se na HUB AP", padding=12)
        step1.pack(fill="x", pady=(0, 10))

        info = ttk.Frame(step1)
        info.pack(fill="x")
        ttk.Label(info, text="SSID:", width=10).pack(side="left")
        ttk.Label(info, text=HUB_AP_SSID, font=("Consolas", 11, "bold"), bootstyle=INFO).pack(side="left")
        ttk.Label(info, text="   Pass:", width=8).pack(side="left")
        ttk.Label(info, text=HUB_AP_PASS, font=("Consolas", 11, "bold"), bootstyle=INFO).pack(side="left")

        btn_row = ttk.Frame(step1)
        btn_row.pack(fill="x", pady=(10, 0))
        ttk.Button(btn_row, text="Otvori browser (blastgate setup)",
                   bootstyle=INFO, command=self._open_browser).pack(side="left")
        ttk.Label(btn_row,
                  text="  ← klikni posle konektovanja na HUB AP",
                  bootstyle=SECONDARY).pack(side="left")

        # Step 2: send directly from here via POST /wifi_set
        step2 = ttk.Labelframe(f, text="Korak 2 — Pošalji direktno (POST /wifi_set)", padding=12)
        step2.pack(fill="x", pady=(0, 10))

        ttk.Label(step2, text="(Računar mora biti konektovan na BLASTGATE_HUB ili istu mrežu)",
                  bootstyle=WARNING).pack(anchor="w", pady=(0, 8))

        # SSID dropdown loaded from /wifi_scan
        r0 = ttk.Frame(step2)
        r0.pack(fill="x", pady=4)
        ttk.Label(r0, text="SSID:", width=10).pack(side="left")
        self.v_ap_ssid = tb.StringVar()
        self.cb_ap_ssid = ttk.Combobox(r0, textvariable=self.v_ap_ssid, state="normal")
        self.cb_ap_ssid.pack(side="left", fill="x", expand=True)
        ttk.Button(r0, text="⟳", width=3, bootstyle=SECONDARY,
                   command=self._scan_networks).pack(side="left", padx=(4, 0))

        r1 = ttk.Frame(step2)
        r1.pack(fill="x", pady=4)
        ttk.Label(r1, text="Lozinka:", width=10).pack(side="left")
        self.v_ap_pass = tb.StringVar()
        self.e_ap_pass = ttk.Entry(r1, textvariable=self.v_ap_pass, show="•")
        self.e_ap_pass.pack(side="left", fill="x", expand=True)
        ttk.Checkbutton(r1, text="Prikaži", bootstyle="round-toggle",
                        command=self._toggle_ap_pass).pack(side="left", padx=8)

        self.btn_ap_send = ttk.Button(step2, text="Pošalji kredencijale →",
                                       bootstyle=SUCCESS, command=self._send_softap)
        self.btn_ap_send.pack(anchor="w", pady=(10, 0))

        self.lbl_ap_result = ttk.Label(f, text="", bootstyle=INFO)
        self.lbl_ap_result.pack(anchor="w", pady=(8, 0))

        # Kick off a background scan immediately
        self.after(300, self._scan_networks)

    def _toggle_ap_pass(self):
        self.e_ap_pass.configure(show="" if self.e_ap_pass.cget("show") == "•" else "•")

    def _open_browser(self):
        webbrowser.open(HUB_SETUP_URL)
        self.lbl_ap_result.configure(
            text="Browser otvoren na http://192.168.4.1/setup — izaberi WiFi i unesi lozinku.",
            bootstyle=INFO)

    def _scan_networks(self):
        """Background scan via GET /wifi_scan — fills the SSID combobox."""
        self.lbl_ap_result.configure(text="Skenujem mreže...", bootstyle=INFO)

        def worker():
            try:
                req = urllib.request.Request(
                    HUB_WIFI_SCAN_URL,
                    headers={"User-Agent": "BlastgateApp/1.0"},
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = _json.loads(resp.read().decode())
                ssids = [n["ssid"] for n in data if n.get("ssid")]
                self.after(0, lambda: self._on_scan_done(ssids))
            except Exception as e:
                logger.warning("WiFi scan failed: %s", e)
                self.after(0, lambda: self.lbl_ap_result.configure(
                    text=f"Skeniranje neuspešno (hub možda nije na 192.168.4.1): {e}",
                    bootstyle=WARNING))

        threading.Thread(target=worker, daemon=True).start()

    def _on_scan_done(self, ssids: list):
        try:
            self.cb_ap_ssid.configure(values=ssids)
            if ssids and not self.v_ap_ssid.get():
                self.v_ap_ssid.set(ssids[0])
            self.lbl_ap_result.configure(
                text=f"Pronađeno {len(ssids)} mreža." if ssids else "Nema mreža.",
                bootstyle=INFO)
        except tk.TclError:
            pass

    def _send_softap(self):
        ssid = self.v_ap_ssid.get().strip()
        pw   = self.v_ap_pass.get()
        if not ssid:
            self.lbl_ap_result.configure(text="Unesi SSID!", bootstyle=DANGER)
            return

        self.btn_ap_send.configure(state="disabled")
        self.lbl_ap_result.configure(text="Šaljem...", bootstyle=INFO)

        def worker():
            try:
                body = _json.dumps({"ssid": ssid, "pass": pw}).encode()
                req  = urllib.request.Request(
                    HUB_WIFI_SET_URL,
                    data=body,
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=8):
                    pass
                msg   = "Uspešno! HUB se restartuje i konektuje na WiFi."
                style = SUCCESS
            except (ConnectionResetError, urllib.error.URLError, OSError):
                # Hub restarted immediately after saving creds — reset = success
                msg   = "Uspešno! HUB se restartuje i konektuje na WiFi."
                style = SUCCESS
            except Exception as e:
                msg   = f"Greška: {e}"
                style = DANGER

            self.after(0, lambda: self.lbl_ap_result.configure(text=msg, bootstyle=style))
            self.after(0, lambda: self.btn_ap_send.configure(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    # ── UDP Set tab ──────────────────────────────────────────────────────────

    def _build_udp_tab(self):
        f = self._tab_udp

        ttk.Label(f, text="UDP WiFi Set", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(f, text="Šalje WIFI_SET komandu na HUB kada si već na istoj mreži.",
                  bootstyle=SECONDARY).pack(anchor="w", pady=(4, 16))

        frm = ttk.Labelframe(f, text="Kredencijali", padding=14)
        frm.pack(fill="x")

        self.v_ssid = tb.StringVar()
        self.v_pass = tb.StringVar()

        r0 = ttk.Frame(frm)
        r0.pack(fill="x", pady=6)
        ttk.Label(r0, text="SSID:", width=10).pack(side="left")
        ttk.Entry(r0, textvariable=self.v_ssid).pack(side="left", fill="x", expand=True)

        r1 = ttk.Frame(frm)
        r1.pack(fill="x", pady=6)
        ttk.Label(r1, text="Lozinka:", width=10).pack(side="left")
        self.e_pass = ttk.Entry(frm, textvariable=self.v_pass, show="•")
        self.e_pass.pack(fill="x", pady=(0, 6))
        ttk.Checkbutton(frm, text="Prikaži lozinku", bootstyle="round-toggle",
                        command=self._toggle_udp_pass).pack(anchor="w")

        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(12, 0))
        self.btn_set = ttk.Button(btns, text="Pošalji (UDP)", bootstyle=SUCCESS, command=self.on_set)
        self.btn_set.pack(side="left")
        ttk.Label(btns, text="   Za brisanje WiFi drži dugme na HUB-u ≥3s",
                  bootstyle=SECONDARY).pack(side="left")

    def _toggle_udp_pass(self):
        self.e_pass.configure(show="" if self.e_pass.cget("show") == "•" else "•")

    # ── Status tab ───────────────────────────────────────────────────────────

    def _build_status_tab(self):
        f = self._tab_status

        ttk.Label(f, text="WiFi Status", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(f, text="Trenutno stanje WiFi veze na HUB-u.",
                  bootstyle=SECONDARY).pack(anchor="w", pady=(4, 12))

        self.txt = tk.Text(f, height=10, wrap="word", state="disabled")
        self.txt.pack(fill="both", expand=True)

        ttk.Button(f, text="Osveži", bootstyle=INFO, command=self.refresh).pack(anchor="w", pady=(10, 0))

    def _close(self):
        """Close window and cleanup"""
        self._stop = True
        try:
            self.app._win_wifi = None
        except (AttributeError, tk.TclError) as e:
            logger.debug("Failed to cleanup WiFi window reference: %s", e)

        try:
            self.destroy()
        except tk.TclError as e:
            logger.debug("Failed to destroy WifiWindow: %s", e)

    def _periodic_refresh(self):
        """Periodically refresh WiFi status (every 2 seconds)"""
        if self._stop:
            return
        # Skip if already busy (operation in progress)
        if not self._busy_flag:
            self.refresh()
        self.after(2000, self._periodic_refresh)  # Refresh every 2 seconds

    def _busy(self, on: bool):
        """Enable/disable buttons during operation and show/hide spinner"""
        self._busy_flag = on
        st = "disabled" if on else "normal"
        for b in (self.btn_set,):
            try:
                b.configure(state=st)
            except tk.TclError as e:
                logger.debug("Failed to set button state: %s", e)

        # Show/hide and animate spinner
        try:
            if on:
                self.spinner.pack(side="left", padx=(0, 8))
                self.spinner.start()
            else:
                self.spinner.stop()
                self.spinner.pack_forget()
        except (tk.TclError, AttributeError) as e:
            logger.debug("Failed to update spinner: %s", e)

    def _write(self, s: str):
        """Write text to status display"""
        try:
            self.txt.configure(state="normal")
            self.txt.delete("1.0", tk.END)
            self.txt.insert(tk.END, s)
            self.txt.configure(state="disabled")
        except tk.TclError as e:
            logger.debug("Failed to update status text: %s", e)

    def refresh(self):
        """Refresh WiFi status from hub"""
        self._busy(True)
        self.var_msg.set("Reading status...")
        logger.info("Refreshing WiFi status...")

        def ok(d):
            try:
                st, state = self.net.get_cached_status()
                hub_ip = self.app.client.best_ip or self.app.client.last_ok_ip or "?"

                # Parse STA status
                sta_raw = d.get('STA', '')
                sta_connected = sta_raw in ('Yes', '1', 'true', 'True', True, 1)

                ssid = d.get('SSID', '') or ''
                wifi_ip = d.get('IP', '') or ''
                rssi = d.get('RSSI', '') or ''

                if sta_connected and ssid:
                    # Connected to WiFi
                    txt = (
                        f"HUB: {hub_ip} ({state})\n\n"
                        f"Status: CONNECTED\n"
                        f"SSID: {ssid}\n"
                        f"IP: {wifi_ip}\n"
                        f"Signal: {rssi} dBm\n"
                    )
                    self.var_msg.set("Connected")
                else:
                    # Not connected
                    txt = (
                        f"HUB: {hub_ip} ({state})\n\n"
                        f"Status: NOT CONNECTED\n"
                        f"No WiFi credentials saved.\n"
                    )
                    self.var_msg.set("Not connected")

                self._write(txt)
                logger.info("WiFi status refreshed: STA=%s, SSID=%s", sta_raw, ssid)
            except Exception as e:
                logger.error("Failed to process WiFi status: %s", e, exc_info=True)
                self.var_msg.set(f"Error: {e}")
            finally:
                self._busy(False)

        def err(e):
            logger.error("WiFi status request failed: %s", e)
            self.var_msg.set(f"Error: {e}")
            self._write(str(e))
            self._busy(False)

        self.net.send("wifi_get", on_ok=ok, on_err=err)

    def on_set(self):
        """WiFi connect/set credentials"""
        ssid = self.v_ssid.get().strip()
        pw = self.v_pass.get()

        if not ssid:
            messagebox.showwarning("SSID", "Unesi SSID.", parent=self)
            return

        self._busy(True)
        self.var_msg.set("Connecting...")
        logger.info("Setting WiFi credentials: SSID=%s", ssid)

        # Show connecting status immediately
        self._write(f"Connecting to: {ssid}\n\nPlease wait...")

        def ok():
            self.var_msg.set("Credentials saved, connecting...")
            logger.info("WiFi credentials set successfully")
            self._write(f"Connecting to: {ssid}\n\nWaiting for connection...")
            self._busy(False)
            # Quick refresh to show new status
            self.after(500, self.refresh)

        def err(e):
            logger.error("WiFi SET failed: %s", e)
            self.var_msg.set("Connection failed")
            self._write(f"Failed to connect to: {ssid}")
            self._busy(False)
            # Show user-friendly error dialog
            show_user_error(self, e, f"Failed to connect to WiFi network: {ssid}")

        self.net.send("wifi_set", ssid, pw, on_ok=ok, on_err=err)


