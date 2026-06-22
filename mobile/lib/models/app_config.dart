/// App configuration model
class AppConfig {
  String hubLanIp;
  String hubApIp;
  String hubEthDirectIp;
  String hubMdns;       // mDNS: hub advertises as "blastgate.local"
  int udpPort;
  int pollMs;
  double timeoutS;
  String preferredHubIp;
  bool autoApDetect;
  bool showOfflineNodes;

  // OTA settings — match desktop AppConfig
  String otaManifestUrl;
  String otaToken;

  AppConfig({
    this.hubLanIp = '192.168.1.116',
    this.hubApIp = '192.168.4.1',
    this.hubEthDirectIp = '169.254.5.1',
    this.hubMdns = 'blastgate.local',   // matches MDNS.begin("blastgate") on hub
    this.udpPort = 8888,
    this.pollMs = 300,
    this.timeoutS = 1.2,
    this.preferredHubIp = '',
    this.autoApDetect = true,
    this.showOfflineNodes = false,
    this.otaManifestUrl = 'https://raw.githubusercontent.com/REPO/blastgate/main/releases/manifest.json',
    this.otaToken = 'blastgate-change-me',
  });

  factory AppConfig.fromJson(Map<String, dynamic> json) {
    return AppConfig(
      hubLanIp: json['hubLanIp'] as String? ?? '192.168.1.116',
      hubApIp: json['hubApIp'] as String? ?? '192.168.4.1',
      hubEthDirectIp: json['hubEthDirectIp'] as String? ?? '169.254.5.1',
      hubMdns: json['hubMdns'] as String? ?? 'blastgate.local',
      udpPort: json['udpPort'] as int? ?? 8888,
      pollMs: json['pollMs'] as int? ?? 300,
      timeoutS: (json['timeoutS'] as num?)?.toDouble() ?? 1.2,
      preferredHubIp: json['preferredHubIp'] as String? ?? '',
      autoApDetect: json['autoApDetect'] as bool? ?? true,
      showOfflineNodes: json['showOfflineNodes'] as bool? ?? false,
      otaManifestUrl: json['otaManifestUrl'] as String? ??
          'https://raw.githubusercontent.com/REPO/blastgate/main/releases/manifest.json',
      otaToken: json['otaToken'] as String? ?? 'blastgate-change-me',
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'hubLanIp': hubLanIp,
      'hubApIp': hubApIp,
      'hubEthDirectIp': hubEthDirectIp,
      'hubMdns': hubMdns,
      'udpPort': udpPort,
      'pollMs': pollMs,
      'timeoutS': timeoutS,
      'preferredHubIp': preferredHubIp,
      'autoApDetect': autoApDetect,
      'showOfflineNodes': showOfflineNodes,
      'otaManifestUrl': otaManifestUrl,
      'otaToken': otaToken,
    };
  }

  String get effectiveHubIp {
    if (preferredHubIp.isNotEmpty) return preferredHubIp;
    return hubLanIp;
  }

  /// Ordered list of IPs to probe: ETH direct → LAN → AP
  List<String> get probeIps {
    final seen = <String>{};
    final result = <String>[];
    for (final ip in [hubEthDirectIp, hubLanIp, hubApIp]) {
      if (ip.isNotEmpty && seen.add(ip)) result.add(ip);
    }
    return result;
  }
}
