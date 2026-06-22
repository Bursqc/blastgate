// file: src/main.cpp
// ============================================================
// BLASTGATE NODE (ESP32 classic)
//
// Pinout:
//   SENSOR=GPIO36 (VP, ADC1_CH0), SERVO=GPIO18, BTN=GPIO27
//   H-bridge: IN1=GPIO19, IN2=GPIO21
//
// Features:
// - Non-blocking ADC sampler (WDT-friendly on both platforms)
// - Warmup offset calibration (non-blocking)
// - BOOT HOLD: sends 0 while stabilizing
// - SERVO BLANKING: ignores sensor after actuator move
// - Consecutive spike detector + EMA smoothing
// - Watchdog timer (30s)
// - NODE_VALUE 1x/2s
// - H-BRIDGE: HW-095/L298N motor support (always active, configurable via CFG)
// ============================================================

#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <ESP32Servo.h>
#include <cmath>
#include <esp_task_wdt.h>

// ================= WIFI (HUB AP) =================
static const char* WIFI_SSID = "BLASTGATE_HUB";
static const char* WIFI_PASS = "12345678";

static IPAddress hubIP(192, 168, 4, 1);
static const uint16_t HUB_PORT = 8888;

// ================= AUTO NODE ID (MAC-based) =================
static String NODE_ID;

// ================= PINS =================
// GPIO36 (VP) = ADC1_CH0: best ADC pin on ESP32
// - ADC1 works with WiFi active (ADC2 does NOT)
// - Input-only, no digital noise, no conflict with LEDC/PWM
constexpr int SENSOR_PIN    = 36;
constexpr int SERVO_PIN     = 18;
constexpr int BTN_PIN       = 27;
constexpr int CALIB_LED_PIN = 2;

// ================= H-BRIDGE PINS (HW-095 / L298N) =================
constexpr int HBRIDGE_IN1_PIN = 19;   // open direction  → IN1 on HW-095
constexpr int HBRIDGE_IN2_PIN = 21;   // close direction → IN2 on HW-095
static uint32_t hbridge_open_ms  = 2000;  // motor run time for OPEN (configurable via CFG)
static uint32_t hbridge_close_ms = 2000;  // motor run time for CLOSE (configurable via CFG)

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

// ================= UDP =================
WiFiUDP udp;
static const uint16_t NODE_LISTEN_PORT = 12000;

uint32_t lastPingMs    = 0;
uint32_t lastValueMs   = 0;
uint32_t lastHubSeenMs = 0;
uint32_t lastHubCmdMs  = 0;

constexpr uint32_t HUB_FAILSAFE_MS     = 12000;  // 8s->12s: PING_SLOW=5s + buffer za packet loss
constexpr uint32_t PING_FAST_MS        = 1000;
constexpr uint32_t PING_SLOW_MS        = 5000;
constexpr uint32_t PING_FAST_WINDOW_MS = 10000;
uint32_t wifiConnectedAtMs = 0;

// ================= PERFORMANCE (NODE_VALUE) =================
constexpr uint32_t VALUE_EVERY_MS = 2000;  // salje 1x/2s

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
// Prihvati spike tek nakon N uzastopnih (ne ignorisi trajne promene)
constexpr float   SPIKE_JUMP_THRESHOLD = 80.0f;
constexpr uint8_t SPIKE_ACCEPT_AFTER   = 3;
static float    lastValidReading     = 0.0f;
static uint8_t  consecutiveSpikeCount = 0;

// ================= STARTUP FIX =================
static uint32_t bootMs = 0;
constexpr uint32_t BOOT_HOLD_MS = 2500;

// ================= KALIBRACIJA OPSEG =================
// Normalna vrednost U MIROVANJU mora biti u ovom opsegu.
// Podesi CALIB_MAX prema svom senzoru: gledaj "send=" dok urdjaj miruje,
// pa stavi CALIB_MAX = ta vrednost + 20% margine.
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

// ================= BUTTON DEBOUNCE =================
bool     lastBtnRaw      = HIGH;
bool     btnLatched      = false;
uint32_t btnLastChangeMs = 0;
constexpr uint32_t BTN_DEBOUNCE_MS = 35;

uint32_t lastHelloSentMs = 0;
constexpr uint32_t HELLO_THROTTLE_MS = 2000;

uint32_t lastBcastPingMs = 0;
constexpr uint32_t BCAST_PING_EVERY_MS = 6000;

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

static void calibLedUpdate() {
  if (!sensorReady || !calibrated) {
    uint32_t now = millis();
    if (now - calibLedT >= 150) {
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

// Called every loop() — stops H-bridge motor after direction-specific run time
static void hbridgeTick() {
  if (hbState == HB_IDLE) return;
  uint32_t runMs = (hbState == HB_OPENING) ? hbridge_open_ms : hbridge_close_ms;
  if ((millis() - hbStartMs) >= runMs) {
    digitalWrite(HBRIDGE_IN1_PIN, LOW);
    digitalWrite(HBRIDGE_IN2_PIN, LOW);
    hbState = HB_IDLE;
    Serial.println("[HBRIDGE] stop");
  }
}

static void gateOpen() {
  servoWriteSafe(SERVO_OPEN_DEG);
  if (hbLastOverride != 1) {
    hbLastOverride = 1;
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
    uint32_t now = millis();
    servoBlankingUntilMs = now + hbridge_close_ms + SERVO_BLANKING_MS;
    Serial.printf("[HBRIDGE] close (%ums)\n", hbridge_close_ms);
    digitalWrite(HBRIDGE_IN1_PIN, LOW);
    digitalWrite(HBRIDGE_IN2_PIN, HIGH);
    hbState   = HB_CLOSING;
    hbStartMs = now;
  }
}

// Extract "key=value" from a message string; returns empty String if not found
static String cfgGetArg(const String& msg, const char* key) {
  String k = String(key) + "=";
  int idx = msg.indexOf(k);
  if (idx < 0) return String();
  int start = idx + k.length();
  int end   = msg.indexOf(' ', start);
  if (end < 0) end = msg.length();
  return msg.substring(start, end);
}

// ================= UDP send =================
static void udpSendToHub(const String& msg) {
  if (WiFi.status() != WL_CONNECTED) return;
  udp.beginPacket(hubIP, HUB_PORT);
  udp.print(msg);
  udp.endPacket();
}

static void udpSendBroadcast(const String& msg) {
  if (WiFi.status() != WL_CONNECTED) return;
  udp.beginPacket(IPAddress(255, 255, 255, 255), HUB_PORT);
  udp.print(msg);
  udp.endPacket();
}

static void sendPing()  { udpSendToHub(String("NODE_PING id=")  + NODE_ID + " port=" + String(NODE_LISTEN_PORT)); }
static void sendHello() { udpSendToHub(String("NODE_HELLO id=") + NODE_ID + " port=" + String(NODE_LISTEN_PORT)); }

static void sendHandshakeBurst() {
  for (int i = 0; i < 2; i++) {
    sendHello(); delay(120);
    sendPing();  delay(120);
  }
}

static void sendValue(float v) { udpSendToHub(String("NODE_VALUE id=") + NODE_ID + " v=" + String(v, 3)); }
static void sendBtnToggle()    { udpSendToHub(String("BTN_TOGGLE id=") + NODE_ID + " port=" + String(NODE_LISTEN_PORT)); }

static void sendGateAck() {
  const char* st = (gateOverride == 1) ? "open" : "close";
  udpSendToHub(String("GATE_ACK id=") + NODE_ID + " state=" + st);
}

// ================= Incoming UDP =================
static void handleIncomingUdp() {
  int p = udp.parsePacket();
  if (p <= 0) return;

  IPAddress rip   = udp.remoteIP();
  uint16_t  rport = udp.remotePort();

  char buf[260];
  int n = udp.read(buf, sizeof(buf) - 1);
  if (n <= 0) return;
  buf[n] = 0;

  String msg(buf);
  msg.trim();
  hubIP = rip;

  uint32_t now = millis();
  lastHubSeenMs = now;

  if (msg.startsWith("HUB_READY")) {
    if (now - lastHelloSentMs >= HELLO_THROTTLE_MS) {
      lastHelloSentMs = now;
      sendHello();
      sendPing();
    }
    lastHubCmdMs = now;
    return;
  }

  if (msg.startsWith("GATE")) {
    uint8_t newOv = gateOverride;
    if      (msg.indexOf("auto")  > 0) newOv = 0;
    else if (msg.indexOf("open")  > 0) newOv = 1;
    else if (msg.indexOf("close") > 0) newOv = 2;

    if (newOv != gateOverride) {
      gateOverride = newOv;
      Serial.printf("[CMD] %s:%u  %s -> ov=%u\n",
                    rip.toString().c_str(), rport, msg.c_str(), gateOverride);
      if (gateOverride == 1) gateOpen();
      else gateHome();
      sendGateAck();
    }
    lastHubCmdMs = now;
    return;
  }

  if (msg.startsWith("CFG")) {
    lastHubCmdMs = now;
    Serial.printf("[CFG] %s\n", msg.c_str());
    String s_hbo = cfgGetArg(msg, "hbridge_open_ms");
    String s_hbc = cfgGetArg(msg, "hbridge_close_ms");
    if (s_hbo.length()) {
      hbridge_open_ms = (uint32_t)s_hbo.toInt();
      Serial.printf("[CFG] hbridge_open_ms=%u\n", hbridge_open_ms);
    }
    if (s_hbc.length()) {
      hbridge_close_ms = (uint32_t)s_hbc.toInt();
      Serial.printf("[CFG] hbridge_close_ms=%u\n", hbridge_close_ms);
    }
    return;
  }
}

// ================= Node ID =================
static void buildNodeIdFromEfuseMac() {
  uint64_t mac = ESP.getEfuseMac();
  char id[16];
  snprintf(id, sizeof(id), "BG-%02X%02X%02X",
           (uint8_t)(mac >> 16),
           (uint8_t)(mac >> 8),
           (uint8_t)(mac >> 0));
  NODE_ID = String(id);
}

// ================= WiFi =================
static void ensureWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  Serial.printf("[WIFI] Connecting %s ... (id=%s)\n", WIFI_SSID, NODE_ID.c_str());
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED) {
    esp_task_wdt_reset();  // ne dopusti WDT reset tokom 15s cekanja
    delay(250);
    Serial.print(".");
    if (millis() - t0 > 15000) break;
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("[WIFI] OK IP=%s\n", WiFi.localIP().toString().c_str());
    udp.stop();
    udp.begin(NODE_LISTEN_PORT);
    Serial.printf("[UDP] listen %u\n", NODE_LISTEN_PORT);

    wifiConnectedAtMs = millis();
    lastPingMs = lastValueMs = lastHubCmdMs = lastHubSeenMs = millis();
    lastHelloSentMs = 0;
    lastBcastPingMs = 0;

    sendHandshakeBurst();
    udpSendBroadcast(String("NODE_PING id=") + NODE_ID + " port=" + String(NODE_LISTEN_PORT));
  } else {
    Serial.println("[WIFI] FAIL (retry)");
    WiFi.disconnect(true);
    delay(250);
  }
}

// ================= Button =================
static void handleButton() {
  bool raw = digitalRead(BTN_PIN);
  if (raw != lastBtnRaw) { lastBtnRaw = raw; btnLastChangeMs = millis(); }
  if (millis() - btnLastChangeMs < BTN_DEBOUNCE_MS) return;

  if (raw == LOW && !btnLatched) {
    btnLatched = true;
    Serial.println("[BTN] toggle -> HUB");
    sendBtnToggle();
  }
  if (raw == HIGH) btnLatched = false;
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
  esp_task_wdt_init(&wdt_cfg);
#else
  esp_task_wdt_init(30, true);
#endif
  esp_task_wdt_add(NULL);

  bootMs = millis();

  buildNodeIdFromEfuseMac();
  Serial.printf("[NODE] ID=%s\n", NODE_ID.c_str());

  pinMode(BTN_PIN, INPUT_PULLUP);
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

  forceRecalOffset();
  ensureWiFi();

  Serial.println("[NODE] START OK (ESP32, non-blocking sampler)");
}

// ================= LOOP =================
void loop() {
  esp_task_wdt_reset();

  ensureWiFi();

  if (WiFi.status() == WL_CONNECTED) {
    handleIncomingUdp();
    handleButton();

    uint32_t now = millis();
    if (now - lastBcastPingMs > BCAST_PING_EVERY_MS) {
      lastBcastPingMs = now;
      udpSendBroadcast(String("NODE_PING id=") + NODE_ID + " port=" + String(NODE_LISTEN_PORT));
    }
  }

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

  if (WiFi.status() == WL_CONNECTED) {
    uint32_t now = millis();

    if (now - lastValueMs >= VALUE_EVERY_MS) {
      sendValue(vSend);
      lastValueMs = now;
    }

    uint32_t pingEvery = (now - wifiConnectedAtMs < PING_FAST_WINDOW_MS) ? PING_FAST_MS : PING_SLOW_MS;
    if (now - lastPingMs > pingEvery) {
      sendPing();
      lastPingMs = now;
    }

    if (now - lastHubSeenMs > HUB_FAILSAFE_MS) {
      if (gateOverride != 2) {
        gateOverride = 2;
        Serial.println("[FAILSAFE] no HUB -> CLOSE");
      }
    }
  }

  applyGateFromOverride();
  hbridgeTick();

  // Debug
  static uint32_t lastPrint = 0;
  if (millis() - lastPrint > 900) {
    lastPrint = millis();
    Serial.printf("[DBG] id=%s ready=%d boot=%d blank=%d calib=%d(%u/%u) ema=%.2f send=%.2f off=%d ov=%u\n",
                  NODE_ID.c_str(),
                  (int)sensorReady, (int)inBootHold(), (int)blanking,
                  (int)calibrated, calibOkCount, CALIB_NEED_OK,
                  ema, vSend, offsetADC, gateOverride);
  }

  calibLedUpdate();
  delay(2);
}
