import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'services/hub_service.dart';
import 'ui/events_page.dart';
import 'ui/icons.dart';
import 'ui/overview_page.dart';
import 'ui/settings_page.dart';
import 'ui/system_page.dart';
import 'ui/theme.dart';

void main() {
  runApp(
    ChangeNotifierProvider(
      create: (_) => HubService()..init(),
      child: const BlastgateApp(),
    ),
  );
}

class BlastgateApp extends StatelessWidget {
  const BlastgateApp({super.key});

  @override
  Widget build(BuildContext context) {
    // Rebuild the whole app when the theme setting changes (config is loaded async)
    final themeName = context.select<HubService, String>((h) => h.config.theme);
    setTheme(themeName);
    return MaterialApp(
      title: 'Blastgate',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(),
      home: const Shell(),
    );
  }
}

/// Same four sections as the desktop sidebar, as a bottom navigation bar.
class Shell extends StatefulWidget {
  const Shell({super.key});

  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  static const _nav = [('Pregled', 'home'), ('Sistem', 'list-details'), ('Događaji', 'bell'), ('Podešavanja', 'settings')];
  int _idx = 0;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        titleSpacing: 16,
        title: Row(children: [
          Ic('layout-grid', P.accent, size: 24),
          const SizedBox(width: 10),
          Text('BLASTGATE',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700, letterSpacing: 0.5, color: P.text)),
        ]),
      ),
      body: SafeArea(
        top: false,
        child: IndexedStack(
          index: _idx,
          children: const [OverviewPage(), SystemPage(), EventsPage(), SettingsPage()],
        ),
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _idx,
        onDestinationSelected: (i) => setState(() => _idx = i),
        destinations: [
          for (final (text, icon) in _nav)
            NavigationDestination(
              icon: Ic(icon, P.muted, size: 24),
              selectedIcon: Ic(icon, P.accent, size: 24),
              label: text,
            ),
        ],
      ),
    );
  }
}
