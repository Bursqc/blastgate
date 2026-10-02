import 'package:blastgate_mobile/ui/state.dart';
import 'package:flutter_test/flutter_test.dart';

// Mirrors desktop_qt/tests/test_ui_state.py for the shared display logic.
void main() {
  test('node status tones', () {
    expect(nodeStatus({'online': 0}), ('OFFLINE', 'danger'));
    expect(nodeStatus({'online': 1, 'err': 1}), ('UPOZORENJE', 'warning'));
    expect(nodeStatus({'online': 1, 'err': 8, 'active': 0}), ('MIRUJE', 'idle')); // calibrating is normal
    expect(nodeStatus({'online': 1, 'active': 1}), ('RADI', 'success'));
  });

  test('gate open from old and new firmware fields', () {
    expect(gateOpen({'gateState': 2}), isTrue);
    expect(gateOpen({'gateState': 3}), isFalse);
    expect(gateOpen({'gateOpen': 1}), isTrue);
    expect(gateOpen({'override': 1}), isTrue);
    expect(gateText({'online': 1, 'gateOpen': 1, 'closeInMs': 4200}), 'Zatvara za 4 s');
    expect(gateText({'online': 0, 'gateOpen': 1}), '—');
  });

  test('signal bars and texts', () {
    expect(signalBars(null), 0);
    expect(signalBars(-55), 4);
    expect(signalBars(-75), 2);
    expect(signalText({'online': 1, 'rssi': -64}), '-64 dBm');
    expect(signalIcon({'online': 1}), 'antenna-bars-off');
  });

  test('hold conversions and bar scale', () {
    expect(holdMsToS(5000), 5.0);
    expect(holdMsToS(1250), 1.3);
    expect(holdSToMs(2.5), 2500);
    expect(barMax(10, 40), 80);
    expect(barMax(100, 40), closeTo(110, 1e-9));
  });

  test('diff events', () {
    final t = DateTime(2026, 9, 29);
    expect(diffEvents({}, {'nodes': []}, t).single.text, 'Hub povezan');
    final prev = {
      'relayState': 0,
      'nodes': [
        {'id': 'A', 'name': 'Cirkular', 'online': 1, 'active': 0, 'gateOpen': 0},
      ],
    };
    final cur = {
      'relayState': 1,
      'nodes': [
        {'id': 'A', 'name': 'Cirkular', 'online': 1, 'active': 1, 'gateOpen': 1, 'err': 2},
        {'id': 'B', 'online': 1},
      ],
    };
    final texts = diffEvents(prev, cur, t).map((e) => e.text).toList();
    expect(texts, [
      'Usisivač uključen',
      'Cirkular: mašina krenula',
      'Cirkular: zatvarač otvoren',
      'Cirkular: ${errTextsMap[2]}',
      'B: nova mašina se javila',
    ]);
  });

  test('machine count in Serbian', () {
    expect(machinesText(1), '1 mašina');
    expect(machinesText(3), '3 mašine');
    expect(machinesText(5), '5 mašina');
    expect(machinesText(12), '12 mašina');
    expect(machinesText(22), '22 mašine');
  });

  test('events survive a save and load', () {
    final e = HubEvent(DateTime(2026, 10, 2, 14, 5, 9), 'warning', 'Glodalica: van mreže');
    final back = HubEvent.fromJson(e.toJson());
    expect(back.time, e.time);
    expect(back.tone, 'warning');
    expect(back.text, 'Glodalica: van mreže');
  });
}
