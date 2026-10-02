import 'dart:async';
import 'dart:convert';
import 'dart:io';

/// The hub did not accept the connection: the request was never sent.
class HubUnreachable implements Exception {
  const HubUnreachable();
  @override
  String toString() => 'Hub nije dostupan.';
}

/// The hub answered, but refused the request (HTTP status other than 200).
class HubRejected implements Exception {
  final int status;
  const HubRejected(this.status);
  @override
  String toString() => 'Hub je odbio zahtev ($status).';
}

/// HTTP calls to the hub (port 80) used by the UI: WiFi scan/set/forget.
/// Port of desktop_qt/blastgate/hub_http.py. Hub OTA stays in ota_service.dart.
class HubHttp {
  static const _ua = 'BlastgateApp/2.1';

  static Future<List<Map<String, dynamic>>> wifiScan(String ip) async {
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 8);
    try {
      final req = await client.getUrl(Uri.parse('http://$ip/wifi_scan')).timeout(const Duration(seconds: 8));
      req.headers.set('User-Agent', _ua);
      final resp = await req.close().timeout(const Duration(seconds: 10));
      final body = await resp.transform(utf8.decoder).join();
      final list = (jsonDecode(body) as List).cast<Map<String, dynamic>>();
      return list.where((n) => (n['ssid'] as String? ?? '').isNotEmpty).toList();
    } finally {
      client.close(force: true);
    }
  }

  /// POST JSON; the hub restarts right after answering, so a dropped
  /// connection after sending counts as saved (same as desktop).
  /// Not reaching the hub at all (no connection) throws — nothing was sent.
  static Future<void> _post(String ip, String path, Map<String, dynamic> body) async {
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 8);
    int? status;
    try {
      final HttpClientRequest req;
      try {
        req = await client.postUrl(Uri.parse('http://$ip$path')).timeout(const Duration(seconds: 8));
      } catch (_) {
        throw const HubUnreachable();
      }
      req.headers.set('User-Agent', _ua);
      req.headers.contentType = ContentType.json;
      final bytes = utf8.encode(jsonEncode(body));
      req.contentLength = bytes.length;
      req.add(bytes);
      final resp = await req.close().timeout(const Duration(seconds: 8));
      status = resp.statusCode;
      await resp.drain<void>();
    } on SocketException {
      // hub restarted
    } on HttpException {
      // hub restarted
    } on TimeoutException {
      // hub restarted
    } finally {
      client.close(force: true);
    }
    if (status != null && status != 200) throw HubRejected(status);
  }

  /// GET /status as JSON, or null when the hub does not answer.
  static Future<Map<String, dynamic>?> status(String ip) async {
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 3);
    try {
      final req = await client.getUrl(Uri.parse('http://$ip/status')).timeout(const Duration(seconds: 3));
      req.headers.set('User-Agent', _ua);
      final resp = await req.close().timeout(const Duration(seconds: 3));
      final body = await resp.transform(utf8.decoder).join().timeout(const Duration(seconds: 3));
      return resp.statusCode == 200 ? jsonDecode(body) as Map<String, dynamic> : null;
    } catch (_) {
      return null;
    } finally {
      client.close(force: true);
    }
  }

  static Future<void> wifiSet(String ip, String ssid, String pass) =>
      _post(ip, '/wifi_set', {'ssid': ssid, 'pass': pass});

  static Future<void> wifiForget(String ip) => _post(ip, '/wifi_forget', {});

  /// Open the 60 s pairing window on the hub (same as holding its button 3 s).
  static Future<void> pairStart(String ip) => _post(ip, '/pair_start', {});

  /// Remove a paired machine; the hub stops listening to it.
  static Future<void> unpair(String ip, String nodeId) => _post(ip, '/unpair', {'id': nodeId});

  /// Change the password the hub asks for before it accepts a firmware update.
  /// Throws [HubRejected] 401 when [oldToken] is not the one on the hub.
  static Future<void> setOtaToken(String ip, String oldToken, String newToken) =>
      _post(ip, '/ota_token_set', {'old': oldToken, 'new': newToken});
}
