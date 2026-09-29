import 'dart:convert';

import 'package:flutter/material.dart' hide Badge, Banner;
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../models/app_config.dart';
import '../services/hub_service.dart';
import 'state.dart';
import 'theme.dart';
import 'widgets.dart';

/// Podešavanja — connection, polling, appearance, OTA (app settings only). Port of settings_page.py.
class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key});

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  final _ip = TextEditingController();
  final _ap = TextEditingController();
  final _port = TextEditingController();
  final _poll = TextEditingController();
  final _timeout = TextEditingController();
  final _manifest = TextEditingController();
  final _token = TextEditingController();
  bool _autoAp = true;
  bool _offline = false;
  String _theme = 'dark';
  bool _dirty = false;
  bool _loading = false;
  String _loadedJson = '';
  List<String> _found = [];
  bool _busy = false;
  Msg _conn;

  @override
  void initState() {
    super.initState();
    _load(context.read<HubService>().config);
    for (final c in [_ip, _ap, _port, _poll, _timeout, _manifest, _token]) {
      c.addListener(_markDirty);
    }
  }

  @override
  void dispose() {
    for (final c in [_ip, _ap, _port, _poll, _timeout, _manifest, _token]) {
      c.dispose();
    }
    super.dispose();
  }

  void _markDirty() {
    if (!_dirty && !_loading && mounted) setState(() => _dirty = true);
  }

  void _load(AppConfig c) {
    _loading = true;
    _loadedJson = jsonEncode(c.toJson());
    _ip.text = c.preferredHubIp;
    _ap.text = c.hubApIp;
    _port.text = '${c.udpPort}';
    _poll.text = '${c.pollMs}';
    _timeout.text = '${c.timeoutS}';
    _manifest.text = c.otaManifestUrl;
    _token.text = c.otaToken;
    _autoAp = c.autoApDetect;
    _offline = c.showOfflineNodes;
    _theme = c.theme;
    _dirty = false;
    _loading = false;
  }

  void _save() {
    final hub = context.read<HubService>();
    final port = int.tryParse(_port.text);
    final poll = int.tryParse(_poll.text);
    final to = double.tryParse(_timeout.text.replaceAll(',', '.'));
    if (port == null || port < 1 || port > 65535 || poll == null || poll < 100 || poll > 10000 ||
        to == null || to < 0.1 || to > 10) {
      setState(() => _conn = ('Proveri vrednosti: port 1–65535, osvežavanje 100–10000 ms, čekanje 0.1–10 s.',
          'warning', 'alert-triangle'));
      return;
    }
    final c = hub.config
      ..preferredHubIp = _ip.text.trim()
      ..hubApIp = _ap.text.trim()
      ..udpPort = port
      ..pollMs = poll
      ..timeoutS = to
      ..otaManifestUrl = _manifest.text.trim()
      ..otaToken = _token.text
      ..autoApDetect = _autoAp
      ..showOfflineNodes = _offline
      ..theme = _theme;
    setTheme(c.theme);
    hub.updateConfig(c);
    setState(() => _dirty = false);
    toast(context, 'Podešavanja sačuvana');
  }

  Future<void> _test() async {
    final hub = context.read<HubService>();
    final ip = _ip.text.trim().isEmpty ? hub.config.effectiveHubIp : _ip.text.trim();
    setState(() {
      _busy = true;
      _conn = ('Testiram $ip…', 'info', 'link');
    });
    final ok = await hub.testConnection(ip);
    if (!mounted) return;
    setState(() {
      _busy = false;
      _conn = ok ? ('Hub na $ip odgovara.', 'success', 'circle-check') : ('Nema odgovora sa $ip.', 'danger', 'alert-circle');
    });
  }

  Future<void> _scan() async {
    final hub = context.read<HubService>();
    setState(() {
      _busy = true;
      _conn = ('Tražim hubove…', 'info', 'search');
    });
    final hubs = await hub.discoverHubs();
    if (!mounted) return;
    setState(() {
      _busy = false;
      _found = hubs;
      _conn = hubs.isEmpty
          ? ('Nijedan hub nije pronađen.', 'warning', 'alert-triangle')
          : ('Pronađeno: ${hubs.length}. Dodirni adresu da je koristiš.', 'info', 'search');
    });
  }

  @override
  Widget build(BuildContext context) {
    final hub = context.watch<HubService>();
    final connected = hub.status.isNotEmpty;
    // Config is loaded async at startup (and changed by discovery): follow it while nothing is edited
    if (!_dirty && jsonEncode(hub.config.toJson()) != _loadedJson) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted && !_dirty) setState(() => _load(hub.config));
      });
    }

    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      const PageHeader('Podešavanja',
          'Veza sa hubom, osvežavanje i izgled aplikacije. Podešavanja mašina su na ekranu svake mašine.'),
      Expanded(
        child: ListView(padding: const EdgeInsets.fromLTRB(16, 0, 16, 16), children: [
          Section('Veza sa hubom', [
            TextField(
              controller: _ip,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(labelText: 'IP adresa huba', hintText: 'prazno = automatski'),
            ),
            const SizedBox(height: 10),
            Row(children: [
              Expanded(
                flex: 3,
                child: TextField(
                    controller: _ap, decoration: const InputDecoration(labelText: 'IP huba na njegovom WiFi-ju')),
              ),
              const SizedBox(width: 8),
              Expanded(
                flex: 2,
                child: TextField(
                  controller: _port,
                  keyboardType: TextInputType.number,
                  inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                  decoration: const InputDecoration(labelText: 'UDP port'),
                ),
              ),
            ]),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: Text('Automatski prepoznaj WiFi huba (BLASTGATE_HUB)', style: TextStyle(color: P.text, fontSize: 14)),
              value: _autoAp,
              onChanged: (v) => setState(() {
                _autoAp = v;
                _dirty = true;
              }),
            ),
            Wrap(spacing: 8, runSpacing: 8, children: [
              Btn('Testiraj vezu', icon: 'link', variant: 'outline', onTap: _busy ? null : _test),
              Btn('Pronađi hubove', icon: 'search', onTap: _busy ? null : _scan),
            ]),
            if (_found.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Wrap(spacing: 6, runSpacing: 6, children: [
                  for (final ip in _found)
                    ActionChip(
                      label: Text(ip),
                      backgroundColor: P.cardHi,
                      side: BorderSide(color: P.accent),
                      onPressed: () => setState(() => _ip.text = ip),
                    ),
                ]),
              ),
            msgBanner(_conn),
          ], trailing: StatusLabel(connected ? 'POVEZAN' : 'NIJE POVEZAN', connected ? 'success' : 'danger'), inset: false),
          const SizedBox(height: 12),
          Section('Osvežavanje', [
            Row(children: [
              Expanded(
                child: TextField(
                  controller: _poll,
                  keyboardType: TextInputType.number,
                  inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                  decoration: const InputDecoration(labelText: 'Interval osvežavanja', suffixText: 'ms'),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: TextField(
                  controller: _timeout,
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  decoration: const InputDecoration(labelText: 'Čekanje odgovora', suffixText: 's'),
                ),
              ),
            ]),
            const SizedBox(height: 8),
            Text('Hub keš statusa je 300 ms; kraće od toga nema smisla. '
                'Na HUB_UPDATE poruku aplikacija osvežava odmah.', style: tsSmall()),
          ], inset: false),
          const SizedBox(height: 12),
          Section('Interfejs', [
            Segmented(
              current: _theme,
              compact: true,
              onChosen: (t) => setState(() {
                _theme = t;
                _dirty = true;
              }),
              options: const [SegOption('dark', 'Tamna', '', 'accent'), SegOption('light', 'Svetla', '', 'accent')],
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: Text('Prikaži mašine koje su van mreže', style: TextStyle(color: P.text, fontSize: 14)),
              value: _offline,
              onChanged: (v) => setState(() {
                _offline = v;
                _dirty = true;
              }),
            ),
          ], inset: false),
          const SizedBox(height: 12),
          Section('Ažuriranje firmware-a (OTA)', [
            TextField(controller: _manifest, decoration: const InputDecoration(labelText: 'Adresa manifesta izdanja')),
            const SizedBox(height: 10),
            TextField(controller: _token, obscureText: true, decoration: const InputDecoration(labelText: 'OTA token huba')),
          ], inset: false),
          const SizedBox(height: 16),
          Text('Blastgate mobile 2.1.0 · hub ${hub.status['version'] ?? '—'} · port ${toInt(hub.config.udpPort)}',
              textAlign: TextAlign.center, style: tsSmall()),
        ]),
      ),
      if (_dirty)
        Container(
          color: P.cardHi,
          padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
          child: Row(children: [
            Expanded(child: Text('Imaš nesačuvane izmene.', style: TextStyle(color: tone('warning')))),
            Btn('Poništi', onTap: () => setState(() => _load(hub.config))),
            const SizedBox(width: 8),
            Btn('Sačuvaj', icon: 'device-floppy', variant: 'primary', onTap: _save),
          ]),
        ),
    ]);
  }
}
