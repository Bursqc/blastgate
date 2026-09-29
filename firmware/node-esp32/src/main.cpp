// file: src/main.cpp
// ============================================================
// BLASTGATE NODE (ESP32 classic) — ESP-NOW transport (v1.5.0)
//
// Pinout:
//   SENSOR=GPIO36 (VP, ADC1_CH0, SCT-013-000), SERVO=GPIO18, BTN=GPIO27, LED=GPIO2
//   H-bridge: IN1=GPIO19, IN2=GPIO21
//   Rev B end switches (optional, active low): END_OPEN=GPIO32, END_CLOSE=GPIO33
//
// Features:
// - Non-blocking ADC sampler (WDT-friendly)
// - Warmup offset calibration (non-blocking)
// - BOOT HOLD: sends 0 while stabilizing
// - SERVO BLANKING: ignores sensor after actuator move
// - Consecutive spike detector + EMA smoothing
// - Watchdog timer (30s)
// - ESP-NOW link to hub (blastgate_proto.h), HMAC-signed frames
// - Channel scan 1..13 when hub heartbeat is lost for 5s (non-blocking)
// - Pairing: hold button 3s -> 60s pairing window
// - Failsafe: no hub for 12s -> gate CLOSE
// - Hybrid OTA: hub sends OTA_START, node joins hub Soft AP and pulls firmware
// - H-BRIDGE: HW-095/L298N motor, optional end switches (config flag from hub)
// ============================================================

#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <esp_mac.h>
#include <Preferences.h>
#include <HTTPClient.h>
#include <Update.h>
#include <mbedtls/sha256.h>
#include <ESP32Servo.h>
#include <cmath>
#include <esp_task_wdt.h>
#include <blastgate_proto.h>

#ifndef FW_VERSION
#define FW_VERSION "1.5.0-dev"
#endif

// TX power in 0.25 dBm units (80 = 20 dBm). External antenna builds back off a bit.
#ifdef EXTERNAL_ANTENNA
#define BG_TX_POWER 68
#else
#define BG_TX_POWER 80
#endif

// Both actuators are driven in parallel; report what this build is for.
#ifndef NODE_ACTUATOR
#define NODE_ACTUATOR BG_ACT_BOTH
#endif

// ================= HUB SOFT AP (only used for OTA) =================
static const char* HUB_AP_SSID = "BLASTGATE_HUB";
static const char* HUB_AP_PASS = "12345678";

// ================= AUTO NODE ID (MAC-based) =================
static String  NODE_ID;
static uint8_t myMac[6];

// ================= PINS =================
// GPIO36 (VP) = ADC1_CH0: best ADC pin on ESP32
// - ADC1 works with WiFi active (ADC2 does NOT)
// - Input-only, no digital noise, no conflict with LEDC/PWM
constexpr int SENSOR_PIN    = 36;
constexpr int SERVO_PIN     = 18;
constexpr int BTN_PIN       = 27;
constexpr int CALIB_LED_PIN = 2;
constexpr int END_OPEN_PIN  = 32;
constexpr int END_CLOSE_PIN = 33;

// ================= H-BRIDGE PINS (HW-095 / L298N) =================
constexpr int HBRIDGE_IN1_PIN = 19;   // open direction  → IN1 on HW-095
constexpr int HBRIDGE_IN2_PIN = 21;   // close direction → IN2 on HW-095
static uint32_t hbridge_open_ms  = 2000;  // run time, or timeout when end switches are enabled
static uint32_t hbridge_close_ms = 2000;
static bool     endstopsEnabled  = false; // set by hub CONFIG

// ================= SERVO ANGLES =================
constexpr int SERVO_HOME_DEG = 0;
constexpr int SERVO_OPEN_DEG = 180;

// ================= SERVO CONTROL =================
Servo gateServo;
constexpr uint32_t SERVO_MIN_MOVE_INTERVAL_MS = 250;
uint32_t lastServoMoveMs = 0;

volatile uint8_t gateOverride = 0;  // 0=AUTO, 1=OPEN, 2=CLOSE

// H-bridge state (non-blocking motor run timer)
enum HBridgeState { HB_IDLE, HB_OPENING, HB_CLOSING };
static HBridgeState hbState        = HB_IDLE;
static uint32_t     hbStartMs      = 0;
static uint8_t      hbLastOverride = 2;  // assume gate starts closed — no h-bridge on boot

// ================= LINK TIMING =================
uint32_t lastValueMs   = 0;
uint32_t lastHubSeenMs = 0;

constexpr uint32_t HUB_FAILSAFE_MS   = 12000;
constexpr uint32_t HEARTBEAT_LOST_MS = 5000;   // start channel scan
constexpr uint32_t SCAN_DWELL_MS     = 100;    // wait for HELLO_ACK per channel
constexpr uint32_t PAIRING_WINDOW_MS = 60000;
constexpr uint32_t BTN_LONG_MS       = 3000;

// ================= PERFORMANCE (DATA) =================
constexpr uint32_t VALUE_EVERY_MS      = 2000;  // periodic DATA
constexpr uint32_t DATA_MIN_GAP_MS     = 250;   // rate limit for change-triggered DATA
constexpr float    VALUE_CHANGE_SEND   = 5.0f;  // send early when value moves this much

// ================= ADC / FILTERS =================
int   offsetADC = 2048;
float ema       = 0.0f;
bool  emaInit   = false;
constexpr float EMA_ALPHA = 0.10f;  // jako smoothing, malo laznih alarma

// ================= SERVO BLANKING =================
// Ignorisi senzor nakon servo pokreta (struja motora pravi spike)
constexpr uint32_t SERVO_BLANKING_MS = 600;
static uint32_t servoBlankingUntilMs = 0;

// ================= SPIKE DETECTOR =================
// Ignorise nagle skokove (npr. elektricni sum), prihvata nakon 3 uzastopna
constexpr float   SPIKE_JUMP_THRESHOLD = 80.0f;
constexpr uint8_t SPIKE_ACCEPT_AFTER   = 3;
static float    lastValidReading     = 0.0f;
static uint8_t  consecutiveSpikeCount = 0;

// ================= STARTUP FIX =================
static uint32_t bootMs = 0;
constexpr uint32_t BOOT_HOLD_MS = 2500;

// ================= KALIBRACIJA OPSEG =================
// Posle warmup-a, EMA mora da bude u opsegu [CALIB_MIN..CALIB_MAX]
// za CALIB_NEED_OK uzastopnih citanja. Ako nije -> restart.
// LED blinka dok kalibracija nije OK.
constexpr float   CALIB_MIN     = 0.0f;
constexpr float   CALIB_MAX     = 30.0f;   // normalna vrednost u mirovanju max 30
constexpr uint8_t CALIB_NEED_OK = 8;       // 8 uzastopnih OK citanja = kalibrisano

static bool    calibrated   = false;
static uint8_t calibOkCount = 0;

// Calibration LED state
static uint32_t calibLedT     = 0;
static bool     calibLedState = false;

// ================= WARMUP OFFSET =================
static bool     sensorReady = false;
static uint32_t warmCount   = 0;
static uint32_t warmTarget  = 1600;
static uint64_t warmSum     = 0;

// ================= THRESHOLDS (ESP32 ADC range) =================
constexpr float    MAX_VALID_VALUE      = 250.0f;
constexpr float    STUCK_HIGH_THRESHOLD = 200.0f;
constexpr uint32_t STUCK_HIGH_MS        = 3000;

static uint32_t stuckHighSinceMs = 0;

// ================= BUTTON =================
bool     lastBtnRaw      = HIGH;
bool     btnStable       = HIGH;
uint32_t btnLastChangeMs = 0;
uint32_t btnDownSinceMs  = 0;
bool     btnLongFired    = false;
constexpr uint32_t BTN_DEBOUNCE_MS = 35;
static uint8_t btnCount = 0;   // reported in DATA; hub toggles gate on change

// ================= END SWITCHES =================
struct DebouncedInput {
  int      pin;
  bool     stable   = false;  // true = active (pulled low)
  bool     lastRaw  = false;
  uint32_t changeMs = 0;
  void tick() {
    bool raw = (digitalRead(pin) == LOW);
    if (raw != lastRaw) { lastRaw = raw; changeMs = millis(); }
    if (millis() - changeMs >= 20) stable = raw;
  }
};
static DebouncedInput endOpen{END_OPEN_PIN};
static DebouncedInput endClose{END_CLOSE_PIN};

static uint8_t errFlags = 0;   // BG_ERR_*

// ================= ESP-NOW LINK STATE =================
static Preferences nprefs;               // namespace "bgnode"
static uint8_t  netKey[BG_KEY_LEN];
static bool     hasKey      = false;
static uint8_t  hubMac[6];
static bool     hubMacKnown = false;
static uint8_t  curChannel  = 1;
static uint8_t  savedChannel = 1;
static int8_t   lastRssi    = 0;
static uint16_t txSeq       = 0;
static uint16_t lastHubSeq  = 0;
static bool     lastHubSeqValid = false;

enum LinkState : uint8_t { LINK_SCAN, LINK_UP };
static LinkState linkState   = LINK_SCAN;
static uint32_t  lastHbMs    = 0;
static uint8_t   scanIdx     = 0;       // 0 = saved channel, 1..13 = channel list
static uint32_t  scanStepMs  = 0;

static uint32_t  pairingUntilMs = 0;
static inline bool pairingActive() { return pairingUntilMs && (int32_t)(pairingUntilMs - millis()) > 0; }

// RX queue: ESP-NOW callback runs in the WiFi task; parse in loop()
struct RxItem { uint8_t src[6]; int8_t rssi; int len; uint8_t data[BG_MAX_FRAME]; };
static QueueHandle_t rxQueue;

// TX retry: last unicast frame, resent up to 3x when the send callback reports FAIL
static uint8_t  txBuf[BG_MAX_FRAME];
static size_t   txLen      = 0;
static uint8_t  txDst[6];
static uint8_t  txRetries  = 0;
static volatile uint8_t txResult = 0;   // 0 idle/pending, 1 ok, 2 fail
constexpr uint8_t TX_MAX_RETRY = 3;

// Last DATA sent (for change-triggered sends)
static float    lastSentValue = -1000.0f;
static uint8_t  lastSentGate  = 0xFF;
static uint8_t  lastSentErr   = 0xFF;
static uint8_t  lastSentBtn   = 0xFF;
static uint8_t  lastSentEnd   = 0xFF;
static bool     dataNow       = false;

static bool     rebootPending = false;
static uint32_t rebootAtMs    = 0;

// ================= OTA =================
enum OtaState : uint8_t { OTA_IDLE, OTA_CONNECTING };
static OtaState otaState   = OTA_IDLE;
static uint32_t otaStartMs = 0;
static bg_cmd_t otaCmd;
constexpr uint32_t OTA_TIMEOUT_MS = 120000;

// ================= NON-BLOCKING SAMPLER =================
struct AvgDevSampler {
  bool     running     = false;
  uint32_t target      = 240;
  uint32_t count       = 0;
  uint32_t acc         = 0;
  uint32_t lastStepUs  = 0;
  uint32_t stepEveryUs = 150;
  bool     done        = false;
  float    result      = 0.0f;

  void start(uint32_t n, uint32_t stepUs) {
    running     = true;
    done        = false;
    target      = n;
    stepEveryUs = stepUs;
    count       = 0;
    acc         = 0;
    lastStepUs  = micros();
  }

  void stop() { running = false; done = false; }

  void tick(int offset) {
    if (!running) return;
    uint32_t nowUs = micros();
    if ((uint32_t)(nowUs - lastStepUs) < stepEveryUs) return;
    lastStepUs = nowUs;

    int raw = analogRead(SENSOR_PIN);
    acc += (uint32_t)abs(raw - offset);
    count++;

    if (count >= target) {
      result  = (float)acc / (float)target;
      done    = true;
      running = false;
    }
  }
};

static AvgDevSampler sampler;

// ================= Helpers =================
static inline bool inBootHold()      { return (millis() - bootMs) < BOOT_HOLD_MS; }
static inline bool inServoBlanking() { return millis() < servoBlankingUntilMs; }

static void resetFilters() {
  emaInit      = false;
  ema          = 0.0f;
  calibrated   = false;
  calibOkCount = 0;
}

// LED priority: pairing (fast) > unpaired (slow) > calibration (150ms) > off
static void calibLedUpdate() {
  uint32_t now = millis();
  uint32_t period = 0;
  if (pairingActive())                  period = 60;
  else if (!hasKey)                     period = 1000;
  else if (!sensorReady || !calibrated) period = 150;

  if (period) {
    if (now - calibLedT >= period) {
      calibLedT     = now;
      calibLedState = !calibLedState;
      digitalWrite(CALIB_LED_PIN, calibLedState ? HIGH : LOW);
    }
  } else {
    digitalWrite(CALIB_LED_PIN, LOW);
  }
}

static void warmupOffsetStep() {
  if (sensorReady) return;

  const int stepN = 12;
  for (int i = 0; i < stepN && warmCount < warmTarget; i++) {
    warmSum += (uint32_t)analogRead(SENSOR_PIN);
    warmCount++;
  }

  if (warmCount >= warmTarget) {
    offsetADC   = (int)(warmSum / (uint64_t)warmCount);
    sensorReady = true;
    resetFilters();
    Serial.printf("[WARMUP] OffsetADC=%d (samples=%u)\n", offsetADC, warmCount);
  }
}

static float sanitizeValue(float v) {
  if (!isfinite(v)) return 0.0f;
  if (v < 0.0f) return 0.0f;
  if (v > MAX_VALID_VALUE) return 0.0f;
  return v;
}

static void forceRecalOffset() {
  Serial.println("[RECAL] force recal offset + reset EMA");
  sensorReady      = false;
  warmCount        = 0;
  warmSum          = 0;
  stuckHighSinceMs = 0;
  resetFilters();
  bootMs = millis();
  sampler.stop();
}

static bool isSpikeReading(float newVal) {
  if (!emaInit) return false;

  float diff = fabs(newVal - lastValidReading);
  if (diff > SPIKE_JUMP_THRESHOLD) {
    consecutiveSpikeCount++;
    if (consecutiveSpikeCount >= SPIKE_ACCEPT_AFTER) {
      Serial.printf("[SPIKE] accept after %u consecutive (diff=%.1f)\n", consecutiveSpikeCount, diff);
      consecutiveSpikeCount = 0;
      return false;
    }
    Serial.printf("[SPIKE] %u/%u diff=%.1f > %.1f ignore\n",
                  consecutiveSpikeCount, SPIKE_ACCEPT_AFTER, diff, SPIKE_JUMP_THRESHOLD);
    return true;
  }
  consecutiveSpikeCount = 0;
  return false;
}

static void servoWriteSafe(int deg) {
  uint32_t now = millis();
  if (now - lastServoMoveMs < SERVO_MIN_MOVE_INTERVAL_MS) return;
  lastServoMoveMs = now;

  deg = constrain(deg, 0, 180);
  static int lastDeg = -999;
  if (deg == lastDeg) return;
  lastDeg = deg;

  servoBlankingUntilMs = now + SERVO_BLANKING_MS;
  Serial.printf("[SERVO] move %d deg, blank until %lu\n", deg, servoBlankingUntilMs);

  gateServo.write(deg);
}

static void hbridgeStop() {
  digitalWrite(HBRIDGE_IN1_PIN, LOW);
  digitalWrite(HBRIDGE_IN2_PIN, LOW);
  hbState = HB_IDLE;
}

// Called every loop(). Without end switches the motor runs for a fixed time.
// With end switches it stops on the switch; the run time becomes a timeout.
static void hbridgeTick() {
  if (hbState == HB_IDLE) return;
  const bool opening = (hbState == HB_OPENING);

  if (endstopsEnabled) {
    bool reached = opening ? endOpen.stable : endClose.stable;
    if (reached) {
      hbridgeStop();
      Serial.printf("[HBRIDGE] stop on end switch (%s)\n", opening ? "open" : "close");
      return;
    }
  }

  uint32_t runMs = opening ? hbridge_open_ms : hbridge_close_ms;
  if ((millis() - hbStartMs) >= runMs) {
    hbridgeStop();
    if (endstopsEnabled) {
      errFlags |= opening ? BG_ERR_OPEN_TIMEOUT : BG_ERR_CLOSE_TIMEOUT;
      Serial.printf("[HBRIDGE] TIMEOUT — end switch not reached (%s)\n", opening ? "open" : "close");
    } else {
      Serial.println("[HBRIDGE] stop");
    }
  }
}

static void gateOpen() {
  servoWriteSafe(SERVO_OPEN_DEG);
  if (hbLastOverride != 1) {
    hbLastOverride = 1;
    errFlags &= ~BG_ERR_OPEN_TIMEOUT;
    if (endstopsEnabled && endOpen.stable) {
      hbridgeStop();
      Serial.println("[HBRIDGE] open: already at END_OPEN");
      return;
    }
    uint32_t now = millis();
    servoBlankingUntilMs = now + hbridge_open_ms + SERVO_BLANKING_MS;
    Serial.printf("[HBRIDGE] open (%ums)\n", hbridge_open_ms);
    digitalWrite(HBRIDGE_IN1_PIN, HIGH);
    digitalWrite(HBRIDGE_IN2_PIN, LOW);
    hbState   = HB_OPENING;
    hbStartMs = now;
  }
}

static void gateHome() {
  servoWriteSafe(SERVO_HOME_DEG);
  if (hbLastOverride != 2) {
    hbLastOverride = 2;
    errFlags &= ~BG_ERR_CLOSE_TIMEOUT;
    if (endstopsEnabled && endClose.stable) {
      hbridgeStop();
      Serial.println("[HBRIDGE] close: already at END_CLOSE");
      return;
    }
    uint32_t now = millis();
    servoBlankingUntilMs = now + hbridge_close_ms + SERVO_BLANKING_MS;
    Serial.printf("[HBRIDGE] close (%ums)\n", hbridge_close_ms);
    digitalWrite(HBRIDGE_IN1_PIN, LOW);
    digitalWrite(HBRIDGE_IN2_PIN, HIGH);
    hbState   = HB_CLOSING;
    hbStartMs = now;
  }
}

static uint8_t gateStateNow() {
  if (endstopsEnabled) {
    if (endOpen.stable && endClose.stable) return BG_GATE_UNKNOWN;
    if (endOpen.stable)  return BG_GATE_OPEN;
    if (endClose.stable) return BG_GATE_CLOSED;
    if (hbState == HB_OPENING) return BG_GATE_OPENING;
    if (hbState == HB_CLOSING) return BG_GATE_CLOSING;
    return BG_GATE_UNKNOWN;
  }
  if (hbState == HB_OPENING) return BG_GATE_OPENING;
  if (hbState == HB_CLOSING) return BG_GATE_CLOSING;
  return (gateOverride == 1) ? BG_GATE_OPEN : BG_GATE_CLOSED;
}

// ================= ESP-NOW =================
static const uint8_t BCAST[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
static const uint8_t ZERO_KEY[BG_KEY_LEN] = {0};

static void onEspNowRecv(const esp_now_recv_info_t* info, const uint8_t* data, int len) {
  if (len <= 0 || len > BG_MAX_FRAME) return;
  RxItem it;
  memcpy(it.src, info->src_addr, 6);
  it.rssi = info->rx_ctrl ? (int8_t)info->rx_ctrl->rssi : 0;
  it.len  = len;
  memcpy(it.data, data, len);
  xQueueSend(rxQueue, &it, 0);
}

static void onEspNowSent(const esp_now_send_info_t* /*info*/, esp_now_send_status_t status) {
  txResult = (status == ESP_NOW_SEND_SUCCESS) ? 1 : 2;
}

static void ensurePeer(const uint8_t mac[6]) {
  if (esp_now_is_peer_exist(mac)) return;
  esp_now_peer_info_t p = {};
  memcpy(p.peer_addr, mac, 6);
  p.channel = 0;             // follow current channel
  p.ifidx   = WIFI_IF_STA;
  p.encrypt = false;
  esp_now_add_peer(&p);
}

static void setChannel(uint8_t ch) {
  if (ch < 1 || ch > 13) return;
  if (ch == curChannel) return;
  esp_wifi_set_channel(ch, WIFI_SECOND_CHAN_NONE);
  curChannel = ch;
}

// Send a signed frame. Unicast frames are kept for retry on send failure.
static void sendFrame(const uint8_t dst[6], uint8_t type, const void* payload, size_t plen,
                      const uint8_t* key) {
  uint8_t buf[BG_MAX_FRAME];
  size_t n = bg_build(buf, type, ++txSeq, myMac, payload, plen, key);
  bool unicast = memcmp(dst, BCAST, 6) != 0;
  if (unicast) {
    ensurePeer(dst);
    memcpy(txBuf, buf, n); txLen = n; memcpy(txDst, dst, 6);
    txRetries = 0; txResult = 0;
  }
  esp_now_send(dst, buf, n);
}

static void txRetryTick() {
  if (txResult != 2 || !txLen) return;
  if (txRetries >= TX_MAX_RETRY) { txLen = 0; txResult = 0; return; }
  txRetries++;
  txResult = 0;
  esp_now_send(txDst, txBuf, txLen);
}

static void sendHello() {
  bg_hello_t h = {};
  strncpy(h.fw, FW_VERSION, sizeof(h.fw) - 1);
  h.actuator = NODE_ACTUATOR;
  h.flags    = pairingActive() ? BG_HELLO_PAIR_REQ : 0;
  h.channel  = curChannel;
  const uint8_t* key = (pairingActive() || !hasKey) ? ZERO_KEY : netKey;
  sendFrame(BCAST, BG_HELLO, &h, sizeof(h), key);
}

static void sendAck(uint16_t seq, uint8_t type, uint8_t status) {
  if (!hubMacKnown) return;
  bg_ack_t a = { seq, type, status };
  sendFrame(hubMac, BG_ACK, &a, sizeof(a), netKey);
}

static uint8_t endstopBits() {
  return (endOpen.stable ? 1 : 0) | (endClose.stable ? 2 : 0);
}

static void sendData(float v) {
  if (!hubMacKnown || !hasKey) return;
  bg_data_t d = {};
  d.value     = v;
  d.gate      = gateStateNow();
  d.err       = errFlags | (calibrated ? 0 : BG_ERR_NOT_CALIBRATED);
  d.btn_count = btnCount;
  d.endstops  = endstopBits();
  d.uptime_s  = millis() / 1000;
  d.rssi      = lastRssi;
  sendFrame(hubMac, BG_DATA, &d, sizeof(d), netKey);
  lastSentValue = v; lastSentGate = d.gate; lastSentErr = d.err;
  lastSentBtn   = d.btn_count; lastSentEnd = d.endstops;
  lastValueMs   = millis();
}

static void saveChannel(uint8_t ch) {
  if (ch == savedChannel) return;
  savedChannel = ch;
  nprefs.begin("bgnode", false);
  nprefs.putUChar("ch", ch);
  nprefs.end();
  Serial.printf("[LINK] saved channel %u\n", ch);
}

static void applyConfig(const bg_config_t& c) {
  hbridge_open_ms  = c.hbridge_open_ms;
  hbridge_close_ms = c.hbridge_close_ms;
  endstopsEnabled  = c.endstops != 0;
  Serial.printf("[CFG] hbo=%u hbc=%u endstops=%d\n", hbridge_open_ms, hbridge_close_ms, (int)endstopsEnabled);
}

static void enterScan(const char* why) {
  if (linkState != LINK_SCAN) Serial.printf("[LINK] scan start (%s)\n", why);
  linkState  = LINK_SCAN;
  scanIdx    = 0;
  scanStepMs = 0;
}

static void startOta(const bg_cmd_t& c);

static void handleHubFrame(const RxItem& it) {
  const uint8_t* f = it.data;
  const bg_hdr_t* h = bg_header(f);
  if (it.len < (int)sizeof(bg_hdr_t)) return;
  if (memcmp(h->mac, it.src, 6) != 0) return;   // header MAC must match radio source

  int plen;
  if (h->type == BG_HELLO_ACK && pairingActive()) {
    // Pairing: the key travels inside this frame; verify the tag with it.
    if (it.len < (int)(sizeof(bg_hdr_t) + sizeof(bg_hello_ack_t) + BG_TAG_LEN)) return;
    bg_hello_ack_t a;
    memcpy(&a, bg_payload(f), sizeof(a));
    if (!(a.flags & BG_ACK_HAS_KEY)) return;
    plen = bg_check(f, it.len, a.key);
    if (plen != (int)sizeof(bg_hello_ack_t)) return;
    memcpy(netKey, a.key, BG_KEY_LEN);
    hasKey = true;
    nprefs.begin("bgnode", false);
    nprefs.putBytes("key", netKey, BG_KEY_LEN);
    nprefs.end();
    pairingUntilMs = 0;
    Serial.println("[PAIR] paired — network key stored");
  } else {
    if (!hasKey) return;
    plen = bg_check(f, it.len, netKey);
    if (plen == -2) { Serial.printf("[RX] unknown proto_version %u — ignored\n", h->ver); return; }
    if (plen < 0) return;
  }

  // Only hub-originated types are handled; other nodes' HELLOs are ignored.
  if (h->type != BG_HELLO_ACK && h->type != BG_CMD &&
      h->type != BG_CONFIG && h->type != BG_HEARTBEAT) return;

  uint32_t now = millis();
  lastHubSeenMs = now;
  lastRssi      = it.rssi;
  if (!hubMacKnown || memcmp(hubMac, it.src, 6) != 0) {
    memcpy(hubMac, it.src, 6);
    hubMacKnown = true;
    ensurePeer(hubMac);
  }

  switch (h->type) {
    case BG_HELLO_ACK: {
      if (plen != (int)sizeof(bg_hello_ack_t)) return;
      bg_hello_ack_t a;
      memcpy(&a, bg_payload(f), sizeof(a));
      setChannel(a.channel);
      saveChannel(a.channel);
      applyConfig(a.cfg);
      if (linkState != LINK_UP) Serial.printf("[LINK] up on channel %u\n", a.channel);
      linkState = LINK_UP;
      lastHbMs  = now;
      dataNow   = true;
      break;
    }
    case BG_HEARTBEAT: {
      if (plen != (int)sizeof(bg_heartbeat_t)) return;
      lastHbMs = now;
      if (linkState != LINK_UP) {
        // Heard the hub while scanning: stay on this channel and announce
        // ourselves (hub answers with HELLO_ACK + config).
        bg_heartbeat_t hb;
        memcpy(&hb, bg_payload(f), sizeof(hb));
        setChannel(hb.channel);
        saveChannel(hb.channel);
        linkState = LINK_UP;
        Serial.printf("[LINK] up on channel %u (heartbeat)\n", hb.channel);
        sendHello();
      }
      break;
    }
    case BG_CONFIG: {
      if (plen != (int)sizeof(bg_config_t)) return;
      bool dup = lastHubSeqValid && h->seq == lastHubSeq;
      lastHubSeq = h->seq; lastHubSeqValid = true;
      if (!dup) {
        bg_config_t c;
        memcpy(&c, bg_payload(f), sizeof(c));
        applyConfig(c);
      }
      sendAck(h->seq, BG_CONFIG, 0);
      break;
    }
    case BG_CMD: {
      if (plen != (int)sizeof(bg_cmd_t)) return;
      bool dup = lastHubSeqValid && h->seq == lastHubSeq;
      lastHubSeq = h->seq; lastHubSeqValid = true;
      bg_cmd_t c;
      memcpy(&c, bg_payload(f), sizeof(c));
      sendAck(h->seq, BG_CMD, 0);
      if (dup) break;
      switch (c.cmd) {
        case BG_CMD_OPEN:      gateOverride = 1; break;
        case BG_CMD_CLOSE:     gateOverride = 2; break;
        case BG_CMD_AUTO:      gateOverride = 0; break;
        case BG_CMD_CALIBRATE: forceRecalOffset(); break;
        case BG_CMD_REBOOT:    rebootPending = true; rebootAtMs = now + 300; break;
        case BG_CMD_OTA_START: startOta(c); break;
      }
      Serial.printf("[CMD] %u -> ov=%u\n", c.cmd, gateOverride);
      dataNow = true;
      break;
    }
  }
}

static void processRx() {
  RxItem it;
  while (xQueueReceive(rxQueue, &it, 0) == pdTRUE) handleHubFrame(it);
}

// Non-blocking scan: one channel per SCAN_DWELL_MS, saved channel first.
static void linkTick() {
  uint32_t now = millis();
  if (otaState != OTA_IDLE) return;

  if (!hasKey && !pairingActive()) return;   // unpaired: stay silent

  if (linkState == LINK_UP) {
    if (now - lastHbMs > HEARTBEAT_LOST_MS) enterScan("heartbeat lost");
    else return;
  }

  if (scanStepMs && now - scanStepMs < SCAN_DWELL_MS) return;
  scanStepMs = now;

  // Order: saved channel, then 1..13 without the saved one (13 steps per cycle)
  uint8_t ch = (scanIdx == 0) ? savedChannel
                              : (scanIdx >= savedChannel ? scanIdx + 1 : scanIdx);
  scanIdx = (scanIdx + 1) % 13;
  if (curChannel != ch) {
    esp_wifi_set_channel(ch, WIFI_SECOND_CHAN_NONE);
    curChannel = ch;
  }
  sendHello();
}

// ================= OTA (hybrid: join hub Soft AP, pull firmware) =================
static void otaAbort(const char* why) {
  Serial.printf("[OTA] abort: %s\n", why);
  errFlags |= BG_ERR_OTA_FAILED;
  otaState = OTA_IDLE;
  WiFi.disconnect(false, false);
  curChannel = 0;   // STA join moved the radio; force the scan to set it again
  enterScan("ota finished");
}

static void startOta(const bg_cmd_t& c) {
  if (otaState != OTA_IDLE) return;
  otaCmd = c;
  otaCmd.url[sizeof(otaCmd.url) - 1] = 0;
  Serial.printf("[OTA] start: %s (%u bytes)\n", otaCmd.url, otaCmd.fw_size);
  errFlags &= ~BG_ERR_OTA_FAILED;
  gateOverride = 2;              // safe state while offline
  otaState   = OTA_CONNECTING;
  otaStartMs = millis();
  WiFi.begin(HUB_AP_SSID, HUB_AP_PASS);
}

static bool otaTimedOut() { return millis() - otaStartMs > OTA_TIMEOUT_MS; }

// Blocking download once connected; feeds the watchdog on every chunk.
static void otaDownload() {
  HTTPClient http;
  http.setTimeout(10000);
  if (!http.begin(otaCmd.url)) { otaAbort("bad url"); return; }
  int code = http.GET();
  if (code != 200) { http.end(); otaAbort("http status"); return; }
  int len = http.getSize();
  if (len <= 0 || (uint32_t)len != otaCmd.fw_size) { http.end(); otaAbort("size mismatch"); return; }
  if (!Update.begin(len)) { http.end(); otaAbort("Update.begin"); return; }

  mbedtls_sha256_context sha;
  mbedtls_sha256_init(&sha);
  mbedtls_sha256_starts(&sha, 0);

  WiFiClient* s = http.getStreamPtr();
  uint8_t buf[1024];
  int left = len;
  while (left > 0) {
    esp_task_wdt_reset();
    if (otaTimedOut() || !http.connected()) break;
    size_t avail = s->available();
    if (!avail) { delay(1); continue; }
    int n = s->readBytes(buf, min((int)sizeof(buf), min((int)avail, left)));
    if (n <= 0) continue;
    mbedtls_sha256_update(&sha, buf, n);
    if (Update.write(buf, n) != (size_t)n) break;
    left -= n;
  }
  uint8_t digest[32];
  mbedtls_sha256_finish(&sha, digest);
  mbedtls_sha256_free(&sha);
  http.end();

  if (left != 0)                               { Update.abort(); otaAbort("download incomplete"); return; }
  if (memcmp(digest, otaCmd.sha256, 32) != 0)  { Update.abort(); otaAbort("sha256 mismatch"); return; }
  if (!Update.end(true))                       { otaAbort("Update.end"); return; }

  Serial.println("[OTA] OK -> restart");
  delay(200);
  ESP.restart();
}

static void otaTick() {
  if (otaState == OTA_IDLE) return;
  if (otaTimedOut()) { otaAbort("timeout 120s"); return; }
  if (WiFi.status() == WL_CONNECTED) otaDownload();
}

// ================= Node ID =================
// Hub derives the same ID from the ESP-NOW source MAC (last 3 bytes).
static void buildNodeId() {
  esp_read_mac(myMac, ESP_MAC_WIFI_STA);
  char id[16];
  snprintf(id, sizeof(id), "BG-%02X%02X%02X", myMac[3], myMac[4], myMac[5]);
  NODE_ID = String(id);
}

// ================= Radio =================
static void radioInit() {
  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.disconnect(false, false);
  esp_wifi_set_protocol(WIFI_IF_STA,
    WIFI_PROTOCOL_11B | WIFI_PROTOCOL_11G | WIFI_PROTOCOL_11N | WIFI_PROTOCOL_LR);
  esp_wifi_set_max_tx_power(BG_TX_POWER);
  esp_wifi_set_channel(savedChannel, WIFI_SECOND_CHAN_NONE);
  curChannel = savedChannel;

  if (esp_now_init() != ESP_OK) {
    Serial.println("[ESPNOW] init FAILED -> restart");
    delay(500);
    ESP.restart();
  }
  esp_now_register_recv_cb(onEspNowRecv);
  esp_now_register_send_cb(onEspNowSent);
  ensurePeer(BCAST);
  Serial.printf("[ESPNOW] ready, channel %u, tx_power %d\n", curChannel, BG_TX_POWER);
}

// ================= Button =================
// Short press (<3s, fires on release): toggle request to hub (btn_count++).
// Long press (>=3s): 60s pairing window.
static void handleButton() {
  bool raw = digitalRead(BTN_PIN);
  uint32_t now = millis();
  if (raw != lastBtnRaw) { lastBtnRaw = raw; btnLastChangeMs = now; }
  if (now - btnLastChangeMs < BTN_DEBOUNCE_MS) return;

  if (raw != btnStable) {
    btnStable = raw;
    if (btnStable == LOW) {
      btnDownSinceMs = now;
      btnLongFired   = false;
    } else if (!btnLongFired) {
      btnCount++;
      dataNow = true;
      Serial.printf("[BTN] short press -> HUB (count=%u)\n", btnCount);
    }
  }

  if (btnStable == LOW && !btnLongFired && now - btnDownSinceMs >= BTN_LONG_MS) {
    btnLongFired   = true;
    pairingUntilMs = now + PAIRING_WINDOW_MS;
    if (!pairingUntilMs) pairingUntilMs = 1;
    enterScan("pairing");
    Serial.println("[PAIR] pairing mode 60s");
  }
}

// ================= Gate logic =================
static void applyGateFromOverride() {
  if (gateOverride == 1) gateOpen();
  else gateHome();
}

// ================= SETUP =================
void setup() {
  Serial.begin(115200);
  delay(150);

  Serial.println("[WDT] Init watchdog (30s)");
#if ESP_IDF_VERSION >= ESP_IDF_VERSION_VAL(5, 0, 0)
  const esp_task_wdt_config_t wdt_cfg = {
    .timeout_ms     = 30000,
    .idle_core_mask = 0,
    .trigger_panic  = true
  };
  esp_task_wdt_reconfigure(&wdt_cfg);
#else
  esp_task_wdt_init(30, true);
#endif
  esp_task_wdt_add(NULL);

  bootMs = millis();

  rxQueue = xQueueCreate(8, sizeof(RxItem));

  pinMode(BTN_PIN, INPUT_PULLUP);
  pinMode(END_OPEN_PIN, INPUT_PULLUP);
  pinMode(END_CLOSE_PIN, INPUT_PULLUP);
  pinMode(CALIB_LED_PIN, OUTPUT);
  digitalWrite(CALIB_LED_PIN, LOW);

  analogReadResolution(12);

  gateServo.setPeriodHertz(50);
  gateServo.attach(SERVO_PIN, 500, 2400);
  gateServo.write(SERVO_HOME_DEG);

  pinMode(HBRIDGE_IN1_PIN, OUTPUT);
  pinMode(HBRIDGE_IN2_PIN, OUTPUT);
  digitalWrite(HBRIDGE_IN1_PIN, LOW);
  digitalWrite(HBRIDGE_IN2_PIN, LOW);
  Serial.println("[HBRIDGE] init OK");

  nprefs.begin("bgnode", true);
  hasKey = nprefs.getBytes("key", netKey, BG_KEY_LEN) == BG_KEY_LEN;
  savedChannel = nprefs.getUChar("ch", 1);
  nprefs.end();
  if (savedChannel < 1 || savedChannel > 13) savedChannel = 1;

  WiFi.mode(WIFI_STA);   // MAC is valid after the driver is up
  buildNodeId();
  Serial.printf("[NODE] ID=%s MAC=%s fw=%s paired=%d ch=%u\n",
                NODE_ID.c_str(), WiFi.macAddress().c_str(), FW_VERSION, (int)hasKey, savedChannel);

  radioInit();
  forceRecalOffset();
  lastHubSeenMs = millis();
  enterScan("boot");

  Serial.println("[NODE] START OK (ESP-NOW)");
}

// ================= LOOP =================
void loop() {
  esp_task_wdt_reset();

  processRx();
  txRetryTick();
  handleButton();
  endOpen.tick();
  endClose.tick();
  linkTick();
  otaTick();

  if (rebootPending && (int32_t)(millis() - rebootAtMs) >= 0) ESP.restart();

  warmupOffsetStep();

  // --- Sensor sampling (non-blocking) ---
  const bool blanking = inServoBlanking();

  if (sensorReady && !blanking && !sampler.running && !sampler.done) {
    sampler.start(240, 150);
  }

  if (sensorReady && !blanking) {
    sampler.tick(offsetADC);
  } else {
    sampler.stop();
  }

  // Update filters when sampler finishes
  if (sampler.done) {
    float avgDeviation = sampler.result;
    sampler.done = false;

    bool isSpike = isSpikeReading(avgDeviation);

    if (!isSpike) {
      if (!emaInit) {
        ema              = avgDeviation;
        emaInit          = true;
        lastValidReading = avgDeviation;
      } else {
        ema              = (EMA_ALPHA * avgDeviation) + ((1.0f - EMA_ALPHA) * ema);
        lastValidReading = avgDeviation;
      }
    }
  }

  // Calibration range check
  if (sensorReady && !inBootHold() && emaInit && !calibrated) {
    if (ema >= CALIB_MIN && ema <= CALIB_MAX) {
      calibOkCount++;
      if (calibOkCount >= CALIB_NEED_OK) {
        calibrated = true;
        Serial.printf("[CALIB] OK: ema=%.2f in [%.1f..%.1f] (%u samples)\n",
                      ema, CALIB_MIN, CALIB_MAX, calibOkCount);
      }
    } else {
      Serial.printf("[CALIB] van opsega (ema=%.2f > %.1f) -> restart!\n", ema, CALIB_MAX);
      delay(300);
      ESP.restart();
    }
  }

  float vSend = sensorReady ? ema : 0.0f;
  if (!sensorReady || inBootHold() || !calibrated) vSend = 0.0f;
  // During blanking (servo/hbridge active): sampler stops but ema holds last valid reading.
  // Send that instead of 0 to avoid false drop on UI.
  vSend = sanitizeValue(vSend);

  // Stuck-high detector
  {
    uint32_t now = millis();
    if (vSend >= STUCK_HIGH_THRESHOLD) {
      if (stuckHighSinceMs == 0) stuckHighSinceMs = now;
      if (now - stuckHighSinceMs >= STUCK_HIGH_MS) forceRecalOffset();
    } else {
      stuckHighSinceMs = 0;
    }
  }

  // End switch wiring fault
  if (endstopsEnabled && endOpen.stable && endClose.stable) errFlags |= BG_ERR_ENDSTOP_BOTH;
  else errFlags &= ~BG_ERR_ENDSTOP_BOTH;

  // DATA: periodic, or early when something changed
  if (linkState == LINK_UP && otaState == OTA_IDLE) {
    uint32_t now = millis();
    uint8_t err = errFlags | (calibrated ? 0 : BG_ERR_NOT_CALIBRATED);
    bool changed = dataNow ||
                   gateStateNow() != lastSentGate || err != lastSentErr ||
                   btnCount != lastSentBtn || endstopBits() != lastSentEnd ||
                   fabs(vSend - lastSentValue) >= VALUE_CHANGE_SEND;
    if (now - lastValueMs >= VALUE_EVERY_MS ||
        (changed && now - lastValueMs >= DATA_MIN_GAP_MS)) {
      dataNow = false;
      sendData(vSend);
    }
  }

  // Failsafe: no valid hub frame for 12s -> close
  if (millis() - lastHubSeenMs > HUB_FAILSAFE_MS) {
    if (gateOverride != 2) {
      gateOverride = 2;
      Serial.println("[FAILSAFE] no HUB -> CLOSE");
    }
  }

  applyGateFromOverride();
  hbridgeTick();

  // Debug
  static uint32_t lastPrint = 0;
  if (millis() - lastPrint > 900) {
    lastPrint = millis();
    Serial.printf("[DBG] id=%s link=%s ch=%u rssi=%d ready=%d calib=%d(%u/%u) ema=%.2f send=%.2f off=%d ov=%u gate=%u err=0x%02X end=%u\n",
                  NODE_ID.c_str(), linkState == LINK_UP ? "UP" : "SCAN", curChannel, lastRssi,
                  (int)sensorReady, (int)calibrated, calibOkCount, CALIB_NEED_OK,
                  ema, vSend, offsetADC, gateOverride, gateStateNow(), errFlags, endstopBits());
  }

  calibLedUpdate();
  delay(2);
}
