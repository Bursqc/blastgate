import 'node_status.dart';

/// Hub status data model.
/// Mirrors hub firmware STATUS JSON (see firmware/hub-wt32/src/main.cpp jsonStatus_build).
class HubStatus {
  // Identity / health (added in proto 1.0)
  final String protoVer;
  final String? version;
  final String? build;
  final int? uptime;    // seconds since boot
  final int? freeHeap;  // bytes

  // Networking
  final String apIp;
  final String staIp;
  final bool sta;
  final bool ethLink;
  final String ethIp;

  // Control state
  final bool manualOverdrive;
  final bool relayState;
  final int relayMode; // 2=auto, 1=force_on, 0=force_off

  final List<NodeStatus> nodes;
  final bool prov;

  HubStatus({
    this.protoVer = '1.0',
    this.version,
    this.build,
    this.uptime,
    this.freeHeap,
    this.apIp = '',
    this.staIp = '',
    this.sta = false,
    this.ethLink = false,
    this.ethIp = '',
    required this.manualOverdrive,
    required this.relayState,
    this.relayMode = 2,
    required this.nodes,
    this.prov = false,
  });

  factory HubStatus.fromJson(Map<String, dynamic> json) {
    final nodesList = (json['nodes'] as List<dynamic>?)
            ?.map((n) => NodeStatus.fromJson(n as Map<String, dynamic>))
            .toList() ??
        [];

    return HubStatus(
      protoVer: (json['protoVer'] as String?) ?? '1.0',
      version: json['version'] as String?,
      build: json['build'] as String?,
      uptime: (json['uptime'] as num?)?.toInt(),
      freeHeap: (json['freeHeap'] as num?)?.toInt(),
      apIp: (json['apIp'] as String?) ?? '',
      staIp: (json['staIp'] as String?) ?? '',
      sta: (json['sta'] as int?) == 1,
      ethLink: (json['ethLink'] as int?) == 1,
      ethIp: (json['ethIp'] as String?) ?? '',
      manualOverdrive: (json['manualOverdrive'] as int?) == 1,
      relayState: (json['relayState'] as int?) == 1,
      relayMode: (json['relayMode'] as int?) ?? 2,
      nodes: nodesList,
      prov: (json['prov'] as int?) == 1,
    );
  }

  List<NodeStatus> get onlineNodes => nodes.where((n) => n.online).toList();
}

/// WiFi info from hub
class WifiInfo {
  final bool connected;
  final String ssid;
  final String ip;
  final int rssi;
  final bool provisioningActive;

  WifiInfo({
    required this.connected,
    required this.ssid,
    required this.ip,
    required this.rssi,
    required this.provisioningActive,
  });

  factory WifiInfo.fromRaw(String raw) {
    // Firmware sends: "WIFI;STA=1;SSID=MyWifi;IP=192.168.1.100;RSSI=-45;PROV=0"
    final parts = raw.split(';');
    final map = <String, String>{};
    for (final part in parts) {
      final eq = part.indexOf('=');
      if (eq > 0) {
        map[part.substring(0, eq)] = part.substring(eq + 1);
      }
    }

    return WifiInfo(
      connected: map['STA'] == '1',
      ssid: map['SSID'] ?? '',
      ip: map['IP'] ?? '',
      rssi: int.tryParse(map['RSSI'] ?? '0') ?? 0,
      provisioningActive: map['PROV'] == '1',
    );
  }
}
