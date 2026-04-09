from __future__ import annotations

import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import time
from typing import Optional
from urllib.parse import urlparse

from .config import (
    DEFAULT_DB_PATH,
    DEFAULT_SNAPSHOTS_DIR,
    ENABLE_REFRESH_ENDPOINT,
    REFRESH_MIN_INTERVAL_SECONDS,
    REFRESH_TOKEN,
)
from .service import VCentenarioService
from .utils import dumps_json


def get_simple_dashboard():
    """Devuelve un dashboard HTML simple con un Canvas chart."""
    return """<!doctype html>
<html lang="es">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>VCentenario · Traffic Monitor</title>
    <link rel="stylesheet" href="/static/maplibre-gl.css">
  <script src="/static/maplibre-gl.js" onload="window._mlLoaded=true" onerror="window._mlError='load failed'"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: "Space Grotesk", system-ui, sans-serif;
            background: #000000;
            color: #E8E8E8;
            min-height: 100vh;
            padding: 32px 20px;
        }
        .shell { max-width: 960px; margin: 0 auto; }
        .nd-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            padding-bottom: 24px;
            border-bottom: 1px solid #222222;
            margin-bottom: 32px;
        }
        .nd-eyebrow {
            font-family: "Space Mono", monospace;
            font-size: 11px;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: #999999;
        }
        .nd-title {
            font-size: 18px;
            font-weight: 500;
            color: #FFFFFF;
            margin-top: 6px;
        }
        .nd-status { text-align: right; }
        .nd-status-dot {
            display: inline-block;
            width: 6px; height: 6px;
            border-radius: 50%;
            background: #4A9E5C;
            margin-right: 6px;
            vertical-align: middle;
        }
        canvas {
            display: block;
            width: 100%;
            border: 1px solid #222222;
            background: #000000;
        }
        .nd-stats-row {
            display: flex;
            justify-content: space-between;
            margin-top: 16px;
            padding-top: 16px;
            border-top: 1px solid #222222;
        }
        .nd-debug {
            margin-top: 24px;
            border: 1px solid #222222;
            background: #111111;
        }
        .nd-debug-header {
            padding: 8px 12px;
            border-bottom: 1px solid #222222;
            font-family: "Space Mono", monospace;
            font-size: 10px;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: #666666;
        }
        #debug {
            padding: 12px;
            font-family: "Space Mono", monospace;
            font-size: 11px;
            color: #666666;
            max-height: 200px;
            overflow-y: auto;
            white-space: pre-wrap;
            line-height: 1.6;
        }
        .nd-footer {
            margin-top: 32px;
            padding-top: 16px;
            border-top: 1px solid #222222;
            display: flex;
            justify-content: space-between;
        }
    </style>
</head>
<body>
    <div class="shell">
        <header class="nd-header">
            <div>
                <div class="nd-eyebrow">Monitor Operativo · Puente del Centenario</div>
                <div class="nd-title">VCentenario</div>
            </div>
            <div class="nd-status">
                <div class="nd-eyebrow"><span class="nd-status-dot"></span>Activo</div>
                <div class="nd-eyebrow" style="margin-top:6px;">Actualización: <span id="lastUpdate">--:--</span></div>
            </div>
        </header>

        <div>
            <div class="nd-eyebrow" style="margin-bottom:12px;">Traffic Score · Últimas 16 lecturas</div>
            <canvas id="chart" width="900" height="320"></canvas>
            <div class="nd-stats-row">
                <span class="nd-eyebrow">Auto-refresh cada 30 s</span>
                <span class="nd-eyebrow" id="statsInfo">Cargando...</span>
            </div>
        </div>

        <div class="nd-debug">
            <div class="nd-debug-header">System log</div>
            <pre id="debug">Inicializando...</pre>
        </div>

        <footer class="nd-footer">
            <span class="nd-eyebrow">Puente del Centenario · Sevilla</span>
            <span class="nd-eyebrow">vcentenario</span>
        </footer>
    </div>

    <script>
        let debugLog = [];
        function log(msg) {
            debugLog.push(msg);
            console.log(msg);
            const debug = document.getElementById('debug');
            if (debug) debug.textContent = debugLog.slice(-10).join('\\n');
        }

        function updateLastUpdate() {
            const now = new Date();
            const h = String(now.getHours()).padStart(2, '0');
            const m = String(now.getMinutes()).padStart(2, '0');
            document.getElementById('lastUpdate').textContent = h + ':' + m;
        }

        async function loadChart() {
            try {
                log('Fetching /api/dashboard...');
                const res = await fetch('/api/dashboard');
                if (!res.ok) { log('Error: HTTP ' + res.status); return; }
                const data = await res.json();
                log('Response received');
                const states = data.recent_states || [];
                log('States: ' + states.length);
                if (states.length > 0) {
                    const lastScore = states[states.length - 1].traffic_score;
                    const avg = (states.reduce((a, s) => a + parseFloat(s.traffic_score || 0), 0) / states.length).toFixed(1);
                    document.getElementById('statsInfo').textContent =
                        'Actual: ' + parseFloat(lastScore).toFixed(1) + ' · Promedio: ' + avg;
                }
                drawChart(states);
                updateLastUpdate();
            } catch (e) { log('Error: ' + e.message); }
        }

        function drawChart(states) {
            const canvas = document.getElementById('chart');
            if (!canvas) { log('Canvas not found'); return; }
            const ctx = canvas.getContext('2d');
            if (!ctx) { log('Canvas context unavailable'); return; }

            const W = canvas.width, H = canvas.height;
            ctx.fillStyle = '#000000';
            ctx.fillRect(0, 0, W, H);

            if (!states || states.length === 0) {
                ctx.fillStyle = '#333333';
                ctx.font = '700 13px "Space Mono"';
                ctx.fillText('[SIN DATOS]', 20, 40);
                return;
            }

            const scores = states.map(s => { const v = parseFloat(s.traffic_score); return isNaN(v) ? 0 : v; });
            const maxScore = Math.max(...scores, 50);
            const minScore = Math.min(...scores, 0);
            const range = maxScore - minScore || 1;
            const pad = { top: 40, right: 32, bottom: 40, left: 56 };
            const w = W - pad.left - pad.right;
            const h = H - pad.top - pad.bottom;

            // Grid lines
            ctx.strokeStyle = '#1A1A1A';
            ctx.lineWidth = 1;
            for (let i = 0; i <= 4; i++) {
                const y = pad.top + (h / 4) * i;
                ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(W - pad.right, y); ctx.stroke();
                ctx.fillStyle = '#666666';
                ctx.font = '400 10px "Space Mono"';
                ctx.textAlign = 'right';
                ctx.fillText((maxScore - (range / 4) * i).toFixed(0), pad.left - 8, y + 4);
            }

            // Line - square caps (percussive, mechanical)
            ctx.strokeStyle = '#FFFFFF';
            ctx.lineWidth = 1.5;
            ctx.lineJoin = 'miter';
            ctx.lineCap = 'square';
            ctx.beginPath();
            scores.forEach((score, i) => {
                const x = pad.left + (i / Math.max(scores.length - 1, 1)) * w;
                const y = pad.top + h - ((score - minScore) / range) * h;
                if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
            });
            ctx.stroke();

            // Points - square, mechanical
            scores.forEach((score, i) => {
                const x = pad.left + (i / Math.max(scores.length - 1, 1)) * w;
                const y = pad.top + h - ((score - minScore) / range) * h;
                ctx.fillStyle = '#FFFFFF';
                ctx.fillRect(x - 3, y - 3, 6, 6);
                ctx.fillStyle = '#000000';
                ctx.fillRect(x - 1, y - 1, 2, 2);
            });

            // X labels
            ctx.fillStyle = '#666666';
            ctx.font = '400 9px "Space Mono"';
            ctx.textAlign = 'center';
            const step = Math.ceil(scores.length / 6);
            for (let i = 0; i < scores.length; i += step) {
                const x = pad.left + (i / Math.max(scores.length - 1, 1)) * w;
                ctx.fillText('#' + (i + 1), x, H - pad.bottom + 16);
            }
            log('Chart rendered · ' + scores.length + ' pts');
        }

        log('Page loaded');
        loadChart();
        setInterval(loadChart, 30000);
    </script>
</body>
</html>"""


HTML_PAGE = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>VCentenario Monitor</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Doto:ROND@0&family=Space+Grotesk:wght@300;400;500&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --black: #000000;
      --surface: #111111;
      --surface-raised: #1A1A1A;
      --border: #222222;
      --border-visible: #333333;
      --text-disabled: #666666;
      --text-secondary: #999999;
      --text-primary: #E8E8E8;
      --text-display: #FFFFFF;
      --accent: #D71921;
      --accent-subtle: rgba(215,25,33,0.15);
      --success: #4A9E5C;
      --warning: #D4A843;
      --space-xs: 4px;
      --space-sm: 8px;
      --space-md: 16px;
      --space-lg: 24px;
      --space-xl: 32px;
      --space-2xl: 48px;
      --space-3xl: 64px;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: "Space Grotesk", system-ui, sans-serif;
      background: var(--black);
      color: var(--text-primary);
      min-height: 100vh;
    }
    .nd-shell {
      max-width: 1280px;
      margin: 0 auto;
      padding: var(--space-xl) var(--space-md) var(--space-2xl);
    }

    /* ---- Typography helpers ---- */
    .nd-eyebrow {
      font-family: "Space Mono", monospace;
      font-size: 11px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--text-secondary);
    }
    .nd-label {
      font-family: "Space Mono", monospace;
      font-size: 11px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--text-secondary);
    }
    .nd-meta {
      font-family: "Space Mono", monospace;
      font-size: 12px;
      color: var(--text-secondary);
      line-height: 1.6;
    }

    /* ---- Header ---- */
    .nd-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      padding-bottom: var(--space-xl);
      border-bottom: 1px solid var(--border);
      margin-bottom: var(--space-2xl);
    }
    .nd-header-title {
      font-size: 18px;
      font-weight: 500;
      color: var(--text-display);
      margin-top: var(--space-sm);
    }
    .nd-header-right { text-align: right; }
    .nd-status-indicator {
      display: inline-flex;
      align-items: center;
      gap: var(--space-sm);
      font-family: "Space Mono", monospace;
      font-size: 11px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--success);
    }
    .nd-status-dot {
      width: 6px; height: 6px;
      border-radius: 50%;
      background: var(--success);
    }

    /* ---- Hero ---- */
    .nd-hero {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: var(--space-2xl);
      align-items: flex-end;
      margin-bottom: var(--space-2xl);
      padding-bottom: var(--space-2xl);
      border-bottom: 1px solid var(--border);
    }
    .nd-hero-score {
      display: flex;
      align-items: baseline;
      gap: var(--space-md);
      margin: var(--space-md) 0;
    }
    .nd-display {
      font-family: "Doto", "Space Mono", monospace;
      font-size: 96px;
      line-height: 1;
      letter-spacing: -0.02em;
      color: var(--text-display);
    }
    .nd-score-unit {
      font-family: "Space Mono", monospace;
      font-size: 14px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--text-secondary);
      margin-bottom: 12px;
    }
    .nd-hero-right {
      text-align: right;
      display: flex;
      flex-direction: column;
      gap: var(--space-sm);
      align-items: flex-end;
    }
    .nd-level-badge {
      font-family: "Space Grotesk", system-ui;
      font-size: 28px;
      font-weight: 400;
      color: var(--text-display);
    }
    .nd-warning {
      margin-top: var(--space-md);
      padding: var(--space-md);
      border: 1px solid var(--accent);
      background: var(--accent-subtle);
      font-family: "Space Mono", monospace;
      font-size: 11px;
      color: var(--text-primary);
      line-height: 1.5;
      display: none;
    }

    /* ---- Metrics grid ---- */
    .nd-metrics {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 1px;
      background: var(--border);
      border: 1px solid var(--border);
      margin-bottom: var(--space-2xl);
    }
    .nd-metric-card {
      background: var(--surface);
      padding: var(--space-lg) var(--space-md);
    }
    .nd-metric-value {
      font-family: "Space Grotesk", system-ui;
      font-size: 32px;
      font-weight: 400;
      color: var(--text-display);
      margin-top: var(--space-md);
      line-height: 1.1;
    }
    .nd-metric-note {
      font-family: "Space Mono", monospace;
      font-size: 11px;
      color: var(--text-disabled);
      margin-top: var(--space-sm);
      letter-spacing: 0.04em;
    }

    /* ---- Sections ---- */
    .nd-section {
      margin-bottom: var(--space-2xl);
      border: 1px solid var(--border);
      background: var(--surface);
    }
    .nd-section-header {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      padding: var(--space-md) var(--space-lg);
      border-bottom: 1px solid var(--border);
    }
    .nd-section-body { padding: var(--space-lg); }

    /* ---- Trend bars ---- */
    .nd-bars-wrap {
      overflow-x: auto;
      scrollbar-width: thin;
      scrollbar-color: var(--border-visible) var(--surface);
    }
    .nd-bars {
      display: flex;
      gap: 3px;
      align-items: flex-end;
      min-height: 140px;
      padding: var(--space-md) 0 var(--space-sm);
    }
    .nd-bar-wrap {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 4px;
      flex: 0 0 34px;
      min-width: 34px;
    }
    .nd-bar {
      width: 100%;
      background: var(--text-display);
      min-height: 4px;
      /* Square ends - no border-radius, mechanical */
    }
    .nd-bar.level-fluido { background: var(--success); }
    .nd-bar.level-denso { background: var(--warning); }
    .nd-bar.level-retenciones { background: var(--accent); }
    .nd-bar.level-congestion_fuerte { background: var(--accent); opacity: 0.7; }
    .nd-bar-score {
      font-family: "Space Mono", monospace;
      font-size: 9px;
      color: var(--text-disabled);
    }
    .nd-bar-label {
      font-family: "Space Mono", monospace;
      font-size: 9px;
      color: var(--text-secondary);
      text-align: center;
      white-space: nowrap;
    }
    .nd-trend-legend {
      display: flex;
      gap: var(--space-lg);
      flex-wrap: wrap;
      padding: var(--space-md) var(--space-lg);
      border-top: 1px solid var(--border);
    }
    .nd-legend-item {
      display: flex;
      align-items: center;
      gap: var(--space-xs);
      font-family: "Space Mono", monospace;
      font-size: 10px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--text-secondary);
    }
    .nd-legend-color { width: 14px; height: 3px; }

    /* ---- Two-column layout ---- */
    .nd-two-col {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 1px;
      background: var(--border);
      border: 1px solid var(--border);
      margin-bottom: var(--space-2xl);
    }
    .nd-two-col > section {
      background: var(--surface);
    }

    /* ---- VMS Panels ---- */
    .nd-vms-list { display: grid; gap: 1px; background: var(--border); }
    .nd-vms-item { background: var(--surface); padding: var(--space-lg); }
    .nd-vms-header {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      margin-bottom: var(--space-xs);
    }
    .nd-vms-name {
      font-size: 14px;
      font-weight: 500;
      color: var(--text-display);
    }
    .nd-vms-km {
      font-family: "Space Mono", monospace;
      font-size: 11px;
      color: var(--text-secondary);
    }
    .nd-vms-dir {
      font-family: "Space Mono", monospace;
      font-size: 11px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--text-secondary);
      margin-bottom: var(--space-md);
    }
    .nd-vms-display {
      background: #0a0a0a;
      border: 1px solid var(--border-visible);
      padding: var(--space-md);
      font-family: "Space Mono", monospace;
      font-size: 13px;
      font-weight: 700;
      text-transform: uppercase;
      text-align: center;
      color: #ffb800;
      line-height: 1.5;
      letter-spacing: 0.08em;
    }
    .nd-vms-pictos {
      display: flex;
      gap: var(--space-sm);
      flex-wrap: wrap;
      margin-top: var(--space-sm);
    }

    /* ---- Incidents list ---- */
    .nd-list { display: grid; gap: 1px; background: var(--border); }
    .nd-list-item { background: var(--surface); padding: var(--space-md) var(--space-lg); }
    .nd-list-head {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      margin-bottom: 4px;
    }
    .nd-list-title {
      font-size: 14px;
      font-weight: 500;
      color: var(--text-display);
    }
    .nd-list-km {
      font-family: "Space Mono", monospace;
      font-size: 11px;
      color: var(--text-secondary);
    }
    .nd-list-sub {
      font-family: "Space Mono", monospace;
      font-size: 11px;
      color: var(--text-secondary);
      margin-bottom: var(--space-sm);
    }
    .nd-chips { display: flex; gap: var(--space-xs); flex-wrap: wrap; }
    .nd-chip {
      font-family: "Space Mono", monospace;
      font-size: 10px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      padding: 3px 8px;
      border: 1px solid var(--border-visible);
      color: var(--text-secondary);
    }
    .nd-chip.warn { border-color: var(--warning); color: var(--warning); }
    .nd-chip.alert { border-color: var(--accent); color: var(--accent); }
    .nd-chip.good { border-color: var(--success); color: var(--success); }

    /* ---- Tags ---- */
    .nd-tag {
      font-family: "Space Mono", monospace;
      font-size: 10px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      padding: 3px 8px;
      border: 1px solid var(--border-visible);
      color: var(--text-secondary);
    }
    .nd-tag.warn { border-color: var(--warning); color: var(--warning); }

    /* ---- Cameras ---- */
    .nd-camera-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 1px;
      background: var(--border);
    }
    .nd-camera { background: var(--surface); overflow: hidden; }
    .nd-camera img { display: block; width: 100%; aspect-ratio: 16/10; object-fit: cover; }
    .nd-camera-placeholder {
      aspect-ratio: 16/10;
      display: grid;
      place-items: center;
      font-family: "Space Mono", monospace;
      font-size: 10px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--text-disabled);
      background: var(--surface-raised);
    }
    .nd-camera-body {
      padding: var(--space-md);
      border-top: 1px solid var(--border);
    }
    .nd-camera-id {
      font-family: "Space Mono", monospace;
      font-size: 11px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--text-display);
      margin-bottom: 4px;
    }
    .nd-camera-meta {
      font-family: "Space Mono", monospace;
      font-size: 10px;
      color: var(--text-secondary);
      line-height: 1.6;
    }
    .nd-camera-count { color: var(--text-primary); font-weight: 700; }

    /* ---- Empty states ---- */
    .nd-empty {
      padding: var(--space-2xl) var(--space-lg);
      font-family: "Space Mono", monospace;
      font-size: 11px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--text-disabled);
      text-align: center;
    }

    /* ---- Footer ---- */
    .nd-footer {
      padding-top: var(--space-xl);
      border-top: 1px solid var(--border);
      display: flex;
      justify-content: space-between;
    }


    /* ---- Tabs ---- */
    .nd-tab-nav {
      display: flex;
      gap: 1px;
      background: var(--border);
      border: 1px solid var(--border);
      margin-bottom: var(--space-2xl);
    }
    .nd-tab {
      font-family: "Space Mono", monospace;
      font-size: 11px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      padding: 12px 20px;
      background: var(--surface);
      color: var(--text-secondary);
      border: none;
      cursor: pointer;
      transition: color 150ms, background 150ms;
    }
    .nd-tab:hover { color: var(--text-primary); }
    .nd-tab.active { background: var(--surface-raised); color: var(--text-display); }

    /* ---- Mapa ---- */
    #nd-map { background: var(--black); }
    .nd-map-marker {
      width: 52px; height: 52px;
      background: var(--surface);
      border: 2px solid var(--border-visible);
      display: flex; align-items: center; justify-content: center;
      font-family: "Space Mono", monospace;
      font-size: 12px; font-weight: 700;
      color: var(--text-display);
      cursor: pointer;
      transition: border-color 150ms;
    }
    .nd-map-marker:hover { border-color: var(--text-display); }
    .maplibregl-popup-content {
      background: #111111 !important;
      border: 1px solid #333333 !important;
      border-radius: 0 !important;
      padding: 0 !important;
      box-shadow: none !important;
    }
    .maplibregl-popup-tip { display: none !important; }
    .maplibregl-ctrl-group {
      background: #111111 !important;
      border: 1px solid #333333 !important;
      border-radius: 0 !important;
      box-shadow: none !important;
    }
    .maplibregl-ctrl-group button {
      background: #111111 !important;
      color: #999999 !important;
    }
    .maplibregl-ctrl-group button:hover { background: #1A1A1A !important; color: #FFFFFF !important; }
    .maplibregl-ctrl-attrib { background: rgba(0,0,0,0.6) !important; color: #666 !important; font-size: 9px !important; }

    /* ---- Responsive ---- */
    @media (max-width: 800px) {
      .nd-hero { grid-template-columns: 1fr; }
      .nd-hero-right { text-align: left; align-items: flex-start; }
      .nd-display { font-size: 72px; }
      .nd-metrics { grid-template-columns: 1fr; }
      .nd-two-col { grid-template-columns: 1fr; }
      .nd-camera-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="nd-shell">

    <!-- Header -->
    <header class="nd-header">
      <div>
        <div class="nd-eyebrow">Monitor Operativo · Puente del Centenario</div>
        <div class="nd-header-title">VCentenario</div>
      </div>
      <div class="nd-header-right">
        <div class="nd-status-indicator">
          <span class="nd-status-dot"></span>
          <span>Activo</span>
        </div>
        <div class="nd-eyebrow" id="generatedAt" style="margin-top:8px;">Sin datos</div>
      </div>
    </header>

    <!-- Tab navigation -->
    <nav class="nd-tab-nav">
      <button class="nd-tab active" id="btn-estado" onclick="showTab('estado')">[ ESTADO ]</button>
      <button class="nd-tab" id="btn-velocidades" onclick="showTab('velocidades')">VELOCIDADES</button>
      <button class="nd-tab" id="btn-mapa" onclick="showTab('mapa')">MAPA</button>
    </nav>

    <div id="tab-estado">
    <!-- Hero: Score (primary) + Level (secondary) + Meta (tertiary) -->
    <section class="nd-hero">
      <div>
        <div class="nd-eyebrow">Tráfico · Score actual</div>
        <div class="nd-hero-score">
          <div class="nd-display" id="heroScoreNum">--</div>
          <div class="nd-score-unit">pts</div>
        </div>
        <div id="heroDetail" class="nd-meta">Ejecuta una recogida para poblar el panel.</div>
        <div id="runWarnings" class="nd-warning"></div>
      </div>
      <div class="nd-hero-right">
        <div class="nd-eyebrow">Estado inferido</div>
        <div id="heroSummary" class="nd-level-badge">Esperando datos</div>
      </div>
    </section>

    <!-- Metrics -->
    <section class="nd-metrics">
      <article class="nd-metric-card">
        <div class="nd-label">Tráfico del puente</div>
        <div id="trafficLevel" class="nd-metric-value">-</div>
        <div id="trafficScore" class="nd-metric-note">Score -</div>
      </article>
      <article class="nd-metric-card">
        <div class="nd-label">Carril reversible</div>
        <div id="reversibleState" class="nd-metric-value">-</div>
        <div id="reversibleConfidence" class="nd-metric-note">Confianza -</div>
      </article>
      <article class="nd-metric-card">
        <div class="nd-label">Evidencia visible</div>
        <div id="evidenceCount" class="nd-metric-value">0</div>
        <div id="countsLine" class="nd-metric-note">Paneles 0 · Incidencias 0 · Cámaras 0</div>
      </article>
    </section>

    <!-- Trend -->
    <section class="nd-section">
      <div class="nd-section-header">
        <span class="nd-label">Pulso reciente</span>
        <span class="nd-meta">Últimas ejecuciones guardadas</span>
      </div>
      <div class="nd-section-body">
        <div class="nd-bars-wrap">
          <div id="trendBars" class="nd-bars"></div>
        </div>
      </div>
      <div class="nd-trend-legend">
        <div class="nd-legend-item">
          <div class="nd-legend-color" style="background:var(--success);"></div>Fluido
        </div>
        <div class="nd-legend-item">
          <div class="nd-legend-color" style="background:var(--warning);"></div>Denso
        </div>
        <div class="nd-legend-item">
          <div class="nd-legend-color" style="background:var(--accent);"></div>Retenciones
        </div>
        <div class="nd-legend-item">
          <div class="nd-legend-color" style="background:var(--accent); opacity:0.7;"></div>Congestión fuerte
        </div>
      </div>
    </section>

    <!-- Panels + Incidents -->
    <div class="nd-two-col">
      <section>
        <div class="nd-section-header">
          <span class="nd-label">Paneles activos</span>
          <span class="nd-meta">Mensajes VMS de la zona</span>
        </div>
        <div id="panelsList"></div>
      </section>
      <section style="border-left: 1px solid var(--border);">
        <div class="nd-section-header">
          <span class="nd-label">Incidencias cercanas</span>
          <span class="nd-meta">Eventos DATEX2 filtrados</span>
        </div>
        <div id="incidentsList"></div>
      </section>
    </div>

    <!-- Cameras -->
    <section class="nd-section">
      <div class="nd-section-header">
        <span class="nd-label">Cámaras</span>
        <span class="nd-meta">Último snapshot disponible</span>
      </div>
      <div id="cameraGrid" class="nd-camera-grid"></div>
    </section>

    </div><!-- /tab-estado -->

    <!-- Velocidades TomTom -->
    <div id="tab-velocidades" style="display:none;">

      <section class="nd-hero" style="margin-top:0;">
        <div>
          <div class="nd-eyebrow">Velocidad media · Puente del Centenario</div>
          <div class="nd-hero-score">
            <div class="nd-display" id="spd-hero">--</div>
            <div class="nd-score-unit">km/h</div>
          </div>
          <div id="spd-hero-meta" class="nd-meta">Media de los sensores activos del puente</div>
          <div class="nd-meta" style="margin-top:8px; color:var(--text-disabled);">Velocidad real GPS (probe data) \xb7 l\xedmite 60 km/h</div>
        </div>
        <div class="nd-hero-right">
          <div class="nd-eyebrow">Fuente</div>
          <div class="nd-level-badge" style="font-size:20px;">TomTom Flow</div>
        </div>
      </section>

      <!-- Speed by direction -->
      <section class="nd-metrics" style="grid-template-columns:1fr 1fr;">
        <article class="nd-metric-card">
          <div class="nd-label">Hacia Cádiz (+)</div>
          <div id="spd-positivo" class="nd-metric-value">-</div>
          <div id="spd-positivo-note" class="nd-metric-note">km/h · puente_positivo</div>
        </article>
        <article class="nd-metric-card">
          <div class="nd-label">Hacia Sevilla (-)</div>
          <div id="spd-negativo" class="nd-metric-value">-</div>
          <div id="spd-negativo-note" class="nd-metric-note">km/h · puente_negativo</div>
        </article>
      </section>

      <!-- Speed history chart -->
      <section class="nd-section">
        <div class="nd-section-header">
          <span class="nd-label">Historial de velocidad · Últimas 6 h</span>
          <span class="nd-meta" id="spd-sensor-count">-</span>
        </div>
        <div class="nd-section-body" style="padding:0;">
          <canvas id="spd-chart" width="900" height="280" style="display:block;width:100%;background:#000;"></canvas>
        </div>
        <div class="nd-trend-legend">
          <div class="nd-legend-item">
            <div class="nd-legend-color" style="background:#4A9E5C;"></div>Hacia Cádiz (+)
          </div>
          <div class="nd-legend-item">
            <div class="nd-legend-color" style="background:#D4A843;"></div>Hacia Sevilla (-)
          </div>
        </div>
      </section>

      <!-- All 4 TomTom points table -->
      <section class="nd-section">
        <div class="nd-section-header">
          <span class="nd-label">Sensores TomTom activos</span>
          <span class="nd-meta" id="spd-collected-at">-</span>
        </div>
        <div id="spd-table"></div>
      </section>

    </div><!-- /tab-velocidades -->

    </div><!-- /tab-velocidades cierre para añadir mapa antes del footer -->

    <!-- Mapa TomTom sensors -->
    <div id="tab-mapa" style="display:none;">

      <section class="nd-section" style="margin-bottom:var(--space-2xl);">
        <div class="nd-section-header">
          <span class="nd-label">Puente del Centenario · Sensores TomTom</span>
          <span class="nd-meta" id="map-status">Cargando mapa...</span>
        </div>
        <div id="nd-map" style="height:560px;"></div>
      </section>

      <!-- Tabla resumen bajo el mapa -->
      <section class="nd-metrics" style="grid-template-columns:repeat(4,1fr); margin-bottom:0;">
        <article class="nd-metric-card" id="map-card-puente-positivo">
          <div class="nd-label">Hacia Cádiz</div>
          <div class="nd-metric-value" id="map-spd-puente-positivo">-</div>
          <div class="nd-metric-note">tomtom_puente_positivo</div>
        </article>
        <article class="nd-metric-card" id="map-card-puente-negativo">
          <div class="nd-label">Hacia Sevilla</div>
          <div class="nd-metric-value" id="map-spd-puente-negativo">-</div>
          <div class="nd-metric-note">tomtom_puente_negativo</div>
        </article>
        <article class="nd-metric-card" id="map-card-sur-positivo">
          <div class="nd-label">Acceso Sur</div>
          <div class="nd-metric-value" id="map-spd-sur-positivo">-</div>
          <div class="nd-metric-note">tomtom_sur_positivo</div>
        </article>
        <article class="nd-metric-card" id="map-card-norte-negativo">
          <div class="nd-label">Acceso Norte</div>
          <div class="nd-metric-value" id="map-spd-norte-negativo">-</div>
          <div class="nd-metric-note">tomtom_norte_negativo</div>
        </article>
      </section>

    </div><!-- /tab-mapa -->

    <!-- Footer -->
    <footer class="nd-footer">
      <span class="nd-eyebrow">Actualización automática cada 60 s</span>
      <span class="nd-eyebrow">Puente del Centenario · Sevilla</span>
    </footer>

  </div>

  <script>
    const stateLabels = {
      fluido: "Fluido",
      denso: "Denso",
      retenciones: "Retenciones",
      congestion_fuerte: "Congestión fuerte",
      indeterminado: "Indeterminado",
      positive: "Probable sentido positivo",
      negative: "Probable sentido negativo"
    };

    const byId = (id) => document.getElementById(id);

    function formatDate(value) {
      if (!value) return "Sin timestamp";
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return value;
      return date.toLocaleString("es-ES", { dateStyle: "medium", timeStyle: "short" });
    }

    function formatKm(value) {
      return value == null ? "km -" : `km ${Number(value).toFixed(1)}`;
    }

    function formatConfidence(value) {
      if (value == null) return "Confianza -";
      return `Confianza ${(value * 100).toFixed(0)}%`;
    }

    function formatForecast(forecast) {
      if (!forecast || forecast.predicted_score_next == null) return "Sin forecast";
      const level = stateLabels[forecast.predicted_level_next] || forecast.predicted_level_next;
      return `Próxima hora: ${level} · score ${forecast.predicted_score_next}`;
    }

    function escapeHtml(text) {
      return String(text ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }

    function chipClass(label) {
      const v = String(label || "").toLowerCase();
      if (v.includes("high") || v.includes("alert") || v.includes("closed")) return "nd-chip alert";
      if (v.includes("medium") || v.includes("warn") || v.includes("retencion")) return "nd-chip warn";
      if (v.includes("200")) return "nd-chip good";
      return "nd-chip";
    }

    function renderPanels(panels) {
      const root = byId("panelsList");
      if (!panels || panels.length === 0) {
        root.innerHTML = '<div class="nd-empty">[Sin paneles activos]</div>';
        return;
      }
      const dirMap = { positive: "HACIA CÁDIZ", negative: "HACIA SEVILLA" };
      root.innerHTML = '<div class="nd-vms-list">' + panels.map((panel) => {
        const title = escapeHtml(panel.location_name || panel.location_id);
        const km = escapeHtml(formatKm(panel.km));
        const dir = dirMap[panel.direction] || "AMBOS SENTIDOS";
        const msg = (panel.legends || []).map(l => escapeHtml(l)).join("<br>");
        const pictos = (panel.pictograms || []).map((p) => `<span class="nd-tag warn">${escapeHtml(p)}</span>`).join("");
        return `
          <div class="nd-vms-item">
            <div class="nd-vms-header">
              <span class="nd-vms-name">${title}</span>
              <span class="nd-vms-km">${km}</span>
            </div>
            <div class="nd-vms-dir">${dir} · ${escapeHtml(panel.status || "Desconocido")}</div>
            <div class="nd-vms-display">${msg || "SIN MENSAJE ACTIVO"}</div>
            ${pictos ? `<div class="nd-vms-pictos">${pictos}</div>` : ""}
          </div>`;
      }).join("") + '</div>';
    }

    function renderIncidents(incidents) {
      const root = byId("incidentsList");
      if (!incidents || incidents.length === 0) {
        root.innerHTML = '<div class="nd-empty">[Sin incidencias cercanas]</div>';
        return;
      }
      root.innerHTML = '<div class="nd-list">' + incidents.map((incident) => `
        <div class="nd-list-item">
          <div class="nd-list-head">
            <span class="nd-list-title">${escapeHtml(incident.incident_type || incident.cause_type || "Incidencia")}</span>
            <span class="nd-list-km">${escapeHtml(formatKm(incident.from_km ?? incident.to_km))}</span>
          </div>
          <div class="nd-list-sub">
            ${escapeHtml(incident.road || "-")} · ${escapeHtml(incident.direction || "sin dirección")}
            · ${escapeHtml(incident.municipality || incident.province || "sin municipio")}
          </div>
          <div class="nd-chips">
            <span class="${chipClass(incident.severity)}">${escapeHtml(incident.severity || "sin severidad")}</span>
            <span class="nd-chip">${escapeHtml(incident.validity_status || "sin estado")}</span>
          </div>
        </div>`).join("") + '</div>';
    }

    function renderCameras(cameras) {
      const root = byId("cameraGrid");
      if (!cameras || cameras.length === 0) {
        root.innerHTML = '<div class="nd-empty">[Sin cámaras inventariadas]</div>';
        return;
      }
      root.innerHTML = cameras.map((camera) => {
        const hasImage = camera.http_status === 200 && camera.image_path;
        const imageUrl = hasImage ? `/snapshots/${encodeURIComponent(camera.image_path.split('/').pop())}` : "";
        return `
          <article class="nd-camera">
            ${hasImage
              ? `<img src="${imageUrl}" alt="Cam ${escapeHtml(camera.camera_id)}">`
              : `<div class="nd-camera-placeholder">[Sin snapshot]</div>`}
            <div class="nd-camera-body">
              <div class="nd-camera-id">Cam ${escapeHtml(camera.camera_id)}</div>
              <div class="nd-camera-meta">
                ${escapeHtml(camera.road || "-")} · ${escapeHtml(formatKm(camera.km))} · ${escapeHtml(camera.direction || "sin dirección")}<br>
                ${camera.vehicle_count != null ? `<span class="nd-camera-count">${camera.vehicle_count} vehículos</span><br>` : ""}
                HTTP ${escapeHtml(camera.http_status ?? "-")} · ${escapeHtml(camera.last_modified || camera.fetched_at || "sin fecha")}
              </div>
            </div>
          </article>`;
      }).join("");
    }

    function renderTrend(states) {
      const root = byId("trendBars");
      if (!states || states.length === 0) {
        root.innerHTML = '<div class="nd-empty" style="min-width:100%;">[Sin histórico]</div>';
        return;
      }
      const maxScore = Math.max(...states.map((item) => item.traffic_score || 0), 1);
      root.innerHTML = states.map((item) => {
        const height = Math.max(8, Math.round(((item.traffic_score || 0) / maxScore) * 110));
        const label = new Date(item.generated_at).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
        const levelClass = `level-${escapeHtml(item.traffic_level || "fluido")}`;
        return `
          <div class="nd-bar-wrap">
            <div class="nd-bar-score">${escapeHtml(String(item.traffic_score ?? "-"))}</div>
            <div class="nd-bar ${levelClass}" style="height:${height}px;" title="${escapeHtml(item.traffic_level)} · ${escapeHtml(String(item.traffic_score))}"></div>
            <div class="nd-bar-label">${escapeHtml(label)}</div>
          </div>`;
      }).join("");
    }

    function renderDashboard(data) {
      const state = data.state;
      const latestRun = data.latest_run;
      const warningBox = byId("runWarnings");
      if (!state) {
        byId("generatedAt").textContent = "Sin ejecuciones";
        byId("heroScoreNum").textContent = "--";
        byId("heroSummary").textContent = "Sin datos";
        byId("heroDetail").textContent = "Esperando a la primera ejección automática.";
        warningBox.style.display = "none";
        return;
      }
      byId("generatedAt").textContent = formatDate(state.generated_at);
      byId("heroScoreNum").textContent = state.traffic_score ?? "--";
      byId("heroSummary").textContent = stateLabels[state.traffic_level] || state.traffic_level;
      byId("heroDetail").textContent = `Reversible: ${stateLabels[state.reversible_probable] || state.reversible_probable} · ${formatConfidence(state.confidence)} · ${formatForecast(state.forecast)}`;
      byId("trafficLevel").textContent = stateLabels[state.traffic_level] || state.traffic_level;
      byId("trafficScore").textContent = `Score ${state.traffic_score}`;
      byId("reversibleState").textContent = stateLabels[state.reversible_probable] || state.reversible_probable;
      byId("reversibleConfidence").textContent = `${formatConfidence(state.confidence)} · ${formatForecast(state.forecast)}`;
      byId("evidenceCount").textContent = String((state.evidence || []).length);
      const sampleCount = state.learning_context && state.learning_context.sample_count != null
        ? ` · muestras franja ${state.learning_context.sample_count}` : "";
      byId("countsLine").textContent = `Paneles ${data.panels.length} · Incidencias ${data.incidents.length} · Cámaras ${data.cameras.length}${sampleCount}`;
      renderPanels(data.panels);
      renderIncidents(data.incidents);
      renderCameras(data.cameras);
      const trendSource = (data.trend_states && data.trend_states.length) ? data.trend_states : data.recent_states;
      renderTrend(trendSource);
      renderSpeedTab(data);
      renderMapTab(data);
      if (latestRun && latestRun.warnings && latestRun.warnings.length > 0) {
        warningBox.style.display = "block";
        warningBox.innerHTML = latestRun.warnings.map((item) => escapeHtml(item)).join("<br>");
      } else {
        warningBox.style.display = "none";
        warningBox.textContent = "";
      }
    }

    async function loadDashboard() {
      const response = await fetch("/api/dashboard");
      if (!response.ok) throw new Error("No se pudo cargar el dashboard");
      const data = await response.json();
      renderDashboard(data);
    }



    // ---- Mapa MapLibre GL ----
    let ndMap = null;
    let ndMapMarkers = {};
    let ndMapLoaded = false;

    const TOMTOM_POSITIONS = {
      'tomtom_puente_positivo': [-6.0168, 37.3727],
      'tomtom_puente_negativo': [-6.0173, 37.3722],
      'tomtom_sur_positivo':    [-6.0050, 37.3612],
      'tomtom_norte_negativo':  [-5.9980, 37.3840],
    };

    function sensorColor(d) {
      if (!d || d.average_speed == null) return '#666666';
      const isFreeFlow = d.free_flow_speed != null && Math.abs(d.average_speed - d.free_flow_speed) < 1;
      if (isFreeFlow) return '#666666';
      if (d.average_speed >= 55) return '#4A9E5C';
      if (d.average_speed >= 30) return '#D4A843';
      return '#D71921';
    }

    function initMap() {
      if (ndMap) { ndMap.resize(); return; }
      // Diagnóstico: comprobar que maplibregl está disponible
      if (typeof maplibregl === 'undefined') {
        const reason = window._mlError ? 'archivo no descargado (HTTP error)' :
                       window._mlLoaded ? 'script cargó pero maplibregl no definido (error de ejecución JS)' :
                       'script aún no cargado';
        byId('map-status').textContent = 'ERROR: ' + reason;
        return;
      }
      const container = byId('nd-map');
      byId('map-status').textContent = 'Iniciando mapa... container=' + container.offsetWidth + 'x' + container.offsetHeight;
      ndMap = new maplibregl.Map({
        container: 'nd-map',
        style: {
          version: 8,
          sources: {
            'carto-dark': {
              type: 'raster',
              tiles: [
                'https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
                'https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png'
              ],
              tileSize: 256,
              attribution: '© OpenStreetMap contributors © CARTO',
            }
          },
          layers: [{ id: 'carto-dark-layer', type: 'raster', source: 'carto-dark' }]
        },
        center: [-6.0170, 37.3722],
        zoom: 13.5,
        attributionControl: false,
      });
      ndMap.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
      ndMap.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right');
      ndMap.on('error', (e) => {
        byId('map-status').textContent = 'Error: ' + (e.error ? e.error.message : 'desconocido');
      });
      ndMap.on('load', () => {
        ndMapLoaded = true;
        byId('map-status').textContent = 'MapLibre GL · CARTO Dark';
        // Dibujar línea del puente
        ndMap.addSource('bridge', {
          type: 'geojson',
          data: {
            type: 'Feature',
            geometry: {
              type: 'LineString',
              coordinates: [
                [-6.0140, 37.3710],
                [-6.0168, 37.3727],
                [-6.0190, 37.3742],
              ]
            }
          }
        });
        ndMap.addLayer({
          id: 'bridge-line',
          type: 'line',
          source: 'bridge',
          paint: {
            'line-color': '#FFFFFF',
            'line-width': 3,
            'line-opacity': 0.25,
          }
        });
        // Si ya hay datos, pintarlos ahora
        if (window._lastDashboardData) renderMapTab(window._lastDashboardData);
      });
    }

    function renderMapTab(data) {
      window._lastDashboardData = data;
      if (!ndMap || !ndMapLoaded) return;

      const detectors = data.detectors || [];
      const tomtom = detectors.filter(d => d.detector_id && d.detector_id.startsWith('tomtom_'));

      // Actualizar tarjetas resumen
      Object.keys(TOMTOM_POSITIONS).forEach(id => {
        const d = tomtom.find(x => x.detector_id === id);
        const el = byId('map-spd-' + id.replace('tomtom_', '').replaceAll('_', '-'));
        if (el) {
          const isFreeFlow = d && d.free_flow_speed != null && d.average_speed != null && Math.abs(d.average_speed - d.free_flow_speed) < 1;
          el.textContent = d && d.average_speed != null ? d.average_speed.toFixed(0) + ' km/h' : '-';
          el.style.color = sensorColor(d);
          el.style.opacity = isFreeFlow ? '0.4' : '1';
        }
      });

      // Limpiar marcadores anteriores
      Object.values(ndMapMarkers).forEach(m => m.remove());
      ndMapMarkers = {};

      // Dibujar marcadores
      tomtom.forEach(d => {
        const pos = TOMTOM_POSITIONS[d.detector_id];
        if (!pos) return;

        const color = sensorColor(d);
        const isFreeFlow = d.free_flow_speed != null && d.average_speed != null && Math.abs(d.average_speed - d.free_flow_speed) < 1;
        const spd = d.average_speed != null ? d.average_speed.toFixed(0) : '--';
        const isPuente = d.detector_id.includes('puente');
        const dir = d.detector_id.includes('positivo') ? '↑ Cádiz' : '↓ Sevilla';
        const ffsNote = d.free_flow_speed != null
          ? `<div style="color:#666666;margin-top:2px;">libre ${d.free_flow_speed.toFixed(0)} km/h</div>`
          : '';
        const statusNote = isFreeFlow
          ? '<div style="color:#666666;margin-top:4px;font-size:9px;letter-spacing:0.06em;">SIN DATO REAL</div>'
          : '<div style="color:#4A9E5C;margin-top:4px;font-size:9px;letter-spacing:0.06em;">EN TIEMPO REAL</div>';

        const el = document.createElement('div');
        el.className = 'nd-map-marker';
        el.style.borderColor = color;
        el.style.color = color;
        el.style.width = isPuente ? '52px' : '44px';
        el.style.height = isPuente ? '52px' : '44px';
        el.style.fontSize = isPuente ? '13px' : '11px';
        el.style.opacity = isFreeFlow ? '0.55' : '1';
        el.textContent = spd;

        const popup = new maplibregl.Popup({ offset: 12, closeButton: true, maxWidth: '200px' })
          .setHTML(`<div style="font-family:'Space Mono',monospace;font-size:11px;color:#E8E8E8;padding:12px 14px;line-height:1.6;">
            <div style="font-size:9px;letter-spacing:0.08em;text-transform:uppercase;color:#999999;margin-bottom:6px;">${escapeHtml(d.detector_id)}</div>
            <div style="font-size:24px;font-weight:700;color:${color};">${spd} <span style="font-size:12px;">km/h</span></div>
            <div style="color:#999999;margin-top:2px;">${isPuente ? dir : 'Acceso'}</div>
            ${ffsNote}${statusNote}
          </div>`);

        const marker = new maplibregl.Marker({ element: el, anchor: 'center' })
          .setLngLat(pos)
          .setPopup(popup)
          .addTo(ndMap);

        ndMapMarkers[d.detector_id] = marker;
      });
    }

    function showTab(name) {
      document.getElementById('tab-estado').style.display = name === 'estado' ? '' : 'none';
      document.getElementById('tab-velocidades').style.display = name === 'velocidades' ? '' : 'none';
      document.getElementById('tab-mapa').style.display = name === 'mapa' ? '' : 'none';
      document.getElementById('btn-estado').classList.toggle('active', name === 'estado');
      document.getElementById('btn-velocidades').classList.toggle('active', name === 'velocidades');
      document.getElementById('btn-mapa').classList.toggle('active', name === 'mapa');
      if (name === 'mapa') requestAnimationFrame(initMap);
    }

    function renderSpeedTab(data) {
      const detectors = data.detectors || [];
      const history = data.tomtom_speed_history || [];

      // Current readings from latest detectors
      const tomtom = detectors.filter(d => d.detector_id && d.detector_id.startsWith('tomtom_'));
      const puente = tomtom.filter(d => d.detector_id.includes('puente'));
      const pos = tomtom.find(d => d.detector_id.includes('positivo') && d.detector_id.includes('puente'));
      const neg = tomtom.find(d => d.detector_id.includes('negativo') && d.detector_id.includes('puente'));

      const avgPuente = puente.length
        ? (puente.reduce((a, d) => a + (d.average_speed || 0), 0) / puente.length).toFixed(0)
        : null;

      const allFreeFlow = puente.length > 0 && puente.every(
        d => d.free_flow_speed != null && d.average_speed != null && Math.abs(d.average_speed - d.free_flow_speed) < 1
      );
      byId('spd-hero').textContent = avgPuente ?? '--';
      byId('spd-hero').style.color = allFreeFlow ? 'var(--text-disabled)' : 'var(--text-display)';
      byId('spd-hero-meta').textContent = puente.length === 0
        ? 'Sin lecturas de sensores del puente'
        : allFreeFlow
          ? 'Sin tr\xe1fico real detectado \xb7 TomTom devuelve velocidad libre (dato est\xe1tico)'
          : `Dato en tiempo real \xb7 ${puente.length} sensor${puente.length > 1 ? 'es' : ''} activo${puente.length > 1 ? 's' : ''}`;

      if (pos) {
        byId('spd-positivo').textContent = pos.average_speed != null ? pos.average_speed.toFixed(0) : '-';
        byId('spd-positivo-note').textContent = `km/h · ${pos.detector_id}`;
      }
      if (neg) {
        byId('spd-negativo').textContent = neg.average_speed != null ? neg.average_speed.toFixed(0) : '-';
        byId('spd-negativo-note').textContent = `km/h · ${neg.detector_id}`;
      }

      byId('spd-sensor-count').textContent = `${puente.length} sensor${puente.length !== 1 ? 'es' : ''} del puente con datos`;
      if (puente.length > 0) {
        byId('spd-collected-at').textContent = formatDate(puente[0].collected_at);
      }

      // Table — solo sensores del puente
      const root = byId('spd-table');
      if (puente.length === 0) {
        root.innerHTML = '<div class="nd-empty">[Sin lecturas TomTom del puente — API key no configurada o sin datos recientes]</div>';
      } else {
        root.innerHTML = '<div class="nd-list">' + puente.map(d => {
          const spd = d.average_speed != null ? d.average_speed.toFixed(1) + ' km/h' : '-';
          const flow = d.vehicle_flow != null ? d.vehicle_flow + ' veh/h' : '-';
          const dir = d.detector_id.includes('positivo') ? '\u2191 C\xe1diz' : d.detector_id.includes('negativo') ? '\u2193 Sevilla' : '-';
          const isFreeFlow = d.free_flow_speed != null && d.average_speed != null && Math.abs(d.average_speed - d.free_flow_speed) < 1;
          const spdColor = isFreeFlow ? 'color:var(--text-disabled)' :
            d.average_speed == null ? '' :
            d.average_speed >= 55 ? 'color:var(--success)' :
            d.average_speed >= 30 ? 'color:var(--warning)' : 'color:var(--accent)';
          const freeFlowBadge = isFreeFlow
            ? ' <span class="nd-chip" style="font-size:9px;padding:2px 6px;border-color:var(--text-disabled);color:var(--text-disabled);">SIN DATOS REALES</span>'
            : '';
          const ffsNote = d.free_flow_speed != null ? ` \xb7 libre ${d.free_flow_speed.toFixed(0)} km/h` : '';
          return `<div class="nd-list-item">
            <div class="nd-list-head">
              <span class="nd-list-title" style="${spdColor}">${spd}${freeFlowBadge}</span>
              <span class="nd-list-km">${dir}</span>
            </div>
            <div class="nd-list-sub">${escapeHtml(d.detector_id)}${ffsNote} \xb7 flujo ${flow}</div>
          </div>`;
        }).join('') + '</div>';
      }

      // History chart — solo sensores del puente
      drawSpeedChart(history.filter(r => r.detector_id && r.detector_id.includes('puente')));
    }

    function drawSpeedChart(history) {
      const canvas = byId('spd-chart');
      if (!canvas) return;
      const ctx = canvas.getContext('2d');
      const W = canvas.width, H = canvas.height;
      ctx.fillStyle = '#000000';
      ctx.fillRect(0, 0, W, H);

      if (!history || history.length === 0) {
        ctx.fillStyle = '#333333';
        ctx.font = '700 12px "Space Mono"';
        ctx.textAlign = 'left';
        ctx.fillText('[SIN HISTÓRICO DE VELOCIDAD]', 20, 40);
        return;
      }

      const pad = { top: 32, right: 32, bottom: 36, left: 52 };
      const w = W - pad.left - pad.right;
      const h = H - pad.top - pad.bottom;

      // Group by detector_id -> sorted timestamps
      const series = {};
      history.forEach(r => {
        if (!series[r.detector_id]) series[r.detector_id] = [];
        series[r.detector_id].push({ t: r.collected_at, v: r.average_speed });
      });

      // All unique timestamps sorted
      const allTimes = [...new Set(history.map(r => r.collected_at))].sort();
      if (allTimes.length < 2) {
        ctx.fillStyle = '#333333';
        ctx.font = '700 12px "Space Mono"';
        ctx.textAlign = 'left';
        ctx.fillText('[DATOS INSUFICIENTES PARA TRAZAR TENDENCIA]', 20, 40);
        return;
      }

      const allSpeeds = history.map(r => r.average_speed).filter(v => v != null);
      const maxV = Math.max(...allSpeeds, 120);
      const minV = Math.min(...allSpeeds, 0);
      const range = maxV - minV || 1;

      // Grid
      ctx.strokeStyle = '#1A1A1A';
      ctx.lineWidth = 1;
      for (let i = 0; i <= 4; i++) {
        const y = pad.top + (h / 4) * i;
        ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(W - pad.right, y); ctx.stroke();
        ctx.fillStyle = '#666666';
        ctx.font = '9px "Space Mono"';
        ctx.textAlign = 'right';
        ctx.fillText((maxV - (range / 4) * i).toFixed(0), pad.left - 6, y + 3);
      }

      // Speed limit reference line at 60 km/h (límite puente + radar de tramo)
      if (60 >= minV && 60 <= maxV) {
        const yLimit = pad.top + h - ((60 - minV) / range) * h;
        ctx.strokeStyle = '#D71921';
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.beginPath(); ctx.moveTo(pad.left, yLimit); ctx.lineTo(W - pad.right, yLimit); ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = '#D71921';
        ctx.font = '9px "Space Mono"';
        ctx.textAlign = 'left';
        ctx.fillText('60', W - pad.right + 4, yLimit + 3);
      }

      // Color map for series
      const colorMap = {
        'tomtom_puente_positivo': '#4A9E5C',
        'tomtom_puente_negativo': '#D4A843',
        'tomtom_sur_positivo':    '#666666',
        'tomtom_norte_negativo':  '#666666',
      };

      // Draw each series
      Object.entries(series).forEach(([detId, points]) => {
        const color = colorMap[detId] || '#999999';
        points.sort((a, b) => a.t.localeCompare(b.t));
        ctx.strokeStyle = color;
        ctx.lineWidth = detId.includes('puente') ? 1.5 : 1;
        ctx.lineJoin = 'miter';
        ctx.lineCap = 'square';
        ctx.beginPath();
        let started = false;
        points.forEach(p => {
          if (p.v == null) return;
          const xi = allTimes.indexOf(p.t);
          const x = pad.left + (xi / (allTimes.length - 1)) * w;
          const y = pad.top + h - ((p.v - minV) / range) * h;
          if (!started) { ctx.moveTo(x, y); started = true; }
          else ctx.lineTo(x, y);
        });
        ctx.stroke();
      });

      // X labels (time)
      ctx.fillStyle = '#666666';
      ctx.font = '9px "Space Mono"';
      ctx.textAlign = 'center';
      const step = Math.max(1, Math.ceil(allTimes.length / 6));
      for (let i = 0; i < allTimes.length; i += step) {
        const x = pad.left + (i / (allTimes.length - 1)) * w;
        const t = new Date(allTimes[i]);
        const label = t.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
        ctx.fillText(label, x, H - 4);
      }
    }

    loadDashboard().catch((error) => {
      byId("heroDetail").textContent = `[ERROR] ${error.message}`;
    });
    window.setInterval(() => {
      loadDashboard().catch(() => {});
    }, 60000);
  </script>
</body>
</html>
"""


class DashboardServer:
    def __init__(
        self,
        service: Optional[VCentenarioService] = None,
        host: str = "127.0.0.1",
        port: int = 8080,
    ) -> None:
        self.service = service or VCentenarioService(db_path=DEFAULT_DB_PATH, snapshots_dir=DEFAULT_SNAPSHOTS_DIR)
        self.host = host
        self.port = port
        self.enable_refresh_endpoint = ENABLE_REFRESH_ENDPOINT
        self.refresh_token = REFRESH_TOKEN
        self.refresh_min_interval_seconds = max(0, REFRESH_MIN_INTERVAL_SECONDS)
        self._refresh_lock = threading.Lock()
        self._last_refresh_started_at = 0.0

    def serve(self) -> None:
        service = self.service
        snapshots_dir = service.snapshots_dir.resolve()
        enable_refresh_endpoint = self.enable_refresh_endpoint
        refresh_token = self.refresh_token
        refresh_min_interval_seconds = self.refresh_min_interval_seconds
        refresh_lock = self._refresh_lock
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path == "/":
                    self._send_html(HTML_PAGE)
                    return
                if parsed.path == "/api/dashboard":
                    self._send_json(service.dashboard_data())
                    return
                if parsed.path == "/healthz":
                    self._send_json({"ok": True})
                    return
                if parsed.path.startswith("/snapshots/"):
                    name = Path(parsed.path.removeprefix("/snapshots/")).name
                    file_path = snapshots_dir / name
                    if not file_path.exists() or snapshots_dir not in file_path.resolve().parents:
                        self.send_error(HTTPStatus.NOT_FOUND, "Snapshot no encontrado")
                        return
                    self._send_file(file_path)
                    return
                if parsed.path.startswith("/static/"):
                    static_dir = Path(__file__).parent / "static"
                    name = Path(parsed.path.removeprefix("/static/")).name
                    file_path = static_dir / name
                    if not file_path.exists() or static_dir not in file_path.resolve().parents:
                        self.send_error(HTTPStatus.NOT_FOUND, "Static file no encontrado")
                        return
                    self._send_file(file_path)
                    return
                self.send_error(HTTPStatus.NOT_FOUND, "Ruta no encontrada")

            def do_POST(self) -> None:
                parsed = urlparse(self.path)
                self._refresh_lock_acquired = False
                if parsed.path == "/api/refresh":
                    if not enable_refresh_endpoint:
                        self._send_json({"error": "refresh endpoint disabled"}, status=HTTPStatus.FORBIDDEN)
                        return
                    if not self._is_refresh_authorized(refresh_token):
                        self._send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
                        return
                    if not self._begin_refresh(refresh_lock, refresh_min_interval_seconds, server):
                        return
                    try:
                        service.run_once()
                    except Exception as exc:
                        self._send_json({"error": str(exc)}, status=500)
                        return
                    self._send_json(service.dashboard_data())
                    return
                self.send_error(HTTPStatus.NOT_FOUND, "Ruta no encontrada")

            def log_message(self, format: str, *args: object) -> None:
                return

            def _send_json(self, payload: object, status: int = 200) -> None:
                body = dumps_json(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self._send_common_headers()
                self.end_headers()
                self.wfile.write(body)

            def _send_html(self, html: str, status: int = 200) -> None:
                body = html.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self._send_common_headers()
                self.end_headers()
                self.wfile.write(body)

            def _send_file(self, file_path: Path) -> None:
                body = file_path.read_bytes()
                mime_type, _ = mimetypes.guess_type(str(file_path))
                self.send_response(200)
                self.send_header("Content-Type", mime_type or "application/octet-stream")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self._send_common_headers()
                self.end_headers()
                self.wfile.write(body)

            def _send_common_headers(self) -> None:
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Cross-Origin-Resource-Policy", "same-origin")

            def _is_refresh_authorized(self, expected_token: str) -> bool:
                if not expected_token:
                    return False
                auth_header = self.headers.get("Authorization", "")
                if auth_header.startswith("Bearer "):
                    provided = auth_header.removeprefix("Bearer ").strip()
                else:
                    provided = self.headers.get("X-Refresh-Token", "").strip()
                return provided == expected_token

            def _begin_refresh(
                self,
                lock: threading.Lock,
                minimum_interval_seconds: int,
                stateful_server: "DashboardServer",
            ) -> bool:
                if not lock.acquire(blocking=False):
                    self._send_json({"error": "refresh already in progress"}, status=HTTPStatus.CONFLICT)
                    return False
                now = time.monotonic()
                elapsed = now - stateful_server._last_refresh_started_at
                if stateful_server._last_refresh_started_at and elapsed < minimum_interval_seconds:
                    lock.release()
                    retry_after = max(1, int(minimum_interval_seconds - elapsed))
                    body = dumps_json(
                        {
                            "error": "refresh rate limited",
                            "retry_after_seconds": retry_after,
                        }
                    ).encode("utf-8")
                    self.send_response(HTTPStatus.TOO_MANY_REQUESTS)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Retry-After", str(retry_after))
                    self._send_common_headers()
                    self.end_headers()
                    self.wfile.write(body)
                    return False
                stateful_server._last_refresh_started_at = now
                self._refresh_lock_acquired = True
                return True

        original_do_post = Handler.do_POST

        def wrapped_do_post(self: Handler) -> None:
            try:
                original_do_post(self)
            finally:
                if getattr(self, "_refresh_lock_acquired", False):
                    try:
                        refresh_lock.release()
                    except RuntimeError:
                        pass

        Handler.do_POST = wrapped_do_post

        httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        print(f"Dashboard en http://{self.host}:{self.port}")
        httpd.serve_forever()
