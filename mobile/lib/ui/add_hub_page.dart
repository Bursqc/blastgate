import 'dart:async';
import 'dart:io' show Platform;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart' hide Badge, Banner;
import 'package:flutter_esp_ble_prov/flutter_esp_ble_prov.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:provider/provider.dart';

import '../services/hub_http.dart';
import '../services/hub_service.dart';
import 'icons.dart';
import 'state.dart';
import 'theme.dart';
import 'widgets.dart';

/// One guided flow for putting a hub on a WiFi network.
///
/// „Dodaj hub" ([hubIp] == null): find the hub over Bluetooth, pick a WiFi
/// network the hub sees, type the password. The hub advertises as PROV_BG_xxxx
/// for 3 minutes after power-up while it has no WiFi set.
///
/// „Promeni WiFi huba" ([hubIp] set): same steps for a hub the app already
/// reaches (router network or the hub's own BLASTGATE_HUB WiFi), over HTTP.
///
/// Either way the hub restarts, and the app waits until it is back on the
/// network before saying it worked.
class AddHubPage extends StatefulWidget {
  final String? hubIp;
  const AddHubPage({super.key, this.hubIp});

  @override
  State<AddHubPage> createState() => _AddHubPageState();
}

enum _Step { unsupported, permission, scanHubs, scanWifi, password, sending, searching, done, error }

class _AddHubPageState extends State<AddHubPage> {
  final _plugin = FlutterEspBleProv();
  final _pop = TextEditingController(text: 'blastgate');
  final _pass = TextEditingController();

  _Step _step = _Step.permission;
  bool _busy = false;
  bool _showPass = false;
  bool _advanced = false;
  String _msg = '';
  String _detail = '';
  String _retryLabel = '';
  VoidCallback? _retry;
  List<String> _hubs = [];
  List<String> _wifis = [];
  String? _hub;
  String? _ssid;
  int _searchLeft = 0;
  bool _reachableNoWifi = false; // HTTP flow: the hub answers but did not join the WiFi
  Timer? _searchTimer;

  static const _searchSeconds = 90;
  static const _joinSeconds = 60; // a hub that answers but is still off WiFi after this has failed

  bool get _http => widget.hubIp != null;

  @override
  void initState() {
    super.initState();
    if (_http) {
      _step = _Step.scanWifi;
      WidgetsBinding.instance.addPostFrameCallback((_) => _scanWifi(''));
    } else if (kIsWeb || !(Platform.isAndroid || Platform.isIOS)) {
      _step = _Step.unsupported;
    } else {
      WidgetsBinding.instance.addPostFrameCallback((_) => _permissions());
    }
  }

  @override
  void dispose() {
    _searchTimer?.cancel();
    _pop.dispose();
    _pass.dispose();
    super.dispose();
  }

  /// Show the error screen: what went wrong in plain words, the raw reason in
  /// small print, and one button that leads to the sensible next try.
  void _fail(String text, {Object? detail, String retryLabel = 'Počni ispočetka', VoidCallback? retry}) {
    if (!mounted) return;
    setState(() {
      _busy = false;
      _step = _Step.error;
      _msg = text;
      _detail = detail == null ? '' : '$detail';
      _retryLabel = retryLabel;
      _retry = retry ?? (_http ? () => _scanWifi('') : _permissions);
    });
  }

  void _toPassword() => setState(() => _step = _Step.password);

  Future<void> _permissions() async {
    setState(() => _step = _Step.permission);
    final res = await [
      Permission.bluetoothScan,
      Permission.bluetoothConnect,
      Permission.locationWhenInUse,
    ].request();
    if (!res.values.every((s) => s.isGranted || s.isLimited)) {
      _fail('Aplikacija nema dozvolu za Bluetooth i lokaciju. Dozvoli ih u podešavanjima telefona pa probaj ponovo.',
          retryLabel: 'Probaj ponovo');
      return;
    }
    _scanHubs();
  }

  Future<void> _scanHubs() async {
    setState(() {
      _step = _Step.scanHubs;
      _busy = true;
      _hubs = [];
    });
    try {
      final list = await _plugin.scanBleDevices('PROV_BG_');
      if (!mounted) return;
      setState(() {
        _busy = false;
        _hubs = list;
      });
    } catch (e) {
      _fail('Bluetooth pretraga nije uspela. Proveri da li je Bluetooth uključen na telefonu.', detail: e);
    }
  }

  Future<void> _scanWifi(String hub) async {
    setState(() {
      _step = _Step.scanWifi;
      _hub = hub;
      _busy = true;
      _wifis = [];
    });
    try {
      final List<String> list;
      if (_http) {
        final nets = await HubHttp.wifiScan(widget.hubIp!);
        nets.sort((a, b) => toInt(b['rssi']).compareTo(toInt(a['rssi']))); // strongest first
        list = [for (final n in nets) n['ssid'] as String];
      } else {
        list = await _plugin.scanWifiNetworks(hub, _pop.text);
      }
      if (!mounted) return;
      setState(() {
        _busy = false;
        _wifis = list.where((s) => s.trim().isNotEmpty).toSet().toList();
      });
    } catch (e) {
      _fail(
          _http
              ? 'Hub nije poslao listu mreža. Proveri da li je hub dostupan pa probaj ponovo.'
              : 'Hub nije poslao listu mreža. Priđi bliže hubu pa probaj ponovo.',
          detail: e);
    }
  }

  Future<void> _manualSsid() async {
    final ctl = TextEditingController();
    final name = await showDialog<String>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Ime WiFi mreže'),
        content: TextField(
          controller: ctl,
          autofocus: true,
          decoration: const InputDecoration(labelText: 'Ime mreže', helperText: 'Tačno kako piše na ruteru'),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c), child: const Text('Otkaži')),
          FilledButton(onPressed: () => Navigator.pop(c, ctl.text.trim()), child: const Text('Dalje')),
        ],
      ),
    );
    if (name == null || name.isEmpty || !mounted) return;
    setState(() {
      _ssid = name;
      _pass.clear();
      _step = _Step.password;
    });
  }

  Future<void> _send() async {
    if (_hub == null || _ssid == null) return;
    final hub = context.read<HubService>();
    setState(() => _step = _Step.sending);
    if (_http) {
      try {
        await HubHttp.wifiSet(widget.hubIp!, _ssid!, _pass.text);
      } catch (e) {
        _fail('Hub nije primio podešavanje. Proveri da li je dostupan pa probaj ponovo.',
            detail: e, retryLabel: 'Probaj ponovo', retry: _toPassword);
        return;
      }
      hub.addEvent('info', 'Hubu poslata WiFi mreža „$_ssid"');
    } else {
      try {
        final ok = await _plugin.provisionWifi(_hub!, _pop.text, _ssid!, _pass.text) == true;
        if (!ok) {
          _fail('Hub nije uspeo da se poveže na „$_ssid". Najčešći razlog je pogrešna šifra.',
              retryLabel: 'Unesi šifru ponovo', retry: _toPassword);
          return;
        }
      } catch (e) {
        _fail('Slanje hubu nije uspelo. Priđi bliže hubu pa probaj ponovo.',
            detail: e, retryLabel: 'Probaj ponovo', retry: _toPassword);
        return;
      }
      hub.addEvent('success', 'Hub povezan na WiFi „$_ssid"');
    }
    if (mounted) _startSearch();
  }

  /// Hub restarts on the new WiFi; look for it on the network until found.
  void _startSearch() {
    _searchTimer?.cancel();
    setState(() {
      _step = _Step.searching;
      _searchLeft = _searchSeconds;
      _reachableNoWifi = false;
    });
    _searchTimer = Timer.periodic(const Duration(seconds: 1), (t) {
      if (!mounted) return t.cancel();
      setState(() => _searchLeft--);
      if (_searchLeft <= 0) t.cancel();
    });
    _searchLoop();
  }

  /// Several hubs answer: the one that has just restarted is the one we set up.
  Future<String> _pick(List<String> ips) async {
    if (ips.length == 1) return ips.first;
    var best = ips.first;
    var bestUp = 1 << 30;
    for (final ip in ips) {
      final up = toInt((await HubHttp.status(ip))?['uptime'], 1 << 30);
      if (up < bestUp) {
        best = ip;
        bestUp = up;
      }
    }
    return best;
  }

  Future<void> _searchLoop() async {
    final hub = context.read<HubService>();
    await Future.delayed(const Duration(seconds: 5)); // hub restart
    while (mounted && _step == _Step.searching && _searchLeft > 0) {
      final found = await hub.discoverHubs();
      if (!mounted || _step != _Step.searching) return;
      if (found.isNotEmpty) {
        final ip = await _pick(found);
        if (!mounted || _step != _Step.searching) return;
        // Bluetooth flow: the hub already confirmed it joined. HTTP flow: ask it.
        final joined = !_http || toInt((await HubHttp.status(ip))?['sta']) == 1;
        if (!mounted || _step != _Step.searching) return;
        if (joined) {
          await hub.selectHub(ip);
          hub.addEvent('success', 'Hub pronađen: $ip');
          _searchTimer?.cancel();
          if (mounted) {
            setState(() {
              _step = _Step.done;
              _msg = ip;
            });
          }
          return;
        }
        _reachableNoWifi = true;
        if (_searchSeconds - _searchLeft >= _joinSeconds) {
          _searchTimer?.cancel();
          setState(() => _searchLeft = 0);
          return;
        }
      }
      await Future.delayed(const Duration(seconds: 2));
    }
    if (mounted && _step == _Step.searching) setState(() {});
  }

  // ------------------------------------------------------------------ UI
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(_http ? 'Promeni WiFi huba' : 'Dodaj hub')),
      body: SafeArea(child: _body()),
    );
  }

  /// [n] counts from the Bluetooth flow (1 hub, 2 network, 3 password); the
  /// HTTP flow has no „find the hub" step.
  Widget _stepHeader(int n, String title, String sub) => Padding(
        padding: const EdgeInsets.fromLTRB(16, 4, 16, 12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('KORAK ${_http ? n - 1 : n} OD ${_http ? 2 : 3}',
              style: TextStyle(color: P.accent, fontSize: 12, fontWeight: FontWeight.w700)),
          const SizedBox(height: 2),
          Text(title, style: tsTitle(22)),
          if (sub.isNotEmpty) Text(sub, style: tsMuted(13)),
        ]),
      );

  Widget _center(String icon, String toneName, String title, String text,
          {List<Widget> actions = const [], String detail = ''}) =>
      Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(28),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Ic(icon, tone(toneName), size: 64),
            const SizedBox(height: 16),
            Text(title, textAlign: TextAlign.center, style: tsTitle(20)),
            const SizedBox(height: 8),
            Text(text, textAlign: TextAlign.center, style: tsMuted()),
            if (detail.isNotEmpty) ...[
              const SizedBox(height: 10),
              Text('Detalj: $detail', textAlign: TextAlign.center, style: tsSmall()),
            ],
            const SizedBox(height: 20),
            for (final a in actions) Padding(padding: const EdgeInsets.only(top: 8), child: a),
          ]),
        ),
      );

  Widget _listTile(String icon, String text, VoidCallback onTap) => Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
        child: BgCard(
          onTap: onTap,
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
          child: Row(children: [
            Ic(icon, P.accent, size: 22),
            const SizedBox(width: 12),
            Expanded(child: Text(text, style: tsMid())),
            Ic('send', P.muted, size: 18),
          ]),
        ),
      );

  Widget _hubCard(String name) => Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 10),
        child: BgCard(
          padding: const EdgeInsets.fromLTRB(14, 12, 12, 12),
          child: Row(children: [
            Ic('server', P.accent, size: 30),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('Blastgate hub', style: tsMid()),
                Text(name, style: tsSmall()),
              ]),
            ),
            Btn('Poveži', icon: 'link', variant: 'primary', onTap: () => _scanWifi(name)),
          ]),
        ),
      );

  Widget _loading(String text) => Padding(
        padding: const EdgeInsets.all(24),
        child: Row(children: [
          const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.5)),
          const SizedBox(width: 14),
          Expanded(child: Text(text, style: tsMuted())),
        ]),
      );

  Widget _body() {
    switch (_step) {
      case _Step.unsupported:
        return _center('access-point', 'warning', 'Samo na telefonu',
            'Dodavanje huba preko Bluetooth-a radi u aplikaciji na telefonu.');
      case _Step.permission:
        return _loading('Tražim dozvolu za Bluetooth…');

      case _Step.scanHubs:
        return ListView(children: [
          _stepHeader(1, 'Pronađi hub', 'Uključi hub i stani na par metara od njega.'),
          if (_busy)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 24),
              child: Column(children: [
                const SizedBox(width: 220, height: 220, child: Radar()),
                const SizedBox(height: 12),
                Text('Tražim hubove u blizini…', style: tsMuted()),
              ]),
            ),
          if (!_busy && _hubs.isEmpty)
            const Padding(
              padding: EdgeInsets.symmetric(horizontal: 16),
              child: Banner(
                  'Nijedan hub nije pronađen.\n\n'
                  'Hub se preko Bluetooth-a vidi samo dok nema podešen WiFi, i to prva 3 minuta posle uključenja. '
                  'Isključi ga i ponovo uključi, pa dodirni „Traži ponovo".\n\n'
                  'Ako hub već ima podešen WiFi, mrežu mu menjaš u Sistem → WiFi huba.',
                  toneName: 'warning',
                  icon: 'alert-triangle'),
            ),
          for (final h in _hubs) _hubCard(h),
          Padding(
            padding: const EdgeInsets.all(16),
            child: Btn('Traži ponovo', icon: 'refresh', variant: 'outline', onTap: _busy ? null : _scanHubs),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: InkWell(
              onTap: () => setState(() => _advanced = !_advanced),
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                Icon(_advanced ? Icons.expand_less : Icons.expand_more, color: P.muted, size: 18),
                Text('Napredno', style: tsSmall()),
              ]),
            ),
          ),
          if (_advanced)
            Padding(
              padding: const EdgeInsets.all(16),
              child: TextField(
                controller: _pop,
                decoration: const InputDecoration(
                    labelText: 'Šifra uređaja', helperText: 'Menjaj samo ako je promenjena na hubu. Podrazumevano: blastgate'),
              ),
            ),
        ]);

      case _Step.scanWifi:
        return ListView(children: [
          _stepHeader(2, 'Izaberi WiFi mrežu', 'Ovo su mreže koje hub vidi. Izaberi onu na koju treba da se poveže.'),
          if (_busy) _loading('Hub traži mreže… (nekoliko sekundi)'),
          if (!_busy && _wifis.isEmpty)
            const Padding(
              padding: EdgeInsets.symmetric(horizontal: 16),
              child: Banner('Hub ne vidi nijednu WiFi mrežu. Približi ga ruteru pa dodirni „Traži ponovo".',
                  toneName: 'warning', icon: 'wifi-off'),
            ),
          for (final w in _wifis)
            _listTile('wifi', w, () => setState(() {
                  _ssid = w;
                  _pass.clear();
                  _step = _Step.password;
                })),
          Padding(
            padding: const EdgeInsets.all(16),
            child: Wrap(spacing: 8, runSpacing: 8, children: [
              Btn('Traži ponovo', icon: 'refresh', variant: 'outline', onTap: _busy ? null : () => _scanWifi(_hub!)),
              Btn('Mreža nije na listi', icon: 'pencil', onTap: _busy ? null : _manualSsid),
              Btn('Nazad', onTap: _busy ? null : (_http ? () => Navigator.pop(context) : _scanHubs)),
            ]),
          ),
        ]);

      case _Step.password:
        return ListView(padding: const EdgeInsets.only(bottom: 24), children: [
          _stepHeader(3, 'Šifra mreže', 'Mreža „$_ssid"'),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: TextField(
              controller: _pass,
              autofocus: true,
              obscureText: !_showPass,
              onSubmitted: (_) => _send(),
              decoration: InputDecoration(
                labelText: 'WiFi šifra',
                helperText: 'Ostavi prazno ako mreža nema šifru.',
                suffixIcon: IconButton(
                  icon: Ic(_showPass ? 'eye-off' : 'eye', P.muted, size: 20),
                  onPressed: () => setState(() => _showPass = !_showPass),
                ),
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(16),
            child: Btn('Poveži hub', icon: 'send', variant: 'primary', expand: true, onTap: _send),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Btn('Nazad', onTap: () => setState(() => _step = _Step.scanWifi)),
          ),
        ]);

      case _Step.sending:
        return _loading('Šaljem hubu mrežu „$_ssid" i čekam da se poveže…');

      case _Step.searching:
        if (_searchLeft > 0) {
          return _center('refresh', 'info', 'Hub se restartuje…',
              'Čekam da se pojavi na mreži „$_ssid" ($_searchLeft s).\nTelefon treba da bude na istoj WiFi mreži.');
        }
        if (_reachableNoWifi) {
          return _center('alert-circle', 'danger', 'Hub se nije povezao',
              'Hub nije uspeo da se poveže na „$_ssid". Najčešći razlog je pogrešna šifra.',
              actions: [Btn('Unesi šifru ponovo', icon: 'pencil', variant: 'primary', onTap: _toPassword)]);
        }
        return _center(
            'wifi-off',
            'warning',
            'Hub još nije pronađen',
            'Poveži telefon na WiFi „$_ssid" pa dodirni „Traži ponovo".'
                '${_http ? '\n\nAko je šifra bila pogrešna, hub se posle oko minut vraća na svoju mrežu BLASTGATE_HUB '
                    '(šifra 12345678). Poveži telefon na nju i ponovi podešavanje.' : ''}',
            actions: [Btn('Traži ponovo', icon: 'search', variant: 'primary', onTap: _startSearch)]);

      case _Step.done:
        final onHubAp = _msg == context.read<HubService>().config.hubApIp;
        return _center(
            'circle-check',
            'success',
            _http ? 'WiFi je promenjen' : 'Hub je dodat',
            'Hub je povezan na „$_ssid".'
                '${onHubAp ? '\n\nTelefon je još na WiFi mreži huba. Prebaci ga na „$_ssid" — aplikacija će sama pronaći hub.' : ''}',
            detail: 'adresa huba $_msg',
            actions: [
              Btn('Otvori Pregled', icon: 'home', variant: 'primary',
                  onTap: () => Navigator.of(context).popUntil((r) => r.isFirst)),
            ]);

      case _Step.error:
        return _center('alert-circle', 'danger', 'Nije uspelo', _msg, detail: _detail, actions: [
          Btn(_retryLabel, icon: 'refresh', variant: 'primary', onTap: _retry),
        ]);
    }
  }
}

