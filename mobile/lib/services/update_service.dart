import 'dart:async';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:package_info_plus/package_info_plus.dart';

import 'hub_service.dart';
import 'ota_service.dart';

/// Knows which versions are installed (app, hub) and which are released, and
/// carries out both updates. Checks the release manifest at startup and every
/// few hours; the UI only reads [appUpdate] / [hubUpdate].
class Updater extends ChangeNotifier {
  final HubService hub;
  Updater(this.hub);

  static const _channel = MethodChannel('blastgate/update');
  static const _recheck = Duration(hours: 6);
  final _ota = OtaService();

  String appVersion = '';
  OtaManifest? firmware;
  AppRelease? app;
  DateTime? checkedAt;
  bool checking = false;
  bool checkFailed = false;
  bool appBannerHidden = false;
  bool hubBannerHidden = false;
  File? apk;                 // downloaded and verified, ready to install
  bool downloading = false;
  Timer? _timer;

  String get hubVersion => hub.status['version'] as String? ?? '';

  bool get appUpdate =>
      Platform.isAndroid && app != null && appVersion.isNotEmpty && isNewer(app!.version, appVersion);

  bool get hubUpdate {
    final fw = firmware;
    if (fw == null || hubVersion.isEmpty || !isNewer(fw.version, hubVersion)) return false;
    // A release may require a minimum installed version to update from
    return fw.minPrevVersion.isEmpty || !isNewer(fw.minPrevVersion, hubVersion);
  }

  Future<void> init() async {
    try {
      appVersion = (await PackageInfo.fromPlatform()).version;
    } catch (e) {
      debugPrint('[update] app version unknown: $e');
    }
    notifyListeners();
    Timer(const Duration(seconds: 3), check);
    _timer = Timer.periodic(_recheck, (_) => check());
  }

  /// Fetch the release manifest. Never throws: no internet just means no news.
  Future<void> check() async {
    if (checking) return;
    checking = true;
    notifyListeners();
    try {
      final r = await _ota.fetchReleases(hub.config.otaManifestUrl);
      firmware = r.firmware;
      app = r.app;
      checkFailed = false;
      checkedAt = DateTime.now();
    } catch (e) {
      debugPrint('[update] check failed: $e');
      checkFailed = true;
    }
    checking = false;
    notifyListeners();
    await _afterCheck();
  }

  /// Keep a finished download from an earlier run; fetch the new version in
  /// the background when the network is not metered; drop stale files.
  Future<void> _afterCheck() async {
    if (!Platform.isAndroid) return;
    try {
      final dir = await _updatesDir();
      if (!appUpdate) {
        if (dir.existsSync()) dir.deleteSync(recursive: true);
        apk = null;
        return;
      }
      final ready = File('${dir.path}/blastgate-${app!.version}.apk');
      if (ready.existsSync()) {
        apk = ready;
        notifyListeners();
      } else if (hub.config.autoDownloadUpdates && await _unmetered()) {
        await ensureApk((_) {});
      }
    } catch (e) {
      debugPrint('[update] background download: $e');
    }
  }

  Future<Directory> _updatesDir() async =>
      Directory('${await _channel.invokeMethod<String>('cacheDir')}/updates');

  Future<bool> _unmetered() async => await _channel.invokeMethod<bool>('unmetered') ?? false;

  void hideBanner({required bool forApp}) {
    forApp ? appBannerHidden = true : hubBannerHidden = true;
    notifyListeners();
  }

  // ------------------------------------------------------------- app (APK)

  Future<bool> canInstall() async => await _channel.invokeMethod<bool>('canInstall') ?? false;

  Future<void> openInstallSettings() => _channel.invokeMethod<void>('openInstallSettings');

  /// The APK for this phone, downloaded into the app cache (SHA256 verified
  /// when the manifest has one). Returns at once when it is already there.
  Future<File> ensureApk(void Function(double? fraction) onProgress) async {
    final have = apk;
    if (have != null && have.existsSync()) return have;
    if (downloading) throw Exception('preuzimanje je već u toku');
    downloading = true;
    notifyListeners();
    try {
      apk = await _downloadApk(onProgress);
      return apk!;
    } finally {
      downloading = false;
      notifyListeners();
    }
  }

  Future<File> _downloadApk(void Function(double? fraction) onProgress) async {
    final abis = (await _channel.invokeListMethod<String>('abis')) ?? const <String>[];
    final release = app?.apkFor(abis);
    if (release == null) throw Exception('Izdanje nema instalaciju za ovaj telefon.');

    final dir = await _updatesDir();
    if (dir.existsSync()) dir.deleteSync(recursive: true); // old downloads
    dir.createSync(recursive: true);
    // Written under a temporary name: a file with the final name is always complete
    final part = File('${dir.path}/download.part');

    final req = http.Request('GET', Uri.parse(release.url))..headers['User-Agent'] = 'BlastgateMobile/$appVersion';
    final resp = await req.send().timeout(const Duration(seconds: 30));
    if (resp.statusCode != 200) throw Exception('server je vratio ${resp.statusCode}');
    final total = release.size > 0 ? release.size : (resp.contentLength ?? 0);

    final digest = _DigestSink();
    final hasher = sha256.startChunkedConversion(digest);
    final out = part.openWrite();
    var done = 0;
    try {
      await for (final chunk in resp.stream.timeout(const Duration(seconds: 30))) {
        out.add(chunk);
        hasher.add(chunk);
        done += chunk.length;
        onProgress(total > 0 ? done / total : null);
      }
    } finally {
      await out.close();
    }
    hasher.close();
    if (release.sha256.isNotEmpty && digest.value.toString() != release.sha256) {
      part.deleteSync();
      throw Exception('preuzeta datoteka je oštećena');
    }
    return part.rename('${dir.path}/blastgate-${app!.version}.apk');
  }

  /// Open the system installer; the user confirms there.
  Future<void> installApk(File file) => _channel.invokeMethod<void>('installApk', {'path': file.path});

  // ------------------------------------------------------------- hub (OTA)

  /// Download the firmware, send it to the hub and wait until the hub is back
  /// on the new version. [onStage] gets a stage name and 0..1 progress
  /// (null = no measurable progress).
  Future<void> updateHub(void Function(HubUpdateStage stage, double? fraction) onStage) async {
    final fw = firmware!;
    final ip = hub.config.effectiveHubIp;

    onStage(HubUpdateStage.download, 0);
    final Uint8List bytes;
    try {
      bytes = await _ota.downloadFirmware(fw,
          onProgress: (done, total) => onStage(HubUpdateStage.download, total > 0 ? done / total : null));
    } catch (e) {
      throw HubUpdateError(HubUpdateStage.download, '$e');
    }

    onStage(HubUpdateStage.upload, null);
    try {
      final resp = await _ota.uploadToHub(hubIp: ip, firmware: bytes, token: hub.config.otaToken);
      if (resp['ok'] != true) throw Exception(resp['error'] ?? 'hub je odbio datoteku');
    } catch (e) {
      throw HubUpdateError(HubUpdateStage.upload, '$e');
    }

    onStage(HubUpdateStage.restart, null);
    final ok = await _ota.waitForReboot(hubIp: ip, expectedVersion: fw.version, timeout: const Duration(seconds: 90));
    if (!ok) throw const HubUpdateError(HubUpdateStage.restart, '');
    await hub.fetchStatus();
    notifyListeners();
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }
}

enum HubUpdateStage { download, upload, restart }

class HubUpdateError implements Exception {
  final HubUpdateStage stage;
  final String detail;
  const HubUpdateError(this.stage, this.detail);
}

class _DigestSink implements Sink<Digest> {
  late Digest value;
  @override
  void add(Digest data) => value = data;
  @override
  void close() {}
}
