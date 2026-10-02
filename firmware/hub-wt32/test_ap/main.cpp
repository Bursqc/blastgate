// Bare AP test: nothing but an open WiFi access point "BLASTGATE_TEST".
// No GPIO, no LED, no buttons, no ETH, no BLE, no ESP-NOW.
#include <Arduino.h>
#include <WiFi.h>

void setup() {
  Serial.begin(115200);
  bool ok = WiFi.softAP("BLASTGATE_TEST");
  Serial.printf("\n[TEST_AP] softAP %s  mac=%s  ch=%d\n", ok ? "OK" : "FAIL",
                WiFi.softAPmacAddress().c_str(), WiFi.channel());
}

void loop() {
  delay(2000);
  Serial.printf("[TEST_AP] stations=%d\n", WiFi.softAPgetStationNum());
}
