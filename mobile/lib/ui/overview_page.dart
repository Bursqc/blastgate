import 'package:flutter/material.dart' hide Badge, Banner;
import 'package:provider/provider.dart';

import '../services/hub_service.dart';
import 'icons.dart';
import 'node_page.dart';
import 'state.dart';
import 'theme.dart';
import 'widgets.dart';

/// Pregled — machine tiles + system bar (suction, hub, counts). Port of overview_page.py.
class OverviewPage extends StatelessWidget {
  const OverviewPage({super.key});

  @override
  Widget build(BuildContext context) {
    final hub = context.watch<HubService>();
    final st = hub.status;
    final nodes = nodesOf(st);
    final shown = nodes.where((n) => hub.config.showOfflineNodes || isOnline(n)).toList()
      ..sort((a, b) => nodeName(a).toLowerCase().compareTo(nodeName(b).toLowerCase()));

    final counts = {'success': 0, 'warning': 0, 'danger': 0};
    for (final n in nodes) {
      final t = nodeStatus(n).$2;
      counts[t == 'idle' ? 'success' : t] = counts[t == 'idle' ? 'success' : t]! + 1;
    }

    Widget? banner;
    if (st.isEmpty) {
      banner = const Banner(
          'Veza sa hubom nije uspostavljena. Proveri da li je hub uključen i da li je telefon na istoj mreži '
          '(ili na WiFi-ju BLASTGATE_HUB). Adresu možeš da podesiš u Podešavanjima.',
          toneName: 'danger',
          icon: 'wifi-off');
    } else if (hub.lockout) {
      banner = const Banner(
          'Hub je u RUČNOM REŽIMU (MANUAL taster). Svi zatvarači su zatvoreni; otvaraju se tasterima na '
          'mašinama. Hub sam izlazi iz ovog režima kad neka mašina krene.',
          toneName: 'warning',
          icon: 'hand-stop');
    }

    String? empty;
    if (st.isNotEmpty && nodes.isEmpty) {
      empty = 'Hub još ne vidi nijednu mašinu.\nUključi nodove — pojaviće se ovde čim se jave.';
    } else if (shown.isEmpty && nodes.isNotEmpty) {
      empty = 'Sve mašine su van mreže (prikaz offline mašina je isključen u Podešavanjima).';
    }

    return RefreshIndicator(
      onRefresh: hub.fullRefresh,
      child: ListView(
        padding: const EdgeInsets.only(bottom: 16),
        children: [
          PageHeader(
            'Pregled mašina',
            st.isNotEmpty && hub.updatedAt != null
                ? 'Ažurirano ${hhmmss(hub.updatedAt!)}'
                : 'Nadzor i upravljanje zatvaračima u realnom vremenu.',
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
            child: Row(children: [
              Text('Hub: ', style: tsMuted(13)),
              st.isNotEmpty
                  ? const StatusLabel('POVEZAN', 'success')
                  : StatusLabel(hub.searching ? 'TRAŽIM…' : 'NEDOSTUPAN', hub.searching ? 'warning' : 'danger'),
              const Spacer(),
              Text('${nodes.length} mašina', style: tsMuted(13)),
              for (final k in ['success', 'warning', 'danger']) ...[
                const SizedBox(width: 10),
                Dot(k),
                const SizedBox(width: 4),
                Text('${counts[k]}', style: TextStyle(color: P.text, fontSize: 13)),
              ],
            ]),
          ),
          if (banner != null) Padding(padding: const EdgeInsets.fromLTRB(16, 0, 16, 12), child: banner),
          for (final n in shown)
            Padding(padding: const EdgeInsets.fromLTRB(16, 0, 16, 12), child: NodeTile(n)),
          if (empty != null)
            Padding(
              padding: const EdgeInsets.all(32),
              child: Text(empty, textAlign: TextAlign.center, style: tsMuted()),
            ),
          const Padding(padding: EdgeInsets.fromLTRB(16, 4, 16, 0), child: SummaryCard()),
        ],
      ),
    );
  }
}

void openNode(BuildContext context, String id) =>
    Navigator.push(context, MaterialPageRoute(builder: (_) => NodePage(nodeId: id)));

class NodeTile extends StatelessWidget {
  final Json n;
  const NodeTile(this.n, {super.key});

  @override
  Widget build(BuildContext context) {
    final online = isOnline(n);
    final (stText, stTone) = nodeStatus(n);
    final v = toDouble(n['value']);
    final thr = toDouble(n['threshold_on']);
    final manual = toInt(n['mode']) == 1;
    final open = gateOpen(n);
    final gateTone = online ? (open ? 'success' : 'danger') : 'muted';
    final errs = errTexts(toInt(n['err']) & errWarningMask);
    final id = n['id'] as String;

    return BgCard(
      onTap: () => openNode(context, id),
      padding: const EdgeInsets.fromLTRB(16, 12, 8, 12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          Flexible(
              child: Text(nodeName(n),
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600, color: P.text))),
          const SizedBox(width: 10),
          StatusLabel(stText, stTone),
          const Spacer(),
          _TileMenu(id),
        ]),
        Padding(
          padding: const EdgeInsets.only(right: 8),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(v != null && online ? v.toStringAsFixed(1) : '—', style: tsBig()),
                  Text('Senzor struje', style: tsMuted(13)),
                ]),
              ),
              Column(children: [
                manual ? const Badge('MANUAL', 'hand-stop', 'warning') : const Badge('AUTO', 'settings', 'info'),
                const SizedBox(height: 8),
                Badge(open ? 'OTVOREN' : 'ZATVOREN', open ? 'gate-open' : 'gate-closed',
                    online ? (open ? 'success' : 'danger') : 'idle'),
              ]),
            ]),
            const SizedBox(height: 8),
            ValueBar(value: online ? v : null, threshold: thr, max: barMax(v, thr)),
            Divider(color: P.border, height: 14),
            Row(children: [
              Expanded(child: IconValue(open ? 'gate-open' : 'gate-closed', 'Zatvarač', gateText(n), toneName: gateTone)),
              Container(width: 1, height: 34, color: P.border, margin: const EdgeInsets.symmetric(horizontal: 10)),
              Expanded(child: IconValue(signalIcon(n), 'Signal', signalText(n))),
            ]),
            if (errs.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(errs.join('\n'), style: TextStyle(color: tone('warning'), fontSize: 12)),
              ),
          ]),
        ),
      ]),
    );
  }
}

class _TileMenu extends StatelessWidget {
  final String id;
  const _TileMenu(this.id);

  @override
  Widget build(BuildContext context) => PopupMenuButton<String>(
        icon: Ic('dots', P.muted, size: 20),
        tooltip: 'Opcije',
        color: P.card,
        onSelected: (a) async {
          if (a == 'open') {
            openNode(context, id);
          } else if (a == 'rename') {
            await renameDialog(context, id);
          } else if (a == 'calibrate') {
            Navigator.push(context, MaterialPageRoute(builder: (_) => NodePage(nodeId: id, calibrate: true)));
          }
        },
        itemBuilder: (_) => const [
          PopupMenuItem(value: 'open', child: Text('Detalji i upravljanje')),
          PopupMenuItem(value: 'rename', child: Text('Preimenuj…')),
          PopupMenuItem(value: 'calibrate', child: Text('Kalibracija praga…')),
        ],
      );
}

Future<void> renameDialog(BuildContext context, String id) async {
  final hub = context.read<HubService>();
  final ctl = TextEditingController(text: ((hub.node(id) ?? {})['name'] as String? ?? '').trim());
  final name = await showDialog<String>(
    context: context,
    builder: (c) => AlertDialog(
      title: const Text('Preimenuj mašinu'),
      content: TextField(controller: ctl, autofocus: true, decoration: InputDecoration(labelText: 'Novo ime za $id')),
      actions: [
        TextButton(onPressed: () => Navigator.pop(c), child: const Text('Otkaži')),
        FilledButton(onPressed: () => Navigator.pop(c, ctl.text.trim()), child: const Text('Sačuvaj')),
      ],
    ),
  );
  if (name == null || name.isEmpty) return;
  final ok = await hub.renameNode(id, name);
  if (ok) {
    hub.addEvent('info', '$id: novo ime „$name”');
  } else if (context.mounted) {
    toast(context, 'Preimenovanje nije uspelo');
  }
}

/// Bottom bar of the desktop overview: overall state | suction + controls | hub | online | updated.
class SummaryCard extends StatefulWidget {
  const SummaryCard({super.key});

  @override
  State<SummaryCard> createState() => _SummaryCardState();
}

class _SummaryCardState extends State<SummaryCard> {
  final _seg = GlobalKey<SegmentedState>();

  Future<void> _relay(HubService hub, String mode) async {
    if (hub.lockout) {
      _seg.currentState?.clearPending();
      toast(context, 'Hub je u ručnom režimu (MANUAL taster). Usisivačem se upravlja sa huba.');
      return;
    }
    const names = {'auto': 'AUTO', 'on': 'ručno UKLJUČEN', 'off': 'ručno ISKLJUČEN'};
    final err = await hub.setRelay(mode);
    if (err == null) {
      hub.addEvent('info', 'Usisivač → ${names[mode]}');
    } else {
      _seg.currentState?.clearPending();
      if (mounted) toast(context, 'Usisivač: $err');
    }
  }

  @override
  Widget build(BuildContext context) {
    final hub = context.watch<HubService>();
    final st = hub.status;
    final nodes = nodesOf(st);
    final online = nodes.where(isOnline).toList();
    final warn = online.where((n) => nodeStatus(n).$2 == 'warning').toList();

    String title, sub, t, ic;
    if (st.isEmpty) {
      (title, sub, t, ic) = ('Hub nije dostupan', 'Tražim hub na mreži…', 'danger', 'alert-circle');
    } else if (hub.lockout) {
      (title, sub, t, ic) = ('Ručni režim na hubu', 'Zatvaračima se upravlja tasterima', 'warning', 'hand-stop');
    } else if (warn.isNotEmpty || online.length < nodes.length) {
      (title, sub, t, ic) = (
        'Potrebna pažnja',
        '${nodes.length - online.length} van mreže, ${warn.length} upozorenje',
        'warning',
        'alert-triangle'
      );
    } else {
      (title, sub, t, ic) = ('Sistem radi normalno', 'Sve mašine su na vezi', 'success', 'circle-check');
    }

    final on = st.isNotEmpty && toInt(st['relayState']) == 1;
    final mode = st.isEmpty ? null : const {0: 'off', 1: 'on'}[toInt(st['relayMode'], 2)] ?? 'auto';

    return BgCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          Ic(ic, tone(t), size: 40),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(title, style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600, color: tone(t))),
              Text(sub, style: tsMuted(13)),
            ]),
          ),
        ]),
        Divider(color: P.border, height: 24),
        Row(children: [
          Ic('wind', on ? tone('success') : P.muted, size: 22),
          const SizedBox(width: 8),
          Text('Usisivač ', style: tsSmall()),
          Text(on ? 'RADI' : (st.isNotEmpty ? 'STOJI' : '—'),
              style: TextStyle(fontSize: 17, fontWeight: FontWeight.w600, color: on ? tone('success') : P.muted)),
          const SizedBox(width: 6),
          if (st.isNotEmpty) Text('· ${relayModeText(st)}', style: tsSmall()),
        ]),
        const SizedBox(height: 8),
        Segmented(
          key: _seg,
          compact: true,
          current: mode,
          enabled: st.isNotEmpty,
          onChosen: (m) => _relay(hub, m),
          options: const [
            SegOption('auto', 'AUTO', 'settings-automation', 'info'),
            SegOption('on', 'UKLJUČI', 'power', 'success'),
            SegOption('off', 'ISKLJUČI', 'player-stop', 'danger'),
          ],
        ),
        Divider(color: P.border, height: 24),
        Row(children: [
          Expanded(
              child: IconValue('server', 'Hub', hubLinkText(st, hub.searching),
                  toneName: st.isNotEmpty ? 'success' : 'danger')),
          Expanded(
              child: IconValue('plug-connected', 'Online', st.isNotEmpty ? '${online.length} / ${nodes.length}' : '—')),
          Expanded(
              child: IconValue('clock', 'Ažurirano', hub.updatedAt != null ? hhmmss(hub.updatedAt!) : '—')),
        ]),
      ]),
    );
  }
}
