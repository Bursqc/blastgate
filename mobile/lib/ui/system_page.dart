import 'dart:convert';

import 'package:flutter/material.dart' hide Badge, Banner;
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../screens/ble_prov_screen.dart';
import '../screens/ota_screen.dart';
import '../screens/provisioning_screen.dart';
import '../services/hub_http.dart';
import '../services/hub_service.dart';
import 'icons.dart';
import 'overview_page.dart' show openNode;
import 'state.dart';
import 'theme.dart';
import 'widgets.dart';

/// Sistem — hub state, machine list, WiFi of the hub, hub firmware. Port of system_page.py.
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
        PageHeader('Sistem', 'Stanje huba, mašina, WiFi i firmware.',
            trailing: StatusLabel(overall.$1, overall.$2, size: 13)),
        const TabBar(tabs: [Tab(text: 'Stanje'), Tab(text: 'WiFi huba'), Tab(text: 'Firmware')]),
        const Expanded(child: TabBarView(children: [_StateTab(), _WifiTab(), _FwTab()])),
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
    _set(hub.status.isNotEmpty ? 'Hub osvežen.' : 'Osvežavanje nije uspelo.');
  }

  Future<void> _reconnect(HubService hub) async {
    _set('Tražim hub…');
    final hubs = await hub.discoverHubs();
    if (hubs.length == 1) {
      hub.config.preferredHubIp = hubs.first;
      hub.updateConfig(hub.config);
      _set('Hub: ${hubs.first}');
    } else {
      _set(hubs.isEmpty ? 'Hub nije pronađen.' : 'Pronađeno više hubova: ${hubs.join(', ')} — izaberi u Podešavanjima');
    }
  }

  Future<void> _ping(HubService hub) async {
    final ip = hub.config.effectiveHubIp;
    final sw = Stopwatch()..start();
    final ok = await hub.testConnection(ip);
    _set('PING $ip: ${ok ? 'PONG' : 'nema odgovora'} (${sw.elapsedMilliseconds} ms)');
  }

  Future<void> _diag(HubService hub) async {
    final cfg = hub.config.toJson()..['otaToken'] = '***';
    final b = StringBuffer()
      ..writeln('Blastgate dijagnostika ${DateTime.now().toIso8601String().substring(0, 19)}')
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
    _set('Dijagnostika kopirana u clipboard.');
  }

  @override
  Widget build(BuildContext context) {
    final hub = context.watch<HubService>();
    final st = hub.status;
    final nodes = nodesOf(st)..sort((a, b) => nodeName(a).toLowerCase().compareTo(nodeName(b).toLowerCase()));
    final up = toInt(st['uptime'], -1);
    final heap = toInt(st['freeHeap'], -1);
    final hasRadio = st.containsKey('espnow');
    final esp = toInt(st['espnow']) == 1;

    return ListView(padding: const EdgeInsets.all(16), children: [
      _infoCard('Hub', 'server', st.isNotEmpty ? 'POVEZAN' : 'NEDOSTUPAN', st.isNotEmpty ? 'success' : 'danger', [
        KV('Adresa', hub.config.effectiveHubIp.isEmpty ? '—' : hub.config.effectiveHubIp),
        KV('Veza', hubLinkText(st, hub.searching)),
        KV('Firmware', st['version'] as String? ?? '—'),
        KV('Radi', up >= 0 ? '${up ~/ 3600} h ${up % 3600 ~/ 60} min' : '—'),
      ]),
      const SizedBox(height: 12),
      _infoCard('Radio veza nodova', 'access-point', hasRadio ? (esp ? 'AKTIVNO' : 'ISKLJUČENO') : 'STARI FW',
          hasRadio ? (esp ? 'success' : 'warning') : 'idle', [
        KV('ESP-NOW', hasRadio ? (esp ? 'da' : 'ne') : '— (hub < 1.5.0)'),
        KV('Kanal', '${st['channel'] ?? '—'}'),
        KV('Upareno', '${st['pairedCount'] ?? '—'}'),
      ]),
      const SizedBox(height: 12),
      _infoCard('Sinhronizacija', 'refresh', st.isNotEmpty ? 'AKTIVNO' : 'ČEKA', st.isNotEmpty ? 'success' : 'warning', [
        KV('Osvežavanje', '${hub.config.pollMs} ms'),
        KV('Poslednji odgovor', hub.updatedAt != null ? hhmmss(hub.updatedAt!) : '—'),
        KV('Slobodna mem.', heap >= 0 ? '${(heap / 1024).round()} KB' : '—'),
      ]),
      const SizedBox(height: 12),
      Section('Mašine', [
        if (nodes.isEmpty) Text('—', style: tsMuted()),
        for (final n in nodes) _nodeRow(context, n),
      ], inset: false),
      const SizedBox(height: 12),
      Section('Sistemske akcije', [
        Text('Održavanje i dijagnostika.', style: tsMuted(13)),
        const SizedBox(height: 10),
        Wrap(spacing: 8, runSpacing: 8, children: [
          Btn('Osveži status', icon: 'refresh', variant: 'outline', onTap: () => _refresh(hub)),
          Btn('Ponovo poveži', icon: 'link', variant: 'outline', onTap: () => _reconnect(hub)),
          Btn('Pošalji test (PING)', icon: 'send', variant: 'outline', onTap: () => _ping(hub)),
          Btn('Kopiraj dijagnostiku', icon: 'download', variant: 'outline', onTap: () => _diag(hub)),
        ]),
        if (_say.isNotEmpty) ...[const SizedBox(height: 8), Text(_say, style: tsSmall())],
      ], inset: false),
    ]);
  }

  Widget _infoCard(String title, String icon, String status, String t, List<Widget> rows) => BgCard(
        child: Row(children: [
          Ic(icon, P.muted, size: 40),
          const SizedBox(width: 14),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Row(children: [
                Text(title, style: tsSection()),
                const SizedBox(width: 10),
                Flexible(child: StatusLabel(status, t)),
              ]),
              Divider(color: P.border, height: 14),
              ...rows,
            ]),
          ),
        ]),
      );

  Widget _nodeRow(BuildContext context, Json n) {
    final (s, t) = nodeStatus(n);
    final manual = toInt(n['mode']) == 1;
    final open = gateOpen(n);
    final link = const {'espnow': 'ESP-NOW', 'udp': 'WiFi (UDP)'}[n['transport']] ?? 'WiFi (UDP)';
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
            Text('${n['id']} · $link', style: tsSmall()),
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
  final _ssid = TextEditingController();
  final _pass = TextEditingController();
  bool _show = false;
  List<String> _nets = [];
  (String, String) _state = ('—', 'idle');
  String _detail = '';
  Msg _msg;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _refresh());
  }

  @override
  void dispose() {
    _ssid.dispose();
    _pass.dispose();
    super.dispose();
  }

  HubService get hub => context.read<HubService>();
  String get ip => hub.config.effectiveHubIp;

  void _say(String text, String t, String icon) {
    if (mounted) setState(() => _msg = (text, t, icon));
  }

  Future<void> _refresh() async {
    final w = await hub.getWifiInfo();
    if (!mounted) return;
    setState(() {
      if (w == null) {
        _state = ('Greška: hub ne odgovara', 'danger');
        _detail = '';
      } else {
        _state = w.connected ? ('POVEZAN', 'success') : ('NIJE POVEZAN', 'warning');
        _detail = 'Mreža: ${w.ssid.isEmpty ? '—' : w.ssid}   IP: ${w.ip.isEmpty ? '—' : w.ip}   '
            'Signal: ${w.rssi == 0 ? '—' : w.rssi} dBm';
      }
    });
  }

  Future<void> _scan() async {
    if (hub.status.isEmpty) {
      _say('Hub nije dostupan.', 'danger', 'alert-circle');
      return;
    }
    _say('Skeniram mreže (hub blokira ~2 s)…', 'info', 'search');
    try {
      final nets = await HubHttp.wifiScan(ip);
      if (!mounted) return;
      setState(() => _nets = nets.map((n) => n['ssid'] as String).toSet().toList());
      _say('Pronađeno mreža: ${_nets.length}', 'info', 'wifi');
    } catch (e) {
      _say('Skeniranje nije uspelo: $e', 'danger', 'alert-circle');
    }
  }

  Future<void> _set() async {
    final ssid = _ssid.text.trim();
    if (ssid.isEmpty || hub.status.isEmpty) {
      _say('Unesi mrežu (i proveri da je hub dostupan).', 'warning', 'alert-triangle');
      return;
    }
    if (!await confirm(context, 'WiFi huba', 'Poslati hubu mrežu „$ssid”?\nHub će se restartovati.')) return;
    try {
      await HubHttp.wifiSet(ip, ssid, _pass.text);
      hub.addEvent('info', 'WiFi huba → $ssid');
      _say('Poslato. Hub se restartuje i povezuje na WiFi.', 'success', 'circle-check');
    } catch (e) {
      _say('Greška: $e', 'danger', 'alert-circle');
    }
  }

  Future<void> _disconnect() async {
    if (!await confirm(context, 'WiFi huba', 'Prekinuti WiFi vezu huba (podaci ostaju sačuvani)?\nHub se restartuje.')) {
      return;
    }
    final r = await hub.command('WIFI_DISCONNECT');
    r != null && r.contains('OK')
        ? _say('Hub se restartuje.', 'info', 'info-circle')
        : _say('Greška: ${r ?? 'hub ne odgovara'}', 'danger', 'alert-circle');
  }

  Future<void> _forget() async {
    if (!await confirm(
        context,
        'Zaboravi WiFi',
        'Hub će zaboraviti WiFi mrežu i restartovati se.\n'
            'Posle toga je dostupan samo preko Etherneta ili BLASTGATE_HUB.\n\nNastaviti?',
        ok: 'Zaboravi')) {
      return;
    }
    try {
      await HubHttp.wifiForget(ip);
      _say('WiFi zaboravljen, hub se restartuje.', 'info', 'info-circle');
    } catch (e) {
      _say('Greška: $e', 'danger', 'alert-circle');
    }
  }

  @override
  Widget build(BuildContext context) => ListView(padding: const EdgeInsets.all(16), children: [
        Section('Trenutna WiFi veza huba', [
          StatusLabel(_state.$1, _state.$2, size: 13),
          const SizedBox(height: 4),
          Text(_detail, style: tsMuted(13)),
        ], trailing: IconButton(onPressed: _refresh, icon: Ic('refresh', P.muted)), inset: false),
        const SizedBox(height: 12),
        Section('Poveži hub na WiFi', [
          Text('Telefon mora biti na istoj mreži kao hub ili na WiFi-ju BLASTGATE_HUB (lozinka 12345678). '
              'Hub se posle slanja restartuje.', style: tsMuted(13)),
          const SizedBox(height: 12),
          Row(children: [
            Expanded(child: TextField(controller: _ssid, decoration: const InputDecoration(labelText: 'Mreža (SSID)'))),
            const SizedBox(width: 8),
            Btn('Skeniraj', icon: 'search', onTap: _scan),
          ]),
          if (_nets.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Wrap(spacing: 6, runSpacing: 6, children: [
                for (final s in _nets)
                  ActionChip(
                    label: Text(s),
                    backgroundColor: P.cardHi,
                    side: BorderSide(color: s == _ssid.text ? P.accent : P.border),
                    onPressed: () => setState(() => _ssid.text = s),
                  ),
              ]),
            ),
          const SizedBox(height: 10),
          TextField(
            controller: _pass,
            obscureText: !_show,
            decoration: InputDecoration(
              labelText: 'Lozinka',
              suffixIcon: IconButton(
                icon: Ic(_show ? 'eye-off' : 'eye', P.muted, size: 20),
                onPressed: () => setState(() => _show = !_show),
              ),
            ),
          ),
          const SizedBox(height: 12),
          Btn('Pošalji hubu', icon: 'send', variant: 'primary', expand: true, onTap: _set),
          msgBanner(_msg),
          const SizedBox(height: 12),
          Wrap(spacing: 8, runSpacing: 8, children: [
            Btn('Prekini WiFi vezu', icon: 'wifi-off', onTap: _disconnect),
            Btn('Zaboravi WiFi', icon: 'trash', variant: 'danger', onTap: _forget),
          ]),
        ], inset: false),
        const SizedBox(height: 12),
        Section('Hub još nije na WiFi-ju?', [
          Text('Podesi ga preko Bluetooth-a (hub u BLE režimu) ili preko njegove WiFi mreže BLASTGATE_HUB.',
              style: tsMuted(13)),
          const SizedBox(height: 10),
          Wrap(spacing: 8, runSpacing: 8, children: [
            Btn('Preko Bluetooth-a', icon: 'access-point', variant: 'outline',
                onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const BleProvScreen()))),
            Btn('Preko BLASTGATE_HUB', icon: 'world', variant: 'outline',
                onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const ProvisioningScreen()))),
          ]),
        ], inset: false),
      ]);
}

// ================================================================== Firmware

class _FwTab extends StatelessWidget {
  const _FwTab();

  @override
  Widget build(BuildContext context) {
    final st = context.watch<HubService>().status;
    return ListView(padding: const EdgeInsets.all(16), children: [
      Section('Ažuriranje firmware-a huba (OTA)', [
        Text('Nova verzija se skida sa servera za izdanja, proverava se SHA256 i šalje hubu. '
            'Hub se posle toga sam restartuje.', style: tsMuted(13)),
        const SizedBox(height: 10),
        KV('Verzija na hubu', st['version'] as String? ?? '—'),
        KV('Build huba', st['build'] as String? ?? '—'),
        const SizedBox(height: 12),
        Btn('Proveri i ažuriraj', icon: 'upload', variant: 'primary', expand: true,
            onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const OtaScreen()))),
      ], inset: false),
    ]);
  }
}
