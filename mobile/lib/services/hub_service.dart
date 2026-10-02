import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../models/app_config.dart';
import '../models/hub_status.dart';
import '../models/node_status.dart';
import '../ui/state.dart';
import 'hub_http.dart';

/// Connection status enum
enum ConnectionStatus {
  disconnected,
  connecting,
  connected,
  error,
}

/// Hub service for UDP communication with Blastgate hub
class HubService extends ChangeNotifier {
  AppConfig _config = AppConfig();
  HubStatus? _hubStatus;
  ConnectionStatus _connectionStatus = ConnectionStatus.disconnected;
  String _lastError = '';
  Timer? _pollTimer;
  RawDatagramSocket? _socket;
  RawDatagramSocket? _broadcastSocket;  // HUB_UPDATE listener
  Future<void> _cmdTail = Future.value(); // commands run one at a time, in order
  int _cmdPending = 0;
  int _misses = 0;                        // consecutive STATUS timeouts
  bool _discovering = false;              // a hub search is running
  DateTime? _lastDiscover;                // when the last search finished
  List<String> _foundHubs = [];           // more than one hub answered: the user picks
  bool _persistEvents = false;            // set by init(); tests never touch storage
  Timer? _eventsSave;

  // Raw STATUS JSON (same map the desktop app works with) + derived events
  Map<String, dynamic> _raw = {};
  DateTime? _updatedAt;
  final List<HubEvent> events = [];
  static const int maxEvents = 500;
  static const int missesBeforeOffline = 3;
  static const _rediscoverEvery = Duration(seconds: 15);

  // Getters
  AppConfig get config => _config;
  HubStatus? get hubStatus => _hubStatus;
  ConnectionStatus get connectionStatus => _connectionStatus;
  String get lastError => _lastError;
  List<NodeStatus> get nodes => _hubStatus?.nodes ?? [];
  List<NodeStatus> get visibleNodes {
    if (_config.showOfflineNodes) return nodes;
    return nodes.where((n) => n.online).toList();
  }

  bool get isConnected => _connectionStatus == ConnectionStatus.connected;
  bool get isOverdrive => _hubStatus?.manualOverdrive ?? false;

  Map<String, dynamic> get status => _raw;
  DateTime? get updatedAt => _updatedAt;
  bool get lockout => _raw.isNotEmpty && toInt(_raw['manualOverdrive']) == 1;
  bool get searching => _discovering;
  /// True once a search has finished without a connected hub.
  bool get searchedOnce => _lastDiscover != null;
  List<String> get foundHubs => _foundHubs;

  Map<String, dynamic>? node(String id) {
    for (final n in nodesOf(_raw)) {
      if (n['id'] == id) return n;
    }
    return null;
  }

  void addEvent(String tone, String text) {
    events.add(HubEvent(DateTime.now(), tone, text));
    if (events.length > maxEvents) events.removeRange(0, events.length - maxEvents);
    _saveEventsSoon();
    notifyListeners();
  }

  /// Events survive an app restart: written a moment after the last change.
  void _saveEventsSoon() {
    if (!_persistEvents) return;
    _eventsSave?.cancel();
    _eventsSave = Timer(const Duration(seconds: 2), () async {
      try {
        final prefs = await SharedPreferences.getInstance();
        await prefs.setString('blastgate_events', jsonEncode([for (final e in events) e.toJson()]));
      } catch (e) {
        debugPrint('Error saving events: $e');
      }
    });
  }

  Future<void> _loadEvents() async {
    try {
      final raw = (await SharedPreferences.getInstance()).getString('blastgate_events');
      if (raw == null) return;
      events.insertAll(0, [for (final j in jsonDecode(raw) as List) HubEvent.fromJson(Map<String, dynamic>.from(j as Map))]);
    } catch (e) {
      debugPrint('Error loading events: $e');
    }
  }

  /// Tests only: show [status] as if the hub had just answered.
  @visibleForTesting
  void debugSetStatus(Map<String, dynamic> status) {
    _setStatus(status);
    _updatedAt = status.isEmpty ? null : DateTime(2026, 10, 2, 14, 5, 9);
    _connectionStatus = status.isEmpty ? ConnectionStatus.disconnected : ConnectionStatus.connected;
    notifyListeners();
  }

  void clearEvents() {
    events.clear();
    _saveEventsSoon();
    notifyListeners();
  }

  void _setStatus(Map<String, dynamic> next) {
    final evs = diffEvents(_raw, next);
    _raw = next;
    events.addAll(evs);
    if (events.length > maxEvents) events.removeRange(0, events.length - maxEvents);
    if (evs.isNotEmpty) _saveEventsSoon();
  }

  /// Initialize the service
  Future<void> init() async {
    await _loadConfig();
    await _loadEvents();
    _persistEvents = true;
    await startPolling();
    _startBroadcastListener();
    // Auto-discover hub after short delay (don't block startup)
    Future.delayed(const Duration(milliseconds: 800), _autoDiscoverHub);
  }

  /// Auto-discover hub on startup (and again while no hub answers).
  Future<void> _autoDiscoverHub() async {
    if (_connectionStatus == ConnectionStatus.connected) return;
    await findHub();
  }

  /// Search the network. Exactly one hub: use it. Several: keep the list in
  /// [foundHubs] for the user to choose from.
  Future<void> findHub() async {
    if (_discovering) return;
    _discovering = true;
    notifyListeners();
    try {
      final hubs = await discoverHubs();
      debugPrint('[findHub] $hubs');
      _foundHubs = hubs.length > 1 ? hubs : [];
      if (hubs.length == 1) await selectHub(hubs.first);
    } catch (e) {
      debugPrint('[findHub] error: $e');
    } finally {
      _discovering = false;
      _lastDiscover = DateTime.now();
      notifyListeners();
    }
  }

  /// Use the hub at [ip] from now on.
  Future<void> selectHub(String ip) async {
    _foundHubs = [];
    _config.preferredHubIp = ip;
    await saveConfig();
    await startPolling();
  }

  /// Start listening for HUB_UPDATE broadcasts (real-time sync)
  Future<void> _startBroadcastListener() async {
    try {
      _broadcastSocket?.close();
      _broadcastSocket = await RawDatagramSocket.bind(
        InternetAddress.anyIPv4,
        _config.udpPort,
        reuseAddress: true,
      );
      _broadcastSocket!.broadcastEnabled = true;

      _broadcastSocket!.listen((event) {
        if (event == RawSocketEvent.read) {
          final datagram = _broadcastSocket?.receive();
          if (datagram != null) {
            final msg = utf8.decode(datagram.data).trim();
            if (msg == 'HUB_UPDATE') {
              debugPrint('Received HUB_UPDATE - refreshing status');
              fetchStatus();  // Immediate refresh
            }
          }
        }
      });

      debugPrint('HUB_UPDATE listener started on port ${_config.udpPort}');
    } catch (e) {
      debugPrint('Failed to start broadcast listener: $e');
    }
  }

  /// Load config from shared preferences
  Future<void> _loadConfig() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final configStr = prefs.getString('blastgate_config');
      if (configStr != null) {
        _config = AppConfig.fromJson(jsonDecode(configStr));
      }
      // Migration: replace the v1 placeholder OTA URL with the current default.
      // Earlier dev builds saved "REPO/blastgate" before the real repo was known.
      if (_config.otaManifestUrl.contains('REPO/blastgate')) {
        debugPrint('[migration] OTA manifest URL had placeholder REPO — resetting to default');
        _config.otaManifestUrl = AppConfig().otaManifestUrl;
        await saveConfig();
      }
    } catch (e) {
      debugPrint('Error loading config: $e');
    }
  }

  /// Save config to shared preferences
  Future<void> saveConfig() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('blastgate_config', jsonEncode(_config.toJson()));
      notifyListeners();
    } catch (e) {
      debugPrint('Error saving config: $e');
    }
  }

  /// Update config
  void updateConfig(AppConfig newConfig) {
    _config = newConfig;
    saveConfig();
    // Restart polling with new config
    startPolling();
  }

  /// Start polling for status
  Future<void> startPolling() async {
    stopPolling();

    // Initial fetch
    await fetchStatus();

    // Start periodic polling
    _pollTimer = Timer.periodic(
      Duration(milliseconds: _config.pollMs),
      (_) => fetchStatus(),
    );
  }

  /// Stop polling
  void stopPolling() {
    _pollTimer?.cancel();
    _pollTimer = null;
  }

  /// Send UDP command and get response. Commands are queued (never dropped),
  /// so a button press is not lost when a STATUS poll is in flight.
  Future<String?> _sendCommand(String command, {Duration? timeout}) {
    final prev = _cmdTail;
    final done = Completer<void>();
    _cmdTail = done.future;
    _cmdPending++;
    return prev.then((_) => _sendCommandNow(command, timeout: timeout)).whenComplete(() {
      _cmdPending--;
      done.complete();
    });
  }

  /// Public raw command: returns the hub reply or null on timeout.
  Future<String?> command(String cmd) => _sendCommand(cmd);

  Future<String?> _sendCommandNow(String command, {Duration? timeout}) async {
    try {
      final targetIp = _config.effectiveHubIp;
      final targetPort = _config.udpPort;
      final timeoutDuration = timeout ?? Duration(
        milliseconds: (_config.timeoutS * 1000).toInt(),
      );

      // Create socket if needed
      _socket?.close();
      _socket = await RawDatagramSocket.bind(InternetAddress.anyIPv4, 0);

      final completer = Completer<String?>();
      Timer? timeoutTimer;

      _socket!.listen((event) {
        if (event == RawSocketEvent.read) {
          final datagram = _socket!.receive();
          if (datagram != null) {
            final response = utf8.decode(datagram.data);
            timeoutTimer?.cancel();
            if (!completer.isCompleted) {
              completer.complete(response);
            }
          }
        }
      });

      // Send command
      final data = utf8.encode(command);
      _socket!.send(data, InternetAddress(targetIp), targetPort);

      // Set timeout
      timeoutTimer = Timer(timeoutDuration, () {
        if (!completer.isCompleted) {
          completer.complete(null);
        }
      });

      final result = await completer.future;
      _socket?.close();
      _socket = null;
      return result;

    } catch (e) {
      debugPrint('UDP error: $e');
      _socket?.close();
      _socket = null;
      return null;
    }
  }

  /// Fetch hub status
  Future<void> fetchStatus() async {
    // A user command is queued/in flight — skip this poll, the next one follows shortly
    if (_cmdPending > 0) return;
    try {
      if (_connectionStatus != ConnectionStatus.connected) {
        _connectionStatus = ConnectionStatus.connecting;
        notifyListeners();
      }

      final response = await _sendCommand('STATUS');

      if (response == null) {
        // One lost UDP packet is not a lost hub: keep the last status for a few polls
        _misses++;
        if (_misses >= missesBeforeOffline || _raw.isEmpty) {
          _connectionStatus = ConnectionStatus.disconnected;
          _lastError = 'No response from hub';
          if (_raw.isNotEmpty) _setStatus({});
          _hubStatus = null;
          // The hub may have a new address (router restart): look for it again
          final last = _lastDiscover;
          if (last != null && DateTime.now().difference(last) > _rediscoverEvery) findHub();
        }
        notifyListeners();
        return;
      }

      // Parse JSON response
      try {
        final json = jsonDecode(response) as Map<String, dynamic>;
        _hubStatus = HubStatus.fromJson(json);
        _setStatus(json);
        _updatedAt = DateTime.now();
        _misses = 0;
        _connectionStatus = ConnectionStatus.connected;
        _lastError = '';
      } catch (e) {
        _connectionStatus = ConnectionStatus.error;
        _lastError = 'Invalid response: $e';
      }

      notifyListeners();
    } catch (e) {
      _connectionStatus = ConnectionStatus.error;
      _lastError = e.toString();
      notifyListeners();
    }
  }

  /// Send gate command for a node
  Future<bool> sendGateCommand(String nodeId, String gateCmd) async {
    // gateCmd: 'auto', 'open', 'close'
    final command = 'NODECMD id=$nodeId gate=$gateCmd';
    final response = await _sendCommand(command);
    if (response != null && response.contains('OK')) {
      await fetchStatus();
      return true;
    }
    return false;
  }

  /// Set node mode: 'auto' or 'manual'
  Future<bool> setMode(String nodeId, String mode) async {
    final response = await _sendCommand('NODEMODE id=$nodeId mode=$mode');
    if (response != null && response.contains('OK')) {
      await fetchStatus();
      return true;
    }
    return false;
  }

  /// Rename a node (hub args are space-separated — spaces become '_', same as desktop)
  Future<bool> renameNode(String nodeId, String newName) async {
    final safe = newName.trim().replaceAll('"', "'").replaceAll(' ', '_');
    final command = 'ASSIGN id=$nodeId name=$safe';
    final response = await _sendCommand(command);
    if (response != null && response.contains('OK')) {
      await fetchStatus();
      return true;
    }
    return false;
  }

  /// Remove a machine from the hub: unpair it and drop its saved name.
  /// Throws when the hub is unreachable or refuses.
  Future<void> removeNode(String nodeId) async {
    await HubHttp.unpair(_config.effectiveHubIp, nodeId);
    await _sendCommand('FORGET id=$nodeId');
    await fetchStatus();
  }

  /// Set node configuration persisted in hub NVS
  Future<bool> setNodeConfig({
    required String nodeId,
    double? threshold,
    int? holdMs,
    int? hbridgeOpenMs,
    int? hbridgeCloseMs,
  }) async {
    final parts = <String>['NODECFG_SET id=$nodeId'];
    if (threshold != null) parts.add('threshold_on=$threshold');
    if (holdMs != null) parts.add('gate_hold_ms=$holdMs');
    if (hbridgeOpenMs != null) parts.add('hbridge_open_ms=$hbridgeOpenMs');
    if (hbridgeCloseMs != null) parts.add('hbridge_close_ms=$hbridgeCloseMs');

    final command = parts.join(' ');
    debugPrint('Sending: $command');
    final response = await _sendCommand(command);
    debugPrint('Response: $response');
    if (response != null && response.contains('OK')) {
      await fetchStatus();
      return true;
    }
    return false;
  }

  /// Get node configuration
  Future<Map<String, dynamic>?> getNodeConfig(String nodeId) async {
    final command = 'NODECFG_GET id=$nodeId';
    final response = await _sendCommand(command);
    if (response != null) {
      try {
        return jsonDecode(response) as Map<String, dynamic>;
      } catch (e) {
        debugPrint('Failed to parse node config: $e');
      }
    }
    return null;
  }

  /// Set relay state: 'on', 'off', 'auto'. Returns null on success, else the reason.
  Future<String?> setRelay(String state) async {
    final response = await _sendCommand('RELAY $state');
    if (response == null) return 'Hub ne odgovara';
    if (response.contains('OK')) {
      await fetchStatus();
      return null;
    }
    if (response.contains('no gate open')) {
      return 'Hub ne pali usisivač dok nijedan zatvarač nije otvoren.';
    }
    return response.trim();
  }

  /// Refresh nodes
  Future<void> refresh() async {
    await _sendCommand('REFRESH');
    await fetchStatus();
  }

  /// Full refresh
  Future<void> fullRefresh() async {
    await _sendCommand('REFRESH_FULL');
    await fetchStatus();
  }

  /// Get WiFi info
  Future<WifiInfo?> getWifiInfo() async {
    final response = await _sendCommand('WIFI_GET');
    if (response != null) {
      return WifiInfo.fromRaw(response);
    }
    return null;
  }

  /// Set WiFi credentials
  Future<bool> setWifi(String ssid, String password) async {
    final command = 'WIFI_SET ssid=$ssid pass=$password';
    final response = await _sendCommand(command);
    return response != null && response.contains('OK');
  }

  /// HTTP probe: GET http://ip/ping (fast) then /status as fallback.
  /// Uses outbound TCP — bypasses firewall without inbound rules.
  Future<bool> _httpProbe(String ip, {int timeoutMs = 2000}) async {
    // Fast path: /ping returns "PONG" in < 20 bytes
    try {
      final client = HttpClient();
      client.connectionTimeout = Duration(milliseconds: timeoutMs);
      final req = await client
          .getUrl(Uri.parse('http://$ip/ping'))
          .timeout(Duration(milliseconds: timeoutMs));
      req.headers.set('User-Agent', 'BlastgateApp/1.0');
      final resp = await req.close().timeout(Duration(milliseconds: timeoutMs));
      final body = await resp.transform(utf8.decoder).join()
          .timeout(Duration(milliseconds: timeoutMs));
      client.close(force: true);
      if (resp.statusCode == 200 && body.trim() == 'PONG') return true;
    } catch (_) {}

    // Fallback: /status JSON (works with older firmware that doesn't have /ping)
    try {
      final client = HttpClient();
      client.connectionTimeout = Duration(milliseconds: timeoutMs);
      final req = await client
          .getUrl(Uri.parse('http://$ip/status'))
          .timeout(Duration(milliseconds: timeoutMs));
      req.headers.set('User-Agent', 'BlastgateApp/1.0');
      final resp = await req.close().timeout(Duration(milliseconds: timeoutMs));
      final body = await resp.transform(utf8.decoder).join()
          .timeout(Duration(milliseconds: timeoutMs));
      client.close(force: true);
      if (resp.statusCode != 200) return false;
      final data = jsonDecode(body) as Map<String, dynamic>;
      return data.containsKey('apIp');
    } catch (e) {
      debugPrint('[HTTP probe] $ip: $e');
      return false;
    }
  }

  /// Resolve mDNS hostname to IP.
  Future<String?> _resolveMdns(String hostname) async {
    try {
      final addrs = await InternetAddress.lookup(hostname, type: InternetAddressType.IPv4);
      if (addrs.isNotEmpty) return addrs.first.address;
    } catch (_) {}
    return null;
  }

  /// Discover hubs on network.
  ///
  /// Runs three strategies truly in parallel (all start at t=0):
  /// 1. HTTP probe to each known IP  — bypasses Windows Firewall / works on AP subnet
  /// 2. HTTP probe to mDNS-resolved IP
  /// 3. UDP broadcast + unicast DISCOVER — also catches periodic HUB_READY heartbeats
  ///
  /// Total time ≈ 2 s (limited by UDP listen window).
  /// Returns list of hub IP strings.
  Future<List<String>> discoverHubs() async {
    final found = <String>{};
    final cfg = _config;
    final probeIps = <String>[...cfg.probeIps];

    await Future.wait([
      // ── HTTP probes to all known IPs ──────────────────────────────────
      ...probeIps.map((ip) async {
        if (await _httpProbe(ip, timeoutMs: 2000)) found.add(ip);
      }),

      // ── mDNS → HTTP probe ─────────────────────────────────────────────
      () async {
        final mdnsIp = await _resolveMdns(cfg.hubMdns);
        if (mdnsIp != null && mdnsIp.isNotEmpty && !probeIps.contains(mdnsIp)) {
          if (await _httpProbe(mdnsIp, timeoutMs: 2000)) found.add(mdnsIp);
        }
      }(),

      // ── UDP broadcast + unicast ───────────────────────────────────────
      // Note: hub replies to our sender-port, so we catch DISCOVER replies.
      // HUB_READY broadcasts go to port 8888 (not our ephemeral port) so they
      // don't arrive here — discovery relies on DISCOVER reply + HTTP probes.
      () async {
        try {
          final socket = await RawDatagramSocket.bind(InternetAddress.anyIPv4, 0);
          socket.broadcastEnabled = true;

          socket.listen((event) {
            if (event == RawSocketEvent.read) {
              final datagram = socket.receive();
              if (datagram != null) {
                final msg = utf8.decode(datagram.data, allowMalformed: true).trim();
                if (msg.startsWith('BLASTGATE_HUB')) {
                  found.add(datagram.address.address);
                  debugPrint('[discoverHubs] UDP found: ${datagram.address.address}');
                }
              }
            }
          });

          final data = utf8.encode('DISCOVER');
          // Send a few times — UDP is fire-and-forget, one might be lost
          for (var i = 0; i < 3; i++) {
            try { socket.send(data, InternetAddress('255.255.255.255'), cfg.udpPort); } catch (_) {}
            for (final ip in probeIps) {
              try { socket.send(data, InternetAddress(ip), cfg.udpPort); } catch (_) {}
            }
            if (i < 2) await Future.delayed(const Duration(milliseconds: 600));
          }

          await Future.delayed(const Duration(milliseconds: 800));
          socket.close();
        } catch (e) {
          debugPrint('[discoverHubs] UDP error: $e');
        }
      }(),
    ]);

    debugPrint('[discoverHubs] found: $found');
    return found.toList();
  }

  /// Test connection to specific IP.
  /// Tries HTTP GET /status first (bypasses Windows Firewall), then UDP PING.
  Future<bool> testConnection(String ip) async {
    // HTTP first — outbound TCP, no firewall rules needed
    if (await _httpProbe(ip, timeoutMs: 2000)) return true;

    // UDP fallback
    try {
      final socket = await RawDatagramSocket.bind(InternetAddress.anyIPv4, 0);
      final responseCompleter = Completer<bool>();

      socket.listen((event) {
        if (event == RawSocketEvent.read) {
          final datagram = socket.receive();
          if (datagram != null) {
            final response = utf8.decode(datagram.data);
            if (response.contains('PONG')) {
              if (!responseCompleter.isCompleted) responseCompleter.complete(true);
            }
          }
        }
      });

      socket.send(utf8.encode('PING'), InternetAddress(ip), _config.udpPort);

      Timer(const Duration(seconds: 2), () {
        if (!responseCompleter.isCompleted) responseCompleter.complete(false);
      });

      final result = await responseCompleter.future;
      socket.close();
      return result;

    } catch (e) {
      return false;
    }
  }

  @override
  void dispose() {
    stopPolling();
    _eventsSave?.cancel();
    _socket?.close();
    _broadcastSocket?.close();
    _broadcastSocket = null;
    super.dispose();
  }
}
