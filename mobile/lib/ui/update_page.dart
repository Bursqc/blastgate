import 'dart:io';

import 'package:flutter/material.dart' hide Badge, Banner;
import 'package:provider/provider.dart';

import '../services/hub_service.dart';
import '../services/update_service.dart';
import 'icons.dart';
import 'theme.dart';
import 'widgets.dart';

enum UpdateKind { app, hub }

enum _Phase { ready, working, needPermission, waitInstall, done, error }

/// One update, start to finish: what is new, one „Ažuriraj" button, progress
/// in plain words, and a clear message when something goes wrong.
class UpdatePage extends StatefulWidget {
  final UpdateKind kind;
  const UpdatePage(this.kind, {super.key});

  @override
  State<UpdatePage> createState() => _UpdatePageState();
}

class _UpdatePageState extends State<UpdatePage> with WidgetsBindingObserver {
  _Phase _phase = _Phase.ready;
  String _stage = '';
  double? _progress;
  String _error = '';
  String _detail = '';
  File? _apk;
  late final String _from, _to, _changelog;

  bool get _isApp => widget.kind == UpdateKind.app;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    final up = context.read<Updater>();
    _from = _isApp ? up.appVersion : up.hubVersion;
    _to = (_isApp ? up.app?.version : up.firmware?.version) ?? '';
    _changelog = ((_isApp ? up.app?.changelog : up.firmware?.changelog) ?? '').trim();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  /// Back from the Android „install unknown apps" screen: carry on by itself.
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed && _phase == _Phase.needPermission) _install();
  }

  void _fail(String text, [Object? detail]) {
    if (!mounted) return;
    setState(() {
      _phase = _Phase.error;
      _error = text;
      _detail = detail == null ? '' : '$detail';
    });
  }

  // ------------------------------------------------------------------ app
  Future<void> _runApp() async {
    final up = context.read<Updater>();
    setState(() {
      _phase = _Phase.working;
      _stage = 'Preuzimam novu verziju…';
      _progress = up.apk != null ? 1 : 0;
    });
    try {
      _apk = await up.ensureApk((f) {
        if (mounted) setState(() => _progress = f);
      });
    } catch (e) {
      _fail('Preuzimanje nije uspelo. Proveri internet na telefonu pa probaj ponovo.', e);
      return;
    }
    await _install();
  }

  Future<void> _install() async {
    final up = context.read<Updater>();
    final apk = _apk;
    if (apk == null) return;
    try {
      if (!await up.canInstall()) {
        if (mounted) setState(() => _phase = _Phase.needPermission);
        return;
      }
      await up.installApk(apk);
      if (mounted) setState(() => _phase = _Phase.waitInstall);
    } catch (e) {
      _fail('Instalacija nije mogla da se pokrene.', e);
    }
  }

  // ------------------------------------------------------------------ hub
  Future<void> _runHub() async {
    final up = context.read<Updater>();
    final hub = context.read<HubService>();
    setState(() => _phase = _Phase.working);
    try {
      await up.updateHub((stage, f) {
        if (!mounted) return;
        setState(() {
          _progress = f;
          _stage = switch (stage) {
            HubUpdateStage.download => 'Preuzimam novu verziju…',
            HubUpdateStage.upload => 'Šaljem hubu… (oko 20 sekundi)',
            HubUpdateStage.restart => 'Hub se restartuje…',
          };
        });
      });
      hub.addEvent('success', 'Hub ažuriran: $_from → $_to');
      if (mounted) setState(() => _phase = _Phase.done);
    } on HubUpdateError catch (e) {
      hub.addEvent('danger', 'Ažuriranje huba nije uspelo');
      _fail(
          switch (e.stage) {
            HubUpdateStage.download =>
              'Preuzimanje nije uspelo. Proveri internet na telefonu pa probaj ponovo. Hub nije diran.',
            HubUpdateStage.upload =>
              'Slanje hubu nije uspelo. Hub je ostao na staroj verziji i radi normalno. Probaj ponovo.',
            HubUpdateStage.restart =>
              'Hub se nije javio za 90 sekundi. Proveri da li je uključen. '
                  'Kad se pojavi na Pregledu, pogledaj koju verziju prikazuje.',
          },
          e.detail);
    }
  }

  // ------------------------------------------------------------------- UI
  @override
  Widget build(BuildContext context) {
    final working = _phase == _Phase.working;
    return PopScope(
      // Leaving while the hub is being flashed would leave the user guessing
      canPop: !(working && !_isApp),
      child: Scaffold(
        appBar: AppBar(title: const Text('Ažuriranje')),
        body: SafeArea(
          child: Center(
            child: SingleChildScrollView(padding: const EdgeInsets.all(24), child: _body()),
          ),
        ),
      ),
    );
  }

  Widget _panel(String icon, String toneName, String title, String text, List<Widget> actions,
          {List<Widget> extra = const []}) =>
      Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Center(child: Ic(icon, tone(toneName), size: 64)),
        const SizedBox(height: 16),
        Text(title, textAlign: TextAlign.center, style: tsTitle(22)),
        const SizedBox(height: 8),
        Text(text, textAlign: TextAlign.center, style: tsMuted()),
        ...extra,
        const SizedBox(height: 20),
        for (final a in actions) Padding(padding: const EdgeInsets.only(top: 8), child: a),
      ]);

  Widget _body() {
    final what = _isApp ? 'aplikacije' : 'za hub';
    switch (_phase) {
      case _Phase.ready:
        return _panel(
          'download',
          'info',
          _isApp ? 'Nova verzija aplikacije' : 'Novi firmware za hub',
          'Sada: $_from   →   Nova: $_to',
          [
            Btn(_isApp && context.read<Updater>().apk != null ? 'Instaliraj' : 'Ažuriraj',
                icon: 'download', variant: 'primary', expand: true, onTap: _isApp ? _runApp : _runHub),
            Btn('Kasnije', expand: true, onTap: () => Navigator.pop(context)),
          ],
          extra: [
            const SizedBox(height: 16),
            if (_changelog.isNotEmpty) Section('Šta je novo', [Text(_changelog, style: tsMuted(13))], inset: false),
            const SizedBox(height: 12),
            Text(
                _isApp
                    ? 'Android otvara instalaciju koju potvrđuješ jednim dodirom. Podešavanja ostaju sačuvana.'
                    : 'Traje oko minut. Hub se sam restartuje; dok traje, mašine ne reaguju. '
                        'Podešavanja huba i mašina ostaju sačuvana.',
                textAlign: TextAlign.center,
                style: tsSmall()),
          ],
        );

      case _Phase.working:
        return Column(mainAxisSize: MainAxisSize.min, children: [
          Text(_stage, textAlign: TextAlign.center, style: tsTitle(20)),
          const SizedBox(height: 18),
          ClipRRect(
            borderRadius: BorderRadius.circular(5),
            child: LinearProgressIndicator(value: _progress, minHeight: 8, backgroundColor: P.track, color: P.accent),
          ),
          const SizedBox(height: 8),
          if (_progress != null) Text('${(_progress! * 100).round()} %', style: tsMuted(13)),
          const SizedBox(height: 18),
          Text(_isApp ? 'Ne zatvaraj aplikaciju.' : 'Ne gasi hub i ne zatvaraj aplikaciju.',
              textAlign: TextAlign.center, style: tsMuted(13)),
        ]);

      case _Phase.needPermission:
        return _panel(
          'lock',
          'warning',
          'Još jedan korak',
          'Android traži da jednom dozvoliš aplikaciji Blastgate da instalira ažuriranja. '
              'Uključi dozvolu i vrati se ovde — instalacija se nastavlja sama.',
          [
            Btn('Otvori podešavanje', icon: 'settings', variant: 'primary', expand: true,
                onTap: () => context.read<Updater>().openInstallSettings()),
            Btn('Odustani', expand: true, onTap: () => Navigator.pop(context)),
          ],
        );

      case _Phase.waitInstall:
        return _panel(
          'circle-check',
          'success',
          'Potvrdi instalaciju',
          'Android je otvorio prozor za instalaciju. Dodirni „Ažuriraj". '
              'Aplikacija se zatvara i otvara u novoj verziji.',
          [
            Btn('Otvori instalaciju ponovo', icon: 'refresh', variant: 'outline', expand: true, onTap: _install),
            Btn('Zatvori', expand: true, onTap: () => Navigator.pop(context)),
          ],
        );

      case _Phase.done:
        return _panel('circle-check', 'success', 'Hub je ažuriran', 'Hub sada radi na verziji $_to.', [
          Btn('Gotovo', icon: 'check', variant: 'primary', expand: true, onTap: () => Navigator.pop(context)),
        ]);

      case _Phase.error:
        return _panel(
          'alert-circle',
          'danger',
          'Ažuriranje $what nije uspelo',
          _error,
          [
            Btn('Probaj ponovo', icon: 'refresh', variant: 'primary', expand: true, onTap: _isApp ? _runApp : _runHub),
            Btn('Zatvori', expand: true, onTap: () => Navigator.pop(context)),
          ],
          extra: [
            if (_detail.isNotEmpty) ...[
              const SizedBox(height: 10),
              Text('Detalj: $_detail', textAlign: TextAlign.center, style: tsSmall()),
            ],
          ],
        );
    }
  }
}

/// „Nova verzija — Ažuriraj" strip shown on Pregled.
class UpdateStrip extends StatelessWidget {
  final UpdateKind kind;
  const UpdateStrip(this.kind, {super.key});

  @override
  Widget build(BuildContext context) {
    final up = context.watch<Updater>();
    final isApp = kind == UpdateKind.app;
    final col = tone('info');
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 8, 4, 8),
      decoration: BoxDecoration(
        color: col.withValues(alpha: 0.12),
        border: Border.all(color: col),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(children: [
        Ic('download', col, size: 22),
        const SizedBox(width: 10),
        Expanded(
          child: Text(
              !isApp
                  ? 'Novi firmware za hub ${up.firmware?.version ?? ''}'
                  : up.downloading
                      ? 'Preuzimam novu verziju aplikacije ${up.app?.version ?? ''}…'
                      : up.apk != null
                          ? 'Nova verzija aplikacije ${up.app?.version ?? ''} je spremna'
                          : 'Nova verzija aplikacije ${up.app?.version ?? ''}',
              style: TextStyle(color: P.text, fontSize: 13.5, fontWeight: FontWeight.w600)),
        ),
        const SizedBox(width: 8),
        if (isApp && up.downloading)
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: 12),
            child: SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)),
          )
        else
          Btn(isApp && up.apk != null ? 'Instaliraj' : 'Ažuriraj', variant: 'primary',
              onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => UpdatePage(kind)))),
        IconButton(
          tooltip: 'Kasnije',
          visualDensity: VisualDensity.compact,
          icon: Ic('x', P.muted, size: 18),
          onPressed: () => up.hideBanner(forApp: isApp),
        ),
      ]),
    );
  }
}
