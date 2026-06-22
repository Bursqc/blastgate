// ===============================
// FILE: src/main.cpp
// BLASTGATE HUB (SIMPLIFIED) - ETH + AP + WiFi STA + UDP
//
// Removed: NimBLE/BLE provisioning, ArduinoOTA, WebServer, DNSServer, ESPmDNS
// Kept:    ETH, WiFi AP (always on), WiFi STA, UDP (all commands), NVS,
//          relay, manual overdrive, status LED, watchdog, heartbeat
// ===============================

#include <Arduino.h>
#include <ETH.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <Preferences.h>
#include <esp_wifi.h>
#include <nvs_flash.h>
#include <esp_task_wdt.h>
#include <ESPmDNS.h>
#include <WebServer.h>
#include <Update.h>
#include <esp_ota_ops.h>

// Forward declaration — defined later in this file.
static inline void invalidateStatusCache();

// Set to 1 to compile in BLE WiFi provisioning. Needs:
//  - pioarduino arduino-esp32 3.x platform (penv install fix), OR
//  - stock platform=espressif32 with vendored SimpleBLE + BT include chain
// See platformio.ini for the deferred-work note.
#ifndef BLAST_BLE_PROV
#define BLAST_BLE_PROV 0
#endif

#if BLAST_BLE_PROV
#include <WiFiProv.h>
#endif

// ---------------- FIRMWARE VERSION ----------------
#ifndef FW_VERSION
#define FW_VERSION "1.4.2-dev"
#endif
#define FW_BUILD __DATE__ " " __TIME__
#define PROTO_VER "1.0"
#define OTA_DEFAULT_TOKEN "blastgate-change-me"
static String g_otaToken;  // loaded from NVS at boot

// ---------------- BLE PROVISIONING (compile-gated) ----------------
// Provisioning is user-triggered (UDP "WIFI_PROV" or POST /wifi_prov), not auto.
// Espressif's manager runs BLE while active, auto-applies received creds, then
// frees BT memory via NETWORK_PROV_SCHEME_HANDLER_FREE_BTDM.
#define PROV_DEFAULT_POP "blastgate"
#if BLAST_BLE_PROV
static String   g_provPop;
static volatile bool g_provActive = false;
#else
// Stub: prov is never active in builds without BLE. Keeps STATUS JSON valid.
static const bool g_provActive = false;
#endif

// ---------------- STATUS LED ----------------
static const int  STATUS_LED_PIN        = 2;
static const bool STATUS_LED_ACTIVE_HIGH = true;

static bool     hub_ready  = false;
static uint32_t led_t0     = 0;
static bool     led_state  = false;
static uint32_t led_no_conn_since = 0;
static const uint32_t LED_CONN_HYSTERESIS_MS = 8000;

// Forward declarations needed by ledUpdate()
static volatile bool staHasIP  = false;
static volatile bool ethHasIP  = false;

static void ledWrite(bool on) {
  if (STATUS_LED_ACTIVE_HIGH) digitalWrite(STATUS_LED_PIN, on ? HIGH : LOW);
  else                        digitalWrite(STATUS_LED_PIN, on ? LOW  : HIGH);
}

static void ledUpdate() {
  uint32_t now = millis();

  if (!hub_ready) {
    // Booting: fast blink 100ms
    if (now - led_t0 >= 100) { led_t0 = now; led_state = !led_state; ledWrite(led_state); }
    return;
  }

  if (ethHasIP) {
    // ETH connected: solid ON
    led_no_conn_since = 0;
    led_state = true;
    led_t0 = now;
    ledWrite(true);
    return;
  }

  if (staHasIP) {
    // WiFi STA: heartbeat — 1700ms ON, 300ms OFF
    led_no_conn_since = 0;
    if (led_state && (now - led_t0 >= 1700))       { led_t0 = now; led_state = false; ledWrite(false); }
    else if (!led_state && (now - led_t0 >= 300))  { led_t0 = now; led_state = true;  ledWrite(true);  }
    return;
  }

  // No uplink — hysteresis then medium blink
  if (led_no_conn_since == 0) led_no_conn_since = now;
  if (now - led_no_conn_since < LED_CONN_HYSTERESIS_MS) {
    ledWrite(true);
  } else {
    if (now - led_t0 >= 500) { led_t0 = now; led_state = !led_state; ledWrite(led_state); }
  }
}

static void ledBlinkFast(uint32_t ms_total = 300, uint32_t period_ms = 60) {
  uint32_t tstart = millis();
  bool st = false;
  while (millis() - tstart < ms_total) { st = !st; ledWrite(st); delay(period_ms); }
}

// ---------------- WIFI AP ----------------
static const char* AP_SSID = "BLASTGATE_HUB";
static const char* AP_PASS = "12345678";
static IPAddress   AP_IP(192, 168, 4, 1);
static IPAddress   AP_GW(192, 168, 4, 1);
static IPAddress   AP_MASK(255, 255, 255, 0);

// ---------------- WIFI STA PLACEHOLDER ----------------
static const char* STA_SSID = "TVOJ_WIFI";
static const char* STA_PASS = "TVOJA_SIFRA";

// ---------------- UDP ----------------
static const uint16_t UDP_PORT = 8888;
static WiFiUDP udp;

// ---------------- ETH (WT32-ETH01 LAN8720) ----------------
#define ETH_ADDR      1
#define ETH_POWER_PIN 16
#define ETH_MDC_PIN   23
#define ETH_MDIO_PIN  18
#define ETH_TYPE      ETH_PHY_LAN8720
#define ETH_CLK_MODE  ETH_CLOCK_GPIO0_IN

static volatile bool ethStarted      = false;
static volatile bool udpRebindNeeded = false;

// ---------------- RELAY ----------------
static const int RELAY_PIN = 17;

// ---------------- MANUAL OVERDRIVE BUTTON ----------------
static const int  MANUAL_BTN_PIN        = 32;
static const int  MANUAL_LED_PIN        = 33;
static const bool MANUAL_LED_ACTIVE_HIGH = true;
static bool manual_overdrive = false;

// ---------------- WIFI RESET BUTTON ----------------
// Short press (<3s): disconnect + restart (creds kept)
// Long press (>=3s): forget creds + restart
static const int WIFI_RESET_BTN_PIN = 4;

// ---------------- TIMEOUTS / LIMITS ----------------
static const uint32_t NODE_TIMEOUT_MS = 3500;
static const int      MAX_NODES       = 16;

static const uint8_t GATE_AUTO  = 0;
static const uint8_t GATE_OPEN  = 1;
static const uint8_t GATE_CLOSE = 2;

static const uint8_t MODE_AUTO   = 0;
static const uint8_t MODE_MANUAL = 1;

// ---------------- PERFORMANCE TUNING ----------------
static constexpr uint32_t NODE_VALUE_MIN_INTERVAL_MS = 1000;  // 1 Hz
static constexpr uint32_t STATUS_CACHE_MS            = 300;   // ~3.3 Hz
static constexpr uint32_t CFG_SEND_MIN_INTERVAL_MS   = 2000;  // max 1x/2s per node

// ---------------- NODE STATE ----------------
struct NodeState {
  String    id;
  String    name;
  IPAddress lastIp;
  uint16_t  listenPort         = 12000;
  uint32_t  lastSeen           = 0;

  bool      active             = false;
  float     lastValue          = NAN;

  float     threshold_on       = 40.0f;
  uint32_t  relay_hold_ms      = 3000;
  uint32_t  gate_hold_ms       = 5000;
  uint32_t  hbridge_open_ms    = 2000;
  uint32_t  hbridge_close_ms   = 2000;

  uint8_t   mode               = MODE_AUTO;
  uint8_t   gateOverride       = GATE_AUTO;

  uint8_t   gateConfirmed      = GATE_CLOSE;
  uint32_t  gateConfirmedMs    = 0;

  uint32_t  closeDueMs         = 0;
  uint8_t   lastGateCmd        = GATE_CLOSE;

  uint32_t  lastValueRxMs      = 0;
  uint32_t  lastCfgSentMs      = 0;

  uint8_t   savedMode          = MODE_AUTO;
  uint8_t   savedGateOverride  = GATE_AUTO;
};

static NodeState nodes[MAX_NODES];

// ---------------- RELAY FORCE ----------------
static bool     relay_force_on      = false;
static bool     relay_force_off     = false;
static uint32_t relay_force_set_ms  = 0;
static const uint32_t RELAY_FORCE_TIMEOUT_MS = 30000;

// ---------------- NVS ----------------
static Preferences prefs;
static const int   NAME_SLOTS = 16;

static String key_id(int i) { return String("id") + String(i); }
static String key_nm(int i) { return String("nm") + String(i); }

static int nameSlotFindById(const String& id) {
  for (int i = 0; i < NAME_SLOTS; i++) {
    String sid = prefs.getString(key_id(i).c_str(), "");
    if (sid.length() && sid == id) return i;
  }
  return -1;
}
static int nameSlotFindEmpty() {
  for (int i = 0; i < NAME_SLOTS; i++) {
    String sid = prefs.getString(key_id(i).c_str(), "");
    if (!sid.length()) return i;
  }
  return -1;
}
static String loadNameForId(const String& id) {
  int s = nameSlotFindById(id);
  return (s < 0) ? "" : prefs.getString(key_nm(s).c_str(), "");
}
static bool saveNameForId(const String& id, const String& name) {
  if (!id.length()) return false;
  int s = nameSlotFindById(id);
  if (s < 0) s = nameSlotFindEmpty();
  if (s < 0) return false;
  prefs.putString(key_id(s).c_str(), id);
  prefs.putString(key_nm(s).c_str(), name);
  return true;
}
static bool forgetNameForId(const String& id) {
  int s = nameSlotFindById(id);
  if (s < 0) return false;
  prefs.putString(key_id(s).c_str(), "");
  prefs.putString(key_nm(s).c_str(), "");
  return true;
}

// ---------------- NODE CONFIG NVS ----------------
static void saveNodeConfigToNVS(const String& id, float threshold, uint32_t relay_hold,
                                 uint32_t gate_hold, uint8_t override_state,
                                 uint32_t hb_open = 2000, uint32_t hb_close = 2000) {
  if (!id.length()) return;
  prefs.begin("node_cfg", false);
  String key = id;
  key.replace(":", "");
  String cfg = String(threshold, 3) + "," + String(relay_hold) + "," +
               String(gate_hold) + "," + String(override_state) + "," +
               String(hb_open) + "," + String(hb_close);
  prefs.putString(key.c_str(), cfg);
  prefs.end();
  Serial.printf("[NVS] Saved config for %s: %s\n", id.c_str(), cfg.c_str());
}

static bool loadNodeConfigFromNVS(const String& id, float& threshold, uint32_t& relay_hold,
                                   uint32_t& gate_hold, uint8_t& override_state,
                                   uint32_t& hb_open, uint32_t& hb_close) {
  if (!id.length()) return false;
  prefs.begin("node_cfg", true);
  String key = id;
  key.replace(":", "");
  String cfg = prefs.getString(key.c_str(), "");
  prefs.end();
  if (!cfg.length()) return false;

  int idx1 = cfg.indexOf(',');
  int idx2 = cfg.indexOf(',', idx1 + 1);
  int idx3 = cfg.indexOf(',', idx2 + 1);
  if (idx1 < 0 || idx2 < 0 || idx3 < 0) return false;

  threshold  = cfg.substring(0, idx1).toFloat();
  relay_hold = cfg.substring(idx1 + 1, idx2).toInt();
  gate_hold  = cfg.substring(idx2 + 1, idx3).toInt();

  int idx4 = cfg.indexOf(',', idx3 + 1);
  if (idx4 > 0) {
    override_state = cfg.substring(idx3 + 1, idx4).toInt();
    int idx5 = cfg.indexOf(',', idx4 + 1);
    if (idx5 > 0) {
      hb_open  = cfg.substring(idx4 + 1, idx5).toInt();
      hb_close = cfg.substring(idx5 + 1).toInt();
    }
  } else {
    override_state = cfg.substring(idx3 + 1).toInt();
  }
  Serial.printf("[NVS] Loaded config for %s: thr=%.1f rh=%u gh=%u ovr=%u hbo=%u hbc=%u\n",
    id.c_str(), threshold, relay_hold, gate_hold, override_state, hb_open, hb_close);
  return true;
}

static void deleteNodeConfigFromNVS(const String& id) {
  if (!id.length()) return;
  prefs.begin("node_cfg", false);
  String key = id;
  key.replace(":", "");
  prefs.remove(key.c_str());
  prefs.end();
  Serial.printf("[NVS] Deleted config for %s\n", id.c_str());
}

// ---------------- NETWORK STATE MACHINE ----------------
// AP (BLASTGATE_HUB) is ALWAYS active.
// Priority: ETH (DHCP) > ETH (link-local) > WiFi STA > AP-only
// Transitions driven by net_tick() from loop().

enum NetState : uint8_t {
  NET_BOOT,        // Hardware settling (~1.5s)
  NET_ETH_WAIT,    // ETH link up, waiting for DHCP
  NET_ETH_ACTIVE,  // ETH is primary (DHCP or link-local)
  NET_WIFI_WAIT,   // Connecting with saved credentials
  NET_WIFI_ACTIVE, // WiFi STA connected
  NET_AP_ONLY,     // No uplink; AP active for nodes
};

static NetState  g_net         = NET_BOOT;
static uint32_t  g_netEnterMs  = 0;
static uint32_t  g_wifiRetries = 0;
static uint32_t  g_ethLostMs   = 0;
static uint32_t  g_wifiLostMs  = 0;

static const uint32_t KNET_BOOT_MS          = 1500;
static const uint32_t KNET_ETH_DEBOUNCE_MS  = 3000;
static const uint32_t KNET_WIFI_DEBOUNCE_MS = 3000;
static const uint32_t KNET_WIFI_TIMEOUT_MS  = 15000;
static const uint32_t KNET_WIFI_MAX_RETRY   = 3;

static const char* netStateName(NetState s) {
  switch (s) {
    case NET_BOOT:        return "BOOT";
    case NET_ETH_WAIT:    return "ETH_WAIT";
    case NET_ETH_ACTIVE:  return "ETH_ACTIVE";
    case NET_WIFI_WAIT:   return "WIFI_WAIT";
    case NET_WIFI_ACTIVE: return "WIFI_ACTIVE";
    case NET_AP_ONLY:     return "AP_ONLY";
    default:              return "?";
  }
}

static void netEnter(NetState next) {
  if (g_net == next) return;
  Serial.printf("[NET] %s → %s\n", netStateName(g_net), netStateName(next));
  g_net        = next;
  g_netEnterMs = millis();
  g_ethLostMs  = 0;
  g_wifiLostMs = 0;
}

// ---------------- HELPERS ----------------
static void relayWrite(bool on) { digitalWrite(RELAY_PIN, on ? HIGH : LOW); }

static void manualLedWrite(bool on) {
  if (MANUAL_LED_ACTIVE_HIGH) digitalWrite(MANUAL_LED_PIN, on ? HIGH : LOW);
  else                        digitalWrite(MANUAL_LED_PIN, on ? LOW  : HIGH);
}

static void restartSoon(uint32_t ms = 250) {
  Serial.printf("[SYS] restarting in %u ms...\n", (unsigned)ms);
  hub_ready = false;
  ledBlinkFast(ms, 60);
  ESP.restart();
}

static String getArg(const String& msg, const String& key) {
  int p = msg.indexOf(key + "=");
  if (p < 0) return "";
  p += key.length() + 1;
  int e = msg.indexOf(' ', p);
  if (e < 0) e = msg.length();
  return msg.substring(p, e);
}

static bool nodeOnlineIdx(int idx) {
  if (idx < 0) return false;
  uint32_t age = nodes[idx].lastSeen ? (millis() - nodes[idx].lastSeen) : 99999999;
  return (age <= NODE_TIMEOUT_MS);
}

static int findNode(const String& id) {
  for (int i = 0; i < MAX_NODES; i++) { if (nodes[i].id == id) return i; }
  return -1;
}

static int allocNode(const String& id) {
  int idx = findNode(id);
  if (idx >= 0) return idx;

  for (int i = 0; i < MAX_NODES; i++) {
    if (nodes[i].id.length() == 0) {
      nodes[i].id   = id;
      nodes[i].name = loadNameForId(id);
      nodes[i].lastIp       = IPAddress(0, 0, 0, 0);
      nodes[i].listenPort   = 12000;
      nodes[i].lastSeen     = 0;
      nodes[i].active       = false;
      nodes[i].lastValue    = NAN;
      nodes[i].threshold_on  = 100.0f;
      nodes[i].relay_hold_ms = 3000;
      nodes[i].gate_hold_ms  = 3000;
      nodes[i].mode          = MODE_AUTO;
      nodes[i].gateOverride  = GATE_AUTO;

      float    saved_thr;
      uint32_t saved_rh, saved_gh, saved_hbo = 2000, saved_hbc = 2000;
      uint8_t  saved_ovr;
      if (loadNodeConfigFromNVS(id, saved_thr, saved_rh, saved_gh, saved_ovr, saved_hbo, saved_hbc)) {
        nodes[i].threshold_on    = saved_thr;
        nodes[i].relay_hold_ms   = saved_rh;
        nodes[i].gate_hold_ms    = saved_gh;
        nodes[i].gateOverride    = saved_ovr;
        nodes[i].hbridge_open_ms  = saved_hbo;
        nodes[i].hbridge_close_ms = saved_hbc;
        Serial.printf("[NODE] Restored config from NVS for %s\n", id.c_str());
      } else {
        Serial.printf("[NODE] No saved config for %s - using defaults\n", id.c_str());
      }

      nodes[i].gateConfirmed   = GATE_CLOSE;
      nodes[i].gateConfirmedMs = 0;
      nodes[i].closeDueMs      = 0;
      nodes[i].lastGateCmd     = GATE_CLOSE;
      nodes[i].lastValueRxMs   = 0;
      nodes[i].lastCfgSentMs   = 0;
      nodes[i].savedMode       = MODE_AUTO;
      nodes[i].savedGateOverride = GATE_AUTO;

      Serial.printf("[NODE] New node allocated: %s\n", id.c_str());
      return i;
    }
  }
  return -1;
}

static const char* modeName(uint8_t m) { return (m == MODE_MANUAL) ? "manual" : "auto"; }
static const char* gateName(uint8_t g) {
  if (g == GATE_OPEN)  return "open";
  if (g == GATE_CLOSE) return "close";
  return "auto";
}

static void udpReply(const IPAddress& ip, uint16_t port, const String& s) {
  udp.beginPacket(ip, port);
  udp.print(s);
  udp.endPacket();
}

static String jsonEscape(const String& s) {
  String o; o.reserve(s.length() + 8);
  for (size_t i = 0; i < s.length(); i++) {
    char c = s[i];
    if (c == '\\' || c == '"') { o += '\\'; o += c; }
    else if (c == '\n') o += "\\n";
    else if (c == '\r') o += "\\r";
    else if (c == '\t') o += "\\t";
    else o += c;
  }
  return o;
}

static IPAddress calcBcast(IPAddress ip, IPAddress mask) {
  IPAddress b;
  for (int i = 0; i < 4; i++) b[i] = ip[i] | (~mask[i]);
  return b;
}

static void sendBroadcast(const IPAddress& bcast, const String& m) {
  udp.beginPacket(bcast, UDP_PORT);
  udp.print(m);
  udp.endPacket();
}

// ---------------- AP ENFORCE ----------------
static void ensureAP() {
  WiFi.setSleep(false);
  WiFi.mode(WIFI_AP_STA);
  WiFi.softAPConfig(AP_IP, AP_GW, AP_MASK);
  bool ok = WiFi.softAP(AP_SSID, AP_PASS);
  if (!ok) {
    delay(200);
    WiFi.softAPdisconnect(true);
    delay(200);
    WiFi.mode(WIFI_AP_STA);
    WiFi.softAPConfig(AP_IP, AP_GW, AP_MASK);
    ok = WiFi.softAP(AP_SSID, AP_PASS);
  }
  Serial.printf("[AP] %s  SSID=%s  IP=%s  mode=%d\n",
    ok ? "OK" : "FAIL", AP_SSID,
    WiFi.softAPIP().toString().c_str(), (int)WiFi.getMode());
}

static bool isPlaceholderStaCreds() {
  if (!STA_SSID || !STA_PASS) return true;
  String s = String(STA_SSID); s.trim();
  if (s.length() == 0 || s == "TVOJ_WIFI") return true;
  return false;
}

static bool hasSavedCreds() {
  // Check our NVS namespace first
  prefs.begin("blastgate", true);
  String nvsSsid = prefs.getString("wifi_ssid", "");
  prefs.end();
  if (nvsSsid.length() > 0) return true;
  // Fall back to WiFi internal storage
  return WiFi.SSID().length() > 0;
}

// ---------------- STA ACTIONS ----------------
static bool setStaCredentialsAndConnect(const String& ssid, const String& pass) {
  if (!ssid.length()) return false;
  prefs.begin("blastgate", false);
  prefs.putString("wifi_ssid", ssid);
  prefs.putString("wifi_pass", pass);
  prefs.end();
  WiFi.persistent(true);
  WiFi.setSleep(false);
  WiFi.mode(WIFI_AP_STA);
  WiFi.disconnect(false, false);
  delay(150);
  Serial.printf("[STA] connecting to '%s'\n", ssid.c_str());
  WiFi.begin(ssid.c_str(), pass.c_str());
  return true;
}

static void staDisconnectKeepCreds() {
  WiFi.disconnect(false, false);
  staHasIP = false;
  Serial.println("[STA] disconnected (creds kept)");
}

static void staForgetCreds() {
  WiFi.disconnect(false, false);
  delay(100);

  // Erase WiFi credentials from ESP32 NVS namespaces
  const char* wifi_ns[] = {"nvs.net80211", "wifi_prov", "protocomm", NULL};
  for (int i = 0; wifi_ns[i]; i++) {
    nvs_handle_t h;
    if (nvs_open(wifi_ns[i], NVS_READWRITE, &h) == ESP_OK) {
      nvs_erase_all(h);
      nvs_commit(h);
      nvs_close(h);
      Serial.printf("[FORGET] Erased NVS namespace: %s\n", wifi_ns[i]);
    }
  }

  // Erase our own wifi_ssid / wifi_pass
  prefs.begin("blastgate", false);
  prefs.remove("wifi_ssid");
  prefs.remove("wifi_pass");
  prefs.end();

  Serial.println("[FORGET] WiFi creds erased");
}

// Factory reset: erase ALL node names + node configs + WiFi creds + OTA token, then restart
static void factoryReset() {
  Serial.println("\n!!! FACTORY RESET !!!");
  staForgetCreds();

  // Erase node names + OTA token (same NVS namespace)
  prefs.begin("blastgate", false);
  for (int i = 0; i < NAME_SLOTS; i++) {
    prefs.remove(key_id(i).c_str());
    prefs.remove(key_nm(i).c_str());
  }
  prefs.remove("ota_tok");
  prefs.remove("prov_pop");
  prefs.end();

  // Erase node configs
  prefs.begin("node_cfg", false);
  prefs.clear();
  prefs.end();

  Serial.println("[RESET] Done -> restarting");
  restartSoon(500);
}

// ---------------- SEND TO NODE ----------------
static void sendCfgToNode(int idx) {
  if (idx < 0) return;
  if (!nodeOnlineIdx(idx)) return;
  if (nodes[idx].lastIp == IPAddress(0, 0, 0, 0)) return;

  String cmd = "CFG ";
  cmd += "threshold_on="    + String(nodes[idx].threshold_on, 3) + " ";
  cmd += "relay_hold_ms="   + String(nodes[idx].relay_hold_ms) + " ";
  cmd += "gate_hold_ms="    + String(nodes[idx].gate_hold_ms) + " ";
  cmd += "hbridge_open_ms=" + String(nodes[idx].hbridge_open_ms) + " ";
  cmd += "hbridge_close_ms="+ String(nodes[idx].hbridge_close_ms) + " ";
  cmd += "mode=" + String(modeName(nodes[idx].mode));

  udp.beginPacket(nodes[idx].lastIp, nodes[idx].listenPort);
  udp.print(cmd);
  udp.endPacket();
  nodes[idx].lastCfgSentMs = millis();
}

static void maybeSendCfgToNode(int idx) {
  if (idx < 0) return;
  uint32_t now = millis();
  if (nodes[idx].lastCfgSentMs != 0 &&
      (now - nodes[idx].lastCfgSentMs) < CFG_SEND_MIN_INTERVAL_MS) return;
  sendCfgToNode(idx);
}

static void sendGateToNode(int idx, uint8_t gate) {
  if (idx < 0) return;
  if (!nodeOnlineIdx(idx)) return;
  if (nodes[idx].lastIp == IPAddress(0, 0, 0, 0)) return;
  String cmd = String("GATE ") + gateName(gate);
  udp.beginPacket(nodes[idx].lastIp, nodes[idx].listenPort);
  udp.print(cmd);
  udp.endPacket();
}

// ---------------- HUB HEARTBEAT ----------------
static uint32_t lastReadyMs = 0;
static constexpr uint32_t HUB_READY_EVERY_MS = 1000;

static void sendHubReadyTo(const IPAddress& ip, uint16_t port) {
  udp.beginPacket(ip, port);
  udp.print("HUB_READY");
  udp.endPacket();
}

static void broadcastHubReady() {
  sendBroadcast(IPAddress(192, 168, 4, 255), "HUB_READY");
  if (staHasIP) sendBroadcast(calcBcast(WiFi.localIP(), WiFi.subnetMask()), "HUB_READY");
  if (ethHasIP) sendBroadcast(calcBcast(ETH.localIP(), ETH.subnetMask()),   "HUB_READY");
}

static void broadcastHello() {
  String m = String("HUB_HELLO manual=") + (manual_overdrive ? "1" : "0");
  sendBroadcast(IPAddress(192, 168, 4, 255), m);
  if (staHasIP) sendBroadcast(calcBcast(WiFi.localIP(), WiFi.subnetMask()), m);
  if (ethHasIP) sendBroadcast(calcBcast(ETH.localIP(), ETH.subnetMask()),   m);
}

static void broadcastHubUpdate() {
  invalidateStatusCache();  // ensure next /status returns fresh data
  sendBroadcast(IPAddress(192, 168, 4, 255), "HUB_UPDATE");
  if (staHasIP) sendBroadcast(calcBcast(WiFi.localIP(), WiFi.subnetMask()), "HUB_UPDATE");
  if (ethHasIP) sendBroadcast(calcBcast(ETH.localIP(), ETH.subnetMask()),   "HUB_UPDATE");
}

// ---------------- RELAY / GATE LOGIC ----------------
static bool nodeWantsOpenNow(int i) {
  if (!nodes[i].id.length()) return false;
  if (!nodeOnlineIdx(i)) return false;
  if (nodes[i].active)                    return true;
  if (nodes[i].gateOverride == GATE_OPEN)  return true;
  if (nodes[i].gateOverride == GATE_CLOSE) return false;
  return false;
}

static bool nodeGateEffectiveOpen(int i, uint32_t /*now*/) {
  if (!nodes[i].id.length()) return false;
  if (!nodeOnlineIdx(i)) return false;
  return (nodes[i].lastGateCmd == GATE_OPEN);
}

static bool anyGateDemandOpenNow() {
  for (int i = 0; i < MAX_NODES; i++) if (nodeWantsOpenNow(i)) return true;
  return false;
}

static bool anyRelayAutoDemandNow() {
  for (int i = 0; i < MAX_NODES; i++) {
    if (!nodes[i].id.length()) continue;
    if (!nodeOnlineIdx(i)) continue;
    if (nodes[i].mode != MODE_AUTO) continue;
    if (nodes[i].active) return true;
    if (nodes[i].gateOverride == GATE_OPEN) return true;
    if (nodes[i].gateOverride == GATE_CLOSE) continue;
  }
  return false;
}

static void applyManualOverdrive(bool on) {
  manual_overdrive = on;
  manualLedWrite(on);

  if (on) {
    for (int i = 0; i < MAX_NODES; i++) {
      if (!nodes[i].id.length()) continue;
      nodes[i].savedMode        = nodes[i].mode;
      nodes[i].savedGateOverride = nodes[i].gateOverride;
      nodes[i].mode         = MODE_MANUAL;
      nodes[i].active       = false;
      nodes[i].gateOverride = GATE_CLOSE;
      nodes[i].closeDueMs   = 0;
      nodes[i].lastGateCmd  = GATE_CLOSE;
      sendCfgToNode(i);
      sendGateToNode(i, GATE_CLOSE);
    }
    Serial.println("[OVERDRIVE] ON - saved all node states");
  } else {
    for (int i = 0; i < MAX_NODES; i++) {
      if (!nodes[i].id.length()) continue;
      nodes[i].mode         = nodes[i].savedMode;
      nodes[i].gateOverride = nodes[i].savedGateOverride;
      nodes[i].active       = false;
      nodes[i].closeDueMs   = 0;
      nodes[i].lastGateCmd  = GATE_CLOSE;
      sendCfgToNode(i);
      if (nodes[i].gateOverride == GATE_OPEN) {
        sendGateToNode(i, GATE_OPEN);
        nodes[i].lastGateCmd = GATE_OPEN;
      } else {
        sendGateToNode(i, GATE_CLOSE);
      }
      Serial.printf("[OVERDRIVE] Restored node %s: mode=%s gate=%s\n",
        nodes[i].id.c_str(), modeName(nodes[i].mode), gateName(nodes[i].gateOverride));
    }
    Serial.println("[OVERDRIVE] OFF - restored all node states");
  }

  relay_force_on  = false;
  relay_force_off = false;
  broadcastHello();
}

static bool applyThresholdLogicAndReturnChanged(int idx, float v) {
  if (idx < 0) return false;
  nodes[idx].lastValue = v;
  if (manual_overdrive) return false;
  if (nodes[idx].mode == MODE_MANUAL) return false;
  bool prev = nodes[idx].active;
  nodes[idx].active = (v >= nodes[idx].threshold_on);
  return (nodes[idx].active != prev);
}

static void updateGateScheduler() {
  uint32_t now = millis();
  for (int i = 0; i < MAX_NODES; i++) {
    if (!nodes[i].id.length()) continue;
    if (!nodeOnlineIdx(i)) continue;
    if (nodes[i].lastIp == IPAddress(0, 0, 0, 0)) continue;

    bool wantOpen = nodeWantsOpenNow(i);

    if (wantOpen) {
      nodes[i].closeDueMs = 0;
      if (nodes[i].lastGateCmd != GATE_OPEN) {
        Serial.printf("[GATE_SCHED] %s: wantOpen=true → GATE_OPEN\n", nodes[i].id.c_str());
        sendGateToNode(i, GATE_OPEN);
        nodes[i].lastGateCmd = GATE_OPEN;
      }
    } else {
      if (nodes[i].lastGateCmd == GATE_OPEN) {
        if (nodes[i].closeDueMs == 0) {
          nodes[i].closeDueMs = now + nodes[i].gate_hold_ms;
          Serial.printf("[GATE_SCHED] %s: wantOpen=false, close in %u ms\n",
            nodes[i].id.c_str(), (unsigned)nodes[i].gate_hold_ms);
        } else if ((int32_t)(now - nodes[i].closeDueMs) >= 0) {
          Serial.printf("[GATE_SCHED] %s: close timer expired → GATE_CLOSE\n", nodes[i].id.c_str());
          sendGateToNode(i, GATE_CLOSE);
          nodes[i].lastGateCmd = GATE_CLOSE;
          nodes[i].closeDueMs  = 0;
        }
      } else {
        nodes[i].closeDueMs = 0;
      }
    }
  }
}

// ---------------- STATUS JSON (cached) ----------------
static String   status_cache;
static uint32_t status_cache_ms = 0;

// Escape a string into a fixed buffer (no heap alloc). Returns chars written.
static size_t escapeJsonTo(char* dst, size_t cap, const char* src) {
  size_t di = 0;
  for (size_t si = 0; src[si] && di + 2 < cap; si++) {
    char c = src[si];
    switch (c) {
      case '\\': case '"': if (di + 3 < cap) { dst[di++]='\\'; dst[di++]=c; } break;
      case '\n': if (di + 3 < cap) { dst[di++]='\\'; dst[di++]='n'; } break;
      case '\r': if (di + 3 < cap) { dst[di++]='\\'; dst[di++]='r'; } break;
      case '\t': if (di + 3 < cap) { dst[di++]='\\'; dst[di++]='t'; } break;
      default:   dst[di++] = c; break;
    }
  }
  dst[di] = 0;
  return di;
}

static String jsonStatus_build() {
  bool anyDemandOpen = anyGateDemandOpenNow();
  bool anyAutoDemand = anyRelayAutoDemandNow();

  uint8_t relayMode  = 2;
  uint8_t relayState = 0;

  if (manual_overdrive) {
    relayMode  = 2;
    relayState = anyDemandOpen ? 1 : 0;
  } else if (relay_force_on) {
    relayMode = 1; relayState = 1;
  } else if (relay_force_off) {
    relayMode = 0; relayState = 0;
  } else {
    relayMode  = 2;
    relayState = anyAutoDemand ? 1 : 0;
  }

  // Static buffer — no heap alloc on each call.
  // ~200 bytes/node × MAX_NODES=16 + 256 header = ~3.5KB; 6KB gives safe headroom.
  static char buf[6144];
  int p = 0;
  uint32_t now = millis();

  char apIpStr[24], staIpStr[24], ethIpStr[24];
  strncpy(apIpStr,  WiFi.softAPIP().toString().c_str(), sizeof(apIpStr)); apIpStr[sizeof(apIpStr)-1]=0;
  strncpy(staIpStr, staHasIP ? WiFi.localIP().toString().c_str() : "", sizeof(staIpStr)); staIpStr[sizeof(staIpStr)-1]=0;
  strncpy(ethIpStr, ethHasIP ? ETH.localIP().toString().c_str() : "", sizeof(ethIpStr)); ethIpStr[sizeof(ethIpStr)-1]=0;

  p += snprintf(buf + p, sizeof(buf) - p,
    "{\"protoVer\":\"" PROTO_VER "\","
    "\"version\":\"" FW_VERSION "\","
    "\"build\":\"" FW_BUILD "\","
    "\"uptime\":%lu,"
    "\"freeHeap\":%u,"
    "\"apIp\":\"%s\","
    "\"staIp\":\"%s\","
    "\"sta\":%d,"
    "\"ethLink\":%d,"
    "\"ethIp\":\"%s\","
    "\"manualOverdrive\":%d,"
    "\"relayState\":%d,"
    "\"relayMode\":%d,"
    "\"prov\":%d,"
    "\"nodes\":[",
    (unsigned long)(now / 1000),
    (unsigned)ESP.getFreeHeap(),
    apIpStr, staIpStr,
    staHasIP ? 1 : 0,
    (ethStarted && ETH.linkUp()) ? 1 : 0,
    ethIpStr,
    manual_overdrive ? 1 : 0,
    relayState, relayMode,
    g_provActive ? 1 : 0);

  bool first = true;
  for (int i = 0; i < MAX_NODES; i++) {
    if (!nodes[i].id.length()) continue;
    // Safety: leave room for closing "]}" and one more node header
    if (p > (int)sizeof(buf) - 384) break;

    uint32_t age      = nodes[i].lastSeen ? (now - nodes[i].lastSeen) : 99999999;
    bool     online   = (age <= NODE_TIMEOUT_MS);
    bool     gateOpen = online ? nodeGateEffectiveOpen(i, now) : false;
    uint32_t closeIn  = (nodes[i].closeDueMs != 0 && (int32_t)(nodes[i].closeDueMs - now) > 0)
                          ? (uint32_t)(nodes[i].closeDueMs - now) : 0;

    char idEsc[48], nameEsc[64], ipStr[24];
    escapeJsonTo(idEsc,   sizeof(idEsc),   nodes[i].id.c_str());
    escapeJsonTo(nameEsc, sizeof(nameEsc), nodes[i].name.c_str());
    strncpy(ipStr, nodes[i].lastIp.toString().c_str(), sizeof(ipStr)); ipStr[sizeof(ipStr)-1]=0;

    p += snprintf(buf + p, sizeof(buf) - p,
      "%s{\"id\":\"%s\","
      "\"name\":\"%s\","
      "\"ip\":\"%s\","
      "\"port\":%u,"
      "\"online\":%d,"
      "\"active\":%d,"
      "\"gateOpen\":%d,"
      "\"override\":%u,"
      "\"mode\":%u,"
      "\"ageMs\":%lu,"
      "\"threshold_on\":%.3f,"
      "\"relay_hold_ms\":%lu,"
      "\"gate_hold_ms\":%lu,"
      "\"hbridge_open_ms\":%lu,"
      "\"hbridge_close_ms\":%lu,",
      first ? "" : ",",
      idEsc, nameEsc, ipStr,
      (unsigned)nodes[i].listenPort,
      online ? 1 : 0,
      nodes[i].active ? 1 : 0,
      gateOpen ? 1 : 0,
      (unsigned)nodes[i].gateOverride,
      (unsigned)nodes[i].mode,
      (unsigned long)age,
      nodes[i].threshold_on,
      (unsigned long)nodes[i].relay_hold_ms,
      (unsigned long)nodes[i].gate_hold_ms,
      (unsigned long)nodes[i].hbridge_open_ms,
      (unsigned long)nodes[i].hbridge_close_ms);

    if (isnan(nodes[i].lastValue)) {
      p += snprintf(buf + p, sizeof(buf) - p,
        "\"value\":null,\"closeInMs\":%lu}", (unsigned long)closeIn);
    } else {
      p += snprintf(buf + p, sizeof(buf) - p,
        "\"value\":%.3f,\"closeInMs\":%lu}", nodes[i].lastValue, (unsigned long)closeIn);
    }

    first = false;
  }

  snprintf(buf + p, sizeof(buf) - p, "]}");
  return String(buf);  // single String alloc at return
}

static String jsonStatus() {
  uint32_t now = millis();
  if (status_cache.length() == 0 || (now - status_cache_ms) >= STATUS_CACHE_MS) {
    status_cache    = jsonStatus_build();
    status_cache_ms = now;
  }
  return status_cache;
}

// Force cache rebuild on next jsonStatus() call.
// Call this after any state change that should be visible immediately
// (relay toggle, override change, config update, manual overdrive flip).
static inline void invalidateStatusCache() {
  status_cache_ms = 0;
  status_cache    = "";
}

static String discoveryReply() {
  IPAddress ip;
  if (ethHasIP)      ip = ETH.localIP();
  else if (staHasIP) ip = WiFi.localIP();
  else               ip = WiFi.softAPIP();

  String s = "BLASTGATE_HUB;";
  s += "NAME=blastgate-hub;";
  s += "IP=" + ip.toString() + ";";
  s += "PORT=" + String(UDP_PORT) + ";";
  s += "ETH=" + String((ethHasIP && ethStarted && ETH.linkUp()) ? 1 : 0) + ";";
  s += "STA=" + String(staHasIP ? 1 : 0) + ";";
  s += "AP=1;";
  s += "APIP=" + WiFi.softAPIP().toString();
  return s;
}

static void doRefresh(bool full) {
  broadcastHubReady();
  broadcastHello();
  if (full) {
    for (int i = 0; i < MAX_NODES; i++) {
      if (!nodes[i].id.length()) continue;
      if (!nodeOnlineIdx(i)) continue;
      sendCfgToNode(i);
    }
  }
}

#if BLAST_BLE_PROV
// ---------------- BLE PROVISIONING HELPERS ----------------
static String makeProvServiceName() {
  uint8_t mac[6];
  WiFi.macAddress(mac);
  char name[24];
  snprintf(name, sizeof(name), "PROV_BG_%02X%02X", mac[4], mac[5]);
  return String(name);
}

static void startBleProvisioning() {
  if (g_provActive) {
    Serial.println("[PROV] already active — ignoring");
    return;
  }

  // We store WiFi creds in TWO namespaces:
  //   * "blastgate" (our own — wifi_ssid/wifi_pass)
  //   * nvs.net80211 (used by Espressif's network_provisioning manager)
  // beginProvision only erases the second one. If we left the first, our
  // net_tick would immediately read those and reconnect to the old WiFi,
  // racing the BLE start. staForgetCreds erases BOTH, so the manager really
  // sees "not provisioned" and starts BLE advertising cleanly.
  Serial.println("[PROV] erasing all saved creds before BLE start");
  staForgetCreds();

  String svc = makeProvServiceName();
  Serial.printf("[PROV] starting BLE prov: service=%s pop=%s\n",
                svc.c_str(), g_provPop.c_str());

  // FREE_BTDM = release BT controller memory after provisioning completes.
  // arduino-esp32 3.x / IDF 5.x: NETWORK_PROV_* (network_provisioning manager).
  WiFiProv.beginProvision(
    NETWORK_PROV_SCHEME_BLE,
    NETWORK_PROV_SCHEME_HANDLER_FREE_BTDM,
    NETWORK_PROV_SECURITY_1,
    g_provPop.c_str(),
    svc.c_str(),
    nullptr,  // service_key
    nullptr,  // uuid (auto)
    false     // creds were just erased above, no need for double-clear
  );
  // Print QR to serial — handy when testing with esp-prov / phone app
  WiFiProv.printQR(svc.c_str(), g_provPop.c_str(), "ble");
}
#endif // BLAST_BLE_PROV

// ---------------- WIFI EVENT ----------------
void WiFiEvent(WiFiEvent_t event) {
  switch (event) {
#if BLAST_BLE_PROV
    case ARDUINO_EVENT_PROV_INIT:
      Serial.println("[PROV] INIT");
      break;
    case ARDUINO_EVENT_PROV_START:
      g_provActive = true;
      Serial.println("[PROV] START (BLE active, waiting for app)");
      invalidateStatusCache();
      break;
    case ARDUINO_EVENT_PROV_CRED_RECV:
      Serial.println("[PROV] credentials received");
      break;
    case ARDUINO_EVENT_PROV_CRED_FAIL:
      Serial.println("[PROV] credentials FAILED (bad password?)");
      break;
    case ARDUINO_EVENT_PROV_CRED_SUCCESS:
      Serial.println("[PROV] credentials SUCCESS — connected to WiFi");
      break;
    case ARDUINO_EVENT_PROV_END:
      g_provActive = false;
      Serial.println("[PROV] END (BT memory released)");
      invalidateStatusCache();
      break;
    case ARDUINO_EVENT_PROV_DEINIT:
      Serial.println("[PROV] DEINIT");
      break;
#endif // BLAST_BLE_PROV
    case ARDUINO_EVENT_ETH_START:
      Serial.println("[ETH] START");
      ETH.setHostname("blastgate-hub");
      ethStarted = true;
      break;
    case ARDUINO_EVENT_ETH_CONNECTED:
      Serial.println("[ETH] CONNECTED");
      break;
    case ARDUINO_EVENT_ETH_GOT_IP:
      ethHasIP = true;
      Serial.println(String("[ETH] GOT IP ") + ETH.localIP().toString());
      ensureAP();
      udpRebindNeeded = true;
      break;
    case ARDUINO_EVENT_ETH_DISCONNECTED:
      ethHasIP = false;
      Serial.println("[ETH] DISCONNECTED");
      ensureAP();
      break;
    case ARDUINO_EVENT_ETH_STOP:
      ethHasIP = false;
      ethStarted = false;
      Serial.println("[ETH] STOP");
      ensureAP();
      break;
    case ARDUINO_EVENT_WIFI_STA_CONNECTED:
      Serial.println("[STA] CONNECTED");
      break;
    case ARDUINO_EVENT_WIFI_STA_GOT_IP:
      staHasIP = true;
      Serial.println(String("[STA] GOT IP ") + WiFi.localIP().toString());
      broadcastHello();
      break;
    case ARDUINO_EVENT_WIFI_STA_DISCONNECTED:
      staHasIP = false;
      Serial.println("[STA] DISCONNECTED");
      break;
    default:
      break;
  }
}

// ---------------- ETH BEGIN ----------------
static const IPAddress ETH_FALLBACK_IP(169, 254, 5, 1);
static const IPAddress ETH_FALLBACK_GW(169, 254, 5, 1);
static const IPAddress ETH_FALLBACK_MASK(255, 255, 0, 0);
static bool ethFallbackActive = false;

static void startEthFixed() {
  Serial.println("[ETH] begin (PWR=16, CLK=GPIO0_IN) ...");
  bool ok = false;
#if defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3)
  ok = ETH.begin(ETH_TYPE, ETH_ADDR, ETH_MDC_PIN, ETH_MDIO_PIN, ETH_POWER_PIN, ETH_CLK_MODE);
#else
  ok = ETH.begin(ETH_ADDR, ETH_POWER_PIN, ETH_MDC_PIN, ETH_MDIO_PIN, ETH_TYPE, ETH_CLK_MODE);
#endif
  if (!ok) { Serial.println("[ETH] begin() FAILED"); return; }
  Serial.println("[ETH] begin OK, waiting link/DHCP...");
}

// If ETH link is up but DHCP hasn't assigned IP after 8s, assign link-local fallback
// so direct laptop-to-hub cable works without a router.
static void ethFallbackCheck() {
  static uint32_t ethLinkUpMs = 0;
  static bool     ethWasLinked = false;

  bool linked = ethStarted && ETH.linkUp();

  if (linked && !ethWasLinked) {
    ethLinkUpMs    = millis();
    ethWasLinked   = true;
    ethFallbackActive = false;
    Serial.println("[ETH] Link UP — waiting for DHCP...");
  } else if (!linked && ethWasLinked) {
    ethWasLinked  = false;
    ethFallbackActive = false;
  }

  if (linked && !ethHasIP && !ethFallbackActive &&
      ethLinkUpMs > 0 && (millis() - ethLinkUpMs > 8000)) {
    ethFallbackActive = true;
    ETH.config(ETH_FALLBACK_IP, ETH_FALLBACK_GW, ETH_FALLBACK_MASK);
    ethHasIP = true;
    Serial.printf("[ETH] DHCP timeout — fallback: %s\n", ETH_FALLBACK_IP.toString().c_str());
    udpRebindNeeded = true;
  }
}

static void startStaWifi() {
  WiFi.setSleep(false);
  WiFi.mode(WIFI_AP_STA);

  prefs.begin("blastgate", true);
  String nvsSsid = prefs.getString("wifi_ssid", "");
  String nvsPass = prefs.getString("wifi_pass", "");
  prefs.end();

  if (nvsSsid.length() > 0) {
    Serial.printf("[STA] connecting with NVS creds: ssid='%s'\n", nvsSsid.c_str());
    WiFi.begin(nvsSsid.c_str(), nvsPass.c_str());
    return;
  }

  if (isPlaceholderStaCreds()) {
    Serial.println("[STA] trying saved creds (WiFi.begin()) ...");
    WiFi.begin();
    return;
  }

  Serial.printf("[STA] connecting to %s ...\n", STA_SSID);
  WiFi.begin(STA_SSID, STA_PASS);
}

// ---------------- UDP HANDLER ----------------
static void handleUdp() {
  int psize = udp.parsePacket();
  if (psize <= 0) return;

  IPAddress rip   = udp.remoteIP();
  uint16_t  rport = udp.remotePort();

  char buf[900];
  int n = udp.read(buf, sizeof(buf) - 1);
  if (n <= 0) return;
  buf[n] = 0;

  String msg(buf);
  msg.trim();

  // ---- WiFi commands ----
  if (msg == "WIFI_GET") {
    String s = "WIFI;";
    s += "STA=" + String(staHasIP ? 1 : 0) + ";";
    s += "SSID=" + WiFi.SSID() + ";";
    s += "IP=" + String(staHasIP ? WiFi.localIP().toString() : "") + ";";
    s += "RSSI=" + String((WiFi.status() == WL_CONNECTED) ? WiFi.RSSI() : 0) + ";";
    s += "PROV=0";
    udpReply(rip, rport, s);
    return;
  }

  if (msg.startsWith("WIFI_SET")) {
    String ssid = getArg(msg, "ssid");
    String pass = getArg(msg, "pass");
    // NOTE: UDP arg parser splits on spaces, so passwords with spaces are not
    // supported via UDP. Use POST /wifi_set (JSON) for passwords with spaces.
    if (!ssid.length()) {
      udpReply(rip, rport, "ERR WIFI_SET ssid=... pass=...");
      return;
    }
    setStaCredentialsAndConnect(ssid, pass);
    udpReply(rip, rport, "OK WIFI_SET (restarting)");
    restartSoon(250);
    return;
  }

  if (msg == "WIFI_DISCONNECT") {
    staDisconnectKeepCreds();
    udpReply(rip, rport, "OK WIFI_DISCONNECT (restarting)");
    restartSoon(200);
    return;
  }

  if (msg == "WIFI_PROV") {
#if BLAST_BLE_PROV
    // Start BLE provisioning on demand. Mobile app then scans for PROV_BG_XXXX
    // and pushes SSID/pass over BLE using Espressif's standard protocol.
    if (g_provActive) {
      udpReply(rip, rport, "OK already_active");
    } else {
      startBleProvisioning();
      char r[64];
      snprintf(r, sizeof(r), "OK WIFI_PROV started pop=%s", g_provPop.c_str());
      udpReply(rip, rport, r);
    }
#else
    udpReply(rip, rport, "ERR BLE not compiled in (see BLAST_BLE_PROV)");
#endif
    return;
  }

  if (msg == "DISCOVER" || msg == "WHO_IS_BLASTGATE?") {
    udpReply(rip, rport, discoveryReply());
    sendHubReadyTo(rip, rport);
    broadcastHello();
    return;
  }

  if (msg == "PING") {
    udpReply(rip, rport, "PONG");
    return;
  }

  if (msg == "REFRESH") {
    doRefresh(false);
    udpReply(rip, rport, jsonStatus());
    return;
  }
  if (msg == "REFRESH_FULL") {
    doRefresh(true);
    udpReply(rip, rport, jsonStatus());
    return;
  }

  if (msg == "STATUS") {
    udpReply(rip, rport, jsonStatus());
    return;
  }

  if (manual_overdrive) {
    bool allowed =
      msg.startsWith("BTN_TOGGLE") || msg.startsWith("NODE_PING")  ||
      msg.startsWith("NODE_HELLO") || msg.startsWith("NODE_VALUE") ||
      msg.startsWith("NODE_UPDATE")|| msg.startsWith("GATE_ACK")   ||
      msg.startsWith("RELAY")      || msg.startsWith("NODECMD")    ||
      msg.startsWith("NODECFG_")   || msg.startsWith("NODEMODE")   ||
      msg.startsWith("ASSIGN")     || msg.startsWith("FORGET");
    if (!allowed) {
      udpReply(rip, rport, "ERR manual_overdrive_lockout");
      return;
    }
  }

  if (msg.startsWith("NODE_HELLO")) {
    String id = getArg(msg, "id");
    if (!id.length()) { udpReply(rip, rport, "ERR NODE_HELLO id=... port=..."); return; }

    bool isNewNode = (findNode(id) < 0);
    int  idx = allocNode(id);
    if (idx < 0) { udpReply(rip, rport, "ERR no slots"); return; }

    nodes[idx].lastSeen = millis();
    nodes[idx].lastIp   = rip;

    String p = getArg(msg, "port");
    if (p.length()) { uint16_t lp = (uint16_t)p.toInt(); if (lp > 0) nodes[idx].listenPort = lp; }

    if (manual_overdrive) {
      nodes[idx].mode = MODE_MANUAL;
    } else if (isNewNode) {
      nodes[idx].mode         = MODE_AUTO;
      nodes[idx].gateOverride = GATE_AUTO;
      nodes[idx].active       = false;
      Serial.printf("[NODE_HELLO] NEW node %s - reset to AUTO mode\n", id.c_str());
    } else {
      Serial.printf("[NODE_HELLO] Node %s reconnected - preserving override=%d\n",
                    id.c_str(), nodes[idx].gateOverride);
    }

    sendCfgToNode(idx);

    if (nodeWantsOpenNow(idx)) {
      sendGateToNode(idx, GATE_OPEN);
      nodes[idx].lastGateCmd = GATE_OPEN;
    } else {
      sendGateToNode(idx, GATE_CLOSE);
      nodes[idx].lastGateCmd = GATE_CLOSE;
    }

    udpReply(rip, rport, "OK");
    return;
  }

  if (msg.startsWith("GATE_ACK")) {
    String id = getArg(msg, "id");
    String st = getArg(msg, "state");
    if (!id.length() || !st.length()) { udpReply(rip, rport, "ERR GATE_ACK id=... state=open|close"); return; }

    int idx = allocNode(id);
    if (idx < 0) { udpReply(rip, rport, "ERR no slots"); return; }

    nodes[idx].lastSeen      = millis();
    nodes[idx].lastIp        = rip;
    nodes[idx].gateConfirmed = (st == "open") ? GATE_OPEN : GATE_CLOSE;
    nodes[idx].gateConfirmedMs = millis();

    udpReply(rip, rport, "OK");
    return;
  }

  if (msg.startsWith("BTN_TOGGLE")) {
    String id = getArg(msg, "id");
    if (!id.length()) { udpReply(rip, rport, "ERR BTN_TOGGLE id=..."); return; }

    int idx = allocNode(id);
    if (idx < 0) { udpReply(rip, rport, "ERR no slots"); return; }

    nodes[idx].lastSeen = millis();
    nodes[idx].lastIp   = rip;

    String p = getArg(msg, "port");
    if (p.length()) { uint16_t lp = (uint16_t)p.toInt(); if (lp > 0) nodes[idx].listenPort = lp; }

    if (!manual_overdrive) { udpReply(rip, rport, "ERR manual_overdrive_off"); return; }

    nodes[idx].mode = MODE_MANUAL;
    nodes[idx].gateOverride = (nodes[idx].gateOverride == GATE_OPEN) ? GATE_CLOSE : GATE_OPEN;

    udpReply(rip, rport, "OK");
    return;
  }

  if (msg.startsWith("ASSIGN")) {
    String id = getArg(msg, "id");
    String nm = getArg(msg, "name");
    if (!id.length() || !nm.length()) { udpReply(rip, rport, "ERR ASSIGN id=... name=..."); return; }
    nm.replace("_", " ");

    int idx = allocNode(id);
    if (idx < 0) { udpReply(rip, rport, "ERR no slots"); return; }

    nodes[idx].name = nm;
    if (!saveNameForId(id, nm)) { udpReply(rip, rport, "ERR name store full"); return; }

    broadcastHubUpdate();
    udpReply(rip, rport, "OK");
    return;
  }

  if (msg.startsWith("FORGET")) {
    String id = getArg(msg, "id");
    if (!id.length()) { udpReply(rip, rport, "ERR FORGET id=..."); return; }

    int idx = findNode(id);
    if (idx >= 0) nodes[idx].name = "";
    (void)forgetNameForId(id);
    broadcastHubUpdate();
    udpReply(rip, rport, "OK");
    return;
  }

  if (msg.startsWith("RELAY")) {
    if (msg.indexOf("auto") > 0) {
      relay_force_on = false; relay_force_off = false; relay_force_set_ms = 0;
      broadcastHubUpdate();
      udpReply(rip, rport, "OK RELAY auto");
    } else if (msg.indexOf("on") > 0) {
      bool anyEff = false;
      uint32_t now = millis();
      for (int i = 0; i < MAX_NODES; i++) if (nodeGateEffectiveOpen(i, now)) { anyEff = true; break; }
      if (!anyEff) {
        relay_force_on = false; relay_force_off = false; relay_force_set_ms = 0;
        udpReply(rip, rport, "ERR RELAY blocked (no gate open)");
        return;
      }
      relay_force_on = true; relay_force_off = false; relay_force_set_ms = millis();
      broadcastHubUpdate();
      udpReply(rip, rport, "OK RELAY on");
    } else if (msg.indexOf("off") > 0) {
      relay_force_off = true; relay_force_on = false; relay_force_set_ms = millis();
      broadcastHubUpdate();
      udpReply(rip, rport, "OK RELAY off");
    } else {
      udpReply(rip, rport, "ERR RELAY auto|on|off");
    }
    return;
  }

  if (msg.startsWith("NODECFG_GET")) {
    String id  = getArg(msg, "id");
    int    idx = findNode(id);
    if (idx < 0) { udpReply(rip, rport, "ERR unknown id"); return; }

    String j  = "{";
    j += "\"threshold_on\":"    + String(nodes[idx].threshold_on, 3) + ",";
    j += "\"relay_hold_ms\":"   + String(nodes[idx].relay_hold_ms) + ",";
    j += "\"gate_hold_ms\":"    + String(nodes[idx].gate_hold_ms) + ",";
    j += "\"hbridge_open_ms\":" + String(nodes[idx].hbridge_open_ms) + ",";
    j += "\"hbridge_close_ms\":"+ String(nodes[idx].hbridge_close_ms) + "}";
    udpReply(rip, rport, j);
    return;
  }

  if (msg.startsWith("NODECFG_SET")) {
    String id = getArg(msg, "id");
    if (!id.length()) { udpReply(rip, rport, "ERR NODECFG_SET missing id"); return; }

    int idx = allocNode(id);
    if (idx < 0) { udpReply(rip, rport, "ERR no slots"); return; }

    String s_on  = getArg(msg, "threshold_on");
    if (!s_on.length()) s_on = getArg(msg, "threshold");
    if (!s_on.length()) s_on = getArg(msg, "gate_threshold");

    String s_rh  = getArg(msg, "relay_hold_ms");
    if (!s_rh.length()) s_rh = getArg(msg, "relay_hold");
    if (!s_rh.length()) s_rh = getArg(msg, "hold_time");

    String s_gh  = getArg(msg, "gate_hold_ms");
    if (!s_gh.length()) s_gh = getArg(msg, "gate_hold");
    if (!s_gh.length()) s_gh = getArg(msg, "close_delay_ms");

    String s_hbo = getArg(msg, "hbridge_open_ms");
    String s_hbc = getArg(msg, "hbridge_close_ms");

    if (s_on.length())  nodes[idx].threshold_on    = s_on.toFloat();
    if (s_rh.length())  nodes[idx].relay_hold_ms   = (uint32_t)s_rh.toInt();
    if (s_gh.length())  nodes[idx].gate_hold_ms    = (uint32_t)s_gh.toInt();
    if (s_hbo.length()) nodes[idx].hbridge_open_ms  = (uint32_t)s_hbo.toInt();
    if (s_hbc.length()) nodes[idx].hbridge_close_ms = (uint32_t)s_hbc.toInt();

    Serial.printf("[CFG_SET] id=%s thr=%.3f rh=%u gh=%u hbo=%u hbc=%u\n",
      id.c_str(), nodes[idx].threshold_on,
      (unsigned)nodes[idx].relay_hold_ms, (unsigned)nodes[idx].gate_hold_ms,
      (unsigned)nodes[idx].hbridge_open_ms, (unsigned)nodes[idx].hbridge_close_ms);

    saveNodeConfigToNVS(id, nodes[idx].threshold_on, nodes[idx].relay_hold_ms,
                        nodes[idx].gate_hold_ms, nodes[idx].gateOverride,
                        nodes[idx].hbridge_open_ms, nodes[idx].hbridge_close_ms);
    sendCfgToNode(idx);
    broadcastHubUpdate();
    udpReply(rip, rport, "OK");
    return;
  }

  if (msg.startsWith("NODEMODE")) {
    String id = getArg(msg, "id");
    String m  = getArg(msg, "mode");
    int    idx = findNode(id);
    if (idx < 0) { udpReply(rip, rport, "ERR unknown id"); return; }

    if (m == "manual")      nodes[idx].mode = MODE_MANUAL;
    else if (m == "auto")   nodes[idx].mode = MODE_AUTO;
    else { udpReply(rip, rport, "ERR NODEMODE id=... mode=auto|manual"); return; }

    if (nodes[idx].mode == MODE_AUTO) nodes[idx].active = false;

    sendCfgToNode(idx);
    broadcastHubUpdate();
    udpReply(rip, rport, "OK");
    return;
  }

  if (msg.startsWith("NODECMD")) {
    String id   = getArg(msg, "id");
    String gate = getArg(msg, "gate");
    int    idx  = findNode(id);

    if (!id.length() || !gate.length()) { udpReply(rip, rport, "ERR NODECMD id=... gate=auto|open|close"); return; }
    if (idx < 0) { udpReply(rip, rport, "ERR unknown id"); return; }

    uint8_t oldOverride = nodes[idx].gateOverride;
    if (gate == "open")        nodes[idx].gateOverride = GATE_OPEN;
    else if (gate == "close")  nodes[idx].gateOverride = GATE_CLOSE;
    else if (gate == "auto")   nodes[idx].gateOverride = GATE_AUTO;
    else { udpReply(rip, rport, "ERR gate=auto|open|close"); return; }

    Serial.printf("[NODECMD] %s: override %s→%s (active=%d)\n",
      id.c_str(), gateName(oldOverride), gate.c_str(), nodes[idx].active);

    saveNodeConfigToNVS(id, nodes[idx].threshold_on, nodes[idx].relay_hold_ms,
                        nodes[idx].gate_hold_ms, nodes[idx].gateOverride);
    broadcastHubUpdate();
    udpReply(rip, rport, "OK");
    return;
  }

  if (msg.startsWith("NODE_PING")) {
    String id = getArg(msg, "id");
    if (!id.length()) { udpReply(rip, rport, "ERR missing id"); return; }

    int idx = allocNode(id);
    if (idx < 0) { udpReply(rip, rport, "ERR no slots"); return; }

    nodes[idx].lastSeen = millis();
    nodes[idx].lastIp   = rip;

    String p = getArg(msg, "port");
    if (p.length()) { uint16_t lp = (uint16_t)p.toInt(); if (lp > 0) nodes[idx].listenPort = lp; }

    if (manual_overdrive) nodes[idx].mode = MODE_MANUAL;

    maybeSendCfgToNode(idx);
    udpReply(rip, rport, "OK");
    return;
  }

  if (msg.startsWith("NODE_VALUE")) {
    String id = getArg(msg, "id");
    String v  = getArg(msg, "v");
    if (!id.length() || !v.length()) { udpReply(rip, rport, "ERR NODE_VALUE id=... v=..."); return; }

    int idx = allocNode(id);
    if (idx < 0) { udpReply(rip, rport, "ERR no slots"); return; }

    uint32_t now = millis();
    nodes[idx].lastSeen = now;
    nodes[idx].lastIp   = rip;

    // Rate-limit per node (1 Hz)
    if (nodes[idx].lastValueRxMs != 0 &&
        (now - nodes[idx].lastValueRxMs) < NODE_VALUE_MIN_INTERVAL_MS) {
      udpReply(rip, rport, "OK");
      return;
    }
    nodes[idx].lastValueRxMs = now;

    float val = v.toFloat();
    nodes[idx].lastValue = val;

    if (manual_overdrive) {
      // Auto-exit overdrive if sensor fires
      if (val >= nodes[idx].threshold_on) {
        Serial.printf("[OVERDRIVE] Sensor %s triggered (%.2f >= %.2f) - AUTO EXIT\n",
          id.c_str(), val, nodes[idx].threshold_on);
        applyManualOverdrive(false);
        (void)applyThresholdLogicAndReturnChanged(idx, val);
      }
    } else {
      (void)applyThresholdLogicAndReturnChanged(idx, val);
    }

    udpReply(rip, rport, "OK");
    return;
  }

  if (msg.startsWith("NODE_UPDATE")) {
    String id = getArg(msg, "id");
    if (!id.length()) { udpReply(rip, rport, "ERR NODE_UPDATE id=..."); return; }

    int idx = allocNode(id);
    if (idx < 0) { udpReply(rip, rport, "ERR no slots"); return; }

    nodes[idx].lastSeen = millis();
    nodes[idx].lastIp   = rip;
    udpReply(rip, rport, "OK");
    return;
  }

  udpReply(rip, rport, "ERR unknown");
}

// ---------------- NETWORK STATE MACHINE ----------------
static void net_tick() {
  const uint32_t now     = millis();
  const uint32_t inState = now - g_netEnterMs;

  const bool ethUp   = ethStarted && ETH.linkUp();
  const bool ethOk   = ethHasIP;
  const bool ethDhcp = ethOk && !ethFallbackActive;
  const bool wifiOk  = staHasIP;

  switch (g_net) {

    case NET_BOOT:
      if (ethOk)  { netEnter(NET_ETH_ACTIVE);  break; }
      if (wifiOk) { netEnter(NET_WIFI_ACTIVE); break; }
      if (inState < KNET_BOOT_MS) break;
      if (ethUp)               netEnter(NET_ETH_WAIT);
      else if (hasSavedCreds()) netEnter(NET_WIFI_WAIT);
      else                      netEnter(NET_AP_ONLY);
      break;

    case NET_ETH_WAIT:
      if (ethOk)  { netEnter(NET_ETH_ACTIVE); break; }
      if (!ethUp) {
        Serial.println("[NET] ETH link lost during ETH_WAIT");
        if (wifiOk)              netEnter(NET_WIFI_ACTIVE);
        else if (hasSavedCreds()) netEnter(NET_WIFI_WAIT);
        else                      netEnter(NET_AP_ONLY);
      }
      break;

    case NET_ETH_ACTIVE:
      if (!ethOk) {
        if (!g_ethLostMs) g_ethLostMs = now;
        if (now - g_ethLostMs >= KNET_ETH_DEBOUNCE_MS) {
          Serial.println("[NET] ETH lost (debounced) — falling back");
          g_ethLostMs   = 0;
          g_wifiRetries = 0;
          if (wifiOk)              netEnter(NET_WIFI_ACTIVE);
          else if (hasSavedCreds()) { WiFi.reconnect(); netEnter(NET_WIFI_WAIT); }
          else                      netEnter(NET_AP_ONLY);
        }
      } else {
        g_ethLostMs = 0;
      }
      break;

    case NET_WIFI_WAIT:
      if (ethOk)          { netEnter(NET_ETH_ACTIVE); break; }
      if (ethUp && !ethOk){ netEnter(NET_ETH_WAIT);   break; }
      if (wifiOk) {
        g_wifiRetries = 0;
        netEnter(NET_WIFI_ACTIVE);
        break;
      }
      if (inState >= KNET_WIFI_TIMEOUT_MS) {
        g_wifiRetries++;
        Serial.printf("[NET] WiFi timeout — attempt %u/%u\n",
          (unsigned)g_wifiRetries, (unsigned)KNET_WIFI_MAX_RETRY);
        if (g_wifiRetries < KNET_WIFI_MAX_RETRY) {
          WiFi.reconnect();
          g_netEnterMs = now;
        } else {
          g_wifiRetries = 0;
          netEnter(NET_AP_ONLY);
        }
      }
      break;

    case NET_WIFI_ACTIVE:
      if (ethDhcp) { netEnter(NET_ETH_ACTIVE); break; }
      if (!wifiOk) {
        if (!g_wifiLostMs) g_wifiLostMs = now;
        if (now - g_wifiLostMs >= KNET_WIFI_DEBOUNCE_MS) {
          Serial.println("[NET] WiFi lost (debounced) — reconnecting");
          g_wifiLostMs  = 0;
          g_wifiRetries = 0;
          WiFi.reconnect();
          netEnter(NET_WIFI_WAIT);
        }
      } else {
        g_wifiLostMs = 0;
      }
      break;

    case NET_AP_ONLY:
      if (ethOk)          { netEnter(NET_ETH_ACTIVE);  break; }
      if (wifiOk)         { netEnter(NET_WIFI_ACTIVE); break; }
      if (ethUp && !ethOk){ netEnter(NET_ETH_WAIT);    break; }
      // No WiFi creds — hub operates in AP-only mode.
      // Use WIFI_SET UDP command or physical button to configure.
      break;
  }
}

// ===============================
// HTTP SERVER + mDNS
// ===============================
// Lightweight HTTP server on port 80, served on ALL interfaces (AP + STA + ETH).
// Endpoints:
//   GET /ping        → "PONG" (firewall probe / liveness)
//   GET /status      → JSON hub status (same as UDP STATUS)
//   GET /wifi_scan   → JSON array of visible SSIDs  (blocks ~2s on first call)
//   POST /wifi_set   → JSON body {"ssid":"...","pass":"..."} → saves + restart
//   POST /wifi_forget→ forgets creds + restart

static WebServer httpServer(80);

// Minimal JSON-value extractor (handles string values only, no library needed)
static String httpJsonGet(const String& json, const String& key) {
  String search = "\"" + key + "\"";
  int p = json.indexOf(search);
  if (p < 0) return "";
  p = json.indexOf(':', p + search.length());
  if (p < 0) return "";
  while (p < (int)json.length() && (json[p] == ':' || json[p] == ' ')) p++;
  if (p >= (int)json.length()) return "";
  if (json[p] != '"') return "";
  p++;
  int e = json.indexOf('"', p);
  if (e < 0) return "";
  return json.substring(p, e);
}

static void httpCors(WebServer& s) {
  s.sendHeader("Access-Control-Allow-Origin", "*");
  s.sendHeader("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
  s.sendHeader("Access-Control-Allow-Headers", "Content-Type");
}

static void setupHttpServer() {

  // CORS preflight for browser-based provisioning pages
  httpServer.on("/", HTTP_OPTIONS, []() { httpCors(httpServer); httpServer.send(204); });
  httpServer.on("/ping", HTTP_OPTIONS, []() { httpCors(httpServer); httpServer.send(204); });
  httpServer.on("/status", HTTP_OPTIONS, []() { httpCors(httpServer); httpServer.send(204); });
  httpServer.on("/wifi_scan", HTTP_OPTIONS, []() { httpCors(httpServer); httpServer.send(204); });
  httpServer.on("/wifi_set", HTTP_OPTIONS, []() { httpCors(httpServer); httpServer.send(204); });
  httpServer.on("/wifi_forget", HTTP_OPTIONS, []() { httpCors(httpServer); httpServer.send(204); });
  httpServer.on("/version", HTTP_OPTIONS, []() { httpCors(httpServer); httpServer.send(204); });
  httpServer.on("/ota", HTTP_OPTIONS, []() { httpCors(httpServer); httpServer.send(204); });
  httpServer.on("/ota_token_set", HTTP_OPTIONS, []() { httpCors(httpServer); httpServer.send(204); });
  httpServer.on("/wifi_prov", HTTP_OPTIONS, []() { httpCors(httpServer); httpServer.send(204); });
  httpServer.on("/prov_pop_set", HTTP_OPTIONS, []() { httpCors(httpServer); httpServer.send(204); });

  // GET /ping — fast liveness probe (used by discovery to confirm hub IP)
  httpServer.on("/ping", HTTP_GET, []() {
    httpCors(httpServer);
    httpServer.send(200, "text/plain", "PONG");
  });

  // GET /status — full JSON hub status (same data as UDP STATUS)
  httpServer.on("/status", HTTP_GET, []() {
    httpCors(httpServer);
    httpServer.send(200, "application/json", jsonStatus());
  });

  // GET /version — compact JSON with firmware identity + health.
  // Apps poll this to decide if an OTA is available.
  httpServer.on("/version", HTTP_GET, []() {
    httpCors(httpServer);
    char buf[256];
    const esp_partition_t* run = esp_ota_get_running_partition();
    const char* partLabel = (run && run->label) ? run->label : "?";
    const char* chip = ESP.getChipModel();
    if (!chip) chip = "?";
    snprintf(buf, sizeof(buf),
      "{\"protoVer\":\"" PROTO_VER "\","
      "\"version\":\"" FW_VERSION "\","
      "\"build\":\"" FW_BUILD "\","
      "\"uptime\":%lu,"
      "\"freeHeap\":%u,"
      "\"chipModel\":\"%s\","
      "\"otaPartition\":\"%s\"}",
      (unsigned long)(millis() / 1000),
      (unsigned)ESP.getFreeHeap(),
      chip, partLabel);
    httpServer.send(200, "application/json", buf);
  });

  // POST /ota — multipart upload of new firmware.bin.
  // Auth: must send header "X-OTA-Token: <token>" matching the value in NVS.
  // On success: hub responds 200 then restarts into the new image.
  static const char* OTA_HEADER_KEYS[] = {"X-OTA-Token"};
  httpServer.collectHeaders(OTA_HEADER_KEYS, 1);
  httpServer.on("/ota", HTTP_POST,
    // Final handler — runs after upload finishes
    []() {
      httpCors(httpServer);
      if (httpServer.header("X-OTA-Token") != g_otaToken) {
        httpServer.send(401, "application/json", "{\"ok\":false,\"error\":\"unauthorized\"}");
        return;
      }
      bool ok = !Update.hasError();
      Serial.printf("[OTA] finish: ok=%d, error=%u\n", (int)ok, Update.getError());
      httpServer.send(ok ? 200 : 500, "application/json",
        ok ? "{\"ok\":true,\"reboot\":true}"
           : "{\"ok\":false,\"error\":\"flash_failed\"}");
      delay(500);
      if (ok) ESP.restart();
    },
    // Upload chunk handler — streams firmware to flash
    []() {
      HTTPUpload& up = httpServer.upload();
      if (up.status == UPLOAD_FILE_START) {
        if (httpServer.header("X-OTA-Token") != g_otaToken) {
          Serial.println("[OTA] reject: bad token");
          return;
        }
        Serial.printf("[OTA] start: %s\n", up.filename.c_str());
        esp_task_wdt_reset();
        if (!Update.begin(UPDATE_SIZE_UNKNOWN)) {
          Update.printError(Serial);
        }
      } else if (up.status == UPLOAD_FILE_WRITE) {
        esp_task_wdt_reset();  // critical — flash write is slow, WDT is 30s
        if (Update.write(up.buf, up.currentSize) != up.currentSize) {
          Update.printError(Serial);
        }
      } else if (up.status == UPLOAD_FILE_END) {
        esp_task_wdt_reset();
        if (Update.end(true)) {
          Serial.printf("[OTA] end: %u bytes written\n", up.totalSize);
        } else {
          Update.printError(Serial);
        }
      } else if (up.status == UPLOAD_FILE_ABORTED) {
        Update.end();
        Serial.println("[OTA] aborted");
      }
    });

  // POST /ota_token_set — change the OTA token. Body: {"old":"...","new":"..."}
  // Requires knowledge of current token (so first change uses OTA_DEFAULT_TOKEN).
  httpServer.on("/ota_token_set", HTTP_POST, []() {
    httpCors(httpServer);
    String body = httpServer.arg("plain");
    String oldT = httpJsonGet(body, "old");
    String newT = httpJsonGet(body, "new");
    if (oldT != g_otaToken) {
      httpServer.send(401, "application/json", "{\"ok\":false,\"error\":\"bad old token\"}");
      return;
    }
    if (newT.length() < 8) {
      httpServer.send(400, "application/json", "{\"ok\":false,\"error\":\"token must be >= 8 chars\"}");
      return;
    }
    prefs.begin("blastgate", false);
    prefs.putString("ota_tok", newT);
    prefs.end();
    g_otaToken = newT;
    Serial.println("[OTA] token rotated");
    httpServer.send(200, "application/json", "{\"ok\":true}");
  });

  // GET /wifi_scan — scan for nearby WiFi networks, return JSON array
  // Blocks ~2s but only called on demand from the provisioning UI
  httpServer.on("/wifi_scan", HTTP_GET, []() {
    httpCors(httpServer);
    esp_task_wdt_reset();
    int n = WiFi.scanNetworks(false, true);  // blocking, include hidden
    esp_task_wdt_reset();

    String json = "[";
    bool first = true;
    for (int i = 0; i < n; i++) {
      if (!first) json += ",";
      first = false;
      json += "{\"ssid\":\"" + jsonEscape(WiFi.SSID(i)) + "\",\"rssi\":" + String(WiFi.RSSI(i)) + "}";
    }
    json += "]";
    WiFi.scanDelete();
    httpServer.send(200, "application/json", json);
  });

  // POST /wifi_set — JSON body: {"ssid":"...","pass":"..."}
  httpServer.on("/wifi_set", HTTP_POST, []() {
    httpCors(httpServer);
    String body = httpServer.arg("plain");
    String ssid = httpJsonGet(body, "ssid");
    String pass = httpJsonGet(body, "pass");
    if (!ssid.length()) {
      httpServer.send(400, "application/json", "{\"error\":\"missing ssid\"}");
      return;
    }
    httpServer.send(200, "application/json", "{\"ok\":true}");
    delay(80);  // Let the HTTP response flush before restart
    setStaCredentialsAndConnect(ssid, pass);
    restartSoon(300);
  });

  // POST /wifi_forget — forget saved credentials + restart
  httpServer.on("/wifi_forget", HTTP_POST, []() {
    httpCors(httpServer);
    httpServer.send(200, "application/json", "{\"ok\":true}");
    delay(80);
    staForgetCreds();
    restartSoon(300);
  });

#if BLAST_BLE_PROV
  // POST /wifi_prov — start BLE provisioning. Returns the PoP and service name
  // so the app can connect without scanning if the user already knows the device.
  httpServer.on("/wifi_prov", HTTP_POST, []() {
    httpCors(httpServer);
    if (g_provActive) {
      httpServer.send(200, "application/json",
        "{\"ok\":true,\"active\":true,\"already\":true}");
      return;
    }
    startBleProvisioning();
    String svc = makeProvServiceName();
    String body = "{\"ok\":true,\"active\":true,\"service\":\"" + svc +
                  "\",\"pop\":\"" + g_provPop + "\"}";
    httpServer.send(200, "application/json", body);
  });

  // POST /prov_pop_set — rotate PoP code (8+ chars). Body: {"old":"...","new":"..."}
  httpServer.on("/prov_pop_set", HTTP_POST, []() {
    httpCors(httpServer);
    String body = httpServer.arg("plain");
    String oldP = httpJsonGet(body, "old");
    String newP = httpJsonGet(body, "new");
    if (oldP != g_provPop) {
      httpServer.send(401, "application/json", "{\"ok\":false,\"error\":\"bad old pop\"}");
      return;
    }
    if (newP.length() < 8) {
      httpServer.send(400, "application/json", "{\"ok\":false,\"error\":\"pop must be >= 8 chars\"}");
      return;
    }
    prefs.begin("blastgate", false);
    prefs.putString("prov_pop", newP);
    prefs.end();
    g_provPop = newP;
    Serial.println("[PROV] PoP rotated");
    httpServer.send(200, "application/json", "{\"ok\":true}");
  });
#else
  // Stub when BLE prov is compiled out — returns 501 so app can surface the message.
  httpServer.on("/wifi_prov", HTTP_POST, []() {
    httpCors(httpServer);
    httpServer.send(501, "application/json",
      "{\"ok\":false,\"error\":\"BLE provisioning not compiled in this firmware\"}");
  });
#endif

  // Captive-portal root: minimal provisioning page served on AP IP
  httpServer.onNotFound([]() {
    // Redirect all unknown requests to /wifi_scan page (captive portal)
    httpServer.sendHeader("Location", "http://" + WiFi.softAPIP().toString() + "/setup");
    httpServer.send(302, "text/plain", "");
  });

  // GET /setup — embedded provisioning web page
  httpServer.on("/setup", HTTP_GET, []() {
    httpCors(httpServer);
    httpServer.send(200, "text/html; charset=utf-8", R"rawhtml(<!DOCTYPE html>
<html lang="sr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Blastgate Setup</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
       background:#0f0f1a;color:#e0e0e0;min-height:100vh;
       display:flex;align-items:center;justify-content:center;padding:16px}
  .card{background:#1a1a2e;border-radius:16px;padding:28px;width:100%;max-width:400px;
        box-shadow:0 8px 32px rgba(0,0,0,0.4)}
  .logo{text-align:center;margin-bottom:24px}
  .logo h1{font-size:22px;color:#89b4fa;font-weight:700;letter-spacing:1px}
  .logo p{font-size:13px;color:#666;margin-top:4px}
  label{display:block;font-size:13px;color:#aaa;margin-bottom:6px;margin-top:16px}
  select,input{width:100%;padding:12px 14px;border-radius:10px;border:1px solid #2a2a40;
               background:#0f0f1a;color:#e0e0e0;font-size:15px;outline:none}
  select:focus,input:focus{border-color:#89b4fa}
  .pw-wrap{position:relative}
  .pw-wrap input{padding-right:44px}
  .pw-toggle{position:absolute;right:12px;top:50%;transform:translateY(-50%);
             background:none;border:none;color:#666;cursor:pointer;font-size:18px;padding:4px}
  .btn{display:block;width:100%;margin-top:24px;padding:14px;border-radius:10px;
       border:none;background:#89b4fa;color:#0f0f1a;font-size:16px;font-weight:700;
       cursor:pointer;transition:background 0.2s}
  .btn:hover{background:#74c7ec}
  .btn:disabled{background:#2a2a40;color:#555;cursor:not-allowed}
  #msg{margin-top:16px;text-align:center;font-size:14px;min-height:20px}
  .ok{color:#a6e3a1}.err{color:#f38ba8}.spin{color:#89b4fa}
  .scanning{display:flex;align-items:center;gap:8px;color:#666;font-size:14px;margin-top:8px}
  @keyframes spin{to{transform:rotate(360deg)}}
  .spinner{width:16px;height:16px;border:2px solid #333;border-top-color:#89b4fa;
           border-radius:50%;animation:spin 0.8s linear infinite}
</style>
</head>
<body>
<div class="card">
  <div class="logo"><h1>BLASTGATE HUB</h1><p>WiFi Setup</p></div>
  <label for="ssid">WiFi mreža</label>
  <select id="ssid"><option value="">-- Skeniranje... --</option></select>
  <div class="scanning" id="scan-status"><div class="spinner"></div><span>Tražim mreže...</span></div>
  <label for="pass">Lozinka</label>
  <div class="pw-wrap">
    <input type="password" id="pass" placeholder="WiFi lozinka" autocomplete="off">
    <button class="pw-toggle" onclick="togglePw()" type="button">&#128065;</button>
  </div>
  <button class="btn" id="btn" onclick="send()" disabled>Poveži</button>
  <div id="msg"></div>
</div>
<script>
function togglePw(){var i=document.getElementById('pass');i.type=i.type==='password'?'text':'password';}
function setMsg(t,c){var m=document.getElementById('msg');m.textContent=t;m.className=c||'';}
function scan(){
  fetch('/wifi_scan').then(r=>r.json()).then(nets=>{
    document.getElementById('scan-status').style.display='none';
    var s=document.getElementById('ssid');
    if(!nets||!nets.length){s.innerHTML='<option value="">-- Nema mreža --</option>';return;}
    s.innerHTML='';
    nets.forEach(function(n){var o=document.createElement('option');o.value=n.ssid;o.textContent=n.ssid+' ('+n.rssi+' dBm)';s.appendChild(o);});
    document.getElementById('btn').disabled=false;
  }).catch(()=>{
    document.getElementById('scan-status').innerHTML='<span class="err">Greška skeniranja</span>';
    document.getElementById('btn').disabled=false;
  });
}
function send(){
  var ssid=document.getElementById('ssid').value,pass=document.getElementById('pass').value;
  if(!ssid){setMsg('Izaberi WiFi','err');return;}
  document.getElementById('btn').disabled=true;
  setMsg('Šaljem...','spin');
  fetch('/wifi_set',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({ssid:ssid,pass:pass})
  }).then(()=>setMsg('Uspešno! Hub se restartuje...','ok'))
    .catch(()=>setMsg('Uspešno! Hub se restartuje...','ok'));
}
scan();
</script>
</body>
</html>)rawhtml");
  });

  httpServer.begin();
  Serial.println("[HTTP] Server started on port 80");
}

// ===============================
// SETUP
// ===============================
void setup() {
  Serial.begin(115200);
  delay(200);

  // Watchdog (30s)
  Serial.println("[WDT] Initializing watchdog (30s)");
#if defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3)
  const esp_task_wdt_config_t wdt_config = { .timeout_ms = 30000, .idle_core_mask = 0, .trigger_panic = true };
  esp_task_wdt_init(&wdt_config);
#else
  esp_task_wdt_init(30, true);
#endif
  esp_task_wdt_add(NULL);

  pinMode(STATUS_LED_PIN, OUTPUT);
  hub_ready = false;
  led_t0    = millis();
  led_state = false;
  ledWrite(false);

  // NVS init
  esp_err_t err = nvs_flash_init();
  if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
    nvs_flash_erase();
    nvs_flash_init();
  }
  prefs.begin("blastgate", false);
  // Load OTA token from NVS (or seed default on first boot)
  g_otaToken = prefs.getString("ota_tok", "");
  if (g_otaToken.length() == 0) {
    g_otaToken = OTA_DEFAULT_TOKEN;
    prefs.putString("ota_tok", g_otaToken);
    Serial.println("[OTA] No token in NVS — seeded default. CHANGE IT via /ota_token_set!");
  }
#if BLAST_BLE_PROV
  // Load BLE provisioning PoP (proof-of-possession) from NVS
  g_provPop = prefs.getString("prov_pop", "");
  if (g_provPop.length() == 0) {
    g_provPop = PROV_DEFAULT_POP;
    prefs.putString("prov_pop", g_provPop);
    Serial.println("[PROV] No PoP in NVS — seeded default. CHANGE via /prov_pop_set!");
  }
#endif
  prefs.end();
  Serial.printf("[FW] version=%s build=%s\n", FW_VERSION, FW_BUILD);

  // Relay
  pinMode(RELAY_PIN, OUTPUT);
  relayWrite(false);

  // Manual overdrive button + LED
  pinMode(MANUAL_BTN_PIN, INPUT_PULLUP);
  pinMode(MANUAL_LED_PIN, OUTPUT);
  manual_overdrive = false;
  manualLedWrite(false);

  // WiFi reset button
  pinMode(WIFI_RESET_BTN_PIN, INPUT_PULLUP);

  // Factory reset: hold MANUAL button 5s during boot
  if (digitalRead(MANUAL_BTN_PIN) == LOW) {
    Serial.println("[BOOT] Button held - hold 5s for FACTORY RESET...");
    manualLedWrite(true);
    uint32_t hold_start = millis();
    while (digitalRead(MANUAL_BTN_PIN) == LOW) {
      esp_task_wdt_reset();
      ledBlinkFast(100, 50);
      if (millis() - hold_start > 5000) {
        Serial.println("[BOOT] 5s reached - FACTORY RESET!");
        manualLedWrite(false);
        factoryReset();
      }
    }
    Serial.println("[BOOT] Button released early - normal boot");
    manualLedWrite(false);
  }

  WiFi.setSleep(false);
  WiFi.mode(WIFI_AP_STA);
  WiFi.onEvent(WiFiEvent);

  WiFi.softAPConfig(AP_IP, AP_GW, AP_MASK);
  WiFi.softAP(AP_SSID, AP_PASS);
  ensureAP();

  startEthFixed();

  if (hasSavedCreds() || !isPlaceholderStaCreds()) {
    Serial.println("[STA] starting non-blocking WiFi connect");
    startStaWifi();
  } else {
    Serial.println("[STA] no creds — AP-only mode");
  }

  udp.begin(UDP_PORT);
  Serial.printf("[UDP] listening on %u\n", UDP_PORT);

  ensureAP();

  // mDNS: hub reachable as blastgate.local on any interface
  if (MDNS.begin("blastgate")) {
    MDNS.addService("http", "tcp", 80);
    Serial.println("[mDNS] blastgate.local started");
  } else {
    Serial.println("[mDNS] FAILED");
  }

  setupHttpServer();

  applyManualOverdrive(manual_overdrive);
  broadcastHello();

  g_net        = NET_BOOT;
  g_netEnterMs = millis();
  Serial.printf("[NET] State machine initialized → %s\n", netStateName(g_net));

  Serial.println("[INFO] HUB ready.");
  hub_ready = true;
  ledWrite(true);

  lastReadyMs = millis();
  broadcastHubReady();
}

// ===============================
// LOOP
// ===============================
void loop() {
  esp_task_wdt_reset();

  ledUpdate();
  handleUdp();
  httpServer.handleClient();
  ethFallbackCheck();
  net_tick();

  // HUB_READY heartbeat (1s)
  if (millis() - lastReadyMs >= HUB_READY_EVERY_MS) {
    lastReadyMs = millis();
    broadcastHubReady();
  }

  // Manual overdrive button debounce (toggle on press)
  {
    static bool     last_btn      = true;
    static uint32_t btn_debounce  = 0;
    static bool     btn_was_down  = false;

    bool btn_now = (digitalRead(MANUAL_BTN_PIN) == LOW);
    if (btn_now != last_btn) { last_btn = btn_now; btn_debounce = millis(); }
    if ((millis() - btn_debounce) > 50) {
      if (btn_now && !btn_was_down) {
        btn_was_down = true;
        applyManualOverdrive(!manual_overdrive);
        Serial.printf("[BTN] Manual overdrive: %s\n", manual_overdrive ? "ON" : "OFF");
      } else if (!btn_now) {
        btn_was_down = false;
      }
    }
  }

  // WiFi reset button
  // Short press (<3s): disconnect + restart (creds kept)
  // Long press (>=3s): forget creds + restart
  {
    static bool     wifi_btn_down    = false;
    static uint32_t wifi_btn_press_t = 0;

    bool btn = (digitalRead(WIFI_RESET_BTN_PIN) == LOW);

    if (btn && !wifi_btn_down) {
      wifi_btn_down    = true;
      wifi_btn_press_t = millis();
    } else if (!btn && wifi_btn_down) {
      wifi_btn_down = false;
      uint32_t held = millis() - wifi_btn_press_t;
      if (held >= 3000) {
        Serial.println("[WIFI_BTN] Long press — FORGET creds + restart");
        ledBlinkFast(1800, 300);
        staForgetCreds();
        restartSoon(300);
      } else {
        Serial.println("[WIFI_BTN] Short press — disconnect + restart");
        ledBlinkFast(600, 100);
        staDisconnectKeepCreds();
        restartSoon(200);
      }
    } else if (btn && wifi_btn_down) {
      uint32_t held = millis() - wifi_btn_press_t;
      if (held >= 3000) {
        if ((millis() / 150) % 2 == 0) ledWrite(true);
        else                            ledWrite(false);
      }
    }
  }

  // Offline node cleanup
  for (int i = 0; i < MAX_NODES; i++) {
    if (nodes[i].id.length() && nodes[i].lastSeen) {
      uint32_t age = millis() - nodes[i].lastSeen;
      if (age > NODE_TIMEOUT_MS) {
        nodes[i].active          = false;
        nodes[i].lastValue       = NAN;
        nodes[i].lastIp          = IPAddress(0, 0, 0, 0);
        nodes[i].listenPort      = 12000;
        nodes[i].closeDueMs      = 0;
        nodes[i].lastGateCmd     = GATE_CLOSE;
        nodes[i].lastValueRxMs   = 0;
        nodes[i].lastCfgSentMs   = 0;
      }
    }
  }

  updateGateScheduler();

  // Relay force timeout (30s)
  if ((relay_force_on || relay_force_off) && relay_force_set_ms != 0) {
    if (millis() - relay_force_set_ms > RELAY_FORCE_TIMEOUT_MS) {
      Serial.println("[RELAY] Force timeout -> reverting to AUTO");
      relay_force_on = false; relay_force_off = false; relay_force_set_ms = 0;
    }
  }

  // Relay logic
  bool anyDemandOpen = anyGateDemandOpenNow();
  bool anyAutoDemand = anyRelayAutoDemandNow();

  if (relay_force_on) {
    bool anyEff = false;
    uint32_t now = millis();
    for (int i = 0; i < MAX_NODES; i++) if (nodeGateEffectiveOpen(i, now)) { anyEff = true; break; }
    if (!anyEff) relay_force_on = false;
  }

  if (manual_overdrive)  relayWrite(anyDemandOpen);
  else if (relay_force_on)  relayWrite(true);
  else if (relay_force_off) relayWrite(false);
  else                      relayWrite(anyAutoDemand);

  // AP watchdog (2s)
  {
    static uint32_t lastApCheck = 0;
    if (millis() - lastApCheck > 2000) {
      lastApCheck = millis();
      wifi_mode_t m = WiFi.getMode();
      if ((m != WIFI_AP && m != WIFI_AP_STA) || WiFi.softAPIP() == IPAddress(0, 0, 0, 0)) {
        Serial.println("[AP] missing -> re-enable");
        ensureAP();
        udp.stop();
        udp.begin(UDP_PORT);
        Serial.println("[UDP] re-bind after AP fix");
      }
    }
  }

  // UDP rebind on ETH IP
  if (udpRebindNeeded) {
    udpRebindNeeded = false;
    udp.stop();
    udp.begin(UDP_PORT);
    Serial.println("[UDP] re-bind after ETH got IP");
  }

  // UDP periodic rebind (10 min) — defensive guard.
  // Was 30s as workaround for old ESP-IDF WiFiUDP buffer bug; that's been
  // fixed upstream. Frequent rebinds drop packets in the rebind window,
  // so we keep it as a long-interval safety net only.
  {
    static uint32_t lastUdpRebind = 0;
    if (millis() - lastUdpRebind > 600000UL) {
      lastUdpRebind = millis();
      udp.stop();
      udp.begin(UDP_PORT);
      Serial.println("[UDP] periodic re-bind (10min)");
    }
  }

  // Heap monitor — restart if critically low
  {
    static uint32_t lastHeapCheck = 0;
    if (millis() - lastHeapCheck > 10000) {
      lastHeapCheck = millis();
      uint32_t freeHeap = ESP.getFreeHeap();
      if (freeHeap < 20000) {
        Serial.printf("[HEAP] CRITICAL: %u bytes -> restart\n", freeHeap);
        restartSoon(200);
      } else if (freeHeap < 40000) {
        Serial.printf("[HEAP] WARNING: %u bytes\n", freeHeap);
        status_cache = "";
      }
    }
  }

  delay(2);
}
