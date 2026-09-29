"""
HTTP calls to the hub (port 80) used by the UI: WiFi scan/set, version.
Hub OTA stays in network/ota.py. In demo mode calls go to FakeHub.
"""
import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from .fake_hub import FakeHub

_UA = {"User-Agent": "BlastgateApp/2.0"}


class HubHttp:
    def __init__(self, demo_hub: Optional[FakeHub] = None) -> None:
        self.demo = demo_hub

    def _get_json(self, ip: str, path: str, timeout: float) -> Any:
        req = urllib.request.Request(f"http://{ip}{path}", headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="ignore"))

    def wifi_scan(self, ip: str) -> List[Dict[str, Any]]:
        if self.demo:
            time.sleep(1.0)
            return self.demo.wifi_scan()
        data = self._get_json(ip, "/wifi_scan", timeout=8)
        return [n for n in data if n.get("ssid")]

    def wifi_set(self, ip: str, ssid: str, password: str) -> None:
        """POST /wifi_set (JSON, supports spaces). The hub restarts right after answering."""
        if self.demo:
            self.demo.wifi_ssid = ssid
            return
        body = json.dumps({"ssid": ssid, "pass": password}).encode("utf-8")
        req = urllib.request.Request(f"http://{ip}/wifi_set", data=body, method="POST",
                                     headers={**_UA, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=8):
                pass
        except (ConnectionResetError, urllib.error.URLError, OSError):
            pass  # hub restarted before the response finished = saved

    def wifi_forget(self, ip: str) -> None:
        if self.demo:
            return
        req = urllib.request.Request(f"http://{ip}/wifi_forget", data=b"{}", method="POST",
                                     headers={**_UA, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5):
                pass
        except (ConnectionResetError, urllib.error.URLError, OSError):
            pass

    def version(self, ip: str) -> Dict[str, Any]:
        if self.demo:
            return self.demo.version()
        return self._get_json(ip, "/version", timeout=5)
