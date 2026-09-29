/// Pure display logic: what a node/hub status map means for the UI.
/// Port of desktop_qt/blastgate/ui/state.py — keep both in sync.
///
/// Works with old firmware (no gateState/rssi/err) and v1.5.0 status fields.
library;

/// err bits reported by v1.5.0 nodes (see firmware/lib/blastgate_proto/blastgate_proto.h)
const Map<int, String> errTextsMap = {
  1: 'Zatvarač nije stigao do krajnjeg prekidača (otvaranje)',
  2: 'Zatvarač nije stigao do krajnjeg prekidača (zatvaranje)',
  4: 'Oba krajnja prekidača aktivna — proveri ožičenje',
  8: 'Senzor se još kalibriše',
  16: 'Poslednji OTA noda nije uspeo',
};
const int errWarningMask = 1 | 2 | 4 | 16; // bit 8 (calibrating) is normal right after boot

const Map<int, String> gateTexts = {
  0: 'Zatvoren',
  1: 'Otvoren',
  2: 'Otvara se',
  3: 'Zatvara se',
  4: 'Nepoznato',
};

typedef Json = Map<String, dynamic>;

int toInt(dynamic v, [int def = 0]) {
  if (v is int) return v;
  if (v is num) return v.toInt();
  if (v is bool) return v ? 1 : 0;
  if (v is String) return int.tryParse(v) ?? double.tryParse(v)?.toInt() ?? def;
  return def;
}

double? toDouble(dynamic v) {
  if (v is num) return v.toDouble();
  if (v is String) return double.tryParse(v);
  return null;
}

bool isOnline(Json n) => toInt(n['online']) == 1;

String nodeName(Json n) {
  final name = (n['name'] as String? ?? '').trim();
  return name.isNotEmpty ? name : (n['id'] as String? ?? '?');
}

/// (label, tone) for the status dot of a node.
(String, String) nodeStatus(Json n) {
  if (!isOnline(n)) return ('OFFLINE', 'danger');
  if (toInt(n['err']) & errWarningMask != 0) return ('UPOZORENJE', 'warning');
  if (toInt(n['active']) == 1) return ('RADI', 'success');
  return ('MIRUJE', 'idle');
}

bool gateOpen(Json n) {
  if (n.containsKey('gateState')) return [1, 2].contains(toInt(n['gateState']));
  if (n['gateOpen'] != null) return toInt(n['gateOpen']) == 1;
  return toInt(n['override']) == 1;
}

String gateText(Json n) {
  if (!isOnline(n)) return '—';
  final closeIn = toInt(n['closeInMs']);
  if (closeIn > 0 && gateOpen(n)) {
    final s = (closeIn / 1000).round();
    return 'Zatvara za ${s < 1 ? 1 : s} s';
  }
  if (n.containsKey('gateState')) return gateTexts[toInt(n['gateState'])] ?? 'Nepoznato';
  return gateOpen(n) ? 'Otvoren' : 'Zatvoren';
}

/// 0..4 bars from RSSI in dBm (null/0 = no data).
int signalBars(int? rssi) {
  if (rssi == null || rssi == 0) return 0;
  for (final (bars, limit) in [(4, -60), (3, -70), (2, -80), (1, -90)]) {
    if (rssi > limit) return bars;
  }
  return 0;
}

String signalText(Json n) {
  final rssi = n['rssi'];
  if (rssi == null || toInt(rssi) == 0 || !isOnline(n)) return '—';
  return '${toInt(rssi)} dBm';
}

String signalIcon(Json n) {
  if (n['rssi'] == null) return 'antenna-bars-off';
  final bars = signalBars(isOnline(n) ? toInt(n['rssi']) : null);
  return 'antenna-bars-${bars + 1}';
}

List<String> errTexts(int err) =>
    [for (final e in errTextsMap.entries) if (err & e.key != 0) e.value];

double holdMsToS(dynamic ms) => (toInt(ms) / 100).round() / 10.0;

int holdSToMs(double s) => (s * 1000).round();

/// Scale for the value bar: threshold sits in the middle, the bar grows with the value.
double barMax(double? value, double? threshold) {
  final thr = (threshold != null && threshold > 0) ? threshold : 40.0;
  final v = (value ?? 0) * 1.1;
  return [thr * 2.0, v, 10.0].reduce((a, b) => a > b ? a : b);
}

String relayModeText(Json st) {
  switch (toInt(st['relayMode'], 2)) {
    case 0:
      return 'ručno isključen';
    case 1:
      return 'ručno uključen';
    default:
      return 'AUTO';
  }
}

String hubLinkText(Json st, bool searching) {
  if (st.isEmpty) return searching ? 'traži hub…' : 'nedostupan';
  if (toInt(st['ethLink']) == 1) return 'Ethernet';
  if (toInt(st['sta']) == 1) return 'WiFi';
  return 'AP (BLASTGATE_HUB)';
}

String ageText(dynamic ageMs) {
  final ms = toInt(ageMs, -1);
  if (ms < 0 || ms > 86400000) return '—';
  final s = ms ~/ 1000;
  if (s < 3) return 'upravo';
  if (s < 60) return 'pre $s s';
  if (s < 3600) return 'pre ${s ~/ 60} min';
  return 'pre ${s ~/ 3600} h';
}

String hhmmss(DateTime t) =>
    '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}:${t.second.toString().padLeft(2, '0')}';

// ---------------------------------------------------------------- events ----

class HubEvent {
  final DateTime time;
  final String tone;
  final String text;
  const HubEvent(this.time, this.tone, this.text);
}

/// Human-readable events between two status snapshots.
List<HubEvent> diffEvents(Json prev, Json cur, [DateTime? now]) {
  final t = now ?? DateTime.now();
  final out = <HubEvent>[];

  if (prev.isNotEmpty != cur.isNotEmpty) {
    out.add(HubEvent(t, cur.isNotEmpty ? 'success' : 'danger',
        cur.isNotEmpty ? 'Hub povezan' : 'Veza sa hubom izgubljena'));
  }
  if (prev.isEmpty || cur.isEmpty) return out;

  if (toInt(prev['manualOverdrive']) != toInt(cur['manualOverdrive'])) {
    final on = toInt(cur['manualOverdrive']) == 1;
    out.add(HubEvent(t, on ? 'warning' : 'info',
        on ? 'Ručni režim na hubu UKLJUČEN' : 'Ručni režim na hubu isključen'));
  }
  if (toInt(prev['relayState']) != toInt(cur['relayState'])) {
    final on = toInt(cur['relayState']) == 1;
    out.add(HubEvent(t, on ? 'success' : 'idle', on ? 'Usisivač uključen' : 'Usisivač isključen'));
  }

  final pn = {for (final n in nodesOf(prev)) n['id']: n};
  for (final n in nodesOf(cur)) {
    final p = pn[n['id']];
    final name = nodeName(n);
    if (p == null) {
      out.add(HubEvent(t, 'info', '$name: nova mašina se javila'));
      continue;
    }
    if (isOnline(p) != isOnline(n)) {
      final on = isOnline(n);
      out.add(HubEvent(t, on ? 'success' : 'danger', '$name: ${on ? 'ponovo na vezi' : 'van mreže'}'));
      continue;
    }
    if (toInt(p['active']) != toInt(n['active'])) {
      final on = toInt(n['active']) == 1;
      out.add(HubEvent(t, on ? 'success' : 'idle', '$name: mašina ${on ? 'krenula' : 'stala'}'));
    }
    if (gateOpen(p) != gateOpen(n)) {
      out.add(HubEvent(t, gateOpen(n) ? 'success' : 'idle',
          '$name: zatvarač ${gateOpen(n) ? 'otvoren' : 'zatvoren'}'));
    }
    final newErr = toInt(n['err']) & errWarningMask & ~toInt(p['err']);
    for (final txt in errTexts(newErr)) {
      out.add(HubEvent(t, 'warning', '$name: $txt'));
    }
  }
  return out;
}

List<Json> nodesOf(Json st) =>
    [for (final n in (st['nodes'] as List? ?? const [])) if (n is Map) Map<String, dynamic>.from(n)];
