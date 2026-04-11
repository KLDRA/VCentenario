# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Traffic monitoring system for the Puente del Centenario (Seville, **SE-30 km 10–12**, sentido Huelva/Cádiz). Ingests public DGT (Spanish Traffic Authority) DATEX2 feeds and TomTom Routing API to estimate reversible lane state with a confidence score and per-direction traffic metrics.

## Commands

```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
pip install -e .[dev]      # adds pytest
pip install -e .[vision]   # adds ultralytics, opencv, numpy

# Run
PYTHONPATH=src python3 -m vcentenario.cli init-db
PYTHONPATH=src python3 -m vcentenario.cli run-once --json
PYTHONPATH=src python3 -m vcentenario.cli latest-state
PYTHONPATH=src python3 -m vcentenario.cli cleanup --vacuum
PYTHONPATH=src python3 -m vcentenario.cli serve --host 0.0.0.0 --port 8080

# Test
pytest
pytest tests/test_inference.py   # single test file

# Deploy (production)
sudo APP_HOST=127.0.0.1 APP_PORT=5000 PUBLIC_PORT=8088 ./deploy.sh
```

## Architecture

**Data flow:** Collectors → Service → Inference → Storage → Web UI/API

### Core Modules (`src/vcentenario/`)

| Module | Role |
|--------|------|
| `cli.py` | CLI entry point, delegates to `service.py` |
| `service.py` | Main orchestrator: runs all collectors, stores results, triggers inference |
| `inference.py` | Scoring engine: weighted signals → `traffic_score`, `reversible_probable`, `confidence` |
| `storage.py` | SQLite abstraction for all persistence |
| `webapp.py` | HTTP server: JSON API + HTML dashboard (Nothing Design) |
| `config.py` | Centralized config reading env vars; hardcoded geo bounds and preferred asset IDs |
| `http.py` | HTTP client with retry/backoff |
| `alerts.py` | Email alerts on high score or severe incidents |
| `learning.py` | EMA-based temporal forecasting and hourly profiling |
| `models.py` | Dataclasses: `PanelMessage`, `Incident`, `Camera`, `DetectorReading`, `BridgeState`, etc. |

### Collectors (`src/vcentenario/collectors/`)

- `panels.py` — VMS panel messages (DGT DATEX2 v1.0 XML)
- `incidents.py` — Road incidents (DGT DATEX2 v3.6 + optional TomTom)
- `cameras.py` — Camera snapshots with hash-based change detection; optional YOLO vehicle counting
- `detectors.py` — TomTom Routing API per-direction speed/delay. DGT detector feed exists in code but is NOT used in production (see Known Issues).

### Inference Pipeline

1. **Score computation:** Weighted contributions from panel keywords/pictograms, incident severity, camera visual change, TomTom route speed/delay.
   - Formula: `score = avg_per_sensor * sqrt(active_count)` — normalizado para que no dependa del número de sensores activos.
   - Speed threshold: **60 km/h** (límite real del tramo SE-30 km 10–12).
2. **Reversible prediction:** Combines direction pressure + temporal scheduling (configurable via `VCENTENARIO_REVERSIBLE_SCHEDULE`) + persistence window to avoid flip-flop.
3. **Traffic level classification:** `fluido` / `denso` / `retenciones` / `congestion_fuerte`.
4. **Historical calibration:** EMA baseline adjustment from recent states in `learning.py`.

### Key Environment Variables

| Variable | Purpose |
|----------|---------|
| `VCENTENARIO_DB_PATH` | SQLite DB location |
| `VCENTENARIO_TOMTOM_API_KEY` | TomTom Traffic API (requerida para datos de velocidad) |
| `VCENTENARIO_REVERSIBLE_SCHEDULE` | Cron-like schedule overriding inference for known reversal times |
| `VCENTENARIO_REVERSIBLE_PERSISTENCE_WINDOW` | Seconds to hold a reversible prediction before flipping |
| `VCENTENARIO_ENABLE_VISION` | Enable YOLO-based vehicle counting in cameras |
| `VCENTENARIO_YOLO_MODEL_PATH` | Path to `.pt` model file |
| `VCENTENARIO_ALERT_EMAIL_ENABLED` | Enable email alerts + SMTP config |

### Persistence

- SQLite tables: `panel_locations`, `panel_messages`, `incidents`, `cameras`, `detector_locations`, `detector_readings`, `camera_snapshots`, `collection_runs`, `bridge_states`
- Camera snapshots saved as files under `var/snapshots/`
- Cleanup via `cli cleanup` (configurable retention counts per table)

### Production Deployment

`deploy.sh` creates a systemd service (`vcentenario.service`) + timer (`vcentenario.timer`, default every 5 min) and configures Nginx as a reverse proxy. The timer runs `run-once`; `serve` runs as the persistent service.

---

## Fuentes de datos — estado y decisiones

### TomTom Routing API ✅ (fuente principal de velocidad)

Dos rutas calculadas cada 5 minutos via `TomTomFlowCollector.fetch_route_speed()`:

| detector_id | Ruta | Dirección |
|---|---|---|
| `tomtom_route_huelva` | km10 (37.343820,−5.986923) → km12 (37.357216,−6.002909) | `positive` |
| `tomtom_route_cadiz` | km12 (37.357216,−6.002909) → km10 (37.343820,−5.986923) | `negative` |

**Campos del modelo `DetectorReading` para estas rutas:**
- `average_speed` — velocidad media con tráfico (km/h)
- `free_flow_speed` — velocidad sin tráfico (km/h)
- `vehicle_flow` — **REUTILIZADO**: almacena `trafficDelayInSeconds` (segundos de retardo), NO vehículos/hora
- `latitude`, `longitude` — `None` (son rutas, no puntos)

**Fiabilidad:** Buena para detectar congestión general. Limitaciones: tramo corto (2 km), sin resolución por carril, se actualiza cada 5 min desde nuestra parte.

### TomTom Flow API ❌ (descartada)

La Flow API (`flowSegmentData`) devuelve el mismo valor para ambos sentidos en este puente, independientemente del parámetro `heading`. No sirve para diferenciación direccional.

### Detectores DGT ❌ (descartados)

Los 7 detectores DGT en km 10–12 de la SE-30 tienen el campo `measurementTimeDefault` congelado en `2025-06-30T10:20:00+02:00` desde al menos junio 2025. Los valores de flujo (vehicle_flow ~1500 veh/h) y velocidad que publican no se actualizan en tiempo real. **No usar como fuente de inferencia.**

El código de colección DGT existe en `collectors/detectors.py` pero `service.py` no lo llama. El `source_status["detector_readings"]` queda siempre en `skipped`.

### Paneles VMS DGT ✅

Fuente fiable. Los paneles del tramo (IDs: 60514, 60833, 60516) publican mensajes en tiempo real vía DATEX2 v1.0. Son la señal más directa de cortes o reversibilidad activa.

**Mensaje a ignorar en inferencia:** `"VEHICULO 20T/HUELVA-MERID/POR A4 CADIZ"` — es un mensaje estático de obras, siempre activo, no indica estado del tráfico.

### Incidencias DGT ✅

Feed DATEX2 v3.6. Fiable para cortes y accidentes. Se complementa opcionalmente con incidencias TomTom si hay API key configurada.

### Cámaras DGT ⚠️

No hay cámaras conocidas en el tramo km 10–12 sentido Huelva (`preferred_camera_ids = ()`). Si aparece alguna cámara en el área bbox, se procesa con hash-based change detection y opcionalmente YOLO.

---

## Known Issues / Decisiones de diseño

- **`vehicle_flow` reutilizado:** En lecturas TomTom Routing, este campo contiene segundos de retardo (`trafficDelayInSeconds`), no vehículos/hora. Toda la UI lo trata como retardo para detectores `tomtom_route_*`. Los detectores DGT (si algún día se rehabilitan) usarían el campo correctamente como flujo.

- **Score histórico contaminado:** Si se cambia la lógica de puntuación, el historial EMA tarda varias horas en recalibrarse porque arrastra valores del modelo anterior. Es normal y esperado.

- **Tramo corto:** 2 km de tramo hace que la velocidad media sea sensible a eventos puntuales (un vehículo lento puede mover ±5 km/h la media).
