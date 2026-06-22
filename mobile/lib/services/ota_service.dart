import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

/// Parsed response from hub GET /version.
class HubVersion {
  final String version;
  final String build;
  final int uptime;
  final int freeHeap;
  final String protoVer;
  final String chipModel;
  final String otaPartition;

  HubVersion({
    required this.version,
    required this.build,
    required this.uptime,
    required this.freeHeap,
    required this.protoVer,
    this.chipModel = '',
    this.otaPartition = '',
  });

  factory HubVersion.fromJson(Map<String, dynamic> json) {
    return HubVersion(
      version: (json['version'] as String?) ?? '0.0.0',
      build: (json['build'] as String?) ?? '',
      uptime: (json['uptime'] as num?)?.toInt() ?? 0,
      freeHeap: (json['freeHeap'] as num?)?.toInt() ?? 0,
      protoVer: (json['protoVer'] as String?) ?? '?',
      chipModel: (json['chipModel'] as String?) ?? '',
      otaPartition: (json['otaPartition'] as String?) ?? '',
    );
  }
}

/// Parsed release manifest fetched from the update server.
class OtaManifest {
  final String version;
  final String url;
  final int size;
  final String sha256;
  final String minPrevVersion;
  final String changelog;

  OtaManifest({
    required this.version,
    required this.url,
    this.size = 0,
    this.sha256 = '',
    this.minPrevVersion = '',
    this.changelog = '',
  });

  factory OtaManifest.fromJson(Map<String, dynamic> json) {
    return OtaManifest(
      version: json['version'] as String,
      url: json['url'] as String,
      size: (json['size'] as num?)?.toInt() ?? 0,
      sha256: ((json['sha256'] as String?) ?? '').toLowerCase(),
      minPrevVersion: (json['minPrevVersion'] as String?) ?? '',
      changelog: (json['changelog'] as String?) ?? '',
    );
  }
}

/// Strips '-rc1' / '+build5' and pads to 3 parts.
List<int> _semverTuple(String v) {
  final core = v.split('-').first.split('+').first;
  final parts = core.split('.');
  final out = <int>[];
  for (final p in parts) {
    out.add(int.tryParse(p) ?? 0);
  }
  while (out.length < 3) {
    out.add(0);
  }
  return out.take(3).toList();
}

bool isNewer(String remote, String current) {
  final a = _semverTuple(remote);
  final b = _semverTuple(current);
  for (var i = 0; i < 3; i++) {
    if (a[i] != b[i]) return a[i] > b[i];
  }
  return false;
}

/// OTA progress callback. Total may be 0 if unknown.
typedef OtaProgressCb = void Function(int done, int total);

/// OTA client for Blastgate hub.
/// Hub firmware exposes /version (GET) and /ota (POST multipart) on port 80.
/// See firmware/hub-wt32/src/main.cpp for the matching server side.
class OtaService {
  static const _hubTimeout = Duration(seconds: 5);
  static const _manifestTimeout = Duration(seconds: 10);
  static const _downloadTimeout = Duration(seconds: 90);
  static const _uploadTimeout = Duration(seconds: 120);

  /// GET http://<hub>/version
  Future<HubVersion> fetchCurrentVersion(String hubIp) async {
    final url = Uri.parse('http://$hubIp/version');
    final resp = await http.get(url).timeout(_hubTimeout);
    if (resp.statusCode != 200) {
      throw Exception('hub /version returned ${resp.statusCode}');
    }
    return HubVersion.fromJson(jsonDecode(resp.body) as Map<String, dynamic>);
  }

  /// GET manifest.json from update server.
  Future<OtaManifest> fetchRemoteManifest(String manifestUrl) async {
    final resp = await http
        .get(Uri.parse(manifestUrl), headers: {'User-Agent': 'BlastgateMobile/1.0'})
        .timeout(_manifestTimeout);
    if (resp.statusCode != 200) {
      throw Exception('manifest returned ${resp.statusCode}');
    }
    return OtaManifest.fromJson(jsonDecode(resp.body) as Map<String, dynamic>);
  }

  /// Stream firmware.bin into RAM (ESP32 firmware is ~1.5 MB — fine on mobile).
  /// Verifies SHA256 if manifest.sha256 is non-empty.
  Future<Uint8List> downloadFirmware(
    OtaManifest manifest, {
    OtaProgressCb? onProgress,
  }) async {
    final req = http.Request('GET', Uri.parse(manifest.url));
    req.headers['User-Agent'] = 'BlastgateMobile/1.0';
    final streamed = await req.send().timeout(_downloadTimeout);
    final total = manifest.size > 0
        ? manifest.size
        : (streamed.contentLength ?? 0);

    final builder = BytesBuilder(copy: false);
    var done = 0;
    await for (final chunk in streamed.stream) {
      builder.add(chunk);
      done += chunk.length;
      if (onProgress != null) onProgress(done, total);
    }
    final bytes = builder.toBytes();

    if (manifest.sha256.isNotEmpty) {
      final got = sha256.convert(bytes).toString();
      if (got != manifest.sha256) {
        throw Exception('SHA256 mismatch: got $got, expected ${manifest.sha256}');
      }
    }
    debugPrint('[OTA] downloaded ${bytes.length} bytes');
    return bytes;
  }

  /// POST firmware to http://<hub>/ota as multipart/form-data with X-OTA-Token.
  /// Returns parsed JSON response. Hub reboots on success.
  Future<Map<String, dynamic>> uploadToHub({
    required String hubIp,
    required Uint8List firmware,
    required String token,
    OtaProgressCb? onProgress,
  }) async {
    final url = Uri.parse('http://$hubIp/ota');
    final req = http.MultipartRequest('POST', url);
    req.headers['X-OTA-Token'] = token;
    req.headers['User-Agent'] = 'BlastgateMobile/1.0';
    req.files.add(http.MultipartFile.fromBytes(
      'firmware',
      firmware,
      filename: 'firmware.bin',
    ));

    if (onProgress != null) onProgress(0, firmware.length);
    final streamed = await req.send().timeout(_uploadTimeout);
    final body = await streamed.stream.bytesToString();
    if (onProgress != null) onProgress(firmware.length, firmware.length);

    if (streamed.statusCode != 200) {
      throw Exception('hub /ota returned ${streamed.statusCode}: $body');
    }
    try {
      return jsonDecode(body) as Map<String, dynamic>;
    } catch (_) {
      return {'ok': false, 'error': 'non-json response', 'raw': body};
    }
  }

  /// Poll /version until expectedVersion appears or timeout.
  /// Hub typically takes 5-10s to reboot and rejoin the network.
  Future<bool> waitForReboot({
    required String hubIp,
    required String expectedVersion,
    Duration timeout = const Duration(seconds: 60),
    Duration interval = const Duration(seconds: 2),
  }) async {
    final deadline = DateTime.now().add(timeout);
    while (DateTime.now().isBefore(deadline)) {
      try {
        final v = await fetchCurrentVersion(hubIp).timeout(const Duration(seconds: 2));
        if (v.version == expectedVersion) return true;
      } on TimeoutException catch (_) {
        // hub still down
      } on SocketException catch (_) {
        // hub still down
      } catch (_) {
        // any error during reboot window — keep polling
      }
      await Future.delayed(interval);
    }
    return false;
  }

  /// Convenience: fetch hub version + manifest in parallel.
  /// Manifest may be null if the server can't be reached (no internet).
  Future<({HubVersion hub, OtaManifest? manifest})> checkAndGetUpdate({
    required String hubIp,
    required String manifestUrl,
  }) async {
    final hubVer = await fetchCurrentVersion(hubIp);
    OtaManifest? m;
    try {
      m = await fetchRemoteManifest(manifestUrl);
    } catch (e) {
      debugPrint('[OTA] manifest fetch failed: $e');
    }
    return (hub: hubVer, manifest: m);
  }
}
