import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'package:url_launcher/url_launcher.dart';
import '../services/hub_service.dart';

/// True on desktop platforms where `webview_flutter` is NOT supported.
/// On these we fall back to launching the system browser.
bool get _isDesktop =>
    !kIsWeb && (Platform.isWindows || Platform.isLinux || Platform.isMacOS);

// ============ WiFi Provisioning Screen ============
// Two provisioning paths:
//   Web tab    — WebView opens hub's /setup page (network scan + form)
//   Soft AP tab — native UI: scan via /wifi_scan, send via POST /wifi_set

class ProvisioningScreen extends StatelessWidget {
  const ProvisioningScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('WiFi Setup'),
          bottom: const TabBar(
            tabs: [
              Tab(icon: Icon(Icons.language), text: 'Web'),
              Tab(icon: Icon(Icons.wifi_tethering), text: 'Soft AP'),
            ],
          ),
        ),
        body: const TabBarView(
          physics: NeverScrollableScrollPhysics(),
          children: [
            _WebTab(),
            _SoftApTab(),
          ],
        ),
      ),
    );
  }
}

// ============ Web Tab (Captive Portal) ============

class _WebTab extends StatefulWidget {
  const _WebTab();
  @override
  State<_WebTab> createState() => _WebTabState();
}

class _WebTabState extends State<_WebTab> {
  // _controller is only initialized on mobile platforms — on desktop we don't
  // construct WebViewController at all (the underlying platform code throws).
  WebViewController? _controller;
  bool _loading = true;
  bool _error = false;
  List<String> _candidateIps = [];
  int _ipIdx = 0;

  @override
  void initState() {
    super.initState();
    final cfg = context.read<HubService>().config;
    // Try IPs in priority: ETH direct → LAN → AP
    _candidateIps = cfg.probeIps;
    if (_candidateIps.isEmpty) _candidateIps = ['192.168.4.1'];

    if (_isDesktop) {
      // On Windows/Linux/macOS webview_flutter has no implementation —
      // skip controller setup; build() renders the launch-in-browser fallback UI.
      _loading = false;
      return;
    }

    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setNavigationDelegate(NavigationDelegate(
        onPageStarted: (_) => setState(() { _loading = true; _error = false; }),
        onPageFinished: (_) => setState(() => _loading = false),
        onWebResourceError: (_) {
          _ipIdx++;
          if (_ipIdx < _candidateIps.length) {
            // Try next IP silently
            setState(() { _loading = true; _error = false; });
            _controller!.loadRequest(Uri.parse('http://${_candidateIps[_ipIdx]}/'));
          } else {
            setState(() { _loading = false; _error = true; });
          }
        },
      ))
      ..loadRequest(Uri.parse('http://${_candidateIps[0]}/'));
  }

  void _reload() {
    _ipIdx = 0;
    setState(() { _loading = true; _error = false; });
    _controller?.loadRequest(Uri.parse('http://${_candidateIps[0]}/'));
  }

  Future<void> _openInBrowser() async {
    final url = Uri.parse('http://${_candidateIps[_ipIdx]}/setup');
    if (!await launchUrl(url, mode: LaunchMode.externalApplication)) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Ne mogu da otvorim $url')),
      );
    }
  }

  Widget _buildDesktopFallback() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.open_in_new, size: 64, color: Colors.grey[700]),
            const SizedBox(height: 20),
            const Text(
              'WiFi setup u browseru',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 12),
            Text(
              'Embedded webview ne radi na desktop verziji.\n'
              'Konektuj se na BLASTGATE_HUB WiFi, pa otvori hub setup u browseru:',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 14, color: Colors.grey[400], height: 1.6),
            ),
            const SizedBox(height: 24),
            ElevatedButton.icon(
              onPressed: _openInBrowser,
              icon: const Icon(Icons.language),
              label: Text('Otvori http://${_candidateIps[_ipIdx]}/setup'),
              style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFF89b4fa),
                foregroundColor: const Color(0xFF1e1e2e),
                padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 24),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
              ),
            ),
            const SizedBox(height: 12),
            Text(
              'Ili koristi Soft AP tab — radi nativno bez browsera.',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 12, color: Colors.grey[600]),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (_isDesktop) return _buildDesktopFallback();
    if (_error) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(Icons.wifi_off, size: 64, color: Colors.grey[700]),
              const SizedBox(height: 20),
              const Text(
                'Hub nije dostupan',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 12),
              Text(
                'Konektuj se na WiFi mrežu:\n\nSSID: BLASTGATE_HUB\nLozinka: 12345678\n\nZatim se vrati ovde.',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 14, color: Colors.grey[400], height: 1.6),
              ),
              const SizedBox(height: 32),
              ElevatedButton.icon(
                onPressed: _reload,
                icon: const Icon(Icons.refresh),
                label: const Text('Pokušaj ponovo'),
                style: ElevatedButton.styleFrom(
                  backgroundColor: const Color(0xFF89b4fa),
                  foregroundColor: const Color(0xFF1e1e2e),
                  padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 24),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                ),
              ),
            ],
          ),
        ),
      );
    }

    return Stack(
      children: [
        if (_controller != null) WebViewWidget(controller: _controller!),
        if (_loading)
          const LinearProgressIndicator(
            valueColor: AlwaysStoppedAnimation<Color>(Color(0xFF89b4fa)),
          ),
      ],
    );
  }
}


// ============ Soft AP Tab ============
// Scans networks via GET /wifi_scan, sends credentials via POST /wifi_set.
// No BLE required — works purely over WiFi (AP or LAN).

enum _SoftApState { idle, scanning, enterCredentials, sending, success, error }

class _SoftApTab extends StatefulWidget {
  const _SoftApTab();
  @override
  State<_SoftApTab> createState() => _SoftApTabState();
}

class _SoftApTabState extends State<_SoftApTab> {
  _SoftApState _state = _SoftApState.idle;
  String _statusMsg = '';
  String _errorMsg = '';
  List<Map<String, dynamic>> _networks = [];
  String? _selectedSsid;
  bool _obscurePassword = true;

  final TextEditingController _ssidController = TextEditingController();
  final TextEditingController _passwordController = TextEditingController();

  @override
  void initState() {
    super.initState();
    _scanNetworks();
  }

  @override
  void dispose() {
    _ssidController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  String get _hubIp => context.read<HubService>().config.hubApIp;

  Future<void> _scanNetworks() async {
    setState(() {
      _state = _SoftApState.scanning;
      _statusMsg = 'Scanning for WiFi networks...';
      _errorMsg = '';
      _networks = [];
    });

    try {
      final client = HttpClient();
      client.connectionTimeout = const Duration(seconds: 10);
      final req = await client.getUrl(Uri.parse('http://$_hubIp/wifi_scan'))
          .timeout(const Duration(seconds: 12));
      req.headers.set('User-Agent', 'BlastgateApp/1.0');
      final resp = await req.close().timeout(const Duration(seconds: 12));
      final body = await resp.transform(utf8.decoder).join();
      client.close();

      if (!mounted) return;
      final List<dynamic> list = jsonDecode(body) as List;
      final nets = list.cast<Map<String, dynamic>>();

      setState(() {
        _networks = nets;
        _state = _SoftApState.enterCredentials;
        _statusMsg = 'Found ${nets.length} network(s)';
        if (nets.isNotEmpty && _ssidController.text.isEmpty) {
          _selectedSsid = nets.first['ssid'] as String?;
          _ssidController.text = _selectedSsid ?? '';
        }
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _state = _SoftApState.enterCredentials;
        _statusMsg = '';
        _errorMsg = 'Could not scan networks.\nMake sure phone is connected to BLASTGATE_HUB.\n($e)';
      });
    }
  }

  Future<void> _sendCredentials() async {
    final ssid = _ssidController.text.trim();
    final password = _passwordController.text;
    if (ssid.isEmpty) {
      setState(() => _errorMsg = 'Enter WiFi name (SSID)');
      return;
    }

    setState(() {
      _state = _SoftApState.sending;
      _errorMsg = '';
    });

    try {
      final client = HttpClient();
      client.connectionTimeout = const Duration(seconds: 10);
      final req = await client.postUrl(Uri.parse('http://$_hubIp/wifi_set'));
      req.headers.contentType = ContentType.json;
      final bodyBytes = utf8.encode(jsonEncode({'ssid': ssid, 'pass': password}));
      req.contentLength = bodyBytes.length;
      req.add(bodyBytes);
      final resp = await req.close().timeout(const Duration(seconds: 10));
      await resp.drain<void>();
      client.close();
      if (!mounted) return;
      setState(() => _state = _SoftApState.success);
    } on SocketException {
      if (!mounted) return;
      setState(() => _state = _SoftApState.success); // hub restarted = success
    } on TimeoutException {
      if (!mounted) return;
      setState(() => _state = _SoftApState.success);
    } catch (e) {
      if (!mounted) return;
      final msg = e.toString().toLowerCase();
      if (msg.contains('reset') || msg.contains('closed') || msg.contains('broken pipe')) {
        setState(() => _state = _SoftApState.success);
      } else {
        setState(() {
          _state = _SoftApState.error;
          _errorMsg = 'Error: $e';
        });
      }
    }
  }

  void _reset() {
    setState(() {
      _errorMsg = '';
      _ssidController.clear();
      _passwordController.clear();
    });
    _scanNetworks();
  }

  @override
  Widget build(BuildContext context) {
    switch (_state) {
      case _SoftApState.idle:
      case _SoftApState.scanning:
        return _buildScanning();
      case _SoftApState.enterCredentials:
        return _buildForm();
      case _SoftApState.sending:
        return _buildSending();
      case _SoftApState.success:
        return _buildSuccess();
      case _SoftApState.error:
        return _buildError();
    }
  }

  Widget _buildScanning() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const SizedBox(width: 64, height: 64,
                child: CircularProgressIndicator(strokeWidth: 3, color: Color(0xFF3A7BD5))),
            const SizedBox(height: 24),
            const Text('Scanning for networks...', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            Text('Make sure phone is connected to BLASTGATE_HUB\n(password: 12345678)',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 12, color: Colors.grey[500])),
          ],
        ),
      ),
    );
  }

  Widget _buildForm() {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // Instructions banner
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            decoration: BoxDecoration(
              color: const Color(0xFF3A7BD5).withValues(alpha: 0.08),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: const Color(0xFF3A7BD5).withValues(alpha: 0.25)),
            ),
            child: Row(
              children: [
                const Icon(Icons.wifi_tethering, color: Color(0xFF3A7BD5), size: 18),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    'Connect phone to BLASTGATE_HUB (pass: 12345678) before scanning.',
                    style: TextStyle(fontSize: 12, color: Colors.grey[300]),
                  ),
                ),
                TextButton(
                  onPressed: _scanNetworks,
                  style: TextButton.styleFrom(
                    padding: const EdgeInsets.symmetric(horizontal: 8),
                    foregroundColor: const Color(0xFF3A7BD5),
                  ),
                  child: const Text('Scan', style: TextStyle(fontSize: 12)),
                ),
              ],
            ),
          ),
          if (_statusMsg.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(_statusMsg, style: TextStyle(fontSize: 12, color: Colors.grey[500])),
          ],
          const SizedBox(height: 16),

          // SSID: dropdown if we have results, text field always
          if (_networks.isNotEmpty) ...[
            const Text('Select network:', style: TextStyle(fontSize: 13, color: Colors.grey)),
            const SizedBox(height: 6),
            Container(
              decoration: BoxDecoration(
                color: const Color(0xFF1C1F24),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: const Color(0xFF2A2F35)),
              ),
              child: DropdownButtonHideUnderline(
                child: DropdownButton<String>(
                  value: _selectedSsid,
                  isExpanded: true,
                  dropdownColor: const Color(0xFF1C1F24),
                  padding: const EdgeInsets.symmetric(horizontal: 14),
                  borderRadius: BorderRadius.circular(12),
                  items: _networks.map((n) {
                    final ssid = n['ssid'] as String? ?? '';
                    final rssi = n['rssi'] as int? ?? 0;
                    return DropdownMenuItem(
                      value: ssid,
                      child: Row(
                        children: [
                          const Icon(Icons.wifi, size: 16, color: Color(0xFF3A7BD5)),
                          const SizedBox(width: 8),
                          Expanded(child: Text(ssid, overflow: TextOverflow.ellipsis)),
                          Text('$rssi dBm', style: TextStyle(fontSize: 11, color: Colors.grey[500])),
                        ],
                      ),
                    );
                  }).toList(),
                  onChanged: (v) {
                    setState(() { _selectedSsid = v; _ssidController.text = v ?? ''; });
                  },
                ),
              ),
            ),
            const SizedBox(height: 8),
            Text('Or type manually:', style: TextStyle(fontSize: 12, color: Colors.grey[600])),
          ],

          const SizedBox(height: 6),
          TextField(
            controller: _ssidController,
            textInputAction: TextInputAction.next,
            autocorrect: false,
            enableSuggestions: false,
            textCapitalization: TextCapitalization.none,
            onChanged: (v) => setState(() => _selectedSsid = v),
            decoration: InputDecoration(
              labelText: 'WiFi Name (SSID)',
              prefixIcon: const Icon(Icons.wifi, color: Color(0xFF3A7BD5)),
              filled: true,
              fillColor: const Color(0xFF1C1F24),
              border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: const BorderSide(color: Color(0xFF2A2F35))),
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _passwordController,
            obscureText: _obscurePassword,
            textInputAction: TextInputAction.done,
            autocorrect: false,
            enableSuggestions: false,
            textCapitalization: TextCapitalization.none,
            onSubmitted: (_) => _sendCredentials(),
            decoration: InputDecoration(
              labelText: 'WiFi Password',
              prefixIcon: const Icon(Icons.lock, color: Color(0xFF3A7BD5)),
              suffixIcon: IconButton(
                icon: Icon(
                  _obscurePassword ? Icons.visibility_off : Icons.visibility,
                  color: Colors.grey[600],
                ),
                onPressed: () => setState(() => _obscurePassword = !_obscurePassword),
              ),
              filled: true,
              fillColor: const Color(0xFF1C1F24),
              border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: const BorderSide(color: Color(0xFF2A2F35))),
            ),
          ),
          if (_errorMsg.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(_errorMsg,
                style: const TextStyle(color: Color(0xFFE74C3C), fontSize: 12)),
          ],
          const SizedBox(height: 24),
          ElevatedButton.icon(
            onPressed: _sendCredentials,
            icon: const Icon(Icons.send),
            label: const Text('Send to Hub'),
            style: ElevatedButton.styleFrom(
              backgroundColor: const Color(0xFF2ECC71),
              foregroundColor: Colors.white,
              padding: const EdgeInsets.symmetric(vertical: 16),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSending() {
    return const Center(
      child: Padding(
        padding: EdgeInsets.all(32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            SizedBox(width: 64, height: 64,
                child: CircularProgressIndicator(strokeWidth: 3, color: Color(0xFF2ECC71))),
            SizedBox(height: 32),
            Text('Sending credentials...', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            SizedBox(height: 12),
            Text('Hub will restart and connect to WiFi',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 13, color: Colors.grey)),
          ],
        ),
      ),
    );
  }

  Widget _buildSuccess() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              padding: const EdgeInsets.all(24),
              decoration: BoxDecoration(
                  color: const Color(0xFF2ECC71).withValues(alpha: 0.1), shape: BoxShape.circle),
              child: const Icon(Icons.check_circle, size: 64, color: Color(0xFF2ECC71)),
            ),
            const SizedBox(height: 32),
            const Text('Credentials Sent!',
                style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
            const SizedBox(height: 12),
            Text(
              'Hub is restarting and connecting to WiFi.\n\nReconnect your phone to your home network.',
              textAlign: TextAlign.center,
              style: TextStyle(color: Colors.grey[500]),
            ),
            const SizedBox(height: 40),
            ElevatedButton.icon(
              onPressed: _reset,
              icon: const Icon(Icons.add),
              label: const Text('Set up another device'),
              style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFF3A7BD5),
                foregroundColor: Colors.white,
                padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 24),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildError() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              padding: const EdgeInsets.all(24),
              decoration: BoxDecoration(
                  color: const Color(0xFFE74C3C).withValues(alpha: 0.1), shape: BoxShape.circle),
              child: const Icon(Icons.error_outline, size: 64, color: Color(0xFFE74C3C)),
            ),
            const SizedBox(height: 32),
            Text(_errorMsg,
                textAlign: TextAlign.center,
                style: const TextStyle(color: Color(0xFFE74C3C))),
            const SizedBox(height: 40),
            ElevatedButton.icon(
              onPressed: _reset,
              icon: const Icon(Icons.refresh),
              label: const Text('Try again'),
              style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFF3A7BD5),
                foregroundColor: Colors.white,
                padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 24),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
