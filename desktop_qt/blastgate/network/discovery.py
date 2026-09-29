"""
Hub discovery via UDP broadcast + HTTP probe

UDP discovery waits for inbound responses which Windows Firewall may block.
HTTP probe uses outbound TCP (GET /status) — always works without firewall rules.
Both run in parallel; results are merged.
"""
import json
import logging
import socket
import threading
import time
import urllib.request
import urllib.error
from typing import List, Dict, Any, Optional
import ipaddress

from ..models.config import AppConfig
from . import protocol

logger = logging.getLogger(__name__)


def is_valid_ipv4(ip: str) -> bool:
    """Check if string is valid IPv4 address"""
    try:
        ipaddress.IPv4Address(ip)
        return True
    except (ValueError, ipaddress.AddressValueError):
        return False


def _resolve_mdns(hostname: str) -> Optional[str]:
    """Resolve mDNS hostname to IP (works on Windows 10+ and macOS)."""
    try:
        return socket.getaddrinfo(hostname, None, socket.AF_INET)[0][4][0]
    except Exception:
        return None


def _http_probe(ip: str, timeout: float = 2.0) -> Optional[Dict[str, Any]]:
    """
    Discover hub at IP via HTTP.

    1. GET /ping  — fast check (new endpoint, avoids parsing JSON)
    2. GET /status — parse JSON to build discovery reply

    Uses outbound TCP so it works through Windows Firewall without inbound rules.
    Returns hub dict {"ip": str, "raw": str} or None.
    """
    try:
        # Fast ping first (cheap, avoids full JSON parse on dead IPs)
        ping_url = f"http://{ip}/ping"
        req = urllib.request.Request(ping_url, headers={"User-Agent": "BlastgateApp/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            body = resp.read().decode("utf-8", errors="ignore").strip()
            if body != "PONG":
                return None
    except Exception as e:
        logger.debug("HTTP ping %s: %s", ip, e)
        return None

    # Ping succeeded — fetch full status for discovery reply
    try:
        status_url = f"http://{ip}/status"
        req = urllib.request.Request(status_url, headers={"User-Agent": "BlastgateApp/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                # Still return a minimal result — ping confirmed hub is there
                raw = f"BLASTGATE_HUB;NAME=blastgate-hub;IP={ip};PORT=8888;AP=1;APIP=192.168.4.1"
                return {"ip": ip, "raw": raw}
            body = resp.read().decode("utf-8", errors="ignore")
            data = json.loads(body)
            if not isinstance(data, dict) or "apIp" not in data:
                raw = f"BLASTGATE_HUB;NAME=blastgate-hub;IP={ip};PORT=8888;AP=1;APIP=192.168.4.1"
                return {"ip": ip, "raw": raw}
            ap_ip = data.get("apIp", "192.168.4.1")
            raw = (
                f"BLASTGATE_HUB;NAME=blastgate-hub;IP={ip};PORT=8888;"
                f"ETH={data.get('ethLink', 0)};STA={data.get('sta', 0)};"
                f"AP=1;APIP={ap_ip}"
            )
            logger.info("HTTP probe found hub at %s (ethIp=%s)", ip, data.get("ethIp", ""))
            return {"ip": ip, "raw": raw}
    except Exception as e:
        logger.debug("HTTP status %s: %s", ip, e)
        # Ping was OK → return minimal result
        raw = f"BLASTGATE_HUB;NAME=blastgate-hub;IP={ip};PORT=8888;AP=1;APIP=192.168.4.1"
        return {"ip": ip, "raw": raw}


def discover_hubs(config: AppConfig, selected_ip: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Discover Blastgate hubs on network.

    Uses two parallel strategies:
    1. UDP broadcast — fast, works on LAN (hub replies to broadcast)
    2. HTTP probe   — works through Windows Firewall (outbound TCP, no rules needed)

    Returns list of dicts: {"ip": str, "raw": str}
    """
    found: Dict[str, Dict[str, Any]] = {}

    # ----------------------------------------------------------------
    # Build probe target list (shared between UDP and HTTP)
    # ----------------------------------------------------------------
    probe_ips: List[str] = []

    # Link-local: direct UTP cable without router
    probe_ips.append("169.254.5.1")

    # mDNS: hub advertises as blastgate.local (works on LAN + direct ETH cable)
    for mdns_name in ("blastgate.local", "blastgate-hub.local"):
        mdns_ip = _resolve_mdns(mdns_name)
        if mdns_ip and is_valid_ipv4(mdns_ip) and mdns_ip not in probe_ips:
            probe_ips.append(mdns_ip)
            logger.info("mDNS resolved %s → %s", mdns_name, mdns_ip)
            break  # one resolves to the same IP, no need to add twice

    if is_valid_ipv4(config.hub_lan_ip) and config.hub_lan_ip not in probe_ips:
        probe_ips.append(config.hub_lan_ip)

    if is_valid_ipv4(config.hub_ap_ip) and config.hub_ap_ip not in probe_ips:
        probe_ips.append(config.hub_ap_ip)

    if selected_ip and is_valid_ipv4(selected_ip) and selected_ip not in probe_ips:
        probe_ips.append(selected_ip)

    # ----------------------------------------------------------------
    # HTTP probes — run in background threads alongside UDP
    # ----------------------------------------------------------------
    http_timeout = max(1.5, float(config.discovery_timeout_s))
    http_results: List[Optional[Dict[str, Any]]] = [None] * len(probe_ips)

    def _probe_worker(idx: int, ip: str) -> None:
        http_results[idx] = _http_probe(ip, http_timeout)

    threads = [
        threading.Thread(target=_probe_worker, args=(i, ip), daemon=True)
        for i, ip in enumerate(probe_ips)
    ]
    for t in threads:
        t.start()

    # ----------------------------------------------------------------
    # UDP broadcast — runs in main thread while HTTP probes run in background
    # ----------------------------------------------------------------
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.settimeout(0.15)
        s.bind(("", 0))

        logger.info("Discovery socket ready (timeout=0.15s)")

        # UDP targets: broadcast + all probe IPs
        udp_targets = [("255.255.255.255", config.udp_port)]
        for ip in probe_ips:
            udp_targets.append((ip, config.udp_port))

        msg = protocol.build_discover_command()
        deadline = time.time() + float(config.discovery_timeout_s)

        logger.info("Starting discovery (UDP timeout=%ss, %d targets, %d HTTP probes)",
                    config.discovery_timeout_s, len(udp_targets), len(probe_ips))

        while time.time() < deadline:
            for host, port in udp_targets:
                try:
                    s.sendto(msg, (host, port))
                    logger.debug("Sent DISCOVER to %s:%d", host, port)
                except (OSError, socket.error) as e:
                    logger.debug("Failed to send DISCOVER to %s:%d: %s", host, port, e)

            try:
                data, addr = s.recvfrom(4096)
            except socket.timeout:
                continue
            except (OSError, socket.error) as e:
                logger.warning("Error receiving discovery response: %s", e)
                break

            rip = addr[0]
            txt = data.decode("utf-8", errors="ignore").strip()

            if protocol.is_hub_discover_response(txt):
                if rip not in found:
                    found[rip] = {"ip": rip, "raw": txt}
                    logger.info("UDP discovered hub at %s: %s", rip, txt[:50])

    except (OSError, socket.error) as e:
        logger.error("Discovery socket setup failed: %s", e)
    finally:
        try:
            s.close()
        except (OSError, socket.error) as e:
            logger.debug("Discovery socket close error (ignored): %s", e)

    # ----------------------------------------------------------------
    # Wait for HTTP probes and merge results
    # ----------------------------------------------------------------
    for t in threads:
        t.join(timeout=http_timeout + 0.5)

    for r in http_results:
        if r and r["ip"] not in found:
            found[r["ip"]] = r
            logger.info("HTTP probe added hub at %s", r["ip"])

    logger.info("Discovery complete: found %d hub(s)", len(found))
    return list(found.values())


def discover_single(ip: str, port: int, timeout: float = 1.0) -> Optional[Dict[str, Any]]:
    """
    Try to discover hub at specific IP address.
    Tries HTTP first (works through Windows Firewall), then UDP.
    """
    if not is_valid_ipv4(ip):
        logger.warning("Invalid IPv4 address: %s", ip)
        return None

    # HTTP probe first — bypasses Windows Firewall
    result = _http_probe(ip, timeout=timeout)
    if result:
        return result

    # UDP fallback
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.settimeout(timeout)
        msg = protocol.build_discover_command()
        logger.debug("Probing %s:%d for hub (UDP)", ip, port)
        s.sendto(msg, (ip, port))

        try:
            data, addr = s.recvfrom(4096)
            txt = data.decode("utf-8", errors="ignore").strip()
            if protocol.is_hub_discover_response(txt):
                logger.info("UDP found hub at %s: %s", ip, txt[:50])
                return {"ip": ip, "raw": txt}
        except socket.timeout:
            logger.debug("No UDP response from %s", ip)

    except (OSError, socket.error) as e:
        logger.warning("Error probing %s: %s", ip, e)
    finally:
        try:
            s.close()
        except (OSError, socket.error) as e:
            logger.debug("Socket close error (ignored): %s", e)

    return None
