import 'dart:async';
import 'dart:io' show Platform;
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter_esp_ble_prov/flutter_esp_ble_prov.dart';
import 'package:permission_handler/permission_handler.dart';

/// BLE WiFi provisioning screen.
///
/// Flow:
///   1. Request runtime BLE/Location permissions (Android)
///   2. Scan for hub BLE peripherals (filter by "PROV_BG_" prefix)
///   3. User picks a hub → we scan its visible WiFi networks via BLE
///   4. User picks SSID, enters password, taps Provision
///   5. Hub applies creds, returns success; we show confirmation
///
/// On platforms without BLE support (Windows desktop, web) the screen renders
/// a message pointing to the Soft AP fallback instead of crashing.
class BleProvScreen extends StatefulWidget {
  const BleProvScreen({super.key});

  @override
  State<BleProvScreen> createState() => _BleProvScreenState();
}

enum _Phase { unsupported, permission, scanDevices, scanWifi, enterPass, provisioning, done, error }

class _BleProvScreenState extends State<BleProvScreen> {
  final _plugin = FlutterEspBleProv();
  final _popController = TextEditingController(text: 'blastgate');
  final _passController = TextEditingController();

  _Phase _phase = _Phase.permission;
  String _status = '';
  String? _error;

  List<String> _devices = [];
  String? _selectedDevice;
  List<String> _wifis = [];
  String? _selectedSsid;

  @override
  void initState() {
    super.initState();
    if (kIsWeb || !(Platform.isAndroid || Platform.isIOS)) {
      _phase = _Phase.unsupported;
      _status = 'BLE provisioning is mobile-only. Use Soft AP tab on desktop.';
    } else {
      WidgetsBinding.instance.addPostFrameCallback((_) => _requestPermissions());
    }
  }

  @override
  void dispose() {
    _popController.dispose();
    _passController.dispose();
    super.dispose();
  }

  Future<void> _requestPermissions() async {
    setState(() {
      _phase = _Phase.permission;
      _status = 'Requesting BLE + Location permissions…';
    });
    final res = await [
      Permission.bluetoothScan,
      Permission.bluetoothConnect,
      Permission.locationWhenInUse,
    ].request();
    final allGranted = res.values.every((s) => s.isGranted || s.isLimited);
    if (!allGranted) {
      setState(() {
        _phase = _Phase.error;
        _status = 'Permissions denied — cannot scan BLE.';
      });
      return;
    }
    _scanDevices();
  }

  Future<void> _scanDevices() async {
    setState(() {
      _phase = _Phase.scanDevices;
      _status = 'Scanning for hubs (filter: PROV_BG_)…';
      _devices = [];
      _selectedDevice = null;
    });
    try {
      final list = await _plugin.scanBleDevices('PROV_BG_');
      if (!mounted) return;
      setState(() {
        _devices = list ?? [];
        _status = _devices.isEmpty
            ? 'No hubs found. Trigger "Start BLE Provisioning" on hub first.'
            : 'Pick a hub:';
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _phase = _Phase.error;
        _status = 'BLE scan failed';
        _error = e.toString();
      });
    }
  }

  Future<void> _scanWifis(String deviceName) async {
    setState(() {
      _phase = _Phase.scanWifi;
      _selectedDevice = deviceName;
      _status = 'Reading WiFi networks via BLE…';
      _wifis = [];
      _selectedSsid = null;
    });
    try {
      final list = await _plugin.scanWifiNetworks(deviceName, _popController.text);
      if (!mounted) return;
      setState(() {
        _wifis = list ?? [];
        _status = _wifis.isEmpty
            ? 'Hub sees no WiFi networks.'
            : 'Pick your WiFi:';
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _phase = _Phase.error;
        _status = 'WiFi scan via BLE failed (wrong PoP code?)';
        _error = e.toString();
      });
    }
  }

  Future<void> _provision() async {
    if (_selectedDevice == null || _selectedSsid == null) return;
    setState(() {
      _phase = _Phase.provisioning;
      _status = 'Sending credentials to hub…';
    });
    try {
      final ok = (await _plugin.provisionWifi(
            _selectedDevice!,
            _popController.text,
            _selectedSsid!,
            _passController.text,
          )) ==
          true;
      if (!mounted) return;
      setState(() {
        _phase = ok ? _Phase.done : _Phase.error;
        _status = ok
            ? 'Hub provisioned. It will reconnect to WiFi in a few seconds.'
            : 'Hub rejected credentials.';
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _phase = _Phase.error;
        _status = 'Provisioning failed';
        _error = e.toString();
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('BLE Provisioning'),
        actions: [
          if (_phase == _Phase.scanDevices || _phase == _Phase.error)
            IconButton(
              icon: const Icon(Icons.refresh),
              onPressed: _scanDevices,
              tooltip: 'Rescan',
            ),
        ],
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: _buildBody(),
        ),
      ),
    );
  }

  Widget _buildBody() {
    switch (_phase) {
      case _Phase.unsupported:
        return _centerMessage(Icons.bluetooth_disabled, _status, secondary:
            'flutter_esp_ble_prov supports Android + iOS only.');
      case _Phase.permission:
      case _Phase.provisioning:
        return _centerLoading(_status);
      case _Phase.scanDevices:
        return _buildDeviceList();
      case _Phase.scanWifi:
        return _buildWifiList();
      case _Phase.enterPass:
        return _buildEnterPass();
      case _Phase.done:
        return _centerMessage(Icons.check_circle, _status, color: const Color(0xFF2ECC71));
      case _Phase.error:
        return _centerMessage(Icons.error_outline, _status,
            secondary: _error, color: const Color(0xFFE74C3C));
    }
  }

  Widget _popField() {
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: TextField(
        controller: _popController,
        decoration: const InputDecoration(
          labelText: 'PoP (proof of possession)',
          helperText: 'Match the hub NVS value (default: blastgate)',
          border: OutlineInputBorder(),
        ),
      ),
    );
  }

  Widget _buildDeviceList() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(_status, style: const TextStyle(fontSize: 15, color: Color(0xFFBBC2CC))),
        const SizedBox(height: 16),
        _popField(),
        Expanded(
          child: _devices.isEmpty
              ? Center(child: ElevatedButton.icon(
                  icon: const Icon(Icons.search),
                  label: const Text('Scan again'),
                  onPressed: _scanDevices,
                ))
              : ListView.builder(
                  itemCount: _devices.length,
                  itemBuilder: (_, i) => Card(
                    child: ListTile(
                      leading: const Icon(Icons.bluetooth, color: Color(0xFF3A7BD5)),
                      title: Text(_devices[i]),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: () => _scanWifis(_devices[i]),
                    ),
                  ),
                ),
        ),
      ],
    );
  }

  Widget _buildWifiList() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text('Hub: $_selectedDevice',
            style: const TextStyle(fontSize: 13, color: Color(0xFF8B95A0))),
        const SizedBox(height: 8),
        Text(_status, style: const TextStyle(fontSize: 15, color: Color(0xFFBBC2CC))),
        const SizedBox(height: 16),
        Expanded(
          child: ListView.builder(
            itemCount: _wifis.length,
            itemBuilder: (_, i) => Card(
              child: ListTile(
                leading: const Icon(Icons.wifi, color: Color(0xFF3A7BD5)),
                title: Text(_wifis[i]),
                trailing: const Icon(Icons.chevron_right),
                onTap: () {
                  setState(() {
                    _selectedSsid = _wifis[i];
                    _phase = _Phase.enterPass;
                    _passController.clear();
                  });
                },
              ),
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildEnterPass() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text('Hub: $_selectedDevice',
            style: const TextStyle(fontSize: 13, color: Color(0xFF8B95A0))),
        Text('WiFi: $_selectedSsid',
            style: const TextStyle(fontSize: 15, fontWeight: FontWeight.bold)),
        const SizedBox(height: 24),
        TextField(
          controller: _passController,
          obscureText: true,
          autofocus: true,
          decoration: const InputDecoration(
            labelText: 'WiFi password',
            border: OutlineInputBorder(),
          ),
        ),
        const SizedBox(height: 24),
        FilledButton(
          onPressed: _provision,
          style: FilledButton.styleFrom(
            padding: const EdgeInsets.symmetric(vertical: 14),
            backgroundColor: const Color(0xFF2ECC71),
          ),
          child: const Text('Provision', style: TextStyle(fontWeight: FontWeight.bold)),
        ),
        const SizedBox(height: 8),
        TextButton(
          onPressed: () => setState(() => _phase = _Phase.scanWifi),
          child: const Text('← back'),
        ),
      ],
    );
  }

  Widget _centerLoading(String msg) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const CircularProgressIndicator(),
          const SizedBox(height: 16),
          Text(msg, textAlign: TextAlign.center),
        ],
      ),
    );
  }

  Widget _centerMessage(IconData icon, String msg, {String? secondary, Color? color}) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(icon, size: 64, color: color ?? Colors.grey[700]),
            const SizedBox(height: 16),
            Text(msg, textAlign: TextAlign.center,
                style: TextStyle(fontSize: 15, color: color)),
            if (secondary != null) ...[
              const SizedBox(height: 8),
              Text(secondary, textAlign: TextAlign.center,
                  style: const TextStyle(color: Color(0xFF8B95A0), fontSize: 12)),
            ],
          ],
        ),
      ),
    );
  }
}
