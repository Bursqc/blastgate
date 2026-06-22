/// Node status data model.
/// Mirrors hub firmware STATUS JSON (see firmware/hub-wt32/src/main.cpp jsonStatus_build).
class NodeStatus {
  final String id;
  final String? name;
  final String? ip;
  final int? port;
  final bool online;
  final bool active;
  final double? value;
  final int override; // 0=AUTO, 1=OPEN, 2=CLOSE
  final int mode;     // 0=AUTO, 1=MANUAL
  final bool? gateOpen;

  // Liveness / scheduling (added in proto 1.0)
  final int? ageMs;
  final int? closeInMs;

  // Per-node config — hub now includes these in STATUS for in-place display
  final double? thresholdOn;
  final int? relayHoldMs;
  final int? gateHoldMs;
  final int? hbridgeOpenMs;
  final int? hbridgeCloseMs;

  NodeStatus({
    required this.id,
    this.name,
    this.ip,
    this.port,
    required this.online,
    required this.active,
    this.value,
    required this.override,
    this.mode = 0,
    this.gateOpen,
    this.ageMs,
    this.closeInMs,
    this.thresholdOn,
    this.relayHoldMs,
    this.gateHoldMs,
    this.hbridgeOpenMs,
    this.hbridgeCloseMs,
  });

  factory NodeStatus.fromJson(Map<String, dynamic> json) {
    return NodeStatus(
      id: json['id'] as String,
      name: json['name'] as String?,
      ip: json['ip'] as String?,
      port: (json['port'] as num?)?.toInt(),
      online: (json['online'] as int?) == 1,
      active: (json['active'] as int?) == 1,
      value: (json['value'] as num?)?.toDouble(),
      override: json['override'] as int? ?? 0,
      mode: json['mode'] as int? ?? 0,
      gateOpen: json['gateOpen'] != null ? (json['gateOpen'] as int) == 1 : null,
      ageMs: (json['ageMs'] as num?)?.toInt(),
      closeInMs: (json['closeInMs'] as num?)?.toInt(),
      thresholdOn: (json['threshold_on'] as num?)?.toDouble(),
      relayHoldMs: (json['relay_hold_ms'] as num?)?.toInt(),
      gateHoldMs: (json['gate_hold_ms'] as num?)?.toInt(),
      hbridgeOpenMs: (json['hbridge_open_ms'] as num?)?.toInt(),
      hbridgeCloseMs: (json['hbridge_close_ms'] as num?)?.toInt(),
    );
  }

  String get displayName => name ?? id;

  String get overrideMode {
    switch (override) {
      case 1: return 'OPEN';
      case 2: return 'CLOSE';
      default: return 'AUTO';
    }
  }

  String get gateState {
    if (gateOpen == null) return 'UNKNOWN';
    return gateOpen! ? 'OPEN' : 'CLOSED';
  }
}
