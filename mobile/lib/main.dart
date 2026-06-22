import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'package:url_launcher/url_launcher.dart';
import 'services/hub_service.dart';
import 'models/node_status.dart';
import 'screens/ota_screen.dart';
import 'screens/ble_prov_screen.dart';

/// True on desktop platforms where `webview_flutter` is NOT supported.
/// On these we fall back to launching the system browser.
bool get _isDesktop =>
    !kIsWeb && (Platform.isWindows || Platform.isLinux || Platform.isMacOS);

void main() {
  runApp(
    ChangeNotifierProvider(
      create: (_) => HubService()..init(),
      child: const BlastgateApp(),
    ),
  );
}

class BlastgateApp extends StatelessWidget {
  const BlastgateApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Blastgate',
      debugShowCheckedModeBanner: false,
      theme: ThemeData.dark().copyWith(
        scaffoldBackgroundColor: const Color(0xFF121418),
        primaryColor: const Color(0xFF3A7BD5),
        colorScheme: const ColorScheme.dark(
          primary: Color(0xFF3A7BD5),
          secondary: Color(0xFF2A9FD6),
          surface: Color(0xFF1C1F24),
          error: Color(0xFFE74C3C),
        ),
        appBarTheme: const AppBarTheme(
          backgroundColor: Color(0xFF1C1F24),
          elevation: 0,
        ),
        cardTheme: CardThemeData(
          color: const Color(0xFF1C1F24),
          elevation: 0,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
          ),
        ),
      ),
      home: const MainScreen(),
    );
  }
}

// ============ Main Screen ============

class MainScreen extends StatelessWidget {
  const MainScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<HubService>(
      builder: (context, hub, _) {
        return Scaffold(
          appBar: AppBar(
            leading: Builder(
              builder: (context) => IconButton(
                icon: const Icon(Icons.menu, color: Colors.white),
                onPressed: () => Scaffold.of(context).openDrawer(),
              ),
            ),
            title: const Text(
              'Blastgate',
              style: TextStyle(
                fontWeight: FontWeight.bold,
                fontSize: 22,
                color: Colors.white,
              ),
            ),
            actions: [
              // Overdrive indicator
              if (hub.isOverdrive)
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  margin: const EdgeInsets.only(right: 8),
                  decoration: BoxDecoration(
                    color: const Color(0xFFE74C3C).withValues(alpha: 0.2),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: const Text(
                    'OVERDRIVE',
                    style: TextStyle(
                      color: Color(0xFFE74C3C),
                      fontWeight: FontWeight.bold,
                      fontSize: 11,
                    ),
                  ),
                ),
              // Connection status
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                margin: const EdgeInsets.only(right: 16),
                decoration: BoxDecoration(
                  color: hub.isConnected
                      ? const Color(0xFF2ECC71).withValues(alpha: 0.2)
                      : const Color(0xFFE74C3C).withValues(alpha: 0.2),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    if (hub.connectionStatus == ConnectionStatus.connecting)
                      const SizedBox(
                        width: 12,
                        height: 12,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: Colors.white54,
                        ),
                      )
                    else
                      Icon(
                        hub.isConnected ? Icons.wifi : Icons.wifi_off,
                        size: 14,
                        color: hub.isConnected
                            ? const Color(0xFF2ECC71)
                            : const Color(0xFFE74C3C),
                      ),
                    const SizedBox(width: 6),
                    Text(
                      hub.isConnected ? 'ONLINE' : 'OFFLINE',
                      style: TextStyle(
                        color: hub.isConnected
                            ? const Color(0xFF2ECC71)
                            : const Color(0xFFE74C3C),
                        fontWeight: FontWeight.w600,
                        fontSize: 13,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          drawer: _buildDrawer(context, hub),
          body: Column(
            children: [
              // Error banner
              if (hub.lastError.isNotEmpty && !hub.isConnected)
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(12),
                  color: const Color(0xFFE74C3C).withValues(alpha: 0.1),
                  child: Row(
                    children: [
                      const Icon(Icons.error_outline, color: Color(0xFFE74C3C), size: 18),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          hub.lastError,
                          style: const TextStyle(color: Color(0xFFE74C3C), fontSize: 13),
                        ),
                      ),
                      TextButton(
                        onPressed: () => hub.fetchStatus(),
                        child: const Text('Retry'),
                      ),
                    ],
                  ),
                ),
              // Nodes
              Expanded(
                child: hub.visibleNodes.isEmpty
                    ? _buildEmptyState(hub)
                    : _buildNodeGrid(context, hub),
              ),
            ],
          ),
          floatingActionButton: FloatingActionButton(
            onPressed: () => hub.fullRefresh(),
            backgroundColor: const Color(0xFF3A7BD5),
            child: const Icon(Icons.refresh),
          ),
        );
      },
    );
  }

  Widget _buildDrawer(BuildContext context, HubService hub) {
    return Drawer(
      backgroundColor: const Color(0xFF1C1F24),
      child: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Header
            Padding(
              padding: const EdgeInsets.all(24),
              child: Row(
                children: [
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: const Color(0xFF3A7BD5).withValues(alpha: 0.1),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: const Icon(Icons.hub, color: Color(0xFF3A7BD5), size: 28),
                  ),
                  const SizedBox(width: 16),
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Blastgate',
                        style: TextStyle(
                          fontSize: 20,
                          fontWeight: FontWeight.bold,
                          color: Colors.grey[100],
                        ),
                      ),
                      Text(
                        'v1.0.0',
                        style: TextStyle(fontSize: 12, color: Colors.grey[500]),
                      ),
                    ],
                  ),
                ],
              ),
            ),
            const Divider(color: Color(0xFF2A2F35), height: 1),
            const SizedBox(height: 8),

            // Menu items
            _buildDrawerItem(
              icon: Icons.settings_ethernet,
              title: 'Connect Hub',
              subtitle: 'UDP connection settings',
              onTap: () {
                Navigator.pop(context);
                Navigator.push(
                  context,
                  MaterialPageRoute(builder: (_) => const ConnectHubScreen()),
                );
              },
            ),
            _buildDrawerItem(
              icon: Icons.wifi,
              title: 'WiFi Settings',
              subtitle: 'Hub WiFi configuration',
              onTap: () {
                Navigator.pop(context);
                Navigator.push(
                  context,
                  MaterialPageRoute(builder: (_) => const WifiSettingsScreen()),
                );
              },
            ),
            _buildDrawerItem(
              icon: Icons.wifi_find,
              title: 'WiFi Provisioning',
              subtitle: 'Web portal or Soft AP setup',
              onTap: () {
                Navigator.pop(context);
                Navigator.push(
                  context,
                  MaterialPageRoute(builder: (_) => const ProvisioningScreen()),
                );
              },
            ),
            _buildDrawerItem(
              icon: Icons.bluetooth,
              title: 'BLE Provisioning',
              subtitle: 'Set WiFi via Bluetooth (Android/iOS)',
              onTap: () {
                Navigator.pop(context);
                Navigator.push(
                  context,
                  MaterialPageRoute(builder: (_) => const BleProvScreen()),
                );
              },
            ),
            _buildDrawerItem(
              icon: Icons.tune,
              title: 'Settings',
              subtitle: 'App preferences',
              onTap: () {
                Navigator.pop(context);
                Navigator.push(
                  context,
                  MaterialPageRoute(builder: (_) => const AppSettingsScreen()),
                );
              },
            ),
            _buildDrawerItem(
              icon: Icons.system_update,
              title: 'Firmware Update',
              subtitle: 'Check for hub firmware',
              onTap: () {
                Navigator.pop(context);
                Navigator.push(
                  context,
                  MaterialPageRoute(builder: (_) => const OtaScreen()),
                );
              },
            ),

            const Spacer(),
            const Divider(color: Color(0xFF2A2F35), height: 1),

            // About
            _buildDrawerItem(
              icon: Icons.info_outline,
              title: 'About',
              subtitle: 'Blastgate v1.0.0',
              onTap: () => Navigator.pop(context),
            ),
            const SizedBox(height: 16),
          ],
        ),
      ),
    );
  }

  Widget _buildDrawerItem({
    required IconData icon,
    required String title,
    required String subtitle,
    required VoidCallback onTap,
  }) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
          child: Row(
            children: [
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: const Color(0xFF2A2F35),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(icon, color: const Color(0xFF3A7BD5), size: 22),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: const TextStyle(
                        fontSize: 15,
                        fontWeight: FontWeight.w600,
                        color: Colors.white,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      subtitle,
                      style: TextStyle(fontSize: 12, color: Colors.grey[500]),
                    ),
                  ],
                ),
              ),
              Icon(Icons.chevron_right, color: Colors.grey[600], size: 20),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildEmptyState(HubService hub) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(
            hub.isConnected ? Icons.sensors_off : Icons.wifi_off,
            size: 80,
            color: Colors.grey[700],
          ),
          const SizedBox(height: 24),
          Text(
            hub.isConnected ? 'No online nodes' : 'Not connected to hub',
            style: TextStyle(
              fontSize: 18,
              fontWeight: FontWeight.w600,
              color: Colors.grey[400],
            ),
          ),
          const SizedBox(height: 8),
          Text(
            hub.isConnected
                ? 'Waiting for nodes to come online'
                : 'Open menu to configure connection',
            style: TextStyle(fontSize: 14, color: Colors.grey[600]),
          ),
        ],
      ),
    );
  }

  Widget _buildNodeGrid(BuildContext context, HubService hub) {
    return GridView.builder(
      padding: const EdgeInsets.all(16),
      gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
        crossAxisCount: 2,
        childAspectRatio: 1.3,
        crossAxisSpacing: 12,
        mainAxisSpacing: 12,
      ),
      itemCount: hub.visibleNodes.length,
      itemBuilder: (context, index) {
        final node = hub.visibleNodes[index];
        return _NodeTile(
          node: node,
          onTap: () => _showNodeDetail(context, node),
        );
      },
    );
  }

  void _showNodeDetail(BuildContext context, NodeStatus node) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) => NodeDetailSheet(node: node),
    );
  }
}

// ============ Node Tile ============

class _NodeTile extends StatelessWidget {
  final NodeStatus node;
  final VoidCallback onTap;

  const _NodeTile({required this.node, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final bool isOpen = node.gateOpen ?? false;
    final bool isOnline = node.online;

    return Container(
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: !isOnline
              ? [const Color(0xFF1A1A1A), const Color(0xFF252525)]
              : isOpen
                  ? [const Color(0xFF0F1D12), const Color(0xFF163A22)]
                  : [const Color(0xFF1D0F0F), const Color(0xFF3A1616)],
        ),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: !isOnline
              ? const Color(0xFF3A3A3A)
              : isOpen
                  ? const Color(0xFF2F6A42)
                  : const Color(0xFF6A2F2F),
          width: 1,
        ),
      ),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(16),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Expanded(
                      child: Text(
                        node.displayName,
                        style: TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.bold,
                          color: isOnline ? Colors.white : Colors.grey[500],
                        ),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                    Text(
                      'Open',
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w600,
                        color: Colors.blue[400],
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 2),
                Text(
                  node.id,
                  style: TextStyle(fontSize: 10, color: Colors.grey[600]),
                ),
                const Spacer(),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    // Gate state
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                      decoration: BoxDecoration(
                        color: !isOnline
                            ? Colors.grey.withValues(alpha: 0.2)
                            : isOpen
                                ? const Color(0xFF2ECC71).withValues(alpha: 0.2)
                                : const Color(0xFFE74C3C).withValues(alpha: 0.2),
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: Text(
                        !isOnline ? 'OFFLINE' : node.gateState,
                        style: TextStyle(
                          fontSize: 11,
                          fontWeight: FontWeight.w600,
                          color: !isOnline
                              ? Colors.grey
                              : isOpen
                                  ? const Color(0xFF2ECC71)
                                  : const Color(0xFFE74C3C),
                        ),
                      ),
                    ),
                    // Sensor value
                    if (node.value != null && isOnline)
                      Row(
                        children: [
                          Icon(
                            node.active ? Icons.sensors : Icons.sensors_off,
                            size: 14,
                            color: node.active
                                ? const Color(0xFF2ECC71)
                                : Colors.grey[600],
                          ),
                          const SizedBox(width: 4),
                          Text(
                            node.value!.toStringAsFixed(1),
                            style: TextStyle(
                              fontSize: 12,
                              fontWeight: FontWeight.w500,
                              color: node.active
                                  ? const Color(0xFF2ECC71)
                                  : Colors.grey[500],
                            ),
                          ),
                        ],
                      ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

// ============ Node Detail Sheet ============

class NodeDetailSheet extends StatefulWidget {
  final NodeStatus node;

  const NodeDetailSheet({super.key, required this.node});

  @override
  State<NodeDetailSheet> createState() => _NodeDetailSheetState();
}

class _NodeDetailSheetState extends State<NodeDetailSheet> with SingleTickerProviderStateMixin {
  late TabController _tabController;
  bool _isRenaming = false;
  final _nameController = TextEditingController();

  final _thresholdController = TextEditingController();
  final _holdMsController = TextEditingController();
  final _hbOpenController = TextEditingController();
  final _hbCloseController = TextEditingController();
  bool _isSaving = false;
  bool _isRefreshing = false;
  String _refreshMessage = '';

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 2, vsync: this);
    _nameController.text = widget.node.displayName;
    _loadNodeConfig();

    // Auto-refresh when entering Settings tab
    _tabController.addListener(_onTabChanged);
  }

  void _onTabChanged() {
    if (_tabController.index == 1 && !_tabController.indexIsChanging) {
      // Switched to Settings tab - refresh from hub
      _refreshFromHub();
    }
  }

  void _loadNodeConfig() async {
    final hub = context.read<HubService>();
    final config = await hub.getNodeConfig(widget.node.id);
    if (config != null && mounted) {
      setState(() {
        _thresholdController.text = (config['threshold_on'] ?? 40.0).toString();
        _holdMsController.text = (config['gate_hold_ms'] ?? 5000).toString();
        _hbOpenController.text = (config['hbridge_open_ms'] ?? 2000).toString();
        _hbCloseController.text = (config['hbridge_close_ms'] ?? 2000).toString();
      });
    } else {
      _thresholdController.text = '40.0';
      _holdMsController.text = '5000';
      _hbOpenController.text = '2000';
      _hbCloseController.text = '2000';
    }
  }

  /// Refresh settings from hub (force fetch latest values)
  void _refreshFromHub() async {
    if (_isRefreshing) return;

    setState(() {
      _isRefreshing = true;
      _refreshMessage = 'Refreshing...';
    });

    try {
      final hub = context.read<HubService>();
      // Force a fresh status fetch from hub
      await hub.fetchStatus();

      // Get fresh node config
      final config = await hub.getNodeConfig(widget.node.id);

      if (!mounted) return;

      if (config != null) {
        setState(() {
          _thresholdController.text = (config['threshold_on'] ?? 40.0).toString();
          _holdMsController.text = (config['gate_hold_ms'] ?? 5000).toString();
          _hbOpenController.text = (config['hbridge_open_ms'] ?? 2000).toString();
          _hbCloseController.text = (config['hbridge_close_ms'] ?? 2000).toString();
          _refreshMessage = 'Loaded from hub';
          _isRefreshing = false;
        });
      } else {
        setState(() {
          _refreshMessage = 'No config from hub';
          _isRefreshing = false;
        });
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _refreshMessage = 'Refresh failed: $e';
        _isRefreshing = false;
      });
    }
  }

  @override
  void dispose() {
    _tabController.removeListener(_onTabChanged);
    _tabController.dispose();
    _nameController.dispose();
    _thresholdController.dispose();
    _holdMsController.dispose();
    _hbOpenController.dispose();
    _hbCloseController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final hub = context.watch<HubService>();
    final node = hub.nodes.firstWhere(
      (n) => n.id == widget.node.id,
      orElse: () => widget.node,
    );

    return Container(
      height: MediaQuery.of(context).size.height * 0.85,
      decoration: const BoxDecoration(
        color: Color(0xFF1C1F24),
        borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
      ),
      child: Column(
        children: [
          // Handle
          Container(
            margin: const EdgeInsets.only(top: 12),
            width: 40,
            height: 4,
            decoration: BoxDecoration(
              color: Colors.grey[700],
              borderRadius: BorderRadius.circular(2),
            ),
          ),

          // Header with rename
          Padding(
            padding: const EdgeInsets.all(20),
            child: Row(
              children: [
                Expanded(
                  child: _isRenaming
                      ? TextField(
                          controller: _nameController,
                          autofocus: true,
                          style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
                          decoration: const InputDecoration(border: InputBorder.none, contentPadding: EdgeInsets.zero),
                          onSubmitted: (_) => _saveRename(hub),
                        )
                      : GestureDetector(
                          onTap: () => setState(() => _isRenaming = true),
                          child: Row(
                            children: [
                              Text(node.displayName, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
                              const SizedBox(width: 8),
                              Icon(Icons.edit, size: 16, color: Colors.grey[500]),
                            ],
                          ),
                        ),
                ),
                if (_isRenaming)
                  IconButton(icon: const Icon(Icons.check, color: Color(0xFF2ECC71)), onPressed: () => _saveRename(hub)),
              ],
            ),
          ),

          // Status cards
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 20),
            child: Row(
              children: [
                Expanded(child: _StatusCard(label: 'Status', value: node.online ? 'ONLINE' : 'OFFLINE', color: node.online ? const Color(0xFF2ECC71) : Colors.grey)),
                const SizedBox(width: 12),
                Expanded(child: _StatusCard(label: 'Gate', value: node.gateState, color: node.gateOpen == true ? const Color(0xFF2ECC71) : const Color(0xFFE74C3C))),
                const SizedBox(width: 12),
                Expanded(child: _StatusCard(label: 'Relay', value: hub.hubStatus?.relayState == true ? 'ON' : 'OFF', color: hub.hubStatus?.relayState == true ? const Color(0xFF2ECC71) : Colors.grey)),
              ],
            ),
          ),

          const SizedBox(height: 16),

          // Tab bar
          Container(
            margin: const EdgeInsets.symmetric(horizontal: 20),
            decoration: BoxDecoration(
              color: const Color(0xFF2A2F35),
              borderRadius: BorderRadius.circular(12),
            ),
            child: TabBar(
              controller: _tabController,
              indicator: BoxDecoration(
                color: const Color(0xFF3A7BD5),
                borderRadius: BorderRadius.circular(12),
              ),
              indicatorSize: TabBarIndicatorSize.tab,
              dividerColor: Colors.transparent,
              labelColor: Colors.white,
              unselectedLabelColor: Colors.grey[500],
              tabs: const [
                Tab(text: 'Control'),
                Tab(text: 'Settings'),
              ],
            ),
          ),

          const SizedBox(height: 16),

          // Tab content
          Expanded(
            child: TabBarView(
              controller: _tabController,
              children: [
                _buildControlTab(hub, node),
                _buildSettingsTab(hub),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildControlTab(HubService hub, NodeStatus node) {
    return SingleChildScrollView(
      padding: const EdgeInsets.symmetric(horizontal: 20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Sensor value
          if (node.value != null)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: const Color(0xFF2A2F35),
                borderRadius: BorderRadius.circular(12),
              ),
              child: Row(
                children: [
                  Icon(
                    node.active ? Icons.sensors : Icons.sensors_off,
                    color: node.active ? const Color(0xFF2ECC71) : Colors.grey,
                    size: 32,
                  ),
                  const SizedBox(width: 16),
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Sensor Value', style: TextStyle(fontSize: 12, color: Colors.grey[500])),
                      Text(
                        node.value!.toStringAsFixed(1),
                        style: TextStyle(
                          fontSize: 24,
                          fontWeight: FontWeight.bold,
                          color: node.active ? const Color(0xFF2ECC71) : Colors.white,
                        ),
                      ),
                    ],
                  ),
                  const Spacer(),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                    decoration: BoxDecoration(
                      color: node.active ? const Color(0xFF2ECC71).withValues(alpha: 0.2) : Colors.grey.withValues(alpha: 0.2),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Text(
                      node.active ? 'ACTIVE' : 'INACTIVE',
                      style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: node.active ? const Color(0xFF2ECC71) : Colors.grey),
                    ),
                  ),
                ],
              ),
            ),

          const SizedBox(height: 20),

          // Gate control
          Text('Gate Control', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: Colors.grey[400])),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(child: _GateButton(label: 'AUTO', icon: Icons.auto_mode, isActive: node.override == 0, onTap: () => hub.sendGateCommand(node.id, 'auto'))),
              const SizedBox(width: 12),
              Expanded(child: _GateButton(label: 'OPEN', icon: Icons.lock_open, color: const Color(0xFF2ECC71), isActive: node.override == 1, onTap: () => hub.sendGateCommand(node.id, 'open'))),
              const SizedBox(width: 12),
              Expanded(child: _GateButton(label: 'CLOSE', icon: Icons.lock, color: const Color(0xFFE74C3C), isActive: node.override == 2, onTap: () => hub.sendGateCommand(node.id, 'close'))),
            ],
          ),

          const SizedBox(height: 24),

          // Relay control
          Text('Relay Control', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: Colors.grey[400])),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(child: _GateButton(label: 'AUTO', icon: Icons.auto_mode, isActive: false, onTap: () => hub.setRelay('auto'))),
              const SizedBox(width: 12),
              Expanded(child: _GateButton(label: 'ON', icon: Icons.power, color: const Color(0xFF2ECC71), isActive: hub.hubStatus?.relayState == true, onTap: () => hub.setRelay('on'))),
              const SizedBox(width: 12),
              Expanded(child: _GateButton(label: 'OFF', icon: Icons.power_off, color: const Color(0xFFE74C3C), isActive: hub.hubStatus?.relayState == false, onTap: () => hub.setRelay('off'))),
            ],
          ),

          const SizedBox(height: 32),
        ],
      ),
    );
  }

  Widget _buildSettingsTab(HubService hub) {
    return SingleChildScrollView(
      padding: const EdgeInsets.symmetric(horizontal: 20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Refresh button and message
          Row(
            children: [
              Expanded(
                child: Text(
                  _refreshMessage,
                  style: TextStyle(
                    fontSize: 12,
                    color: _refreshMessage.contains('failed')
                        ? const Color(0xFFE74C3C)
                        : Colors.grey[500],
                  ),
                ),
              ),
              TextButton.icon(
                onPressed: _isRefreshing ? null : _refreshFromHub,
                icon: _isRefreshing
                    ? const SizedBox(
                        width: 14,
                        height: 14,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.refresh, size: 18),
                label: const Text('Refresh'),
                style: TextButton.styleFrom(
                  foregroundColor: const Color(0xFF3A7BD5),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),

          _buildSettingField(
            label: 'Threshold',
            hint: 'Activation threshold (e.g. 40.0)',
            controller: _thresholdController,
            suffix: '',
            icon: Icons.trending_up,
          ),
          _buildSettingField(
            label: 'Hold Time',
            hint: 'Gate/Relay hold time in ms',
            controller: _holdMsController,
            suffix: 'ms',
            icon: Icons.timer,
          ),
          _buildSettingField(
            label: 'Gate Open Time',
            hint: 'H-bridge open duration (e.g. 2000)',
            controller: _hbOpenController,
            suffix: 'ms',
            icon: Icons.lock_open,
          ),
          _buildSettingField(
            label: 'Gate Close Time',
            hint: 'H-bridge close duration (e.g. 2000)',
            controller: _hbCloseController,
            suffix: 'ms',
            icon: Icons.lock,
          ),

          const SizedBox(height: 24),

          // Save button
          SizedBox(
            width: double.infinity,
            child: ElevatedButton.icon(
              onPressed: _isSaving ? null : () => _saveSettings(hub),
              icon: _isSaving
                  ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.save),
              label: const Text('Save Settings'),
              style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFF2ECC71),
                foregroundColor: Colors.white,
                padding: const EdgeInsets.symmetric(vertical: 16),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
              ),
            ),
          ),

          const SizedBox(height: 32),
        ],
      ),
    );
  }

  Widget _buildSettingField({
    required String label,
    required String hint,
    required TextEditingController controller,
    required String suffix,
    required IconData icon,
  }) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w500, color: Colors.grey[400])),
          const SizedBox(height: 8),
          TextField(
            controller: controller,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            style: const TextStyle(color: Colors.white),
            decoration: InputDecoration(
              hintText: hint,
              hintStyle: TextStyle(color: Colors.grey[600]),
              prefixIcon: Icon(icon, color: const Color(0xFF3A7BD5), size: 20),
              suffixText: suffix,
              suffixStyle: TextStyle(color: Colors.grey[500]),
              filled: true,
              fillColor: const Color(0xFF2A2F35),
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide.none),
              contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
            ),
          ),
        ],
      ),
    );
  }

  void _saveRename(HubService hub) async {
    final newName = _nameController.text.trim();
    if (newName.isNotEmpty && newName != widget.node.displayName) {
      await hub.renameNode(widget.node.id, newName);
    }
    setState(() => _isRenaming = false);
  }

  void _saveSettings(HubService hub) async {
    setState(() => _isSaving = true);

    final success = await hub.setNodeConfig(
      nodeId: widget.node.id,
      threshold: double.tryParse(_thresholdController.text),
      holdMs: int.tryParse(_holdMsController.text),
      hbridgeOpenMs: int.tryParse(_hbOpenController.text),
      hbridgeCloseMs: int.tryParse(_hbCloseController.text),
    );

    if (!mounted) return;
    setState(() => _isSaving = false);

    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(success ? 'Settings saved to hub!' : 'Failed to save settings'),
        backgroundColor: success ? const Color(0xFF2ECC71) : const Color(0xFFE74C3C),
      ),
    );
  }
}

class _StatusCard extends StatelessWidget {
  final String label;
  final String value;
  final Color color;

  const _StatusCard({required this.label, required this.value, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withValues(alpha: 0.3)),
      ),
      child: Column(
        children: [
          Text(label, style: TextStyle(fontSize: 11, color: Colors.grey[500])),
          const SizedBox(height: 4),
          Text(value, style: TextStyle(fontSize: 14, fontWeight: FontWeight.bold, color: color)),
        ],
      ),
    );
  }
}

class _GateButton extends StatelessWidget {
  final String label;
  final IconData icon;
  final Color? color;
  final bool isActive;
  final VoidCallback onTap;

  const _GateButton({required this.label, required this.icon, this.color, required this.isActive, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final buttonColor = color ?? const Color(0xFF3A7BD5);
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 16),
          decoration: BoxDecoration(
            color: buttonColor.withValues(alpha: isActive ? 0.3 : 0.1),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: buttonColor.withValues(alpha: isActive ? 0.8 : 0.3), width: isActive ? 2 : 1),
          ),
          child: Column(
            children: [
              Icon(icon, color: buttonColor, size: 24),
              const SizedBox(height: 8),
              Text(label, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: buttonColor)),
            ],
          ),
        ),
      ),
    );
  }
}

// ============ Connect Hub Screen ============

class ConnectHubScreen extends StatefulWidget {
  const ConnectHubScreen({super.key});

  @override
  State<ConnectHubScreen> createState() => _ConnectHubScreenState();
}

class _ConnectHubScreenState extends State<ConnectHubScreen> {
  final _ipController = TextEditingController();
  final _portController = TextEditingController();
  List<String> _discoveredHubs = [];
  bool _isScanning = false;
  bool _isTesting = false;
  String? _testResult;

  @override
  void initState() {
    super.initState();
    final hub = context.read<HubService>();
    _ipController.text = hub.config.preferredHubIp.isEmpty
        ? hub.config.hubLanIp
        : hub.config.preferredHubIp;
    _portController.text = hub.config.udpPort.toString();
  }

  @override
  void dispose() {
    _ipController.dispose();
    _portController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Connect Hub'),
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // Auto discover
          _buildSection(
            title: 'Auto Discover',
            child: Column(
              children: [
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton.icon(
                    onPressed: _isScanning ? null : _scanForHubs,
                    icon: _isScanning
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.search),
                    label: Text(_isScanning ? 'Scanning...' : 'Scan Network'),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: const Color(0xFF3A7BD5),
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 14),
                    ),
                  ),
                ),
                if (_discoveredHubs.isNotEmpty) ...[
                  const SizedBox(height: 16),
                  ...List.generate(_discoveredHubs.length, (i) {
                    final ip = _discoveredHubs[i];
                    return ListTile(
                      leading: const Icon(Icons.hub, color: Color(0xFF3A7BD5)),
                      title: Text(ip),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: () {
                        _ipController.text = ip;
                        setState(() {});
                      },
                    );
                  }),
                ],
              ],
            ),
          ),

          const SizedBox(height: 24),

          // Manual config
          _buildSection(
            title: 'Manual Configuration',
            child: Column(
              children: [
                TextField(
                  controller: _ipController,
                  decoration: _inputDecoration('Hub IP Address'),
                  keyboardType: TextInputType.number,
                ),
                const SizedBox(height: 16),
                TextField(
                  controller: _portController,
                  decoration: _inputDecoration('UDP Port'),
                  keyboardType: TextInputType.number,
                ),
                const SizedBox(height: 16),
                Row(
                  children: [
                    Expanded(
                      child: OutlinedButton.icon(
                        onPressed: _isTesting ? null : _testConnection,
                        icon: _isTesting
                            ? const SizedBox(
                                width: 16,
                                height: 16,
                                child: CircularProgressIndicator(strokeWidth: 2),
                              )
                            : const Icon(Icons.wifi_find),
                        label: const Text('Test'),
                        style: OutlinedButton.styleFrom(
                          padding: const EdgeInsets.symmetric(vertical: 14),
                        ),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: ElevatedButton.icon(
                        onPressed: _saveConfig,
                        icon: const Icon(Icons.save),
                        label: const Text('Save'),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: const Color(0xFF2ECC71),
                          foregroundColor: Colors.white,
                          padding: const EdgeInsets.symmetric(vertical: 14),
                        ),
                      ),
                    ),
                  ],
                ),
                if (_testResult != null) ...[
                  const SizedBox(height: 16),
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: _testResult!.contains('Success')
                          ? const Color(0xFF2ECC71).withValues(alpha: 0.1)
                          : const Color(0xFFE74C3C).withValues(alpha: 0.1),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Row(
                      children: [
                        Icon(
                          _testResult!.contains('Success')
                              ? Icons.check_circle
                              : Icons.error,
                          color: _testResult!.contains('Success')
                              ? const Color(0xFF2ECC71)
                              : const Color(0xFFE74C3C),
                        ),
                        const SizedBox(width: 12),
                        Text(_testResult!),
                      ],
                    ),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSection({required String title, required Widget child}) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          style: const TextStyle(
            fontSize: 16,
            fontWeight: FontWeight.bold,
          ),
        ),
        const SizedBox(height: 12),
        // Material (not bare Container) so child ListTiles get visible ink
        // ripples + background. ClipRRect handles the rounded corners.
        ClipRRect(
          borderRadius: BorderRadius.circular(12),
          child: Material(
            color: const Color(0xFF1C1F24),
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: child,
            ),
          ),
        ),
      ],
    );
  }

  InputDecoration _inputDecoration(String label) {
    return InputDecoration(
      labelText: label,
      filled: true,
      fillColor: const Color(0xFF2A2F35),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: BorderSide.none,
      ),
    );
  }

  void _scanForHubs() async {
    setState(() {
      _isScanning = true;
      _discoveredHubs = [];
    });

    final hub = context.read<HubService>();
    final hubs = await hub.discoverHubs();

    setState(() {
      _isScanning = false;
      _discoveredHubs = hubs;
    });
  }

  void _testConnection() async {
    setState(() {
      _isTesting = true;
      _testResult = null;
    });

    final hub = context.read<HubService>();
    final success = await hub.testConnection(_ipController.text);

    setState(() {
      _isTesting = false;
      _testResult = success ? 'Success! Hub responded.' : 'Failed. No response.';
    });
  }

  void _saveConfig() {
    final hub = context.read<HubService>();
    hub.config.preferredHubIp = _ipController.text;
    hub.config.udpPort = int.tryParse(_portController.text) ?? 8888;
    hub.updateConfig(hub.config);

    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Settings saved')),
    );
    Navigator.pop(context);
  }
}

// ============ WiFi Settings Screen ============

class WifiSettingsScreen extends StatefulWidget {
  const WifiSettingsScreen({super.key});

  @override
  State<WifiSettingsScreen> createState() => _WifiSettingsScreenState();
}

class _WifiSettingsScreenState extends State<WifiSettingsScreen> {
  final _ssidController = TextEditingController();
  final _passwordController = TextEditingController();
  bool _isLoading = false;
  String? _currentSsid;
  String? _currentIp;
  int? _rssi;

  @override
  void initState() {
    super.initState();
    _loadWifiInfo();
  }

  void _loadWifiInfo() async {
    final hub = context.read<HubService>();
    final info = await hub.getWifiInfo();
    if (info != null && mounted) {
      setState(() {
        _currentSsid = info.ssid;
        _currentIp = info.ip;
        _rssi = info.rssi;
      });
    }
  }

  @override
  void dispose() {
    _ssidController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('WiFi Settings'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loadWifiInfo,
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // Current connection
          if (_currentSsid != null && _currentSsid!.isNotEmpty)
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: const Color(0xFF2ECC71).withValues(alpha: 0.1),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: const Color(0xFF2ECC71).withValues(alpha: 0.3)),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      const Icon(Icons.wifi, color: Color(0xFF2ECC71)),
                      const SizedBox(width: 12),
                      const Text(
                        'Connected',
                        style: TextStyle(
                          fontWeight: FontWeight.bold,
                          color: Color(0xFF2ECC71),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  Text('SSID: $_currentSsid'),
                  Text('IP: $_currentIp'),
                  if (_rssi != null) Text('Signal: $_rssi dBm'),
                ],
              ),
            ),

          const SizedBox(height: 24),

          // Set WiFi
          const Text(
            'Connect to WiFi',
            style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: const Color(0xFF1C1F24),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Column(
              children: [
                TextField(
                  controller: _ssidController,
                  decoration: InputDecoration(
                    labelText: 'WiFi Name (SSID)',
                    prefixIcon: const Icon(Icons.wifi),
                    filled: true,
                    fillColor: const Color(0xFF2A2F35),
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(12),
                      borderSide: BorderSide.none,
                    ),
                  ),
                ),
                const SizedBox(height: 16),
                TextField(
                  controller: _passwordController,
                  obscureText: true,
                  decoration: InputDecoration(
                    labelText: 'Password',
                    prefixIcon: const Icon(Icons.lock),
                    filled: true,
                    fillColor: const Color(0xFF2A2F35),
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(12),
                      borderSide: BorderSide.none,
                    ),
                  ),
                ),
                const SizedBox(height: 16),
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton.icon(
                    onPressed: _isLoading ? null : _connectWifi,
                    icon: _isLoading
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.wifi),
                    label: const Text('Connect'),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: const Color(0xFF3A7BD5),
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 14),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  void _connectWifi() async {
    if (_ssidController.text.isEmpty || _passwordController.text.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Enter SSID and password')),
      );
      return;
    }

    setState(() => _isLoading = true);

    final hub = context.read<HubService>();
    final success = await hub.setWifi(
      _ssidController.text,
      _passwordController.text,
    );

    if (!mounted) return;
    setState(() => _isLoading = false);

    if (success) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('WiFi credentials sent')),
      );
      _loadWifiInfo();
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Failed to send WiFi credentials')),
      );
    }
  }

}

// ============ App Settings Screen ============

class AppSettingsScreen extends StatelessWidget {
  const AppSettingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Settings'),
      ),
      body: Consumer<HubService>(
        builder: (context, hub, _) {
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              SwitchListTile(
                title: const Text('Show offline nodes'),
                subtitle: const Text('Display nodes that are not connected'),
                value: hub.config.showOfflineNodes,
                onChanged: (value) {
                  hub.config.showOfflineNodes = value;
                  hub.updateConfig(hub.config);
                },
              ),
              const Divider(),
              ListTile(
                title: const Text('Poll interval'),
                subtitle: Text('${hub.config.pollMs} ms'),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => _showPollIntervalDialog(context, hub),
              ),
              ListTile(
                title: const Text('Connection timeout'),
                subtitle: Text('${hub.config.timeoutS} s'),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => _showTimeoutDialog(context, hub),
              ),
            ],
          );
        },
      ),
    );
  }

  void _showPollIntervalDialog(BuildContext context, HubService hub) {
    final controller = TextEditingController(text: hub.config.pollMs.toString());
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Poll Interval'),
        content: TextField(
          controller: controller,
          keyboardType: TextInputType.number,
          decoration: const InputDecoration(
            labelText: 'Milliseconds',
            suffixText: 'ms',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () {
              final value = int.tryParse(controller.text);
              if (value != null && value >= 100) {
                hub.config.pollMs = value;
                hub.updateConfig(hub.config);
              }
              Navigator.pop(context);
            },
            child: const Text('Save'),
          ),
        ],
      ),
    );
  }

  void _showTimeoutDialog(BuildContext context, HubService hub) {
    final controller = TextEditingController(text: hub.config.timeoutS.toString());
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Connection Timeout'),
        content: TextField(
          controller: controller,
          keyboardType: TextInputType.number,
          decoration: const InputDecoration(
            labelText: 'Seconds',
            suffixText: 's',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () {
              final value = double.tryParse(controller.text);
              if (value != null && value >= 0.5) {
                hub.config.timeoutS = value;
                hub.updateConfig(hub.config);
              }
              Navigator.pop(context);
            },
            child: const Text('Save'),
          ),
        ],
      ),
    );
  }
}

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
