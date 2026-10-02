// Pumps every screen with a fake hub and fails on any layout exception
// (overflow, missing asset, null error).
//
// With --dart-define=SHOTS=true --update-goldens it also writes each screen
// to test/shots/*.png, to look at the result without a phone:
//   flutter test test/screens_test.dart --dart-define=SHOTS=true --update-goldens
import 'dart:io';

import 'package:blastgate_mobile/models/hub_status.dart';
import 'package:blastgate_mobile/services/hub_service.dart';
import 'package:blastgate_mobile/services/ota_service.dart';
import 'package:blastgate_mobile/services/update_service.dart';
import 'package:blastgate_mobile/ui/add_hub_page.dart';
import 'package:blastgate_mobile/ui/events_page.dart';
import 'package:blastgate_mobile/ui/node_page.dart';
import 'package:blastgate_mobile/ui/overview_page.dart';
import 'package:blastgate_mobile/ui/pair_page.dart';
import 'package:blastgate_mobile/ui/settings_page.dart';
import 'package:blastgate_mobile/ui/system_page.dart';
import 'package:blastgate_mobile/ui/theme.dart';
import 'package:blastgate_mobile/ui/update_page.dart';
import 'package:blastgate_mobile/ui/whats_new.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

const shots = bool.fromEnvironment('SHOTS');

class FakeHub extends HubService {
  bool fakeSearching = false;
  bool fakeSearchedOnce = true;
  List<String> fakeFound = [];

  @override
  bool get searching => fakeSearching;
  @override
  bool get searchedOnce => fakeSearchedOnce;
  @override
  List<String> get foundHubs => fakeFound;
  @override
  Future<WifiInfo?> getWifiInfo() async =>
      WifiInfo(connected: true, ssid: 'Radionica', ip: '192.168.1.119', rssi: -58, provisioningActive: false);
  @override
  Future<void> findHub() async {}
  @override
  Future<void> fetchStatus() async {}
  @override
  Future<bool> renameNode(String nodeId, String newName) async => true;
}

class FakeUpdater extends Updater {
  FakeUpdater(super.hub);
  bool appOffered = false;

  @override
  bool get appUpdate => appOffered; // the real check is Android-only
}

Map<String, dynamic> node(String id, String name, double value, double thr,
        {int online = 1, int active = 0, int mode = 0, int gate = 0, int rssi = -62, int err = 0}) =>
    {
      'id': id,
      'name': name,
      'online': online,
      'active': active,
      'value': value,
      'threshold_on': thr,
      'mode': mode,
      'override': 0,
      'gateState': gate,
      'rssi': rssi,
      'err': err,
      'ageMs': 400,
      'closeInMs': 0,
      'transport': 'espnow',
      'fw': '1.5.0',
      'mac': 'AC:67:B2:A1:00:00',
      'gate_hold_ms': 5000,
      'hbridge_open_ms': 2000,
      'hbridge_close_ms': 2000,
    };

Map<String, dynamic> status({List<Map<String, dynamic>>? nodes, int overdrive = 0, int pairing = 0}) => {
      'protoVer': '1.0',
      'version': '1.5.0',
      'build': 'Oct  2 2026 09:42:57',
      'uptime': 8040,
      'freeHeap': 111000,
      'apIp': '192.168.4.1',
      'staIp': '192.168.1.119',
      'sta': 1,
      'ethLink': 0,
      'manualOverdrive': overdrive,
      'relayState': 1,
      'relayMode': 2,
      'prov': 0,
      'espnow': 1,
      'channel': 1,
      'pairing': pairing,
      'pairedCount': nodes?.length ?? 3,
      'nodes': nodes ??
          [
            node('BG-A10000', 'Cirkular', 63.5, 40, active: 1, gate: 1, rssi: -59),
            node('BG-A11111', 'Abrihter', 5.1, 55, rssi: -64),
            node('BG-A14444', 'Glodalica', 4.9, 45, rssi: -77, err: 1),
          ],
    };

Future<void> loadFonts() async {
  final dir = '${Platform.environment['FLUTTER_ROOT']}/bin/cache/artifacts/material_fonts';
  final loader = FontLoader('Roboto');
  for (final f in ['roboto-regular', 'roboto-medium', 'roboto-bold']) {
    final bytes = File('$dir/$f.ttf').readAsBytesSync();
    loader.addFont(Future.value(ByteData.view(bytes.buffer)));
  }
  await loader.load();
  final icons = FontLoader('MaterialIcons')
    ..addFont(Future.value(ByteData.view(File('$dir/materialicons-regular.otf').readAsBytesSync().buffer)));
  await icons.load();
}

late FakeHub hub;
late FakeUpdater up;

Future<void> show(WidgetTester t, String name, Widget page, {bool scaffold = true}) async {
  t.view.physicalSize = const Size(1080, 2340);
  t.view.devicePixelRatio = 2.75;
  addTearDown(t.view.reset);
  setTheme('dark');
  await t.pumpWidget(MultiProvider(
    providers: [
      ChangeNotifierProvider<HubService>.value(value: hub),
      ChangeNotifierProvider<Updater>.value(value: up),
    ],
    child: MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: buildTheme(),
      home: scaffold ? Scaffold(body: SafeArea(child: page)) : page,
    ),
  ));
  // SVG icons load from the asset bundle with real I/O
  for (var i = 0; i < 4; i++) {
    await t.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 60)));
    await t.pump(const Duration(milliseconds: 100));
  }
  await snap(name);
}

Future<void> snap(String name) async {
  if (shots) await expectLater(find.byType(MaterialApp), matchesGoldenFile('shots/$name.png'));
}

void main() {
  setUpAll(loadFonts);

  setUp(() {
    hub = FakeHub()..debugSetStatus(status());
    up = FakeUpdater(hub)..appVersion = '2.3.0';
  });

  testWidgets('overview: machines', (t) async {
    await show(t, '01_pregled', const OverviewPage());
  });

  testWidgets('overview: updates offered', (t) async {
    up
      ..firmware = OtaManifest(version: '1.5.1', url: 'x', changelog: '- Stabilnija WiFi veza')
      ..app = const AppRelease(version: '2.4.0', changelog: '- Novo', apks: {'universal': ApkFile(url: 'x')})
      ..appOffered = true;
    await show(t, '02_pregled_azuriranja', const OverviewPage());
  });

  testWidgets('overview: hub not found', (t) async {
    hub.debugSetStatus({});
    await show(t, '03_pregled_nema_huba', const OverviewPage());
  });

  testWidgets('overview: several hubs found', (t) async {
    hub
      ..debugSetStatus({})
      ..fakeFound = ['192.168.1.119', '192.168.1.124'];
    await show(t, '04_pregled_vise_hubova', const OverviewPage());
  });

  testWidgets('overview: hub without machines', (t) async {
    hub.debugSetStatus(status(nodes: []));
    await show(t, '05_pregled_bez_masina', const OverviewPage());
  });

  testWidgets('overview: manual mode on the hub', (t) async {
    hub.debugSetStatus(status(overdrive: 1));
    await show(t, '06_pregled_rucni_rezim', const OverviewPage());
  });

  testWidgets('system: state', (t) async {
    await show(t, '10_sistem_stanje', const SystemPage());
  });

  testWidgets('system: wifi', (t) async {
    await show(t, '10_sistem_stanje', const SystemPage());
    await t.tap(find.text('WiFi huba'));
    await t.pumpAndSettle();
    await snap('11_sistem_wifi');
  });

  testWidgets('system: updates', (t) async {
    up
      ..firmware = OtaManifest(version: '1.5.1', url: 'x')
      ..app = const AppRelease(version: '2.3.0')
      ..checkedAt = DateTime(2026, 10, 2, 14, 0, 0);
    await show(t, '10_sistem_stanje', const SystemPage());
    await t.tap(find.text('Ažuriranja'));
    await t.pumpAndSettle();
    await snap('12_sistem_azuriranja');
  });

  testWidgets('settings', (t) async {
    await show(t, '20_podesavanja', const SettingsPage());
    await t.tap(find.text('Napredno'));
    await t.pump(const Duration(milliseconds: 300));
    await snap('21_podesavanja_napredno');
  });

  testWidgets('events', (t) async {
    hub
      ..addEvent('success', 'Hub povezan')
      ..addEvent('info', 'Cirkular: mašina krenula')
      ..addEvent('warning', 'Glodalica: zatvarač nije stigao do krajnjeg prekidača (otvaranje)');
    await show(t, '30_dogadjaji', const EventsPage());
  });

  testWidgets('machine page', (t) async {
    await show(t, '40_masina', const NodePage(nodeId: 'BG-A10000'), scaffold: false);
  });

  testWidgets('update page: hub', (t) async {
    up.firmware = OtaManifest(
        version: '1.5.1', url: 'x', changelog: '- WiFi mreža huba se ponovo vidi\n- Dodavanje huba preko Bluetooth-a');
    await show(t, '50_azuriranje_hub', const UpdatePage(UpdateKind.hub), scaffold: false);
  });

  testWidgets('update page: app', (t) async {
    up.app = const AppRelease(version: '2.4.0', changelog: '- Brže pronalaženje huba');
    await show(t, '51_azuriranje_aplikacija', const UpdatePage(UpdateKind.app), scaffold: false);
  });

  testWidgets('add machine: pair, name, threshold', (t) async {
    await show(t, '70_dodaj_masinu', PairPage(startPairing: (_) async {}), scaffold: false);
    await t.tap(find.text('Počni'));
    await t.pump(const Duration(milliseconds: 100));
    expect(find.textContaining('Hub čeka još'), findsOneWidget);
    await snap('71_dodaj_masinu_ceka');

    // A machine that was not there before comes online
    final st = status();
    (st['nodes'] as List).add(node('BG-B20000', '', 3.2, 40));
    hub.debugSetStatus(st);
    await t.pump(const Duration(seconds: 1));
    await t.pump(const Duration(milliseconds: 100));
    expect(find.text('Mašina je uparena'), findsOneWidget);
    await t.enterText(find.byType(TextField), 'Tračna testera');
    await t.pump(const Duration(milliseconds: 400)); // label float animation
    await snap('72_dodaj_masinu_ime');

    await t.tap(find.text('Dalje'));
    await t.pump(const Duration(milliseconds: 100));
    expect(find.text('Kalibriši sada'), findsOneWidget);
    await snap('73_dodaj_masinu_prag');
  });

  testWidgets('add machine: nobody answers', (t) async {
    await show(t, '70_dodaj_masinu', PairPage(startPairing: (_) async {}), scaffold: false);
    await t.tap(find.text('Počni'));
    await t.pump(const Duration(milliseconds: 100));
    for (var i = 0; i < 61; i++) {
      await t.pump(const Duration(seconds: 1));
    }
    expect(find.text('Nijedna mašina se nije javila'), findsOneWidget);
    await snap('74_dodaj_masinu_niko');
  });

  testWidgets('what is new', (t) async {
    await show(t, '80_sta_je_novo', const Align(alignment: Alignment.bottomCenter, child: Material(child: WhatsNewSheet())));
  });

  testWidgets('settings: factory hub password is flagged', (t) async {
    await show(t, '20_podesavanja', const SettingsPage());
    expect(find.text('Postavi šifru huba'), findsOneWidget);
  });

  testWidgets('add hub: desktop fallback', (t) async {
    await show(t, '60_dodaj_hub', const AddHubPage(), scaffold: false);
  });
}
