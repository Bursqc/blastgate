"""
Blastgate HUB diagnostics - pokreni iz command line:
    python diag_hub.py
"""
import socket
import time
import subprocess
import sys

UDP_PORT = 8888
DISCOVER_MSG = b"DISCOVER"
TIMEOUT = 1.5

# IPs to try (edit if needed)
KNOWN_IPS = [
    "192.168.1.112",   # preferred_hub_ip iz config
    "192.168.1.116",   # hub_lan_ip iz config
    "192.168.4.1",     # AP mode
]


def hr(char="-", n=60):
    print(char * n)


def ping_ip(ip):
    """System ping"""
    try:
        result = subprocess.run(
            ["ping", "-n", "1", "-w", "1000", ip],
            capture_output=True, text=True, timeout=3
        )
        ok = result.returncode == 0
        return ok
    except Exception:
        return False


def udp_ping(ip, timeout=TIMEOUT):
    """Send PING UDP command, expect PONG"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        s.sendto(b"PING", (ip, UDP_PORT))
        data, addr = s.recvfrom(256)
        return True, data.decode("utf-8", errors="ignore").strip()
    except socket.timeout:
        return False, "timeout"
    except OSError as e:
        return False, str(e)
    finally:
        s.close()


def udp_discover_broadcast(timeout=2.0):
    """Send DISCOVER broadcast, collect all responses"""
    found = []
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.settimeout(0.3)
    s.bind(("", 0))
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            try:
                s.sendto(DISCOVER_MSG, ("255.255.255.255", UDP_PORT))
            except OSError:
                pass
            try:
                data, addr = s.recvfrom(1024)
                txt = data.decode("utf-8", errors="ignore").strip()
                if "BLASTGATE_HUB" in txt and addr[0] not in [h["ip"] for h in found]:
                    found.append({"ip": addr[0], "resp": txt[:80]})
                    print(f"  ✓ FOUND: {addr[0]}  →  {txt[:60]}")
            except socket.timeout:
                pass
    finally:
        s.close()
    return found


def check_port_open(ip):
    """Check if UDP port is reachable (firewall test via TCP won't work,
    but we can check if anything arrives)"""
    ok, resp = udp_ping(ip)
    return ok, resp


def check_broadcast_listener():
    """Check if we can bind to port 8888 to receive HUB_READY broadcasts"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.setblocking(False)
        s.bind(("", UDP_PORT))
        s.close()
        return True, "OK"
    except OSError as e:
        return False, str(e)


# ============================================================
print()
hr("=")
print("  BLASTGATE HUB DIAGNOSTICS")
hr("=")
print()

# 1) Broadcast discovery
hr()
print("1) UDP BROADCAST DISCOVERY (255.255.255.255:8888, 2s)...")
hr()
found = udp_discover_broadcast(timeout=2.0)
if not found:
    print("  ✗ Nema odgovora na broadcast")
    print("    → Hub nije na mreži, ili Windows Firewall blokira UDP 8888")
else:
    print(f"  Pronađeno {len(found)} hub(ova)")

# 2) Direct UDP ping to known IPs
print()
hr()
print("2) DIREKTNI UDP PING na poznate IP adrese...")
hr()
for ip in KNOWN_IPS:
    ok, resp = udp_ping(ip)
    status = f"✓ ODGOVORIO  ({resp[:40]})" if ok else f"✗ nema odgovora ({resp})"
    print(f"  {ip:20s}  {status}")

# 3) ICMP ping
print()
hr()
print("3) ICMP PING (system ping)...")
hr()
for ip in KNOWN_IPS:
    ok = ping_ip(ip)
    print(f"  {ip:20s}  {'✓ ping OK' if ok else '✗ ping FAIL'}")

# 4) Broadcast listener check
print()
hr()
print("4) BROADCAST LISTENER (može li program bindovati port 8888?)...")
hr()
ok, msg = check_broadcast_listener()
if ok:
    print(f"  ✓ Port 8888 slobodan za bind")
else:
    print(f"  ✗ Ne može bindovati port 8888: {msg}")
    print(f"    → Neka druga aplikacija koristi port 8888, ili je Firewall problem")

# 5) Listen for HUB_READY broadcasts (5s)
print()
hr()
print("5) SLUŠAM HUB_READY broadcasts 5 sekundi (hub ih šalje svake sekunde)...")
hr()
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.settimeout(0.5)
    s.bind(("", UDP_PORT))
    deadline = time.time() + 5.0
    heard = []
    while time.time() < deadline:
        try:
            data, addr = s.recvfrom(256)
            txt = data.decode("utf-8", errors="ignore").strip()
            if addr[0] not in [h[0] for h in heard]:
                heard.append((addr[0], txt))
                print(f"  ✓ Primio od {addr[0]}: '{txt[:60]}'")
        except socket.timeout:
            remaining = int(deadline - time.time())
            print(f"  ... čekam ({remaining}s)...", end="\r")
    s.close()
    if not heard:
        print()
        print("  ✗ Nema HUB_READY broadcastova")
        print("    → Hub nije na mreži, ili broadcast ne prolazi kroz switch/router")
    else:
        print(f"\n  Primio broadcastove od {len(heard)} uređaja")
except OSError as e:
    print(f"  ✗ Greška pri bind-u: {e}")

# Summary
print()
hr("=")
print("  ZAKLJUČAK:")
hr("=")
if found or any(udp_ping(ip)[0] for ip in KNOWN_IPS):
    print("  Hub je dostupan na mreži!")
    best = found[0]["ip"] if found else next(ip for ip in KNOWN_IPS if udp_ping(ip)[0])
    print(f"  Koristiti IP: {best}")
    print(f"  → Podesi 'preferred_hub_ip' na {best} u GUI settingsima")
else:
    print("  Hub NIJE pronađen. Provjeri:")
    print("   1. Da li je ETH kabl dobro uključen na oba kraja?")
    print("   2. Da li switch/router pokazuje link na portu?")
    print("   3. Da li je hub dobio IP od DHCP-a? (provjeri router DHCP tabelu)")
    print("   4. Probaj direktan kabl PC ↔ HUB (bez switcha)")
    print("   5. Windows Firewall → Dozvoli Python ili dodaj izuzetak za port 8888 UDP")
print()
input("Pritisni Enter za izlaz...")
