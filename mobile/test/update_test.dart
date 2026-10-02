import 'dart:convert';

import 'package:blastgate_mobile/services/ota_service.dart';
import 'package:flutter_test/flutter_test.dart';

const _manifest = '''
{
  "version": "1.5.1",
  "url": "https://example.invalid/firmware.bin",
  "size": 1955824,
  "sha256": "AB12",
  "minPrevVersion": "1.2.0",
  "changelog": "fw notes",
  "app": {
    "version": "2.3.0",
    "changelog": "app notes",
    "apks": {
      "arm64-v8a": {"url": "https://example.invalid/arm64.apk", "size": 20, "sha256": "CD34"},
      "universal": {"url": "https://example.invalid/all.apk"}
    }
  }
}
''';

void main() {
  test('isNewer compares numerically and ignores build suffixes', () {
    expect(isNewer('2.3.0', '2.2.1'), isTrue);
    expect(isNewer('2.10.0', '2.9.9'), isTrue);
    expect(isNewer('2.3.0', '2.3.0'), isFalse);
    expect(isNewer('2.3.0+5', '2.3.0+4'), isFalse);
    expect(isNewer('1.4.3', '1.5.0'), isFalse);
  });

  test('firmware part of the manifest keeps the old top-level layout', () {
    final fw = OtaManifest.fromJson(jsonDecode(_manifest) as Map<String, dynamic>);
    expect(fw.version, '1.5.1');
    expect(fw.sha256, 'ab12');
    expect(fw.minPrevVersion, '1.2.0');
  });

  test('app release picks the APK for the phone, else the universal one', () {
    final json = jsonDecode(_manifest) as Map<String, dynamic>;
    final app = AppRelease.fromJson(Map<String, dynamic>.from(json['app'] as Map));
    expect(app.version, '2.3.0');
    expect(app.apkFor(['arm64-v8a', 'armeabi-v7a'])!.url, endsWith('arm64.apk'));
    expect(app.apkFor(['arm64-v8a'])!.sha256, 'cd34');
    expect(app.apkFor(['x86_64'])!.url, endsWith('all.apk'));
    expect(const AppRelease(version: '1.0.0').apkFor(['arm64-v8a']), isNull);
  });

  test('a manifest without an app section is still valid', () {
    final json = jsonDecode('{"version":"1.4.3","url":"https://example.invalid/f.bin"}') as Map<String, dynamic>;
    expect(OtaManifest.fromJson(json).version, '1.4.3');
    expect(json['app'], isNull);
  });
}
