"""
Pure display logic (no Qt): what a node/hub status dict means for the UI.

Works with old firmware (no gateState/rssi/err) and v1.5.0 status fields.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# err bits reported by v1.5.0 nodes (see firmware/lib/blastgate_proto/blastgate_proto.h)
ERR_TEXTS = {
    1: "Zatvarač nije stigao do krajnjeg prekidača (otvaranje)",
    2: "Zatvarač nije stigao do krajnjeg prekidača (zatvaranje)",
    4: "Oba krajnja prekidača aktivna — proveri ožičenje",
    8: "Senzor se još kalibriše",
    16: "Poslednji OTA noda nije uspeo",
}
ERR_WARNING_MASK = 1 | 2 | 4 | 16  # bit 8 (calibrating) is normal right after boot

GATE_TEXTS = {0: "Zatvoren", 1: "Otvoren", 2: "Otvara se", 3: "Zatvara se", 4: "Nepoznato"}


def to_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def to_float(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def node_name(node: Dict[str, Any]) -> str:
    return (node.get("name") or "").strip() or node.get("id", "?")


def node_status(node: Dict[str, Any]) -> Tuple[str, str]:
    """(label, tone) for the status dot of a node."""
    if to_int(node.get("online")) != 1:
        return "OFFLINE", "danger"
    if to_int(node.get("err")) & ERR_WARNING_MASK:
        return "UPOZORENJE", "warning"
    if to_int(node.get("active")) == 1:
        return "RADI", "success"
    return "MIRUJE", "idle"


def gate_open(node: Dict[str, Any]) -> bool:
    if "gateState" in node:
        return to_int(node.get("gateState")) in (1, 2)
    if "gateOpen" in node and node.get("gateOpen") is not None:
        return to_int(node.get("gateOpen")) == 1
    return to_int(node.get("override")) == 1


def gate_text(node: Dict[str, Any]) -> str:
    if to_int(node.get("online")) != 1:
        return "—"
    close_in = to_int(node.get("closeInMs"))
    if close_in > 0 and gate_open(node):
        return f"Zatvara za {max(1, round(close_in / 1000))} s"
    if "gateState" in node:
        return GATE_TEXTS.get(to_int(node.get("gateState")), "Nepoznato")
    return "Otvoren" if gate_open(node) else "Zatvoren"


def signal_bars(rssi: Optional[int]) -> int:
    """0..4 bars from RSSI in dBm (None/0 = no data)."""
    if rssi is None or rssi == 0:
        return 0
    for bars, limit in ((4, -60), (3, -70), (2, -80), (1, -90)):
        if rssi > limit:
            return bars
    return 0


def signal_text(node: Dict[str, Any]) -> str:
    rssi = node.get("rssi")
    if rssi is None or to_int(rssi) == 0 or to_int(node.get("online")) != 1:
        return "—"
    return f"{to_int(rssi)} dBm"


def err_texts(err: int) -> List[str]:
    return [txt for bit, txt in ERR_TEXTS.items() if err & bit]


def hold_ms_to_s(ms: Any) -> float:
    return round(to_int(ms) / 1000.0, 1)


def hold_s_to_ms(s: float) -> int:
    return int(round(float(s) * 1000))


def bar_max(value: Optional[float], threshold: Optional[float]) -> float:
    """Scale for the value bar: threshold sits in the middle, the bar grows with the value."""
    thr = threshold if threshold and threshold > 0 else 40.0
    return max(thr * 2.0, (value or 0.0) * 1.1, 10.0)


def relay_mode_text(st: Dict[str, Any]) -> str:
    mode = to_int(st.get("relayMode"), 2)
    return {0: "ručno isključen", 1: "ručno uključen"}.get(mode, "AUTO")


def hub_link_text(st: Dict[str, Any], state: str) -> str:
    if not st:
        return "traži hub…" if state == "SEARCHING" else "nedostupan"
    if to_int(st.get("ethLink")) == 1:
        return "Ethernet"
    if to_int(st.get("sta")) == 1:
        return "WiFi"
    return "AP (BLASTGATE_HUB)"


def age_text(age_ms: Any) -> str:
    ms = to_int(age_ms, -1)
    if ms < 0 or ms > 86_400_000:
        return "—"
    s = ms // 1000
    if s < 3:
        return "upravo"
    if s < 60:
        return f"pre {s} s"
    if s < 3600:
        return f"pre {s // 60} min"
    return f"pre {s // 3600} h"


# ---------------------------------------------------------------- events ----

def diff_events(prev: Dict[str, Any], cur: Dict[str, Any], now: Optional[datetime] = None) -> List[Tuple[datetime, str, str]]:
    """Human-readable events between two status snapshots: (time, tone, text)."""
    t = now or datetime.now()
    out: List[Tuple[datetime, str, str]] = []

    if bool(prev) != bool(cur):
        out.append((t, "success" if cur else "danger", "Hub povezan" if cur else "Veza sa hubom izgubljena"))
    if not prev or not cur:
        return out

    if to_int(prev.get("manualOverdrive")) != to_int(cur.get("manualOverdrive")):
        on = to_int(cur.get("manualOverdrive")) == 1
        out.append((t, "warning" if on else "info", "Ručni režim na hubu UKLJUČEN" if on else "Ručni režim na hubu isključen"))
    if to_int(prev.get("relayState")) != to_int(cur.get("relayState")):
        on = to_int(cur.get("relayState")) == 1
        out.append((t, "success" if on else "idle", "Usisivač uključen" if on else "Usisivač isključen"))

    pn = {n.get("id"): n for n in prev.get("nodes", []) or []}
    for n in cur.get("nodes", []) or []:
        p = pn.get(n.get("id"))
        name = node_name(n)
        if p is None:
            out.append((t, "info", f"{name}: nova mašina se javila"))
            continue
        if to_int(p.get("online")) != to_int(n.get("online")):
            on = to_int(n.get("online")) == 1
            out.append((t, "success" if on else "danger", f"{name}: {'ponovo na vezi' if on else 'van mreže'}"))
            continue
        if to_int(p.get("active")) != to_int(n.get("active")):
            on = to_int(n.get("active")) == 1
            out.append((t, "success" if on else "idle", f"{name}: mašina {'krenula' if on else 'stala'}"))
        if gate_open(p) != gate_open(n):
            out.append((t, "success" if gate_open(n) else "idle", f"{name}: zatvarač {'otvoren' if gate_open(n) else 'zatvoren'}"))
        new_err = to_int(n.get("err")) & ERR_WARNING_MASK & ~to_int(p.get("err"))
        for txt in err_texts(new_err):
            out.append((t, "warning", f"{name}: {txt}"))
    return out
