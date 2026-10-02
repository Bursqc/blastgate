import 'package:flutter/material.dart' hide Badge, Banner;
import 'package:provider/provider.dart';

import '../services/hub_http.dart';
import '../services/hub_service.dart';
import '../services/update_service.dart';
import 'icons.dart';
import 'add_hub_page.dart';
import 'node_page.dart';
import 'pair_page.dart';
import 'state.dart';
import 'theme.dart';
import 'update_page.dart';
import 'widgets.dart';

/// Pregled — machine tiles + system bar (suction, hub, counts). Port of overview_page.py.
class OverviewPage extends StatelessWidget {
  const OverviewPage({super.key});

  @override
  Widget build(BuildContext context) {
    final hub = context.watch<HubService>();
    final up = context.watch<Updater>();
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
    if (st.isNotEmpty && hub.lockout) {
      banner = const Banner(
          'Hub je u RUČNOM REŽIMU (MANUAL taster). Svi zatvarači su zatvoreni; otvaraju se tasterima na '
          'mašinama. Hub sam izlazi iz ovog režima kad neka mašina krene.',
          toneName: 'warning',
          icon: 'hand-stop');
    }

    String? empty;
    if (shown.isEmpty && nodes.isNotEmpty) {
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
              if (nodes.isNotEmpty) ...[
                Text(machinesText(nodes.length), style: tsMuted(13)),
                for (final k in ['success', 'warning', 'danger']) ...[
                  const SizedBox(width: 10),
                  Dot(k),
                  const SizedBox(width: 4),
                  Text('${counts[k]}', style: TextStyle(color: P.text, fontSize: 13)),
                ],
              ],
            ]),
          ),
          if (up.appUpdate && !up.appBannerHidden)
            const Padding(padding: EdgeInsets.fromLTRB(16, 0, 16, 12), child: UpdateStrip(UpdateKind.app)),
          if (st.isNotEmpty && up.hubUpdate && !up.hubBannerHidden)
            const Padding(padding: EdgeInsets.fromLTRB(16, 0, 16, 12), child: UpdateStrip(UpdateKind.hub)),
          if (banner != null) Padding(padding: const EdgeInsets.fromLTRB(16, 0, 16, 12), child: banner),
          if (st.isEmpty) const Padding(padding: EdgeInsets.fromLTRB(16, 0, 16, 12), child: NoHubCard()),
          if (st.isNotEmpty) const Padding(padding: EdgeInsets.fromLTRB(16, 0, 16, 12), child: SummaryCard()),
          for (final n in shown)
            Padding(padding: const EdgeInsets.fromLTRB(16, 0, 16, 12), child: NodeTile(n)),
          if (empty != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(32, 24, 32, 12),
              child: Text(empty, textAlign: TextAlign.center, style: tsMuted()),
            ),
          if (st.isNotEmpty && nodes.isEmpty)
            const Padding(padding: EdgeInsets.fromLTRB(16, 0, 16, 12), child: PairCard()),
          if (nodes.isNotEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 0),
              child: Btn('Dodaj mašinu', icon: 'link', variant: 'outline', expand: true, onTap: () => openPairing(context)),
            ),
        ],
      ),
    );
  }
}

/// Shown instead of the machines while no hub answers: what is wrong and what to do.
class NoHubCard extends StatelessWidget {
  const NoHubCard({super.key});

  @override
  Widget build(BuildContext context) {
    final hub = context.watch<HubService>();
    void addHub() => Navigator.push(context, MaterialPageRoute(builder: (_) => const AddHubPage()));

    if (hub.foundHubs.length > 1) {
      return Section('Pronađeno je više hubova', [
        Text('Izaberi hub kojim želiš da upravljaš.', style: tsMuted(13)),
        const SizedBox(height: 10),
        for (final ip in hub.foundHubs)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Btn('Hub na adresi $ip', icon: 'server', variant: 'outline', expand: true,
                onTap: () => hub.selectHub(ip)),
          ),
      ], inset: false);
    }

    if (!hub.searchedOnce) {
      return BgCard(
        child: Row(children: [
          const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.5)),
          const SizedBox(width: 14),
          Expanded(child: Text('Tražim hub na mreži…', style: tsMid())),
        ]),
      );
    }

    return BgCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          Ic('wifi-off', tone('danger'), size: 36),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('Hub nije pronađen', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600, color: P.text)),
              Text(hub.searching ? 'Tražim ponovo…' : 'Aplikacija ga sama traži svakih 15 sekundi.', style: tsSmall()),
            ]),
          ),
        ]),
        const SizedBox(height: 12),
        Text('Proveri dve stvari:\n1. Hub je uključen.\n2. Telefon je na istoj WiFi mreži kao hub.', style: tsMuted()),
        const SizedBox(height: 14),
        Btn('Traži ponovo', icon: 'search', variant: 'primary', expand: true, onTap: hub.searching ? null : hub.findHub),
        const SizedBox(height: 14),
        Text('Hub je nov ili resetovan? Dodaj ga preko Bluetooth-a.', style: tsMuted(13)),
        const SizedBox(height: 8),
        Btn('Dodaj novi hub', icon: 'access-point', variant: 'outline', expand: true, onTap: addHub),
      ]),
    );
  }
}

/// Hub is connected but has no machines yet.
class PairCard extends StatelessWidget {
  const PairCard({super.key});

  @override
  Widget build(BuildContext context) => BgCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Center(child: Ic('link', P.accent, size: 44)),
          const SizedBox(height: 10),
          Text('Još nema mašina', textAlign: TextAlign.center, style: tsSection()),
          const SizedBox(height: 4),
          Text('Dodaj prvu mašinu — aplikacija te vodi kroz uparivanje, ime i prag.',
              textAlign: TextAlign.center, style: tsMuted(13)),
          const SizedBox(height: 14),
          Btn('Dodaj mašinu', icon: 'link', variant: 'primary', expand: true, onTap: () => openPairing(context)),
        ]),
      );
}

void openPairing(BuildContext context) =>
    Navigator.push(context, MaterialPageRoute(builder: (_) => const PairPage()));

/// Ask, then remove the machine from the hub. True when it was removed.
Future<bool> removeNodeDialog(BuildContext context, String id) async {
  final hub = context.read<HubService>();
  final n = hub.node(id);
  final name = n != null ? nodeName(n) : id;
  if (!await confirm(
      context,
      'Ukloni mašinu',
      'Ukloniti „$name" sa huba?\n\n'
          'Hub prestaje da je sluša i briše joj ime. Vraćaš je preko „Dodaj mašinu".',
      ok: 'Ukloni')) {
    return false;
  }
  try {
    await hub.removeNode(id);
    hub.addEvent('info', 'Mašina uklonjena: $name');
    if (context.mounted) toast(context, '„$name" je uklonjena.');
    return true;
  } on HubRejected {
    if (context.mounted) toast(context, 'Hub ne može da ukloni ovu mašinu: nije uparena sa njim.');
  } catch (e) {
    if (context.mounted) toast(context, 'Uklanjanje nije uspelo: $e');
  }
  return false;
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
          } else if (a == 'remove') {
            await removeNodeDialog(context, id);
          }
        },
        itemBuilder: (_) => const [
          PopupMenuItem(value: 'open', child: Text('Detalji i upravljanje')),
          PopupMenuItem(value: 'rename', child: Text('Preimenuj…')),
          PopupMenuItem(value: 'calibrate', child: Text('Kalibracija praga…')),
          PopupMenuItem(value: 'remove', child: Text('Ukloni mašinu…')),
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

/// Overall state + suction control, above the machines (the desktop app has it as a bottom bar).
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
      (title, sub, t, ic) = ('Hub nije dostupan', 'Upravljanje nije moguće dok se hub ne pronađe', 'danger', 'alert-circle');
    } else if (nodes.isEmpty) {
      (title, sub, t, ic) = ('Hub je spreman', 'Još nema dodatih mašina', 'info', 'info-circle');
    } else if (hub.lockout) {
      (title, sub, t, ic) = ('Ručni režim na hubu', 'Zatvaračima se upravlja tasterima', 'warning', 'hand-stop');
    } else if (warn.isNotEmpty || online.length < nodes.length) {
      (title, sub, t, ic) = (
        'Potrebna pažnja',
        [
          if (online.length < nodes.length) '${nodes.length - online.length} van mreže',
          if (warn.isNotEmpty) '${warn.length} sa upozorenjem',
        ].join(', '),
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
          Ic(ic, tone(t), size: 34),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(title, style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600, color: tone(t))),
              Text(sub, style: tsMuted(13)),
            ]),
          ),
        ]),
        Divider(color: P.border, height: 20),
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
      ]),
    );
  }
}
