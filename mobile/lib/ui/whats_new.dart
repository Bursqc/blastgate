import 'package:flutter/material.dart' hide Badge, Banner;
import 'package:shared_preferences/shared_preferences.dart';

import 'icons.dart';
import 'theme.dart';
import 'widgets.dart';

/// Shown once after the app is updated to this version. Keep it to what the
/// user will notice, in the user's words.
const whatsNewVersion = '2.4.0';
const whatsNew = <(String, String, String)>[
  ('download', 'Ažuriranja stižu sama', 'Nova verzija se preuzme na WiFi-ju. Ti samo potvrdiš instalaciju.'),
  ('link', 'Dodaj mašinu u tri koraka', 'Uparivanje, ime i prag — jedno za drugim, na Pregledu.'),
  ('trash', 'Ukloni mašinu', 'Mašinu koju više ne koristiš uklanjaš iz njenog menija.'),
  ('wifi', 'WiFi huba bez nagađanja', 'Izabereš mrežu, ukucaš šifru; aplikacija kaže da li se hub povezao.'),
  ('bell', 'Događaji ostaju sačuvani', 'Istorija se više ne briše kad zatvoriš aplikaciju.'),
];

/// Existing users see the sheet once per [whatsNewVersion]; a fresh install does not.
Future<void> maybeShowWhatsNew(BuildContext context) async {
  final prefs = await SharedPreferences.getInstance();
  if (prefs.getString('whats_new_seen') == whatsNewVersion) return;
  await prefs.setString('whats_new_seen', whatsNewVersion);
  final existingUser = prefs.containsKey('blastgate_config');
  if (!existingUser || !context.mounted) return;
  await showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    builder: (_) => const WhatsNewSheet(),
  );
}

class WhatsNewSheet extends StatelessWidget {
  const WhatsNewSheet({super.key});

  @override
  Widget build(BuildContext context) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 20, 20, 16),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Text('Šta je novo', style: tsTitle(22)),
            Text('Blastgate $whatsNewVersion', style: tsMuted(13)),
            const SizedBox(height: 16),
            for (final (icon, title, text) in whatsNew)
              Padding(
                padding: const EdgeInsets.only(bottom: 14),
                child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Container(
                    width: 40,
                    height: 40,
                    alignment: Alignment.center,
                    decoration: BoxDecoration(color: P.navActive, borderRadius: BorderRadius.circular(10)),
                    child: Ic(icon, P.accent, size: 22),
                  ),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(title, style: TextStyle(fontSize: 15.5, fontWeight: FontWeight.w600, color: P.text)),
                      const SizedBox(height: 2),
                      Text(text, style: tsMuted(13)),
                    ]),
                  ),
                ]),
              ),
            const SizedBox(height: 4),
            Btn('U redu', variant: 'primary', expand: true, onTap: () => Navigator.pop(context)),
          ]),
        ),
      );
}
