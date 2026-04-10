# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Traffic monitoring system for the Puente del Centenario (Seville, SE-30 km 12–16). Ingests public DGT (Spanish Traffic Authority) DATEX2 feeds and TomTom APIs to estimate reversible lane state with a confidence score.

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
- `detectors.py` — Traffic detector flow/speed/occupancy (DGT DATEX2 + optional TomTom flow)

### Inference Pipeline

1. **Score computation:** Weighted contributions from panel keywords/pictograms, incident severity, camera visual change, detector speed/occupancy.
2. **Reversible prediction:** Combines direction pressure + temporal scheduling (configurable via `VCENTENARIO_REVERSIBLE_SCHEDULE`) + persistence window to avoid flip-flop.
3. **Traffic level classification:** `fluido` / `denso` / `retenciones` / `congestion_fuerte`.
4. **Historical calibration:** EMA baseline adjustment from recent states in `learning.py`.

### Key Environment Variables

| Variable | Purpose |
|----------|---------|
| `VCENTENARIO_DB_PATH` | SQLite DB location |
| `VCENTENARIO_TOMTOM_API_KEY` | TomTom Traffic API (optional but improves coverage) |
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
