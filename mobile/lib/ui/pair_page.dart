import 'dart:async';

import 'package:flutter/material.dart' hide Badge, Banner;
import 'package:provider/provider.dart';

import '../services/hub_http.dart';
import '../services/hub_service.dart';
import 'icons.dart';
import 'node_page.dart';
import 'state.dart';
import 'theme.dart';
import 'widgets.dart';

enum _Step { intro, waiting, timeout, name, threshold }

/// „Dodaj mašinu": open the pairing window on the hub, wait for the machine's
/// device to join, give it a name, then offer the threshold calibration.
class PairPage extends StatefulWidget {
  /// Opens the pairing window on the hub; replaced in tests.
  final Future<void> Function(String hubIp) startPairing;
  const PairPage({super.key, this.startPairing = HubHttp.pairStart});

  @override
  State<PairPage> createState() => _PairPageState();
}

class _PairPageState extends State<PairPage> {
  static const _window = 60; // seconds the hub keeps pairing open

  final _name = TextEditingController();
  _Step _step = _Step.intro;
  Set<String> _onlineBefore = {};
  String? _id;
  int _left = 0;
  bool _busy = false;
  String _error = '';
  Timer? _timer;

  HubService get hub => context.read<HubService>();

  @override
  void dispose() {
    _timer?.cancel();
    _name.dispose();
    super.dispose();
  }

  Future<void> _start() async {
    setState(() {
      _busy = true;
      _error = '';
    });
    try {
      await widget.startPairing(hub.config.effectiveHubIp);
    } catch (e) {
      if (mounted) {
        setState(() {
          _busy = false;
          _error = 'Hub nije pokrenuo uparivanje. Proveri da li je dostupan pa probaj ponovo.';
        });
      }
      return;
    }
    if (!mounted) return;
    hub.addEvent('info', 'Uparivanje pokrenuto (60 s)');
    _onlineBefore = {for (final n in nodesOf(hub.status)) if (isOnline(n)) n['id'] as String};
    setState(() {
      _busy = false;
      _step = _Step.waiting;
      _left = _window;
    });
    _timer?.cancel();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) => _tick());
  }

  /// A machine that was not online before and is now: that is the new one.
  void _tick() {
    if (!mounted) return;
    for (final n in nodesOf(hub.status)) {
      final id = n['id'] as String;
      if (isOnline(n) && !_onlineBefore.contains(id)) {
        _timer?.cancel();
        hub.addEvent('success', 'Mašina uparena: $id');
        setState(() {
          _id = id;
          _name.text = (n['name'] as String? ?? '').trim();
          _step = _Step.name;
        });
        return;
      }
    }
    setState(() => _left--);
    if (_left <= 0) {
      _timer?.cancel();
      setState(() => _step = _Step.timeout);
    }
  }

  Future<void> _saveName() async {
    final name = _name.text.trim();
    if (name.isEmpty) {
      setState(() => _step = _Step.threshold);
      return;
    }
    setState(() => _busy = true);
    final ok = await hub.renameNode(_id!, name);
    if (!mounted) return;
    setState(() => _busy = false);
    if (ok) {
      hub.addEvent('info', '$_id: novo ime „$name"');
      setState(() => _step = _Step.threshold);
    } else {
      toast(context, 'Hub nije sačuvao ime. Probaj ponovo.');
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Dodaj mašinu')),
      body: SafeArea(child: Center(child: SingleChildScrollView(padding: const EdgeInsets.all(24), child: _body()))),
    );
  }

  Widget _numbered(int n, String text) => Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Container(
            width: 26,
            height: 26,
            alignment: Alignment.center,
            decoration: BoxDecoration(color: P.navActive, shape: BoxShape.circle),
            child: Text('$n', style: TextStyle(color: P.accent, fontWeight: FontWeight.w700, fontSize: 13)),
          ),
          const SizedBox(width: 12),
          Expanded(child: Padding(padding: const EdgeInsets.only(top: 3), child: Text(text, style: tsMuted()))),
        ]),
      );

  Widget _panel(String icon, String toneName, String title, String text, List<Widget> actions) =>
      Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Center(child: Ic(icon, tone(toneName), size: 64)),
        const SizedBox(height: 16),
        Text(title, textAlign: TextAlign.center, style: tsTitle(22)),
        const SizedBox(height: 8),
        Text(text, textAlign: TextAlign.center, style: tsMuted()),
        const SizedBox(height: 20),
        for (final a in actions) Padding(padding: const EdgeInsets.only(top: 8), child: a),
      ]);

  Widget _body() {
    switch (_step) {
      case _Step.intro:
        return Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Center(child: Ic('link', P.accent, size: 64)),
          const SizedBox(height: 16),
          Text('Poveži mašinu sa hubom', textAlign: TextAlign.center, style: tsTitle(22)),
          const SizedBox(height: 18),
          _numbered(1, 'Uključi uređaj na mašini u struju. Treba da bude u dometu huba.'),
          _numbered(2, 'Dodirni „Počni". Hub čeka mašinu 60 sekundi.'),
          _numbered(3, 'Na uređaju mašine drži taster 3 sekunde, dok lampica ne počne brzo da trepće.'),
          if (_error.isNotEmpty) ...[
            const SizedBox(height: 6),
            Banner(_error, toneName: 'danger', icon: 'alert-circle'),
          ],
          const SizedBox(height: 14),
          Btn(_busy ? 'Pokrećem…' : 'Počni', icon: 'link', variant: 'primary', expand: true, onTap: _busy ? null : _start),
        ]);

      case _Step.waiting:
        return Column(mainAxisSize: MainAxisSize.min, children: [
          const SizedBox(width: 200, height: 200, child: Radar(icon: 'link')),
          const SizedBox(height: 16),
          Text('Drži taster na uređaju mašine 3 sekunde', textAlign: TextAlign.center, style: tsTitle(20)),
          const SizedBox(height: 8),
          Text('Kad lampica počne brzo da trepće, pusti taster. Mašina se javlja za nekoliko sekundi.',
              textAlign: TextAlign.center, style: tsMuted()),
          const SizedBox(height: 16),
          Text('Hub čeka još $_left s', style: tsMuted(13)),
        ]);

      case _Step.timeout:
        return _panel(
          'alert-triangle',
          'warning',
          'Nijedna mašina se nije javila',
          'Proveri da li je uređaj uključen u struju i da li si taster držao pune 3 sekunde. '
              'Ako je daleko od huba, približi ga za prvo uparivanje.',
          [
            Btn('Probaj ponovo', icon: 'refresh', variant: 'primary', expand: true, onTap: _start),
            Btn('Zatvori', expand: true, onTap: () => Navigator.pop(context)),
          ],
        );

      case _Step.name:
        return Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Center(child: Ic('circle-check', tone('success'), size: 64)),
          const SizedBox(height: 16),
          Text('Mašina je uparena', textAlign: TextAlign.center, style: tsTitle(22)),
          const SizedBox(height: 8),
          Text('Daj joj ime po kom ćeš je prepoznati.', textAlign: TextAlign.center, style: tsMuted()),
          const SizedBox(height: 18),
          TextField(
            controller: _name,
            autofocus: true,
            textCapitalization: TextCapitalization.sentences,
            onSubmitted: (_) => _saveName(),
            decoration: InputDecoration(labelText: 'Ime mašine', hintText: 'npr. Cirkular', helperText: 'Oznaka uređaja: $_id'),
          ),
          const SizedBox(height: 16),
          Btn(_busy ? 'Čuvam…' : 'Dalje', variant: 'primary', expand: true, onTap: _busy ? null : _saveName),
        ]);

      case _Step.threshold:
        return _panel(
          'ruler-measure',
          'info',
          'Još samo prag',
          'Prag je jačina struje iznad koje hub zna da mašina radi i otvara zatvarač. '
              'Kalibracija traje oko pola minuta: upališ mašinu, pa je ugasiš.',
          [
            Btn('Kalibriši sada', icon: 'ruler-measure', variant: 'primary', expand: true,
                onTap: () => Navigator.pushReplacement(
                    context, MaterialPageRoute(builder: (_) => NodePage(nodeId: _id!, calibrate: true)))),
            Btn('Kasnije', expand: true, onTap: () => Navigator.pop(context)),
          ],
        );
    }
  }
}
