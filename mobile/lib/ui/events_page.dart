import 'package:flutter/material.dart' hide Badge, Banner;
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../services/hub_service.dart';
import 'icons.dart';
import 'state.dart';
import 'theme.dart';
import 'widgets.dart';

const toneText = {'success': 'OK', 'warning': 'PAŽNJA', 'danger': 'GREŠKA', 'info': 'INFO', 'idle': 'INFO'};

String toneIcon(String t) => switch (t) {
      'success' => 'circle-check',
      'warning' => 'alert-triangle',
      'danger' => 'alert-circle',
      _ => 'info-circle',
    };

String _stamp(DateTime t) =>
    '${t.day.toString().padLeft(2, '0')}.${t.month.toString().padLeft(2, '0')}. ${hhmmss(t)}';

/// Događaji — what happened (derived from status changes + own commands). Port of events_page.py.
class EventsPage extends StatefulWidget {
  const EventsPage({super.key});

  @override
  State<EventsPage> createState() => _EventsPageState();
}

class _EventsPageState extends State<EventsPage> {
  String _q = '';

  @override
  Widget build(BuildContext context) {
    final hub = context.watch<HubService>();
    final evs = hub.events.reversed.where((e) => _q.isEmpty || e.text.toLowerCase().contains(_q)).toList();

    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      const PageHeader('Događaji', 'Poslednjih 500 događaja. Ostaju sačuvani i kad zatvoriš aplikaciju.'),
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 10),
        child: Row(children: [
          Expanded(
            child: TextField(
              onChanged: (v) => setState(() => _q = v.trim().toLowerCase()),
              decoration: InputDecoration(
                hintText: 'Pretraži događaje…',
                prefixIcon: Padding(padding: const EdgeInsets.all(12), child: Ic('search', P.muted, size: 18)),
              ),
            ),
          ),
          const SizedBox(width: 8),
          IconButton(
            tooltip: 'Kopiraj kao tekst',
            icon: Ic('file-export', P.accent),
            onPressed: () async {
              final txt = hub.events
                  .map((e) => '${e.time.toIso8601String().substring(0, 19)}\t${toneText[e.tone] ?? 'INFO'}\t${e.text}')
                  .join('\n');
              await Clipboard.setData(ClipboardData(text: txt));
              if (context.mounted) toast(context, 'Događaji kopirani (${hub.events.length})');
            },
          ),
          IconButton(tooltip: 'Očisti', icon: Ic('trash', P.muted), onPressed: hub.clearEvents),
        ]),
      ),
      Expanded(
        child: evs.isEmpty
            ? Center(child: Text('Nema događaja.', style: tsMuted()))
            : ListView.separated(
                padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
                itemCount: evs.length,
                separatorBuilder: (_, _) => Divider(color: P.border, height: 1),
                itemBuilder: (_, i) {
                  final e = evs[i];
                  return Padding(
                    padding: const EdgeInsets.symmetric(vertical: 10),
                    child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Ic(toneIcon(e.tone), tone(e.tone), size: 18),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Text(e.text, style: TextStyle(color: P.text, fontSize: 14)),
                          const SizedBox(height: 2),
                          Text('${_stamp(e.time)}  ·  ${toneText[e.tone] ?? 'INFO'}',
                              style: TextStyle(color: tone(e.tone == 'idle' ? 'muted' : e.tone), fontSize: 11.5)),
                        ]),
                      ),
                    ]),
                  );
                },
              ),
      ),
    ]);
  }
}
