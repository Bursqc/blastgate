import 'dart:convert';

import 'package:flutter/material.dart' hide Badge, Banner;
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../models/app_config.dart';
import '../services/hub_http.dart';
import '../services/hub_service.dart';
import '../services/update_service.dart';
import 'add_hub_page.dart';
import 'theme.dart';
import 'widgets.dart';

/// Podešavanja — which hub, appearance, and (folded away) the technical
/// connection values. Port of settings_page.py.
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
  bool _offline = false;
  bool _autoDownload = true;
  String _theme = 'dark';
  bool _dirty = false;
  bool _loading = false;
  bool _advanced = false;
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
    _offline = c.showOfflineNodes;
    _autoDownload = c.autoDownloadUpdates;
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
      setState(() {
        _advanced = true;
        _conn = ('Proveri vrednosti u „Napredno": port 1–65535, osvežavanje 100–10000 ms, čekanje 0.1–10 s.',
            'warning', 'alert-triangle');
      });
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
      ..showOfflineNodes = _offline
      ..autoDownloadUpdates = _autoDownload
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
      _conn = ('Proveravam $ip…', 'info', 'link');
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
      _found = [];
      _conn = ('Tražim hub na mreži…', 'info', 'search');
    });
    final hubs = await hub.discoverHubs();
    if (!mounted) return;
    if (hubs.length == 1) await hub.selectHub(hubs.first);
    if (!mounted) return;
    setState(() {
      _busy = false;
      _found = hubs.length > 1 ? hubs : [];
      _conn = hubs.isEmpty
          ? ('Hub nije pronađen. Proveri da li je uključen i da li je telefon na istoj WiFi mreži.', 'warning',
              'alert-triangle')
          : hubs.length == 1
              ? ('Hub pronađen na adresi ${hubs.first}.', 'success', 'circle-check')
              : ('Pronađeno je više hubova. Dodirni onaj kojim želiš da upravljaš.', 'info', 'search');
    });
  }

  /// Replace the password the hub asks for before a firmware update.
  Future<void> _changeHubPassword() async {
    final hub = context.read<HubService>();
    final ctl = TextEditingController();
    final next = await showDialog<String>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Šifra huba'),
        content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Hub traži ovu šifru pre nego što prihvati ažuriranje. Sa svojom šifrom niko drugi na mreži '
              'ne može da mu menja softver.', style: tsMuted(13)),
          const SizedBox(height: 12),
          TextField(
            controller: ctl,
            autofocus: true,
            decoration: const InputDecoration(labelText: 'Nova šifra', helperText: 'Najmanje 8 znakova'),
          ),
          const SizedBox(height: 8),
          Text('Istu šifru upiši i u aplikaciju na računaru, ako je koristiš.', style: tsSmall()),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c), child: const Text('Otkaži')),
          FilledButton(onPressed: () => Navigator.pop(c, ctl.text.trim()), child: const Text('Postavi')),
        ],
      ),
    );
    if (next == null || !mounted) return;
    if (next.length < 8) {
      setState(() => _conn = ('Šifra mora imati najmanje 8 znakova.', 'warning', 'alert-triangle'));
      return;
    }
    try {
      await HubHttp.setOtaToken(hub.config.effectiveHubIp, hub.config.otaToken, next);
    } on HubRejected catch (e) {
      if (!mounted) return;
      setState(() => _conn = (
            e.status == 401
                ? 'Šifra upisana u aplikaciji nije ista kao na hubu. Upiši tačnu u „Napredno", sačuvaj, pa probaj ponovo.'
                : 'Hub nije prihvatio šifru (${e.status}).',
            'danger',
            'alert-circle'
          ));
      return;
    } catch (e) {
      if (mounted) setState(() => _conn = ('Hub nije dostupan. Šifra nije promenjena.', 'danger', 'alert-circle'));
      return;
    }
    hub.updateConfig(hub.config..otaToken = next);
    hub.addEvent('info', 'Postavljena nova šifra huba');
    if (mounted) setState(() => _conn = ('Nova šifra je postavljena na hubu i sačuvana u aplikaciji.', 'success', 'circle-check'));
  }

  @override
  Widget build(BuildContext context) {
    final hub = context.watch<HubService>();
    final connected = hub.status.isNotEmpty;
    final factoryPassword = hub.config.otaToken == AppConfig.defaultOtaToken;
    // Config is loaded async at startup (and changed by discovery): follow it while nothing is edited
    if (!_dirty && jsonEncode(hub.config.toJson()) != _loadedJson) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted && !_dirty) setState(() => _load(hub.config));
      });
    }

    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      const PageHeader('Podešavanja', 'Hub i izgled aplikacije. Podešavanja mašina su na ekranu svake mašine.'),
      Expanded(
        child: ListView(padding: const EdgeInsets.fromLTRB(16, 0, 16, 16), children: [
          Section('Hub', [
            KV('Adresa', connected ? hub.config.effectiveHubIp : '—'),
            Text('Aplikacija sama pronalazi hub na mreži. Ako ga ne vidi, dodirni „Pronađi hub".', style: tsMuted(13)),
            const SizedBox(height: 10),
            Wrap(spacing: 8, runSpacing: 8, children: [
              Btn('Pronađi hub', icon: 'search', variant: 'outline', onTap: _busy ? null : _scan),
              Btn('Dodaj novi hub', icon: 'access-point', variant: 'outline',
                  onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const AddHubPage()))),
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
                      onPressed: () async {
                        await hub.selectHub(ip);
                        if (mounted) setState(() => _found = []);
                      },
                    ),
                ]),
              ),
            if (connected && factoryPassword) ...[
              Divider(color: P.border, height: 24),
              Text('Hub još ima fabričku šifru. Postavi svoju, da niko drugi na mreži ne može da mu menja softver.',
                  style: tsMuted(13)),
              const SizedBox(height: 10),
              Btn('Postavi šifru huba', icon: 'lock', variant: 'outline', onTap: _changeHubPassword),
            ],
            msgBanner(_conn),
          ], trailing: StatusLabel(connected ? 'POVEZAN' : 'NIJE POVEZAN', connected ? 'success' : 'danger'), inset: false),
          const SizedBox(height: 12),
          Section('Izgled', [
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
          Section('Ažuriranja', [
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: Text('Sama preuzmi novu verziju na WiFi-ju', style: TextStyle(color: P.text, fontSize: 14)),
              subtitle: Text('Instalaciju uvek potvrđuješ ti.', style: tsSmall()),
              value: _autoDownload,
              onChanged: (v) => setState(() {
                _autoDownload = v;
                _dirty = true;
              }),
            ),
          ], inset: false),
          const SizedBox(height: 12),
          BgCard(
            padding: EdgeInsets.zero,
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              InkWell(
                onTap: () => setState(() => _advanced = !_advanced),
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
                  child: Row(children: [
                    Expanded(
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text('Napredno', style: tsSection()),
                        Text('Za servis. U normalnom radu ovde se ništa ne menja.', style: tsSmall()),
                      ]),
                    ),
                    Icon(_advanced ? Icons.expand_less : Icons.expand_more, color: P.muted),
                  ]),
                ),
              ),
              if (_advanced)
                Padding(
                  padding: const EdgeInsets.fromLTRB(14, 0, 14, 14),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                    TextField(
                      controller: _ip,
                      keyboardType: const TextInputType.numberWithOptions(decimal: true),
                      decoration: const InputDecoration(
                          labelText: 'Adresa huba', hintText: 'prazno = aplikacija ga traži sama'),
                    ),
                    const SizedBox(height: 10),
                    Row(children: [
                      Expanded(
                        flex: 3,
                        child: TextField(
                            controller: _ap,
                            decoration: const InputDecoration(labelText: 'Adresa na WiFi-ju huba')),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        flex: 2,
                        child: TextField(
                          controller: _port,
                          keyboardType: TextInputType.number,
                          inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                          decoration: const InputDecoration(labelText: 'Port'),
                        ),
                      ),
                    ]),
                    const SizedBox(height: 10),
                    Row(children: [
                      Expanded(
                        child: TextField(
                          controller: _poll,
                          keyboardType: TextInputType.number,
                          inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                          decoration: const InputDecoration(labelText: 'Osvežavanje stanja', suffixText: 'ms'),
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
                    const SizedBox(height: 10),
                    Btn('Proveri vezu sa ovom adresom', icon: 'link', variant: 'outline', onTap: _busy ? null : _test),
                    const SizedBox(height: 14),
                    TextField(
                        controller: _manifest,
                        decoration: const InputDecoration(labelText: 'Adresa sa koje stižu ažuriranja')),
                    const SizedBox(height: 10),
                    TextField(
                        controller: _token,
                        obscureText: true,
                        decoration: const InputDecoration(
                            labelText: 'Šifra huba', helperText: 'Ona koju hub trenutno ima')),
                    if (connected && !factoryPassword) ...[
                      const SizedBox(height: 10),
                      Btn('Promeni šifru na hubu', icon: 'lock', variant: 'outline', onTap: _changeHubPassword),
                    ],
                  ]),
                ),
            ]),
          ),
          const SizedBox(height: 16),
          Text('Blastgate ${context.watch<Updater>().appVersion} · hub ${hub.status['version'] ?? '—'}',
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
