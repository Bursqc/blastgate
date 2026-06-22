import 'dart:async';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/hub_service.dart';
import '../services/ota_service.dart';

/// Hub firmware OTA screen.
/// Flow: check → display versions → user taps Update → download → upload → wait reboot.
class OtaScreen extends StatefulWidget {
  const OtaScreen({super.key});

  @override
  State<OtaScreen> createState() => _OtaScreenState();
}

enum _Phase { checking, idle, downloading, uploading, rebooting, done, error }

class _OtaScreenState extends State<OtaScreen> {
  final OtaService _ota = OtaService();

  _Phase _phase = _Phase.checking;
  HubVersion? _hubVer;
  OtaManifest? _manifest;
  double _progress = 0.0;          // 0..1
  String _statusText = 'Checking for updates…';
  String? _errorText;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _runCheck());
  }

  String? _resolveHubIp() {
    final hub = context.read<HubService>();
    final ip = hub.config.effectiveHubIp;
    return ip.isEmpty ? null : ip;
  }

  Future<void> _runCheck() async {
    final ip = _resolveHubIp();
    if (ip == null) {
      setState(() {
        _phase = _Phase.error;
        _statusText = 'No hub IP configured — connect first.';
      });
      return;
    }
    final hub = context.read<HubService>();
    try {
      final result = await _ota.checkAndGetUpdate(
        hubIp: ip,
        manifestUrl: hub.config.otaManifestUrl,
      );
      if (!mounted) return;
      setState(() {
        _hubVer = result.hub;
        _manifest = result.manifest;
        _phase = _Phase.idle;
        if (result.manifest == null) {
          _statusText = 'Release server unreachable.';
        } else if (isNewer(result.manifest!.version, result.hub.version)) {
          _statusText =
              'Update available: ${result.hub.version} → ${result.manifest!.version}';
        } else {
          _statusText = 'Hub is up to date.';
        }
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _phase = _Phase.error;
        _statusText = 'Hub unreachable';
        _errorText = e.toString();
      });
    }
  }

  bool get _canUpdate {
    return _phase == _Phase.idle &&
        _hubVer != null &&
        _manifest != null &&
        isNewer(_manifest!.version, _hubVer!.version);
  }

  Future<void> _runUpdate() async {
    final ip = _resolveHubIp();
    final m = _manifest;
    if (ip == null || m == null) return;

    final hub = context.read<HubService>();
    final token = hub.config.otaToken;

    setState(() {
      _phase = _Phase.downloading;
      _progress = 0.0;
      _statusText = 'Downloading ${m.version}…';
      _errorText = null;
    });

    Uint8List firmware;
    try {
      firmware = await _ota.downloadFirmware(m, onProgress: (done, total) {
        if (!mounted) return;
        setState(() {
          _progress = total > 0 ? (done / total) * 0.6 : 0.0;
        });
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _phase = _Phase.error;
        _statusText = 'Download failed';
        _errorText = e.toString();
      });
      return;
    }

    // Upload
    if (!mounted) return;
    setState(() {
      _phase = _Phase.uploading;
      _progress = 0.6;
      _statusText = 'Uploading to hub…';
    });

    Map<String, dynamic> resp;
    try {
      resp = await _ota.uploadToHub(
        hubIp: ip,
        firmware: firmware,
        token: token,
        onProgress: (done, total) {
          if (!mounted) return;
          setState(() {
            _progress = 0.6 + (total > 0 ? (done / total) * 0.3 : 0.0);
          });
        },
      );
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _phase = _Phase.error;
        _statusText = 'Upload failed';
        _errorText = e.toString();
      });
      return;
    }

    if (resp['ok'] != true) {
      if (!mounted) return;
      setState(() {
        _phase = _Phase.error;
        _statusText = 'Hub rejected upload';
        _errorText = (resp['error'] ?? 'unknown').toString();
      });
      return;
    }

    // Wait for reboot
    if (!mounted) return;
    setState(() {
      _phase = _Phase.rebooting;
      _progress = 0.9;
      _statusText = 'Hub rebooting…';
    });

    final ok = await _ota.waitForReboot(
      hubIp: ip,
      expectedVersion: m.version,
      timeout: const Duration(seconds: 60),
    );

    if (!mounted) return;
    if (ok) {
      setState(() {
        _phase = _Phase.done;
        _progress = 1.0;
        _statusText = 'Update complete → ${m.version}';
        _hubVer = HubVersion(
          version: m.version,
          build: '',
          uptime: 0,
          freeHeap: 0,
          protoVer: _hubVer?.protoVer ?? '?',
        );
      });
    } else {
      setState(() {
        _phase = _Phase.error;
        _statusText = 'Timed out waiting for reboot';
        _errorText = 'Hub did not return within 60s — check power and network.';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final busy = _phase == _Phase.downloading ||
        _phase == _Phase.uploading ||
        _phase == _Phase.rebooting;

    return PopScope(
      // Block back nav while flashing — interrupting will brick the hub
      canPop: !busy,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Firmware Update'),
          actions: [
            if (_phase != _Phase.checking && !busy)
              IconButton(
                icon: const Icon(Icons.refresh),
                tooltip: 'Re-check',
                onPressed: () {
                  setState(() {
                    _phase = _Phase.checking;
                    _statusText = 'Checking for updates…';
                  });
                  _runCheck();
                },
              ),
          ],
        ),
        body: SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _buildVersionCard(),
              const SizedBox(height: 16),
              _buildChangelogCard(),
              const SizedBox(height: 24),
              _buildStatusSection(),
              const SizedBox(height: 24),
              _buildActionButton(busy),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildVersionCard() {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _kv('Hub version',     _hubVer?.version ?? '—'),
            _kv('Hub build',       _hubVer?.build.isNotEmpty == true ? _hubVer!.build : '—'),
            _kv('Hub uptime',      _hubVer != null && _hubVer!.uptime > 0
                                    ? '${(_hubVer!.uptime / 60).toStringAsFixed(0)} min'
                                    : '—'),
            _kv('Free heap',       _hubVer != null && _hubVer!.freeHeap > 0
                                    ? '${(_hubVer!.freeHeap / 1024).toStringAsFixed(1)} KB'
                                    : '—'),
            _kv('Protocol',        _hubVer?.protoVer ?? '—'),
            const Divider(height: 24),
            _kv('Latest version',  _manifest?.version ?? '—', highlight: _canUpdate),
          ],
        ),
      ),
    );
  }

  Widget _kv(String k, String v, {bool highlight = false}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 130,
            child: Text(k, style: const TextStyle(color: Color(0xFF8B95A0))),
          ),
          Expanded(
            child: Text(
              v,
              style: TextStyle(
                fontWeight: highlight ? FontWeight.bold : FontWeight.normal,
                color: highlight ? const Color(0xFF2ECC71) : null,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildChangelogCard() {
    final cl = _manifest?.changelog ?? '';
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Changelog', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
            const SizedBox(height: 8),
            Text(cl.isEmpty ? '(no changelog provided)' : cl,
                style: const TextStyle(color: Color(0xFFBBC2CC), height: 1.4)),
          ],
        ),
      ),
    );
  }

  Widget _buildStatusSection() {
    final color = switch (_phase) {
      _Phase.error => const Color(0xFFE74C3C),
      _Phase.done  => const Color(0xFF2ECC71),
      _ => null,
    };
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(_statusText,
            style: TextStyle(fontSize: 15, color: color, fontWeight: FontWeight.w500)),
        if (_errorText != null) ...[
          const SizedBox(height: 6),
          Text(_errorText!, style: const TextStyle(color: Color(0xFF8B95A0), fontSize: 12)),
        ],
        const SizedBox(height: 12),
        if (_phase != _Phase.checking && _phase != _Phase.idle && _phase != _Phase.error)
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(
              value: _progress,
              minHeight: 6,
              backgroundColor: const Color(0xFF2A2F35),
            ),
          )
        else if (_phase == _Phase.checking)
          const LinearProgressIndicator(minHeight: 6),
      ],
    );
  }

  Widget _buildActionButton(bool busy) {
    if (_phase == _Phase.done) {
      return FilledButton(
        onPressed: () => Navigator.pop(context),
        style: FilledButton.styleFrom(padding: const EdgeInsets.symmetric(vertical: 14)),
        child: const Text('Close'),
      );
    }
    if (busy) {
      return FilledButton(
        onPressed: null,
        style: FilledButton.styleFrom(padding: const EdgeInsets.symmetric(vertical: 14)),
        child: const Text('Working…'),
      );
    }
    return FilledButton(
      onPressed: _canUpdate ? _runUpdate : null,
      style: FilledButton.styleFrom(
        padding: const EdgeInsets.symmetric(vertical: 14),
        backgroundColor: const Color(0xFF2ECC71),
      ),
      child: const Text('Update', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
    );
  }
}
