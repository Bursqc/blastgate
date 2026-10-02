import 'dart:async';

import 'package:flutter/material.dart' hide Badge, Banner;
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../services/hub_service.dart';
import 'icons.dart';
import 'overview_page.dart' show removeNodeDialog;
import 'state.dart';
import 'theme.dart';
import 'widgets.dart';

/// Machine screen — state, AUTO/MANUAL, manual gate + suction, settings, calibration.
/// Port of node_dialog.py (NodeDialog + CalibrationDialog).
class NodePage extends StatefulWidget {
  final String nodeId;
  final bool calibrate;
  const NodePage({super.key, required this.nodeId, this.calibrate = false});

  @override
  State<NodePage> createState() => _NodePageState();
}

class _NodePageState extends State<NodePage> {
  final _mode = GlobalKey<SegmentedState>();
  final _gate = GlobalKey<SegmentedState>();
  final _relay = GlobalKey<SegmentedState>();

  final _name = TextEditingController();
  final _thr = TextEditingController();
  final _hold = TextEditingController();
  final _hbo = TextEditingController();
  final _hbc = TextEditingController();
  bool _loaded = false;
  bool _saving = false;
  Msg _msg;

  String get id => widget.nodeId;
  HubService get hub => context.read<HubService>();

  @override
  void initState() {
    super.initState();
    if (widget.calibrate) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _calibrate());
    }
  }

  @override
  void dispose() {
    for (final c in [_name, _thr, _hold, _hbo, _hbc]) {
      c.dispose();
    }
    super.dispose();
  }

  void _fill(Json n) {
    _name.text = (n['name'] as String? ?? '').trim();
    _thr.text = fmtG(toDouble(n['threshold_on']) ?? 40.0);
    _hold.text = fmtG(holdMsToS(n['gate_hold_ms'] ?? 5000));
    _hbo.text = '${toInt(n['hbridge_open_ms'], 2000)}';
    _hbc.text = '${toInt(n['hbridge_close_ms'], 2000)}';
  }

  String _nodeName() {
    final n = hub.node(id);
    return n != null ? nodeName(n) : id;
  }

  void _say(String text, String t, String icon) => setState(() => _msg = (text, t, icon));

  // -------------------------------------------------------------- commands
  Future<void> _setMode(String mode) async {
    final ok = await hub.setMode(id, mode);
    if (!ok) {
      _mode.currentState?.clearPending();
      _say('Režim: hub nije potvrdio', 'danger', 'alert-circle');
      return;
    }
    hub.addEvent('info', '${_nodeName()}: režim → ${mode.toUpperCase()}');
    // Back to AUTO also clears the manual gate override (same as the desktop app)
    if (mode == 'auto' && !await hub.sendGateCommand(id, 'auto')) {
      _say('Reset zatvarača: hub nije potvrdio', 'danger', 'alert-circle');
    }
  }

  Future<void> _setGate(String gate) async {
    // Hub decides the relay; never send RELAY off here (it forces suction off for all gates).
    if (await hub.sendGateCommand(id, gate)) {
      hub.addEvent('info', '${_nodeName()}: ručno ${gate == 'open' ? 'OTVORI' : 'ZATVORI'}');
    } else {
      _gate.currentState?.clearPending();
      _say('Zatvarač: hub nije potvrdio', 'danger', 'alert-circle');
    }
  }

  Future<void> _setRelay(String mode) async {
    final anyOpen = nodesOf(hub.status).any((n) => isOnline(n) && gateOpen(n));
    if (mode == 'on' && !anyOpen) {
      _relay.currentState?.clearPending();
      _say('Usisivač se ne pali dok nijedan zatvarač nije otvoren.', 'warning', 'alert-triangle');
      return;
    }
    final err = await hub.setRelay(mode);
    if (err == null) {
      hub.addEvent('info', 'Usisivač → ručno ${mode == 'on' ? 'UKLJUČEN' : 'ISKLJUČEN'}');
    } else {
      _relay.currentState?.clearPending();
      _say('Usisivač: $err', 'danger', 'alert-circle');
    }
  }

  Future<void> _reload() async {
    final cfg = await hub.getNodeConfig(id);
    if (!mounted) return;
    if (cfg == null) {
      _say('Učitavanje nije uspelo.', 'danger', 'alert-circle');
      return;
    }
    setState(() => _fill({...?hub.node(id), ...cfg}));
    _say('Podešavanja učitana sa huba.', 'info', 'refresh');
  }

  Future<void> _apply() async {
    final thr = double.tryParse(_thr.text.replaceAll(',', '.'));
    final hold = double.tryParse(_hold.text.replaceAll(',', '.'));
    final hbo = int.tryParse(_hbo.text);
    final hbc = int.tryParse(_hbc.text);
    if (thr == null || thr < 0.1 || thr > 250 || hold == null || hold < 0 || hold > 600 ||
        hbo == null || hbo < 100 || hbo > 60000 || hbc == null || hbc < 100 || hbc > 60000) {
      _say('Proveri vrednosti: prag 0.1–250, ostaje otvoren 0–600 s, motor 100–60000 ms.', 'warning',
          'alert-triangle');
      return;
    }
    setState(() => _saving = true);
    _say('Šaljem na hub…', 'info', 'send');
    final thrR = (thr * 10).round() / 10;
    var ok = await hub.setNodeConfig(
        nodeId: id, threshold: thrR, holdMs: holdSToMs(hold), hbridgeOpenMs: hbo, hbridgeCloseMs: hbc);
    if (ok) {
      hub.addEvent('info', '${_nodeName()}: prag ${fmtG(thrR)}, ostaje otvoren ${fmtG(hold)} s');
      final newName = _name.text.trim();
      final cur = ((hub.node(id) ?? {})['name'] as String? ?? '').trim();
      if (newName.isNotEmpty && newName != cur) {
        ok = await hub.renameNode(id, newName);
        if (ok) hub.addEvent('info', '$id: novo ime „$newName”');
      }
    }
    if (!mounted) return;
    setState(() => _saving = false);
    ok
        ? _say('Sačuvano na hubu.', 'success', 'circle-check')
        : _say('Čuvanje nije uspelo.', 'danger', 'alert-circle');
  }

  Future<void> _calibrate() async {
    final thr = await showModalBottomSheet<double>(
      context: context,
      isScrollControlled: true,
      isDismissible: false,
      builder: (_) => ChangeNotifierProvider.value(value: hub, child: CalibrationSheet(nodeId: id)),
    );
    if (thr == null || !mounted) return;
    setState(() => _thr.text = fmtG(thr));
    if (await hub.setNodeConfig(nodeId: id, threshold: thr)) {
      hub.addEvent('info', '${_nodeName()}: kalibrisan prag ${fmtG(thr)}');
      _say('Prag ${fmtG(thr)} upisan na hub.', 'success', 'circle-check');
    } else {
      _say('Upis praga nije uspeo.', 'danger', 'alert-circle');
    }
  }

  // ---------------------------------------------------------------- build
  @override
  Widget build(BuildContext context) {
    final hub = context.watch<HubService>();
    final st = hub.status;
    final n = hub.node(id);

    if (n == null) {
      return Scaffold(
        appBar: AppBar(title: Text(id)),
        body: Padding(
          padding: const EdgeInsets.all(16),
          child: StatusLabel(st.isNotEmpty ? 'NEPOZNATA' : 'HUB NEDOSTUPAN', 'danger', size: 14),
        ),
      );
    }
    if (!_loaded) {
      _loaded = true;
      _fill(n);
    }

    final online = isOnline(n);
    final v = toDouble(n['value']);
    final thr = toDouble(n['threshold_on']);
    final open = gateOpen(n);
    final manual = toInt(n['mode']) == 1;
    final locked = hub.lockout;
    final can = online && !locked;
    final extra = [
      'Oznaka uređaja $id',
      if (n['fw'] != null) 'verzija ${n['fw']}',
    ];
    final errs = errTexts(toInt(n['err']) & errWarningMask);
    Widget? banner;
    if (locked) {
      banner = const Banner('Hub je u ručnom režimu (MANUAL taster) — komande iz aplikacije su zaključane.',
          toneName: 'warning', icon: 'lock');
    } else if (!online) {
      banner = const Banner('Mašina je van mreže.', toneName: 'danger', icon: 'wifi-off');
    } else if (errs.isNotEmpty) {
      banner = Banner(errs.join('\n'), toneName: 'warning', icon: 'alert-triangle');
    }

    return Scaffold(
      appBar: AppBar(title: Text(nodeName(n)), actions: [
        PopupMenuButton<String>(
          icon: Ic('dots', P.muted, size: 22),
          tooltip: 'Opcije',
          color: P.card,
          onSelected: (_) async {
            if (await removeNodeDialog(context, id) && context.mounted) Navigator.pop(context);
          },
          itemBuilder: (_) => const [PopupMenuItem(value: 'remove', child: Text('Ukloni mašinu…'))],
        ),
      ]),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
        children: [
          StatusLabel(nodeStatus(n).$1, nodeStatus(n).$2, size: 14),
          const SizedBox(height: 4),
          Text(extra.join('  ·  '), style: tsSmall()),
          const SizedBox(height: 12),

          // --- live value ---------------------------------------------------
          BgCard(
            inset: true,
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Text('Trenutna vrednost senzora', style: tsMuted()),
              Text(v != null && online ? v.toStringAsFixed(1) : '—', style: tsBig(44)),
              ValueBar(value: online ? v : null, threshold: thr, max: barMax(v, thr), barHeight: 12),
              Divider(color: P.border, height: 18),
              Row(children: [
                Expanded(
                    child: IconValue(open ? 'gate-open' : 'gate-closed', 'Zatvarač', gateText(n),
                        toneName: online ? (open ? 'success' : 'danger') : 'muted')),
                Expanded(child: IconValue(signalIcon(n), 'Signal', signalText(n))),
              ]),
            ]),
          ),
          if (banner != null) ...[const SizedBox(height: 12), banner],
          const SizedBox(height: 12),

          // --- mode -----------------------------------------------------------
          Section('Režim rada', [
            Segmented(
              key: _mode,
              current: manual ? 'manual' : 'auto',
              enabled: can,
              onChosen: _setMode,
              options: const [
                SegOption('auto', 'AUTO', 'settings', 'info'),
                SegOption('manual', 'MANUAL', 'hand-stop', 'warning'),
              ],
            ),
            const SizedBox(height: 8),
            Text('AUTO: hub otvara zatvarač kad mašina radi. MANUAL: ti upravljaš.', style: tsSmall()),
          ]),
          const SizedBox(height: 12),

          // --- manual gate + suction -----------------------------------------
          Section('Ručna komanda', [
            Segmented(
              key: _gate,
              current: const {1: 'open', 2: 'close'}[toInt(n['override'])],
              enabled: can && manual,
              onChosen: _setGate,
              options: const [
                SegOption('open', 'OTVORI', 'gate-open', 'success'),
                SegOption('close', 'ZATVORI', 'gate-closed', 'danger'),
              ],
            ),
            const SizedBox(height: 8),
            Text('Usisivač (ceo sistem, ručno max 30 s pa hub vraća na AUTO)', style: tsSmall()),
            const SizedBox(height: 8),
            Segmented(
              key: _relay,
              compact: true,
              current: const {0: 'off', 1: 'on'}[toInt(st['relayMode'], 2)],
              enabled: can && manual,
              onChosen: _setRelay,
              options: const [
                SegOption('on', 'UKLJUČI', 'power', 'success'),
                SegOption('off', 'ISKLJUČI', 'player-stop', 'danger'),
              ],
            ),
            if (!manual) ...[
              const SizedBox(height: 8),
              Text('Ručne komande su dostupne samo u MANUAL režimu.', style: tsSmall()),
            ],
          ]),
          const SizedBox(height: 12),

          // --- settings -------------------------------------------------------
          Section('Podešavanja mašine', [
            _field('Ime', _name, hint: 'npr. Cirkular', text: true),
            _thrField(),
            _field('Ostaje otvoren', _hold, suffix: 's', help: 'posle gašenja mašine'),
            _field('Motor — otvaranje', _hbo, suffix: 'ms', help: 'vreme rada H-mosta', integer: true),
            _field('Motor — zatvaranje', _hbc, suffix: 'ms', help: 'vreme rada H-mosta', integer: true),
            const SizedBox(height: 6),
            Wrap(spacing: 8, runSpacing: 8, children: [
              Btn('Kalibracija praga', icon: 'ruler-measure', variant: 'outline', onTap: _calibrate),
              Btn('Učitaj sa huba', icon: 'refresh', onTap: _reload),
            ]),
          ]),
          msgBanner(_msg),
          const SizedBox(height: 12),
          Btn(_saving ? 'Šaljem…' : 'Primeni izmene',
              icon: 'device-floppy', variant: 'primary', expand: true, onTap: _saving ? null : _apply),
        ],
      ),
    );
  }

  Widget _thrField() {
    final v = double.tryParse(_thr.text.replaceAll(',', '.')) ?? 40.0;
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          SizedBox(width: 130, child: Text('Prag', style: tsMuted())),
          Expanded(
            child: Slider(
              min: 0.1,
              max: 250,
              value: v.clamp(0.1, 250),
              onChanged: (x) => setState(() => _thr.text = fmtG((x * 10).round() / 10)),
            ),
          ),
          SizedBox(
            width: 76,
            child: TextField(
              controller: _thr,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              onChanged: (_) => setState(() {}),
            ),
          ),
        ]),
        Padding(
          padding: const EdgeInsets.only(left: 130),
          child: Text('Iznad praga mašina se smatra upaljenom', style: tsSmall()),
        ),
      ]),
    );
  }

  Widget _field(String caption, TextEditingController c,
      {String suffix = '', String help = '', String hint = '', bool text = false, bool integer = false}) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SizedBox(width: 130, child: Padding(padding: const EdgeInsets.only(top: 12), child: Text(caption, style: tsMuted()))),
        Expanded(
          child: TextField(
            controller: c,
            keyboardType: text
                ? TextInputType.text
                : TextInputType.numberWithOptions(decimal: !integer),
            inputFormatters: integer ? [FilteringTextInputFormatter.digitsOnly] : null,
            decoration: InputDecoration(
              hintText: hint,
              suffixText: suffix.isEmpty ? null : suffix,
              helperText: help.isEmpty ? null : help,
              helperStyle: tsSmall(),
            ),
          ),
        ),
      ]),
    );
  }
}

// ============================================================== calibration

enum _Cal { start, waitOn, sampleOn, waitOff, sampleOff, done }

/// Same algorithm as the desktop wizard: baseline -> machine ON samples -> verify OFF.
/// Pops with the recommended threshold, or null when cancelled.
class CalibrationSheet extends StatefulWidget {
  final String nodeId;
  const CalibrationSheet({super.key, required this.nodeId});

  @override
  State<CalibrationSheet> createState() => _CalibrationSheetState();
}

class _CalibrationSheetState extends State<CalibrationSheet> {
  static const steps = {
    _Cal.start: 'Mašina mora biti UGAŠENA. Pritisni „Počni”.',
    _Cal.waitOn: 'Merim mirovanje… zatim UPALI mašinu.',
    _Cal.sampleOn: 'Mašina radi — merim…',
    _Cal.waitOff: 'Sada UGASI mašinu.',
    _Cal.sampleOff: 'Proveravam da vrednost pada ispod praga…',
    _Cal.done: 'Gotovo.',
  };

  _Cal _state = _Cal.start;
  final List<double> _baseline = [], _on = [], _off = [];
  double _baseAvg = 0;
  double? _last, _reading, recommended;
  double _progress = 0;
  String _detail = '';
  String _btn = 'Počni';
  bool _btnEnabled = true;
  Timer? _timer;

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  void _action() {
    if (_state == _Cal.done && recommended != null) {
      Navigator.pop(context, recommended);
      return;
    }
    setState(() {
      _state = _Cal.waitOn;
      _baseline.clear();
      _on.clear();
      _off.clear();
      _last = null;
      recommended = null;
      _btnEnabled = false;
      _btn = 'Merim…';
    });
    _timer?.cancel();
    _timer = Timer.periodic(const Duration(milliseconds: 400), (_) => _tick());
    _tick();
  }

  void _tick() {
    final n = context.read<HubService>().node(widget.nodeId);
    final v = n == null ? null : toDouble(n['value']);
    setState(() {
      if (v == null) {
        _detail = 'Čekam podatke sa senzora…';
        return;
      }
      _reading = v;
      final isNew = _last == null || (v - _last!).abs() > 0.01; // hub refreshes ~650 ms
      _last = v;

      switch (_state) {
        case _Cal.waitOn:
          if (_baseline.length < 5) {
            if (isNew) _baseline.add(v);
            _progress = _baseline.length / 5;
            _detail = 'Mirovanje: ${_baseline.length}/5 merenja';
          } else {
            _baseAvg = _baseline.reduce((a, b) => a + b) / _baseline.length;
            final trig = _baseAvg * 1.5 > _baseAvg + 8.0 ? _baseAvg * 1.5 : _baseAvg + 8.0;
            if (v > trig) {
              _state = _Cal.sampleOn;
              _progress = 0;
            }
            _detail = 'Mirovanje ${_baseAvg.toStringAsFixed(1)} — čekam da mašina krene';
          }
        case _Cal.sampleOn:
          if (isNew) _on.add(v);
          _progress = (_on.length / 15).clamp(0, 1);
          if (_on.length >= 10) {
            final minOn = _on.reduce((a, b) => a < b ? a : b);
            var thr = ((_baseAvg + minOn) / 2 * 10).round() / 10;
            if (thr <= _baseAvg) thr = ((_baseAvg + (minOn - _baseAvg) * 0.3) * 10).round() / 10;
            recommended = thr;
            _state = _Cal.waitOff;
            _detail = 'Predlog praga ${fmtG(thr)} (mirovanje ${_baseAvg.toStringAsFixed(1)}, '
                'min rad ${minOn.toStringAsFixed(1)})';
          }
        case _Cal.waitOff:
          if (recommended != null && v < recommended!) {
            _state = _Cal.sampleOff;
            _off.clear();
            _progress = 0;
          }
        case _Cal.sampleOff:
          if (isNew) _off.add(v);
          _progress = (_off.length / 5).clamp(0, 1);
          if (_off.length >= 5) {
            _timer?.cancel();
            _btnEnabled = true;
            final maxOff = _off.reduce((a, b) => a > b ? a : b);
            if (maxOff < (recommended ?? 0)) {
              _state = _Cal.done;
              _btn = 'Upiši prag ${fmtG(recommended!)}';
            } else {
              _state = _Cal.start;
              recommended = null;
              _btn = 'Ponovi';
              _detail = 'Provera nije prošla: posle gašenja vrednost je ${maxOff.toStringAsFixed(1)}, '
                  'a to je iznad predloga. Pokušaj ponovo.';
            }
          }
        case _Cal.start:
        case _Cal.done:
          break;
      }
    });
  }

  @override
  Widget build(BuildContext context) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 18, 20, 16),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Text('Kalibracija praga', style: tsSection()),
            const SizedBox(height: 10),
            Text(steps[_state]!, style: TextStyle(fontSize: 16, color: P.text)),
            const SizedBox(height: 10),
            Text('Vrednost: ${_reading?.toStringAsFixed(1) ?? '—'}', style: tsMid()),
            const SizedBox(height: 10),
            LinearProgressIndicator(value: _progress, minHeight: 8, borderRadius: BorderRadius.circular(4)),
            const SizedBox(height: 8),
            Text(_detail, style: tsSmall()),
            const SizedBox(height: 16),
            Row(mainAxisAlignment: MainAxisAlignment.end, children: [
              Btn('Otkaži', onTap: () => Navigator.pop(context)),
              const SizedBox(width: 10),
              Btn(_btn, variant: 'primary', onTap: _btnEnabled ? _action : null),
            ]),
          ]),
        ),
      );
}
