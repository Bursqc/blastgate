"""
Demo mode: an in-process fake hub.

FakeHubClient replaces only the UDP transport (_send_cmd) of the real
HubClientUDP, so NetEngine, protocol parsing and pydantic models run exactly
as with a real hub. FakeHub mirrors the hub firmware rules (threshold -> gate,
gate_hold, relay auto / forced 30 s, manual overdrive lockout + auto-exit).
"""
import json
import random
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from .network.client import HubClientUDP

DEMO_IP = "127.0.0.1"
RELAY_FORCE_TIMEOUT_S = 30.0

_MACHINES = [
    # name, threshold, base rssi, gate_hold_ms
    ("Cirkular", 40.0, -58, 5000),
    ("Abrihter", 55.0, -66, 5000),
    ("Debljinac", 60.0, -71, 8000),
    ("Tračna testera", 35.0, -62, 4000),
    ("Glodalica", 45.0, -79, 5000),
    ("Brusilica", 30.0, -84, 3000),
]


class FakeHub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._t0 = time.time()
        self.lost = False                    # simulate "hub unreachable"
        self.manual_overdrive = False
        self.relay_force: Optional[str] = None  # "on" / "off"
        self.relay_force_t = 0.0
        self.channel = 6
        self.wifi_ssid = "Radionica"
        self.nodes: List[Dict[str, Any]] = []
        for i, (name, thr, rssi, hold) in enumerate(_MACHINES):
            self.nodes.append({
                "id": f"BG-{0xA10000 + i * 0x1111:06X}", "name": name,
                "threshold_on": thr, "gate_hold_ms": hold, "relay_hold_ms": 3000,
                "hbridge_open_ms": 2000, "hbridge_close_ms": 2000, "endstops": 1 if i == 4 else 0,
                "mode": 0, "override": 0, "saved_mode": 0, "saved_override": 0,
                "online": 1, "active": 0, "value": 4.0,
                "running": i in (0, 3), "next_toggle": time.time() + random.uniform(4, 40),
                "gate_cmd_open": False, "close_due": 0.0, "motion_until": 0.0,
                "base_rssi": rssi, "rssi": rssi, "err": 1 if i == 4 else 0,
                "fw": "1.5.0", "uptime0": time.time() - random.randint(600, 9000),
            })

    # ------------------------------------------------------------ simulation
    def _tick(self) -> None:
        now = time.time()
        if self.relay_force and now - self.relay_force_t > RELAY_FORCE_TIMEOUT_S:
            self.relay_force = None
        cycle = (now - self._t0) % 60
        for i, n in enumerate(self.nodes):
            # last machine drops off the network for 12 s every minute
            n["online"] = 0 if (i == 5 and 40 < cycle < 52) else 1
            if not n["online"]:
                n["active"] = 0
                continue
            if now >= n["next_toggle"]:
                n["running"] = not n["running"]
                n["next_toggle"] = now + (random.uniform(8, 20) if n["running"] else random.uniform(10, 30))
            target = n["threshold_on"] * random.uniform(1.4, 1.9) if n["running"] else random.uniform(2, 8)
            n["value"] = round(n["value"] + (target - n["value"]) * 0.35, 2)
            n["rssi"] = int(n["base_rssi"] + random.randint(-3, 3))

            above = n["value"] >= n["threshold_on"]
            if self.manual_overdrive and above:
                self._set_overdrive(False)          # hub auto-exits overdrive when a machine starts
            if not self.manual_overdrive and n["mode"] == 0:
                n["active"] = 1 if above else 0

            want_open = (n["active"] == 1 or n["override"] == 1) and n["override"] != 2
            if want_open:
                n["close_due"] = 0.0
                if not n["gate_cmd_open"]:
                    n["gate_cmd_open"] = True
                    n["motion_until"] = now + n["hbridge_open_ms"] / 1000
            elif n["gate_cmd_open"]:
                if not n["close_due"]:
                    n["close_due"] = now + n["gate_hold_ms"] / 1000
                elif now >= n["close_due"]:
                    n["gate_cmd_open"] = False
                    n["close_due"] = 0.0
                    n["motion_until"] = now + n["hbridge_close_ms"] / 1000

    def _relay(self) -> Tuple[int, int]:
        """(relayState, relayMode) using the hub rules."""
        online = [n for n in self.nodes if n["online"]]
        demand_open = any(n["gate_cmd_open"] for n in online)
        auto_demand = any(n["mode"] == 0 and (n["active"] or n["override"] == 1) and n["override"] != 2
                          for n in online)
        if self.manual_overdrive:
            return int(demand_open), 2
        if self.relay_force == "on":
            return 1, 1
        if self.relay_force == "off":
            return 0, 0
        return int(auto_demand), 2

    def _set_overdrive(self, on: bool) -> None:
        self.manual_overdrive = on
        for n in self.nodes:
            if on:
                n["saved_mode"], n["saved_override"] = n["mode"], n["override"]
                n["mode"], n["override"], n["active"] = 1, 2, 0
                if n["gate_cmd_open"]:           # hub closes every gate immediately (no hold)
                    n["gate_cmd_open"], n["close_due"] = False, 0.0
                    n["motion_until"] = time.time() + n["hbridge_close_ms"] / 1000
            else:
                n["mode"], n["override"] = n["saved_mode"], n["saved_override"]
        self.relay_force = None

    def _node_json(self, n: Dict[str, Any]) -> Dict[str, Any]:
        now = time.time()
        moving = now < n["motion_until"]
        gate_state = (2 if n["gate_cmd_open"] else 3) if moving else (1 if n["gate_cmd_open"] else 0)
        close_in = int(max(0.0, n["close_due"] - now) * 1000) if n["close_due"] else 0
        return {
            "id": n["id"], "name": n["name"], "ip": "", "port": 12000,
            "online": n["online"], "active": n["active"], "gateOpen": int(n["gate_cmd_open"] and n["online"]),
            "override": n["override"], "mode": n["mode"], "ageMs": 400 if n["online"] else 9000,
            "threshold_on": n["threshold_on"], "relay_hold_ms": n["relay_hold_ms"],
            "gate_hold_ms": n["gate_hold_ms"], "hbridge_open_ms": n["hbridge_open_ms"],
            "hbridge_close_ms": n["hbridge_close_ms"],
            "transport": "espnow", "mac": "AC:67:B2:" + n["id"][3:5] + ":" + n["id"][5:7] + ":" + n["id"][7:9],
            "paired": 1, "rssi": n["rssi"] if n["online"] else 0, "nodeRssi": n["rssi"] - 2,
            "lastSeenMs": 400 if n["online"] else 9000, "fw": n["fw"],
            "gateState": gate_state if n["online"] else 0, "err": n["err"],
            "endstops": n["endstops"], "endstopBits": 1 if gate_state == 1 else 2,
            "nodeUptime": int(now - n["uptime0"]), "txFails": 0,
            "value": n["value"] if n["online"] else None, "closeInMs": close_in,
        }

    def status(self) -> Dict[str, Any]:
        relay_state, relay_mode = self._relay()
        return {
            "protoVer": "1.0", "version": "1.5.0", "build": "demo", "uptime": int(time.time() - self._t0) + 3600,
            "freeHeap": 142000, "apIp": "192.168.4.1", "staIp": "192.168.1.50", "sta": 1,
            "ethLink": 0, "ethIp": "", "manualOverdrive": int(self.manual_overdrive),
            "relayState": relay_state, "relayMode": relay_mode, "prov": 0,
            "espnow": 1, "channel": self.channel, "pairing": 0, "pairedCount": len(self.nodes),
            "nodes": [self._node_json(n) for n in self.nodes],
        }

    # -------------------------------------------------------------- protocol
    @staticmethod
    def _arg(msg: str, key: str) -> str:
        for part in msg.split():
            if part.startswith(key + "="):
                return part[len(key) + 1:]
        return ""

    def _find(self, node_id: str) -> Optional[Dict[str, Any]]:
        return next((n for n in self.nodes if n["id"] == node_id), None)

    def handle(self, msg: str) -> Optional[str]:
        with self._lock:
            if self.lost:
                return None
            self._tick()
            return self._handle(msg.strip())

    def _handle(self, msg: str) -> str:
        if msg in ("STATUS", "REFRESH", "REFRESH_FULL"):
            return json.dumps(self.status())
        if msg == "PING":
            return "PONG"
        if msg in ("DISCOVER", "WHO_IS_BLASTGATE?"):
            return f"BLASTGATE_HUB;NAME=blastgate-hub;IP={DEMO_IP};PORT=8888;ETH=0;STA=1;AP=1;APIP=192.168.4.1"
        if msg == "WIFI_GET":
            return f"WIFI;STA=1;SSID={self.wifi_ssid};IP=192.168.1.50;RSSI=-57;PROV=0"
        if msg.startswith("WIFI_SET"):
            self.wifi_ssid = self._arg(msg, "ssid") or self.wifi_ssid
            return "OK WIFI_SET (restarting)"
        if msg == "WIFI_DISCONNECT":
            return "OK WIFI_DISCONNECT (restarting)"

        allowed_in_overdrive = ("RELAY", "NODECMD", "NODECFG_", "NODEMODE", "ASSIGN", "FORGET")
        if self.manual_overdrive and not msg.startswith(allowed_in_overdrive):
            return "ERR manual_overdrive_lockout"

        if msg.startswith("RELAY"):
            if "auto" in msg:
                self.relay_force = None
                return "OK RELAY auto"
            if " on" in msg:
                if not any(n["gate_cmd_open"] for n in self.nodes if n["online"]):
                    self.relay_force = None
                    return "ERR RELAY blocked (no gate open)"
                self.relay_force, self.relay_force_t = "on", time.time()
                return "OK RELAY on"
            if " off" in msg:
                self.relay_force, self.relay_force_t = "off", time.time()
                return "OK RELAY off"
            return "ERR RELAY auto|on|off"

        n = self._find(self._arg(msg, "id"))
        if msg.startswith("NODECMD"):
            if not n:
                return "ERR unknown id"
            gate = self._arg(msg, "gate")
            if gate not in ("auto", "open", "close"):
                return "ERR gate=auto|open|close"
            n["override"] = {"auto": 0, "open": 1, "close": 2}[gate]
            return "OK"
        if msg.startswith("NODEMODE"):
            if not n:
                return "ERR unknown id"
            mode = self._arg(msg, "mode")
            if mode not in ("auto", "manual"):
                return "ERR NODEMODE id=... mode=auto|manual"
            n["mode"] = 0 if mode == "auto" else 1
            if n["mode"] == 0:
                n["active"] = 0
            return "OK"
        if msg.startswith("NODECFG_GET"):
            if not n:
                return "ERR unknown id"
            return json.dumps({k: n[k] for k in ("threshold_on", "relay_hold_ms", "gate_hold_ms",
                                                  "hbridge_open_ms", "hbridge_close_ms")})
        if msg.startswith("NODECFG_SET"):
            if not n:
                return "ERR unknown id"
            for key, cast in (("threshold_on", float), ("relay_hold_ms", int), ("gate_hold_ms", int),
                              ("hbridge_open_ms", int), ("hbridge_close_ms", int), ("endstops", int)):
                v = self._arg(msg, key)
                if v:
                    n[key] = cast(v)
            return "OK"
        if msg.startswith("ASSIGN"):
            if not n:
                return "ERR unknown id"
            n["name"] = self._arg(msg, "name").replace("_", " ")
            return "OK"
        if msg.startswith("FORGET"):
            if n:
                n["name"] = ""
            return "OK"
        return "ERR unknown"

    # ------------------------------------------------------- demo controls
    def toggle_overdrive(self) -> None:
        with self._lock:
            self._set_overdrive(not self.manual_overdrive)

    def set_lost(self, lost: bool) -> None:
        with self._lock:
            self.lost = lost

    def wifi_scan(self) -> List[Dict[str, Any]]:
        return [{"ssid": "Radionica", "rssi": -52}, {"ssid": "Radionica 5G", "rssi": -63},
                {"ssid": "Komšija", "rssi": -81}]

    def version(self) -> Dict[str, Any]:
        return {"protoVer": "1.0", "version": "1.5.0", "build": "demo", "uptime": int(time.time() - self._t0),
                "freeHeap": 142000, "chipModel": "ESP32-D0WD-V3", "otaPartition": "app0"}


class FakeHubClient(HubClientUDP):
    """Real HubClientUDP with the UDP transport replaced by FakeHub."""

    def __init__(self, cfg, hub: FakeHub) -> None:
        super().__init__(cfg)
        self.hub = hub

    def _send_cmd(self, ip: str, cmd: bytes) -> Optional[str]:
        return self.hub.handle(cmd.decode("utf-8", errors="ignore"))

    def pick_best_ip(self) -> Tuple[Optional[str], str]:
        if self.hub.lost:
            self.best_ip = None
            return None, "OFFLINE"
        self.best_ip = self.last_ok_ip = DEMO_IP
        return DEMO_IP, "DEMO"

    def discover_hubs(self) -> List[Dict[str, Any]]:
        raw = self.hub.handle("DISCOVER")
        return [{"ip": DEMO_IP, "raw": raw}] if raw else []
