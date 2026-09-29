import 'dart:async';
import 'dart:convert';
import 'dart:io';

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
  static Future<void> _post(String ip, String path, Map<String, dynamic> body) async {
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 8);
    try {
      final req = await client.postUrl(Uri.parse('http://$ip$path')).timeout(const Duration(seconds: 8));
      req.headers.set('User-Agent', _ua);
      req.headers.contentType = ContentType.json;
      final bytes = utf8.encode(jsonEncode(body));
      req.contentLength = bytes.length;
      req.add(bytes);
      final resp = await req.close().timeout(const Duration(seconds: 8));
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
  }

  static Future<void> wifiSet(String ip, String ssid, String pass) =>
      _post(ip, '/wifi_set', {'ssid': ssid, 'pass': pass});

  static Future<void> wifiForget(String ip) => _post(ip, '/wifi_forget', {});
}
