"""
UDP Client for communication with Blastgate ESP32 Hub

This module provides the HubClientUDP class which handles all UDP communication
with the ESP32 hub, including discovery, status polling, and command execution.

Threading Safety:
- All socket operations are protected with a lock (_lock)
- Can be safely used from multiple threads
- Best IP selection is cached to minimize network calls
"""
import json
import logging
import socket
import threading
import time
import urllib.request
import urllib.error
from typing import Optional, Tuple, Dict, Any, List
import ipaddress

from ..models.config import AppConfig
from ..models.status import HubStatus, WifiInfo
from ..constants import AP_DETECT_INTERVAL_S
from ..exceptions import HubOfflineError, HubCommandError, NetworkError, ValidationError
from . import protocol

logger = logging.getLogger(__name__)


class HubClientUDP:
    """
    UDP client for Blastgate ESP32 Hub communication.

    Features:
    - Automatic hub discovery via broadcast
    - Best IP selection (LAN vs AP mode)
    - Command/response pattern with retries
    - Thread-safe socket operations
    - Response validation with Pydantic

    Example:
        >>> client = HubClientUDP(config)
        >>> ip, state = client.pick_best_ip()
        >>> status = client.get_status_fast()
        >>> client.set_node_gate("BG-123", "open")
    """

    def __init__(self, cfg: AppConfig):
        """
        Initialize UDP client

        Args:
            cfg: Application configuration
        """
        self.cfg = cfg
        self.best_ip: Optional[str] = None
        self.last_ok_ip: Optional[str] = None
        self.selected_ip: Optional[str] = None

        # AP mode detection cache
        self._ap_mode_cached: bool = False
        self._last_ap_check: float = 0.0

        # Thread safety
        self._lock = threading.Lock()

        # Create UDP socket
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.settimeout(self.cfg.timeout_s)
            logger.info("UDP client initialized (timeout=%ss, port=%d)",
                       self.cfg.timeout_s, self.cfg.udp_port)
        except OSError as e:
            logger.error("Failed to create UDP socket: %s", e)
            raise NetworkError(f"Cannot create UDP socket: {e}")

    def close(self) -> None:
        """Close UDP socket (best-effort cleanup)"""
        try:
            self.sock.close()
            logger.debug("UDP socket closed")
        except OSError as e:
            logger.debug("Socket close error (ignored): %s", e)

    @staticmethod
    def is_ipv4(ip: str) -> bool:
        """
        Check if string is valid IPv4 address

        Args:
            ip: IP address string to validate

        Returns:
            True if valid IPv4 address
        """
        try:
            ipaddress.IPv4Address(ip)
            return True
        except (ValueError, ipaddress.AddressValueError):
            return False

    def discover_hubs(self) -> List[Dict[str, Any]]:
        """
        Discover hubs via parallel HTTP probes + UDP broadcast.
        Delegates to discovery.discover_hubs() which handles both strategies.

        Returns:
            List of discovered hubs with {"ip": str, "raw": str}
        """
        from .discovery import discover_hubs as _disc
        return _disc(self.cfg, selected_ip=self.selected_ip)

    def _send_cmd(self, ip: str, cmd: bytes) -> Optional[str]:
        """
        Send command and wait for response (single attempt)

        Args:
            ip: Target IP address
            cmd: Command bytes

        Returns:
            Response string or None if timeout/error
        """
        try:
            with self._lock:
                self.sock.sendto(cmd, (ip, self.cfg.udp_port))
                logger.debug("Sent to %s:%d: %s", ip, self.cfg.udp_port, cmd[:50])

                data, _addr = self.sock.recvfrom(8192)
                response = data.decode("utf-8", errors="ignore").strip()
                logger.debug("Received from %s: %s", ip, response[:100])
                return response

        except socket.timeout:
            logger.warning("Socket timeout waiting for %s", ip)
            return None

        except (OSError, socket.error) as e:
            logger.warning("Socket error communicating with %s: %s", ip, e)
            return None

    def _send_cmd_retry(self, ip: str, cmd: bytes, retries: int = 1) -> Optional[str]:
        """
        Send command with retries

        Args:
            ip: Target IP address
            cmd: Command bytes
            retries: Number of retry attempts

        Returns:
            Response string or None if all attempts fail
        """
        for attempt in range(max(0, int(retries)) + 1):
            resp = self._send_cmd(ip, cmd)
            if resp:
                return resp
            if attempt < retries:
                logger.debug("Retry %d/%d for command to %s", attempt + 1, retries, ip)

        logger.warning("All attempts failed for command to %s", ip)
        return None

    def _resolve_mdns(self, hostname: str) -> Optional[str]:
        """Resolve mDNS hostname (e.g. blastgate.local) to IP.
        Works on Windows 10+ and macOS via built-in mDNS.
        Returns IP string or None on failure."""
        try:
            ip = socket.getaddrinfo(hostname, None, socket.AF_INET)[0][4][0]
            logger.debug("mDNS resolved %s → %s", hostname, ip)
            return ip
        except Exception:
            logger.debug("mDNS resolve failed for %s", hostname)
            return None

    def _try_http_status(self, ip: str, timeout: float = 1.5) -> bool:
        """
        Check if hub is reachable via HTTP GET /ping  (fast, ~1 byte response).

        Uses outbound TCP so it works through Windows Firewall without inbound rules.
        Falls back to /status for older firmware that doesn't have /ping yet.
        """
        for path, check in (("/ping", lambda b: b.strip() == "PONG"),
                             ("/status", lambda b: "apIp" in b)):
            try:
                url = f"http://{ip}{path}"
                req = urllib.request.Request(url, headers={"User-Agent": "BlastgateApp/1.0"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    if resp.status == 200:
                        body = resp.read().decode("utf-8", errors="ignore")
                        if check(body):
                            logger.debug("HTTP %s OK at %s", path, ip)
                            return True
            except Exception as e:
                logger.debug("HTTP %s %s: %s", path, ip, e)
        return False

    def _try_ping(self, ip: str) -> bool:
        """
        Try to ping hub at IP address

        Args:
            ip: IP address to ping

        Returns:
            True if hub responds with PONG
        """
        cmd = protocol.build_ping_command()
        response = self._send_cmd_retry(ip, cmd, retries=1)
        is_pong = protocol.is_pong_response(response) if response else False

        if is_pong:
            logger.debug("Ping successful: %s", ip)
        else:
            logger.debug("Ping failed: %s", ip)

        return is_pong

    def _is_on_hub_ap(self) -> bool:
        """Check if we are connected to hub's AP (cached)."""
        if not self.cfg.auto_ap_detect:
            return False

        now = time.time()
        if (now - self._last_ap_check) < AP_DETECT_INTERVAL_S:
            return self._ap_mode_cached

        self._last_ap_check = now
        ok = False
        if self.is_ipv4(self.cfg.hub_ap_ip):
            # HTTP first (works through Windows Firewall), then UDP ping
            ok = self._try_http_status(self.cfg.hub_ap_ip, timeout=0.8) or \
                 self._try_ping(self.cfg.hub_ap_ip)
            logger.debug("AP mode detection: %s (IP: %s)", ok, self.cfg.hub_ap_ip)

        self._ap_mode_cached = ok
        return ok

    def pick_best_ip(self) -> Tuple[Optional[str], str]:
        """
        Pick best IP for hub communication.

        Runs HTTP probes to all candidate IPs in PARALLEL (max 2 s window),
        then returns the highest-priority IP that responded.
        Falls back to sequential UDP ping only when all HTTP probes fail.

        Priority: ETH direct > mDNS > selected > last_ok > LAN > AP
        """
        # Build ordered candidate list (deduped)
        seen: set = set()
        candidates: List[Tuple[str, str]] = []  # (ip, label)

        def _add(ip: Optional[str], label: str) -> None:
            if ip and self.is_ipv4(ip) and ip not in seen:
                seen.add(ip)
                candidates.append((ip, label))

        _add("169.254.5.1", "OK (ETH direct)")

        # mDNS — run in a thread with timeout so it doesn't block the list build
        mdns_result: List[Optional[str]] = [None]

        def _mdns():
            mdns_result[0] = self._resolve_mdns("blastgate.local")

        mdns_t = threading.Thread(target=_mdns, daemon=True)
        mdns_t.start()
        mdns_t.join(timeout=1.5)
        if mdns_result[0]:
            _add(mdns_result[0], "OK (mDNS)")

        _add(self.selected_ip, "OK (selected)")
        _add(self.last_ok_ip, "OK (last good)")
        _add(self.cfg.hub_lan_ip, "OK (LAN)")
        _add(self.cfg.hub_ap_ip, "OK (AP)")

        if not candidates:
            self.best_ip = None
            return None, "OFFLINE"

        # HTTP probe all candidates in parallel — outbound TCP, works through
        # Windows Firewall without any inbound rules.
        http_ok: Dict[str, bool] = {ip: False for ip, _ in candidates}

        def _probe(ip: str) -> None:
            http_ok[ip] = self._try_http_status(ip, timeout=1.5)

        threads = [threading.Thread(target=_probe, args=(ip,), daemon=True)
                   for ip, _ in candidates]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=2.0)

        # Return first responding IP in priority order
        for ip, label in candidates:
            if http_ok[ip]:
                self.best_ip = ip
                self.last_ok_ip = ip
                logger.info("Selected IP: %s (%s, via HTTP)", ip, label)
                return ip, label

        # HTTP failed for all — try UDP ping as fallback
        # (useful on LANs where Windows Firewall is not the issue)
        for ip, label in candidates:
            if self._try_ping(ip):
                self.best_ip = ip
                self.last_ok_ip = ip
                logger.info("Selected IP: %s (%s, via UDP ping)", ip, label)
                return ip, label

        self.best_ip = None
        logger.warning("No hub found on network")
        return None, "OFFLINE"

    def _ensure_connected(self) -> None:
        """
        Ensure hub is connected

        Raises:
            HubOfflineError: If hub is offline
        """
        if not self.best_ip:
            self.pick_best_ip()
        if not self.best_ip:
            raise HubOfflineError("Hub is offline - no response from any IP")

    def get_status_fast(self) -> HubStatus:
        """
        Get hub status (fast path with minimal retries)

        Returns:
            HubStatus instance with validated data

        Raises:
            HubOfflineError: If hub is offline
            HubCommandError: If response is invalid
        """
        # Try current best IP first (no retries for speed)
        if self.best_ip:
            cmd = protocol.build_status_command()
            resp = self._send_cmd_retry(self.best_ip, cmd, retries=0)
            if resp:
                try:
                    data = json.loads(resp)
                    return HubStatus.model_validate(data)
                except (json.JSONDecodeError, ValueError) as e:
                    logger.error("Invalid STATUS response: %s", e)

        # Best IP failed, try to find new one
        ip, _state = self.pick_best_ip()
        if not ip:
            raise HubOfflineError("Hub is offline")

        cmd = protocol.build_status_command()
        resp = self._send_cmd_retry(ip, cmd, retries=1)
        if not resp:
            self.best_ip = None
            raise HubOfflineError(f"No response from hub at {ip}")

        try:
            data = json.loads(resp)
            return HubStatus.model_validate(data)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error("Invalid JSON in STATUS response: %s", e)
            raise HubCommandError(f"Invalid STATUS response: {e}")

    def refresh_status(self, full: bool = False) -> HubStatus:
        """
        Refresh node status on hub

        Args:
            full: If True, performs full refresh (slower but more thorough)

        Returns:
            HubStatus with updated node data

        Raises:
            HubOfflineError: If hub is offline
            HubCommandError: If command fails or response is invalid
        """
        self._ensure_connected()

        cmd = protocol.build_refresh_command(full=full)
        resp = self._send_cmd_retry(self.best_ip, cmd, retries=1)

        if not resp:
            raise HubCommandError(f"No response to {'REFRESH_FULL' if full else 'REFRESH'}")

        if protocol.is_error_response(resp):
            raise HubCommandError(resp)

        try:
            data = json.loads(resp)
            return HubStatus.model_validate(data)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error("Invalid JSON in REFRESH response: %s", e)
            raise HubCommandError(f"Invalid response: {e}")

    def set_node_gate(self, node_id: str, gate: str) -> None:
        """
        Set gate command for node

        Args:
            node_id: Node identifier (e.g., "BG-1F8A3C")
            gate: Gate command ("auto", "open", "close")

        Raises:
            HubOfflineError: If hub is offline
            HubCommandError: If command fails
        """
        self._ensure_connected()

        cmd = protocol.build_node_command(node_id, gate)
        resp = self._send_cmd_retry(self.best_ip, cmd, retries=1)

        if not resp:
            raise HubCommandError(f"No response to NODECMD (node={node_id}, gate={gate})")

        if protocol.is_error_response(resp):
            raise HubCommandError(f"NODECMD failed: {resp}")

        logger.info("Set gate %s -> %s", node_id, gate)

    def set_node_mode(self, node_id: str, mode: str) -> None:
        """
        Set node mode (AUTO/MANUAL)

        Args:
            node_id: Node identifier (e.g., "BG-1F8A3C")
            mode: Mode ("auto", "manual")

        Raises:
            HubOfflineError: If hub is offline
            HubCommandError: If command fails
        """
        self._ensure_connected()

        cmd = protocol.build_node_mode_command(node_id, mode)
        resp = self._send_cmd_retry(self.best_ip, cmd, retries=1)

        if not resp:
            raise HubCommandError(f"No response to NODEMODE (node={node_id}, mode={mode})")

        if protocol.is_error_response(resp):
            raise HubCommandError(f"NODEMODE failed: {resp}")

        logger.info("Set mode %s -> %s", node_id, mode)

    def set_relay(self, mode: str) -> None:
        """
        Set relay mode

        Args:
            mode: Relay mode ("on", "off", "auto")

        Raises:
            HubOfflineError: If hub is offline
            HubCommandError: If command fails
        """
        self._ensure_connected()

        cmd = protocol.build_relay_command(mode)
        resp = self._send_cmd_retry(self.best_ip, cmd, retries=1)

        if not resp:
            raise HubCommandError(f"No response to RELAY {mode}")

        if protocol.is_error_response(resp):
            raise HubCommandError(f"RELAY failed: {resp}")

        logger.info("Set relay -> %s", mode)

    def set_node_name(self, node_id: str, name: str) -> None:
        """
        Assign name to node

        Args:
            node_id: Node identifier
            name: New name for node

        Raises:
            ValidationError: If name is empty
            HubOfflineError: If hub is offline
            HubCommandError: If command fails
        """
        self._ensure_connected()

        try:
            cmd = protocol.build_assign_command(node_id, name)
        except ValueError as e:
            raise ValidationError(str(e))

        resp = self._send_cmd_retry(self.best_ip, cmd, retries=1)

        if not resp:
            raise HubCommandError(f"No response to ASSIGN (node={node_id})")

        if protocol.is_error_response(resp):
            raise HubCommandError(f"ASSIGN failed: {resp}")

        logger.info("Assigned name to %s: %s", node_id, name)

    def set_node_config(self, node_id: str, cfg: Dict[str, Any]) -> None:
        """
        Set node configuration

        Args:
            node_id: Node identifier
            cfg: Configuration dict with keys: threshold_on, relay_hold_ms, gate_hold_ms

        Raises:
            HubOfflineError: If hub is offline
            HubCommandError: If command fails
        """
        self._ensure_connected()

        # Extract config parameters (support both naming conventions)
        thr = cfg.get("threshold_on", cfg.get("thr", None))
        hold_ms = cfg.get("relay_hold_ms", cfg.get("holdMs", None))
        gate_hold_ms = cfg.get("gate_hold_ms", cfg.get("gateHoldMs", None))
        hbridge_open_ms = cfg.get("hbridge_open_ms", None)
        hbridge_close_ms = cfg.get("hbridge_close_ms", None)

        # Default gate_hold_ms to relay_hold_ms if not specified
        if gate_hold_ms is None:
            gate_hold_ms = hold_ms

        cmd = protocol.build_node_config_command(
            node_id, thr, hold_ms, gate_hold_ms,
            hbridge_open_ms, hbridge_close_ms,
        )
        resp = self._send_cmd_retry(self.best_ip, cmd, retries=1)

        if not resp:
            raise HubCommandError(f"No response to NODECFG_SET (node={node_id})")

        if protocol.is_error_response(resp):
            raise HubCommandError(f"NODECFG_SET failed: {resp}")

        logger.info("Updated config for %s", node_id)

    def get_node_config(self, node_id: str) -> Dict[str, Any]:
        """
        Get node configuration from hub

        Args:
            node_id: Node identifier (e.g., "BG-1F8A3C")

        Returns:
            Dict with node config (threshold_on, hyst, gate_hold_ms, etc.)

        Raises:
            HubOfflineError: If hub is offline
            HubCommandError: If command fails or response is invalid
        """
        self._ensure_connected()

        cmd = protocol.build_node_config_get_command(node_id)
        resp = self._send_cmd_retry(self.best_ip, cmd, retries=1)

        if not resp:
            raise HubCommandError(f"No response to NODECFG_GET (node={node_id})")

        if protocol.is_error_response(resp):
            raise HubCommandError(f"NODECFG_GET failed: {resp}")

        try:
            data = json.loads(resp)
            logger.info("Got config for %s: %s", node_id, data)
            return data
        except (json.JSONDecodeError, ValueError) as e:
            logger.error("Invalid JSON in NODECFG_GET response: %s", e)
            raise HubCommandError(f"Invalid NODECFG_GET response: {e}")

    # WiFi controls
    def wifi_get(self) -> WifiInfo:
        """
        Get WiFi connection information

        Returns:
            WifiInfo with connection status

        Raises:
            HubOfflineError: If hub is offline
            HubCommandError: If command fails
        """
        self._ensure_connected()

        cmd = protocol.build_wifi_get_command()
        resp = self._send_cmd_retry(self.best_ip, cmd, retries=1)

        if not resp:
            raise HubCommandError("No response to WIFI_GET")

        if protocol.is_error_response(resp):
            raise HubCommandError(f"WIFI_GET failed: {resp}")

        # Parse WiFi response
        data = protocol.parse_wifi_response(resp)
        return WifiInfo.model_validate(data)

    def wifi_set(self, ssid: str, password: str) -> None:
        """
        Set WiFi credentials and connect

        Args:
            ssid: WiFi SSID
            password: WiFi password

        Raises:
            ValidationError: If SSID is empty
            HubOfflineError: If hub is offline
            HubCommandError: If command fails
        """
        self._ensure_connected()

        try:
            cmd = protocol.build_wifi_set_command(ssid, password)
        except ValueError as e:
            raise ValidationError(str(e))

        resp = self._send_cmd_retry(self.best_ip, cmd, retries=1)

        if not resp:
            raise HubCommandError("No response to WIFI_SET")

        if protocol.is_error_response(resp):
            raise HubCommandError(f"WIFI_SET failed: {resp}")

        logger.info("WiFi credentials set: SSID=%s", ssid)

    def wifi_disconnect(self) -> None:
        """
        Disconnect from WiFi (keep credentials)

        Raises:
            HubOfflineError: If hub is offline
            HubCommandError: If command fails
        """
        self._ensure_connected()

        cmd = protocol.build_wifi_disconnect_command()
        resp = self._send_cmd_retry(self.best_ip, cmd, retries=1)

        if not resp:
            raise HubCommandError("No response to WIFI_DISCONNECT")

        if protocol.is_error_response(resp):
            raise HubCommandError(f"WIFI_DISCONNECT failed: {resp}")

        logger.info("WiFi disconnected")

    def wifi_forget(self) -> None:
        """
        Forget WiFi credentials via HTTP POST /wifi_forget (hub restarts).

        Uses HTTP so it works even when hub is only reachable on the AP subnet
        and firewall blocks UDP replies.
        """
        ip = self.best_ip
        if not ip:
            ip, _ = self.pick_best_ip()
        if not ip:
            raise HubOfflineError("Hub is offline")

        try:
            req = urllib.request.Request(
                f"http://{ip}/wifi_forget",
                data=b"{}",
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5):
                pass
            logger.info("WiFi credentials forgotten (hub restarting)")
        except (ConnectionResetError, urllib.error.URLError, OSError):
            # Hub restarted immediately = success
            logger.info("WiFi forget sent (hub restarting)")
        except Exception as e:
            raise HubCommandError(f"WIFI_FORGET failed: {e}")
