# Test plan — Blastgate v1.5.0 (ESP-NOW)

Oprema: 1 hub (WT32-ETH01), 2 noda (A i B), ruter sa podesivim kanalom, ETH kabl, telefon/laptop.
Serijski monitor otvoren na hubu i na bar jednom nodu kroz ceo test (115200).

Build (već prošao 28.09.2026, bez warninga):

| env | Flash | napomena |
|---|---|---|
| `hub-wt32` → `wt32_s1_eth01` | 99,7 % (ostaje 5.188 B) | ESP-NOW + prelazni UDP — **ovaj se flešuje** |
| `hub-wt32` → `wt32_espnow_only` | 99,5 % | kad svi nodovi pređu |
| `node-esp32` → `esp32doit-devkit-v1` | 85,0 % | |

Flash: svaki put zaseban CMD prozor, port se proverava neposredno pre flash-a, potvrda pre svakog flash-a.

---

## 0. Pre svega — ID noda (5 min)

Posle flash-a noda serijski ispiše:
```
[NODE] ID=BG-xxxxxx MAC=AA:BB:CC:DD:EE:FF fw=1.5.0 paired=0 ch=1
```
- [ ] ID mora biti **poslednja tri** bajta MAC-a (`DD EE FF`).
- [ ] Zapiši stari ID tog noda (iz aplikacije) i novi. Stari firmware je uzimao bajtove `mac>>16, >>8, >>0`
      od `getEfuseMac()` — sumnja je da je to bio **OUI** (prva tri bajta, obrnuto), isti za sve nodove iz
      iste serije. Ako se stari ID poklapa sa `CC BB AA` → sumnja potvrđena.
- Posledica: nod se u hubu javlja pod novim ID-em → ime, prag i hold treba ponovo uneti u aplikaciji
  (hub NVS i `desktop/blastgate_gui_config.json` su vezani za stari ID).

## 1. Hub se podiže

- [ ] Log: `[ESPNOW] up: mac=... channel=N tx_power=80`
- [ ] `[PAIR] generated new network key` (samo prvi put) i `[PAIR] 0 paired node(s)`
- [ ] `http://<hub>/status` → `"espnow":1`, `"channel":N`, `"pairedCount":0`
- [ ] `http://<hub>/nodes` se otvara (tabela prazna)
- [ ] Telefon se kači na `BLASTGATE_HUB` kao i ranije (uključen LR protokol ne sme da smeta)

## 2. Uparivanje

Nod posle flash-a nema ključ: LED sporo trepće (1 Hz), radio ćuti, zatvarač zatvoren.

- [ ] Hub: MANUAL drži **3 s** → status LED brzo trepće (80 ms), log `[PAIR] pairing window open (60s)`.
      (Kratak pritisak MANUAL-a sad radi **na otpuštanje**, ne na pritisak.)
- [ ] Nod A: taster drži **3 s** → LED jako brzo (60 ms), log `[PAIR] pairing mode 60s`
- [ ] Očekivano: hub `[PAIR] added ...` + `[ESPNOW] HELLO BG-... (pairing)`,
      nod `[PAIR] paired — network key stored` pa `[LINK] up on channel N`
- [ ] Isto za nod B. `/status` → `"pairedCount":2`, oba noda `"transport":"espnow"`, `"paired":1`
- [ ] Restart noda (reset taster) → ponovo `[LINK] up` **bez** uparivanja (ključ u NVS)
- [ ] `/nodes` → "Ukloni" za B → hub loguje `ignored unpaired node` za B; ponovo upariti B

## 3. Osnovni rad (isto kao pre)

- [ ] Mašina radi → vrednost raste → zatvarač se otvara, relej ON. Mašina stane → zatvaranje posle `gate_hold_ms`
- [ ] Vreme reakcije: od paljenja mašine do otvaranja (očekivano < 1 s; DATA ide i odmah na promenu ≥ 5)
- [ ] Iz aplikacije: `open` / `close` / `auto` za nod → pomera se; u `/status` `"txFails":0`
- [ ] MANUAL kratko → overdrive ON, svi zatvoreni. Taster noda kratko → taj nod se otvori/zatvori
- [ ] Obe aplikacije (desktop + mobile) prikazuju nodove normalno (nova polja u `/status` ignorišu)

## 4. Promena kanala rutera (NAJVAŽNIJE)

Hub na WiFi-ju (ETH izvučen).
- [ ] Promeni kanal na ruteru (npr. 1 → 11). Hub: STA se ponovo poveže, kanal se menja
- [ ] Nod: `[LINK] scan start (heartbeat lost)` → `[LINK] up on channel 11 (heartbeat)` ili `(... HELLO_ACK)`
- [ ] **Izmeri** vreme od promene do `[LINK] up` — mora < 12 s, inače failsafe zatvori zatvarač
- [ ] Posle toga `/status` → `"channel":11`, nodovi online

## 5. Restart huba

- [ ] Isključi/uključi hub dok je zatvarač otvoren (mašina radi)
- [ ] Nodovi: ako hub ćuti > 12 s → `[FAILSAFE] no HUB -> CLOSE` (očekivano). Zapiši koliko se hub diže
- [ ] Posle podizanja: nodovi se vraćaju **bez** uparivanja, `/status` ih pokazuje, logika radi

## 6. Nod van dometa

- [ ] Odnesi nod B (ili ga zakloni metalom) dok je otvoren
- [ ] Hub: B `"online":0` posle ~3,5 s. Nod B: failsafe CLOSE posle 12 s
- [ ] Vrati B → sam se vrati (`scan` → `up`), bez uparivanja
- [ ] Zapiši `"rssi"` (hub strana) i `"nodeRssi"` (nod strana) na radnom mestu i na granici dometa

## 7. ETH kabl

- [ ] Uključi ETH → hub `[NET] STA off (ETH uplink) — ESP-NOW on fixed channel 1`
- [ ] Nodovi prelaze na kanal 1 (scan → up), < 12 s
- [ ] `/nodes` → Fiksni kanal = 6 → Sačuvaj → nodovi prelaze na 6
- [ ] Izvuci ETH → posle ~3 s `[NET] STA on (ETH lost) — channel follows the router`, nodovi prate ruter
- [ ] Telefon i dalje vidi `BLASTGATE_HUB` posle svakog prelaza (AP se restartuje pri promeni kanala — kratko ispadanje je očekivano)

## 8. OTA noda (hibridni)

- [ ] `/nodes` → OTA token → izaberi `node-esp32/.pio/build/esp32doit-devkit-v1/firmware.bin` → "Pošalji na hub"
      → odgovor `{"ok":true,"size":...,"sha256":"..."}`
- [ ] "OTA" kod noda A → nod: `[OTA] start` → kači se na `BLASTGATE_HUB` → `[OTA] OK -> restart` → vraća se na ESP-NOW
- [ ] Hub log `[NODE_FW] served N/N bytes`. Nod B za to vreme **ne sme** da ode u failsafe (hub šalje HEARTBEAT i dok servira fajl)
- [ ] Negativno: pokreni OTA pa isključi hub → nod posle 120 s `[OTA] abort: timeout 120s` i vraća se na scan, **bez** flešovanja
- [ ] Napomena: posle ovoga hub OTA preko aplikacije briše uskladišteni fajl noda (isti slot) — očekivano

## 9. Krajnji prekidači (samo Rev B hardver)

- [ ] `/nodes` → štikliraj "Prekidači" za nod
- [ ] Otvori → motor staje na END_OPEN (`[HBRIDGE] stop on end switch (open)`), `"gateState":1`
- [ ] Zatvori → staje na END_CLOSE, `"gateState":0`
- [ ] Odspoji END_OPEN i otvori → posle `hbridge_open_ms` stop + `"err":1` (open timeout)
- [ ] Oba prekidača kratko na masu → `"err"` sadrži 4 (0x04 = oba aktivna)
- [ ] Bez štikle → radi po vremenu, kao ranije

## 10. Prelazni UDP

- [ ] Jedan stari nod (v1.4.x) i dalje radi uz nove; u `/status` `"transport":"udp"`

## 11. BLE provisioning

- [ ] `/wifi_prov` → hub se restartuje, log `[ESPNOW] skipped (BLE-only provisioning boot)`.
      Nodovi posle 12 s zatvaraju (failsafe) — **očekivano**
- [ ] Posle uparivanja preko telefona → normalan boot → `[ESPNOW] up`, nodovi se vraćaju
- [ ] Hub **bez** sačuvanog WiFi-ja (auto-BLE iz 1.4.4): BLE i ESP-NOW rade **istovremeno** — proveri da
      nodovi rade i da telefon vidi `PROV_BG_...`. Ovo nije testirano ni u 1.4.4.

---

## Poznati rizici (proveriti usput)

1. **Hub je na 99,7 % flash-a.** Sledeća iole veća izmena ne staje. Izlaz je nova tabela particija
   (bez neiskorišćenog SPIFFS-a) — to traži USB flash, ne ide preko OTA.
2. **STA koji ne može da se poveže skače po kanalima.** Ako ruter nestane (hub u `AP_ONLY`), Arduino
   auto-reconnect i dalje skenira → ESP-NOW trpi. Proveriti: isključi ruter, gledaj da li nodovi gube vezu.
3. **Watchdog huba je verovatno 5 s, ne 30 s** (core 3.x ga sam startuje na 5 s, pa `esp_task_wdt_init` ne prođe).
   Nije provereno na ploči. Ako hub pukne sa `task_wdt` u logu — to je razlog.
4. Ključ ide nešifrovan u HELLO_ACK tokom 60 s prozora za uparivanje.
5. `/pair_start`, `/unpair`, `/node_endstops`, `/espnow_channel` ne traže token (samo `/node_fw` i `/node_ota`).
6. Nodovi šalju unicast na **AP MAC** huba (hub šalje sa AP interfejsa). Ako DATA ne stiže a HEARTBEAT stiže — ovo je prvo mesto za gledanje.
