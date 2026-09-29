// blastgate_proto.h — shared HUB <-> NODE ESP-NOW protocol (v1)
//
// Frame layout:  [bg_hdr_t][payload][8-byte HMAC-SHA256 tag]
// The tag covers header + payload and is keyed with the 16-byte network key
// that the hub hands out during pairing. ESP-NOW encryption (PMK/LMK) is NOT
// used: the precompiled IDF caps encrypted peers at 7, we need up to 16 nodes.
// Payloads are not secret (sensor values, gate commands); authenticity is what
// matters, and HMAC gives that for unicast and broadcast alike.
#pragma once
#include <stdint.h>
#include <stddef.h>

#define BG_MAGIC        0xB6A7
#define BG_PROTO_VER    1
#define BG_TAG_LEN      8
#define BG_KEY_LEN      16
#define BG_MAX_FRAME    250   // ESP-NOW v1 payload limit
#define BG_FW_LEN       12

enum bg_msg_type : uint8_t {
  BG_HELLO      = 1,  // node -> broadcast
  BG_HELLO_ACK  = 2,  // hub  -> node
  BG_DATA       = 3,  // node -> hub
  BG_CMD        = 4,  // hub  -> node (needs BG_ACK)
  BG_CONFIG     = 5,  // hub  -> node (needs BG_ACK)
  BG_HEARTBEAT  = 6,  // hub  -> broadcast
  BG_ACK        = 7,  // node -> hub
};

enum bg_cmd_code : uint8_t {
  BG_CMD_OPEN      = 1,
  BG_CMD_CLOSE     = 2,
  BG_CMD_AUTO      = 3,
  BG_CMD_CALIBRATE = 4,
  BG_CMD_REBOOT    = 5,
  BG_CMD_OTA_START = 6,
};

enum bg_actuator : uint8_t { BG_ACT_SERVO = 0, BG_ACT_HBRIDGE = 1, BG_ACT_BOTH = 2 };

enum bg_gate_state : uint8_t {
  BG_GATE_CLOSED  = 0,
  BG_GATE_OPEN    = 1,
  BG_GATE_OPENING = 2,
  BG_GATE_CLOSING = 3,
  BG_GATE_UNKNOWN = 4,   // end switches enabled but neither is active
};

// HELLO flags
#define BG_HELLO_PAIR_REQ   0x01   // node is in pairing mode, wants the key
// HELLO_ACK flags
#define BG_ACK_HAS_KEY      0x01
// DATA error flags
#define BG_ERR_OPEN_TIMEOUT   0x01  // end switch not reached within hbridge_open_ms
#define BG_ERR_CLOSE_TIMEOUT  0x02
#define BG_ERR_ENDSTOP_BOTH   0x04  // both end switches active = wiring fault
#define BG_ERR_NOT_CALIBRATED 0x08
#define BG_ERR_OTA_FAILED     0x10
// HEARTBEAT flags
#define BG_SYS_MANUAL_OVERDRIVE 0x01
#define BG_SYS_RELAY_ON         0x02
#define BG_SYS_PAIRING          0x04

#pragma pack(push, 1)

typedef struct {
  uint16_t magic;
  uint8_t  ver;
  uint8_t  type;
  uint16_t seq;
  uint8_t  mac[6];   // sender MAC, must match ESP-NOW src_addr
} bg_hdr_t;

typedef struct {
  uint32_t hbridge_open_ms;   // motor run time, or timeout when end switches are enabled
  uint32_t hbridge_close_ms;
  uint8_t  endstops;          // 1 = end switches fitted (Rev B)
} bg_config_t;

typedef struct {
  char    fw[BG_FW_LEN];
  uint8_t actuator;           // bg_actuator
  uint8_t flags;              // BG_HELLO_*
  uint8_t channel;            // channel the HELLO was sent on
} bg_hello_t;

typedef struct {
  uint8_t     channel;
  uint8_t     flags;          // BG_ACK_HAS_KEY
  bg_config_t cfg;
  uint8_t     key[BG_KEY_LEN];  // only valid when BG_ACK_HAS_KEY
} bg_hello_ack_t;

typedef struct {
  float    value;             // filtered sensor value (0 during boot hold / calibration)
  uint8_t  gate;              // bg_gate_state
  uint8_t  err;               // BG_ERR_*
  uint8_t  btn_count;         // increments on every short button press
  uint8_t  endstops;          // bit0 = END_OPEN active, bit1 = END_CLOSE active
  uint32_t uptime_s;
  int8_t   rssi;              // RSSI of last frame received from hub
} bg_data_t;

typedef struct {
  uint8_t  cmd;               // bg_cmd_code
  uint32_t fw_size;           // OTA_START only
  uint8_t  sha256[32];        // OTA_START only
  char     url[96];           // OTA_START only, NUL terminated
} bg_cmd_t;

typedef struct {
  uint8_t channel;
  uint8_t sys;                // BG_SYS_*
  uint32_t uptime_s;
} bg_heartbeat_t;

typedef struct {
  uint16_t acked_seq;
  uint8_t  acked_type;
  uint8_t  status;            // 0 = OK
} bg_ack_t;

#pragma pack(pop)

static_assert(sizeof(bg_hdr_t) + sizeof(bg_hello_ack_t) + BG_TAG_LEN <= BG_MAX_FRAME, "HELLO_ACK too big");
static_assert(sizeof(bg_hdr_t) + sizeof(bg_cmd_t)       + BG_TAG_LEN <= BG_MAX_FRAME, "CMD too big");
static_assert(sizeof(bg_hdr_t) + sizeof(bg_data_t)      + BG_TAG_LEN <= BG_MAX_FRAME, "DATA too big");

// Build a frame into out[] (header + payload + tag). Returns total length.
size_t bg_build(uint8_t* out, uint8_t type, uint16_t seq, const uint8_t mac[6],
                const void* payload, size_t payload_len, const uint8_t key[BG_KEY_LEN]);

// Validate magic/version/length and tag. Returns payload length, or -1 if invalid.
// Unknown proto versions return -2 so the caller can log them.
int bg_check(const uint8_t* frame, int len, const uint8_t key[BG_KEY_LEN]);

// Payload pointer inside a validated frame.
static inline const uint8_t* bg_payload(const uint8_t* frame) { return frame + sizeof(bg_hdr_t); }

// Header of a frame (no validation beyond length).
static inline const bg_hdr_t* bg_header(const uint8_t* frame) { return (const bg_hdr_t*)frame; }

// Constant-time tag compare + HMAC helper (also used for unsigned pairing HELLO).
void bg_tag(const uint8_t* data, size_t len, const uint8_t key[BG_KEY_LEN], uint8_t tag[BG_TAG_LEN]);
