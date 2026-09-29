#include "blastgate_proto.h"
#include <string.h>
#include <mbedtls/md.h>

void bg_tag(const uint8_t* data, size_t len, const uint8_t key[BG_KEY_LEN], uint8_t tag[BG_TAG_LEN]) {
  uint8_t full[32];
  mbedtls_md_hmac(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), key, BG_KEY_LEN, data, len, full);
  memcpy(tag, full, BG_TAG_LEN);
}

size_t bg_build(uint8_t* out, uint8_t type, uint16_t seq, const uint8_t mac[6],
                const void* payload, size_t payload_len, const uint8_t key[BG_KEY_LEN]) {
  bg_hdr_t h;
  h.magic = BG_MAGIC;
  h.ver   = BG_PROTO_VER;
  h.type  = type;
  h.seq   = seq;
  memcpy(h.mac, mac, 6);
  memcpy(out, &h, sizeof(h));
  if (payload_len) memcpy(out + sizeof(h), payload, payload_len);
  size_t n = sizeof(h) + payload_len;
  bg_tag(out, n, key, out + n);
  return n + BG_TAG_LEN;
}

int bg_check(const uint8_t* frame, int len, const uint8_t key[BG_KEY_LEN]) {
  if (len < (int)(sizeof(bg_hdr_t) + BG_TAG_LEN)) return -1;
  const bg_hdr_t* h = (const bg_hdr_t*)frame;
  if (h->magic != BG_MAGIC) return -1;
  if (h->ver != BG_PROTO_VER) return -2;
  size_t n = len - BG_TAG_LEN;
  uint8_t tag[BG_TAG_LEN];
  bg_tag(frame, n, key, tag);
  uint8_t diff = 0;
  for (int i = 0; i < BG_TAG_LEN; i++) diff |= tag[i] ^ frame[n + i];
  if (diff) return -1;
  return (int)(n - sizeof(bg_hdr_t));
}
