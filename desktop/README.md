# Blastgate ESP32 Hub Controller

**Version:** 2.0.0 (Modular Architecture)
**Status:** ✅ Refactored (75% complete)

GUI aplikacija za kontrolu Blastgate sistema prikupljanja prašine preko UDP komunikacije sa ESP32 hub-ovima.

## 🏗️ Architecture (v2.0)

**Modular refactored codebase** with:
- ✅ **Pydantic models** - Config validation, type safety
- ✅ **Clean network layer** - Proper error handling, comprehensive logging
- ✅ **Business logic separation** - AutoController for AUTO mode
- ✅ **Type-safe utilities** - Helpers and validators
- ✅ **Unit tests** - 26/26 passing (100%)
- ✅ **Professional documentation** - 35+ pages architecture docs

### Module Structure

```
blastgate/
├── models/           Pydantic data models (config, status, nodes)
├── network/          UDP communication (client, engine, protocol, discovery)
├── controllers/      Business logic (AutoController)
├── gui/              UI components (utils, RoundedTile)
├── utils/            Generic helpers (type conversion, validation)
└── Infrastructure    Logging, exceptions, constants
```

**See [docs/architecture.md](docs/architecture.md) for full documentation.**

## Instalacija

### Zahtevi
- Python 3.9 ili noviji
- pip package manager

### Instalacija sa pip

```bash
cd blastgate
pip install -r requirements.txt
```

Ili instalirati u development modu:

```bash
pip install -e .
```

Za development sa dodatnim alatima:

```bash
pip install -e ".[dev]"
```

## Pokretanje

```bash
python -m blastgate
```

## Konfiguracija

Konfiguracija se čuva u `blastgate_gui_config.json` fajlu u direktorijumu aplikacije.

### Primer konfiguracije:

```json
{
  "hub_lan_ip": "192.168.1.116",
  "hub_ap_ip": "192.168.4.1",
  "udp_port": 8888,
  "poll_ms": 650,
  "timeout_s": 1.2,
  "discovery_timeout_s": 2.0,
  "theme": "darkly",
  "preferred_hub_ip": "",
  "auto_ap_detect": true,
  "ui_scale": 1.30,
  "nodes": {}
}
```

## Funkcionalnosti

- **AUTO mod**: Automatsko upravljanje gate-ovima na osnovu senzorskih vrednosti
- **MANUAL mod**: Ručno upravljanje svim gate-ovima i relay-em
- **Hub Discovery**: Automatsko pronalaženje hub-ova na mreži
- **Wi-Fi konfiguracija**: Upravljanje Wi-Fi konekcijom ESP32 hub-a
- **Per-node konfiguracija**: Podešavanje threshold-a, hysteresis-a, hold timera

## Modovi Rada

### MODE 1: APP AUTO
Aplikacija automatski kontroliše gate-ove na osnovu senzorskih vrednosti sa threshold i hysteresis logikom.

### MODE 2: APP MANUAL
Manuelna kontrola svih gate-ova i relay-a direktno iz aplikacije.

### MODE 3: HUB MANUAL (LOCKED)
Hub je u manual override modu - aplikacija je zaključana.

## Arhitektura

```
blastgate/
├── blastgate/              # Main package
│   ├── models/            # Pydantic models za validaciju
│   ├── network/           # UDP komunikacija
│   ├── gui/               # GUI komponente
│   ├── controllers/       # Business logika
│   └── utils/             # Helper funkcije
└── tests/                 # Unit testovi
```

## Development

### Pokretanje testova

```bash
pytest
```

Sa coverage:

```bash
pytest --cov=blastgate --cov-report=html
```

### Type checking

```bash
mypy blastgate/
```

### Code formatting

```bash
black blastgate/ tests/
```

### Linting

```bash
ruff check blastgate/ tests/
```

## Logovanje

Log fajlovi se čuvaju u `logs/blastgate.log` sa automatskom rotacijom (5MB max, 3 backup fajla).

Log level se može promeniti u `blastgate/__main__.py`:

```python
logger = setup_logging("DEBUG", LOG_PATH, console=True)
```

## Licenca

Proprietary - Blastgate Team

## Autor

Blastgate Team

## Verzija

2.0.0 - Refaktorisan monolitni kod u modularnu strukturu sa proper error handling-om i logging-om.
