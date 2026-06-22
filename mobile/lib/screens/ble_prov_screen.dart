import 'package:flutter/material.dart';

/// Placeholder BLE Provisioning screen.
///
/// The real implementation (with flutter_esp_ble_prov + permissions + scan/pair
/// flow) was removed temporarily because:
///   1. Hub firmware's BLE_PROV is gated behind BLAST_BLE_PROV (not yet built
///      because the pioarduino toolchain install is broken on dev machine).
///   2. flutter_esp_ble_prov 0.1.7 fails AGP-8 Android build (missing
///      namespace declaration).
///
/// Once both are unblocked, restore the full screen from git history
/// (commit before this placeholder was added).
class BleProvScreen extends StatelessWidget {
  const BleProvScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('BLE Provisioning')),
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(Icons.bluetooth_disabled, size: 64, color: Colors.grey[700]),
              const SizedBox(height: 20),
              const Text(
                'BLE provisioning — coming soon',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 12),
              Text(
                'Hub firmware needs BLAST_BLE_PROV compiled in.\n'
                'Until then use WiFi Setup → Soft AP tab to configure the hub.',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 14, color: Colors.grey[400], height: 1.6),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
