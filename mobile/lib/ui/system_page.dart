import 'dart:convert';

import 'package:flutter/material.dart' hide Badge, Banner;
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../models/hub_status.dart';
import '../services/hub_http.dart';
import '../services/hub_service.dart';
import '../services/update_service.dart';
import 'add_hub_page.dart';
import 'icons.dart';
import 'overview_page.dart' show openNode, openPairing;
import 'state.dart';
import 'theme.dart';
import 'update_page.dart';
import 'widgets.dart';

/// Sistem — hub state and machine list, WiFi of the hub, updates. Port of system_page.py.
class SystemPage extends StatelessWidget {
  const SystemPage({super.key});

  @override
  Widget build(BuildContext context) {
    final hub = context.watch<HubService>();
    final st = hub.status;
    final nodes = nodesOf(st);
    final (String, String) overall = st.isEmpty
        ? ('Hub nije dostupan', 'danger')
        : hub.lockout
            ? ('Ručni režim na hubu', 'warning')
            : nodes.any((n) => ['warning', 'danger'].contains(nodeStatus(n).$2))
                ? ('Potrebna pažnja', 'warning')
                : ('Sve radi normalno', 'success');

    return DefaultTabController(
      length: 3,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        PageHeader('Sistem', 'Stanje huba i mašina, WiFi huba i ažuriranja.',
            trailing: StatusLabel(overall.$1, overall.$2, size: 13)),
        const TabBar(tabs: [Tab(text: 'Stanje'), Tab(text: 'WiFi huba'), Tab(text: 'Ažuriranja')]),
        const Expanded(child: TabBarView(children: [_StateTab(), _WifiTab(), _UpdatesTab()])),
      ]),
    );
  }
}

// ==================================================================== Stanje

class _StateTab extends StatefulWidget {
  const _StateTab();

  @override
  State<_StateTab> createState() => _StateTabState();
}

class _StateTabState extends State<_StateTab> {
  String _say = '';

  void _set(String s) {
    if (mounted) setState(() => _say = s);
  }

  Future<void> _refresh(HubService hub) async {
    _set('Osvežavam…');
    await hub.fullRefresh();
    _set(hub.status.isNotEmpty ? 'Stanje je osveženo.' : 'Hub ne odgovara.');
  }

  Future<void> _reconnect(HubService hub) async {
    _set('Tražim hub na mreži…');
    final hubs = await hub.discoverHubs();
    if (hubs.length == 1) {
      await hub.selectHub(hubs.first);
      _set('Hub pronađen na adresi ${hubs.first}.');
    } else {
      _set(hubs.isEmpty
          ? 'Hub nije pronađen. Proveri da li je uključen i da li je telefon na istoj WiFi mreži.'
          : 'Pronađeno je više hubova (${hubs.join(', ')}). Adresu izaberi u Podešavanjima.');
    }
  }

  Future<void> _ping(HubService hub) async {
    _set('Proveravam vezu…');
    final sw = Stopwatch()..start();
    final ok = await hub.testConnection(hub.config.effectiveHubIp);
    _set(ok ? 'Hub odgovara (${sw.elapsedMilliseconds} ms).' : 'Hub ne odgovara.');
  }

  Future<void> _diag(HubService hub) async {
    final cfg = hub.config.toJson()..['otaToken'] = '***';
    final b = StringBuffer()
      ..writeln('Blastgate dijagnostika ${DateTime.now().toIso8601String().substring(0, 19)}')
      ..writeln('Aplikacija: ${context.read<Updater>().appVersion}')
      ..writeln('Hub IP: ${hub.config.effectiveHubIp}  stanje: ${hub.connectionStatus.name}')
      ..writeln('\n== STATUS ==')
      ..writeln(const JsonEncoder.withIndent('  ').convert(hub.status))
      ..writeln('\n== CONFIG ==')
      ..writeln(const JsonEncoder.withIndent('  ').convert(cfg))
      ..writeln('\n== DOGAĐAJI ==');
    for (final e in hub.events) {
      b.writeln('${hhmmss(e.time)} ${e.text}');
    }
    await Clipboard.setData(ClipboardData(text: b.toString()));
    _set('Podaci su kopirani. Nalepi ih u poruku kad tražiš pomoć.');
  }

  @override
  Widget build(BuildContext context) {
    final hub = context.watch<HubService>();
    final st = hub.status;
    final nodes = nodesOf(st)..sort((a, b) => nodeName(a).toLowerCase().compareTo(nodeName(b).toLowerCase()));
    final up = toInt(st['uptime'], -1);

    return ListView(padding: const EdgeInsets.all(16), children: [
      BgCard(
        child: Row(children: [
          Ic('server', P.muted, size: 40),
          const SizedBox(width: 14),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Row(children: [
                Text('Hub', style: tsSection()),
                const SizedBox(width: 10),
                Flexible(
                    child: StatusLabel(
                        st.isNotEmpty ? 'POVEZAN' : 'NEDOSTUPAN', st.isNotEmpty ? 'success' : 'danger')),
              ]),
              Divider(color: P.border, height: 14),
              KV('Veza', hubLinkText(st, hub.searching)),
              KV('Adresa', st.isEmpty ? '—' : hub.config.effectiveHubIp),
              KV('Verzija', st['version'] as String? ?? '—'),
              if (st.containsKey('pairedCount')) KV('Uparenih mašina', '${st['pairedCount']}'),
              KV('Radi bez prekida', up >= 0 ? '${up ~/ 3600} h ${up % 3600 ~/ 60} min' : '—'),
            ]),
          ),
        ]),
      ),
      const SizedBox(height: 12),
      Section('Mašine', [
        if (nodes.isEmpty) Text(st.isEmpty ? '—' : 'Hub još nema nijednu mašinu.', style: tsMuted()),
        for (final n in nodes) _nodeRow(context, n),
      ],
          trailing: st.isEmpty ? null : Btn('Dodaj', icon: 'link', variant: 'outline', onTap: () => openPairing(context)),
          inset: false),
      const SizedBox(height: 12),
      Section('Provera i pomoć', [
        Wrap(spacing: 8, runSpacing: 8, children: [
          Btn('Osveži stanje', icon: 'refresh', variant: 'outline', onTap: () => _refresh(hub)),
          Btn('Proveri vezu', icon: 'link', variant: 'outline', onTap: () => _ping(hub)),
          Btn('Pronađi hub ponovo', icon: 'search', variant: 'outline', onTap: () => _reconnect(hub)),
          Btn('Kopiraj podatke za podršku', icon: 'download', variant: 'outline', onTap: () => _diag(hub)),
        ]),
        if (_say.isNotEmpty) ...[const SizedBox(height: 10), Text(_say, style: tsMuted(13))],
      ], inset: false),
    ]);
  }

  Widget _nodeRow(BuildContext context, Json n) {
    final (s, t) = nodeStatus(n);
    final manual = toInt(n['mode']) == 1;
    final open = gateOpen(n);
    return InkWell(
      onTap: () => openNode(context, n['id'] as String),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text(nodeName(n), style: tsMid())),
            StatusLabel(s, t),
          ]),
          const SizedBox(height: 4),
          Wrap(spacing: 14, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
            Text('${n['id']}', style: tsSmall()),
            Text(manual ? 'MANUAL' : 'AUTO', style: TextStyle(fontSize: 12, color: tone(manual ? 'warning' : 'info'))),
            Text(gateText(n),
                style: TextStyle(fontSize: 12, color: tone(isOnline(n) ? (open ? 'success' : 'danger') : 'idle'))),
            Text(signalText(n), style: tsSmall()),
            Text(ageText(n['ageMs']), style: tsSmall()),
          ]),
        ]),
      ),
    );
  }
}

// ================================================================= WiFi huba

class _WifiTab extends StatefulWidget {
  const _WifiTab();

  @override
  State<_WifiTab> createState() => _WifiTabState();
}

class _WifiTabState extends State<_WifiTab> {
  WifiInfo? _wifi;
  bool _loaded = false;
  bool _wasConnected = false;
  Msg _msg;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _refresh());
  }

  HubService get hub => context.read<HubService>();
  String get ip => hub.config.effectiveHubIp;

  Future<void> _refresh() async {
    final w = await hub.getWifiInfo();
    if (!mounted) return;
    setState(() {
      _wifi = w;
      _loaded = true;
    });
  }

  Future<void> _change() async {
    await Navigator.push(context, MaterialPageRoute(builder: (_) => AddHubPage(hubIp: ip)));
    if (mounted) _refresh();
  }

  Future<void> _forget() async {
    if (!await confirm(
        context,
        'Zaboravi WiFi',
        'Hub briše sačuvanu WiFi mrežu i restartuje se.\n\n'
            'Posle toga ga ponovo dodaješ preko „Dodaj hub" (Bluetooth).',
        ok: 'Zaboravi')) {
      return;
    }
    try {
      await HubHttp.wifiForget(ip);
      hub.addEvent('info', 'Hub je zaboravio WiFi mrežu');
      if (mounted) {
        setState(() => _msg = ('Hub je zaboravio WiFi i restartuje se. Dodaj ga ponovo preko „Dodaj hub".', 'info',
            'info-circle'));
      }
    } catch (e) {
      if (mounted) setState(() => _msg = ('Nije uspelo: $e', 'danger', 'alert-circle'));
    }
  }

  @override
  Widget build(BuildContext context) {
    final connected = context.watch<HubService>().status.isNotEmpty;
    // Re-read the WiFi state whenever the hub comes back (e.g. after a restart)
    if (connected != _wasConnected) {
      _wasConnected = connected;
      WidgetsBinding.instance.addPostFrameCallback((_) => _refresh());
    }
    final w = _wifi;
    final onWifi = connected && w != null && w.connected;

    return ListView(padding: const EdgeInsets.all(16), children: [
      Section('WiFi mreža huba', [
        if (!connected) ...[
          const StatusLabel('HUB NIJE DOSTUPAN', 'danger', size: 13),
          const SizedBox(height: 6),
          Text('WiFi huba može da se promeni tek kad aplikacija vidi hub.', style: tsMuted(13)),
        ] else if (!_loaded || w == null) ...[
          Text(_loaded ? 'Hub nije poslao podatke o WiFi-ju.' : 'Učitavam…', style: tsMuted(13)),
        ] else ...[
          StatusLabel(onWifi ? 'POVEZAN' : 'NIJE POVEZAN NA WIFI', onWifi ? 'success' : 'warning', size: 13),
          const SizedBox(height: 6),
          if (onWifi) ...[
            KV('Mreža', w.ssid.isEmpty ? '—' : w.ssid),
            KV('Signal', w.rssi == 0 ? '—' : '${signalWords(w.rssi)} (${w.rssi} dBm)'),
            KV('Adresa', w.ip.isEmpty ? '—' : w.ip),
          ] else
            Text('Hub trenutno radi bez WiFi mreže (preko kabla ili direktno).', style: tsMuted(13)),
        ],
        const SizedBox(height: 12),
        Btn(onWifi ? 'Promeni WiFi mrežu' : 'Poveži hub na WiFi',
            icon: 'wifi', variant: 'primary', expand: true, onTap: connected ? _change : null),
        msgBanner(_msg),
      ], trailing: IconButton(onPressed: _refresh, tooltip: 'Osveži', icon: Ic('refresh', P.muted)), inset: false),
      const SizedBox(height: 12),
      Section('Hub je nov ili se ne vidi?', [
        Text('Nov ili resetovan hub dodaješ preko Bluetooth-a: aplikacija ga nađe, ti izabereš mrežu i ukucaš šifru.',
            style: tsMuted(13)),
        const SizedBox(height: 10),
        Btn('Dodaj hub', icon: 'access-point', variant: 'outline', expand: true,
            onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const AddHubPage()))),
      ], inset: false),
      const SizedBox(height: 12),
      Section('Zaboravi WiFi', [
        Text('Koristi kad hub seliš na drugo mesto ili ga daješ nekom drugom. Hub briše sačuvanu mrežu.',
            style: tsMuted(13)),
        const SizedBox(height: 10),
        Btn('Zaboravi WiFi', icon: 'trash', variant: 'danger', onTap: connected ? _forget : null),
      ], inset: false),
    ]);
  }
}

// ================================================================ Ažuriranja

class _UpdatesTab extends StatelessWidget {
  const _UpdatesTab();

  @override
  Widget build(BuildContext context) {
    final up = context.watch<Updater>();
    final connected = context.watch<HubService>().status.isNotEmpty;

    Widget card(String title, String installed, String? latest, bool update, UpdateKind kind,
        {String unknown = ''}) {
      final (String, String) state = update
          ? ('IMA NOVA VERZIJA', 'info')
          : latest == null || installed.isEmpty
              ? ('NIJE PROVERENO', 'idle')
              : ('AŽURNO', 'success');
      return Section(title, [
        KV('Instalirana verzija', installed.isEmpty ? '—' : installed),
        KV('Najnovija verzija', latest ?? '—'),
        if (unknown.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 4), child: Text(unknown, style: tsSmall())),
        if (update) ...[
          const SizedBox(height: 12),
          if (kind == UpdateKind.app && up.downloading)
            Text('Preuzimam novu verziju…', style: tsMuted(13))
          else
            Btn(kind == UpdateKind.app && up.apk != null ? 'Instaliraj $latest' : 'Ažuriraj na $latest',
                icon: 'download', variant: 'primary', expand: true,
                onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => UpdatePage(kind)))),
        ],
      ], trailing: StatusLabel(state.$1, state.$2), inset: false);
    }

    return ListView(padding: const EdgeInsets.all(16), children: [
      card('Aplikacija', up.appVersion, up.app?.version, up.appUpdate, UpdateKind.app),
      const SizedBox(height: 12),
      card('Hub', connected ? up.hubVersion : '', up.firmware?.version, connected && up.hubUpdate,
          UpdateKind.hub,
          unknown: connected ? '' : 'Hub nije dostupan, pa se njegova verzija ne vidi.'),
      const SizedBox(height: 12),
      Section('Provera', [
        Text(
            up.checking
                ? 'Proveravam…'
                : up.checkFailed
                    ? 'Provera nije uspela. Telefon nema pristup internetu.'
                    : up.checkedAt != null
                        ? 'Poslednja provera: ${hhmmss(up.checkedAt!)}. Aplikacija proverava sama pri pokretanju.'
                        : 'Još nije provereno.',
            style: tsMuted(13)),
        const SizedBox(height: 10),
        Btn('Proveri sada', icon: 'refresh', variant: 'outline', expand: true, onTap: up.checking ? null : up.check),
      ], inset: false),
    ]);
  }
}
