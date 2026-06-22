# Blastgate

ESP32-based dust collection gate controller. WT32-ETH01 hub coordinates ESP32 sensor nodes over UDP/HTTP; mobile (Flutter) and desktop (Python) apps drive the system.

## Architecture

```
                ┌────────────┐
                │  Mobile    │  Flutter (Android/iOS/Windows desktop)
                │  Desktop   │  Python ttkbootstrap
                └─────┬──────┘
                      │  UDP 8888 + HTTP 80
                      │  /status /version /ota /wifi_set ...
                ┌─────▼──────┐
                │ Hub        │  WT32-ETH01 (ESP32 + LAN8720)
                │ AP+STA+ETH │  Captive portal, OTA, BLE prov (gated)
                └─────┬──────┘
                      │  UDP to nodes
                ┌─────▼──────┐
                │ Nodes      │  ESP32 sensor + servo/H-bridge gates
                └────────────┘
```

## Repository layout

| Path | Contents |
|------|----------|
| `firmware/hub-wt32/` | Hub firmware — UDP server, HTTP API, OTA, captive portal |
| `firmware/node-esp32/` | Sensor/gate node firmware |
| `firmware/lib/` | Shared / vendored libraries (e.g. WiFiProv) |
| `desktop/` | Python ttkbootstrap GUI for PC |
| `mobile/` | Flutter app (Android, iOS, Windows desktop) |
| `releases/` | OTA manifest + (via GitHub Releases) firmware binaries |

## OTA flow

1. Hub exposes `GET /version` and `POST /ota` (auth: `X-OTA-Token`)
2. Apps fetch `releases/manifest.json` from this repo (raw URL)
3. If `manifest.version > hub.version` → user is prompted to update
4. App downloads the `.bin` from the GitHub Release, verifies SHA256, POSTs to hub
5. Hub flashes new image into the inactive OTA partition and reboots

See `desktop/blastgate/network/ota.py` and `mobile/lib/services/ota_service.dart` for the client side.

## Build

**Hub firmware** (PlatformIO):
```bash
cd firmware/hub-wt32
pio run               # build
pio run -t upload     # flash via USB
pio device monitor    # serial log
```

**Python desktop**:
```bash
cd desktop
pip install -r requirements.txt
python -m blastgate
```

**Flutter mobile** (Windows desktop build):
```bash
cd mobile
flutter pub get
flutter run -d windows
```

## Status

Working: hub OTA, status JSON sync between firmware ↔ Python ↔ Flutter, captive portal WiFi provisioning, Soft AP fallback.

Deferred: BLE WiFi provisioning (code wired in firmware behind `BLAST_BLE_PROV` define; Flutter UI ready; needs working pioarduino toolchain on dev machine).
