from __future__ import annotations

import json
import mimetypes
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import time
from typing import Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from .config import (
    ADSENSE_CLIENT_ID,
    DEFAULT_DB_PATH,
    DEFAULT_SNAPSHOTS_DIR,
    ENABLE_REFRESH_ENDPOINT,
    LOCAL_TIMEZONE,
    REFRESH_MIN_INTERVAL_SECONDS,
    REFRESH_TOKEN,
    UMAMI_WEBSITE_ID,
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
    <title>5Centenario · Traffic Monitor</title>
    <link rel="icon" type="image/svg+xml" href="/favicon.svg">
  <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
    <script src="/static/three.min.js" defer></script>
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
                <div class="nd-title">5Centenario</div>
            </div>
            <div class="nd-status">
                <div class="nd-eyebrow"><span class="nd-status-dot"></span>Activo</div>
                <div class="nd-eyebrow" style="margin-top:6px;">Actualización: <span id="lastUpdate">--:--</span></div>
            </div>
        </header>

        <div>
            <div class="nd-eyebrow" style="margin-bottom:12px;">Traffic Score · Últimas 16 lecturas</div>
            <canvas id="chart" style="min-height:200px;"></canvas>
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

            const cssW = canvas.offsetWidth || window.innerWidth - 40 || 900;
            const cssH = window.innerWidth < 600 ? 200 : 320;
            canvas.width = Math.max(cssW, 200);
            canvas.height = cssH;

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

            // X labels — máximo que caben sin solaparse (etiqueta ~40 px)
            ctx.fillStyle = '#666666';
            ctx.font = '400 9px "Space Mono"';
            ctx.textAlign = 'center';
            const maxLabels = Math.max(1, Math.floor(w / 44));
            const step = Math.max(1, Math.ceil(scores.length / maxLabels));
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
  <title>5Centenario Monitor</title>
  <link rel="icon" type="image/svg+xml" href="/favicon.svg">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Doto:ROND@0&family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&family=Space+Grotesk:wght@300;400;500&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
  <script src="/static/three.min.js" defer></script>
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
      /* Canvas / chart tokens (sincronizados con el tema) */
      --canvas-bg: #000000;
      --canvas-grid: #1A1A1A;
      --canvas-grid-strong: #333333;
      --canvas-text: #666666;
      --canvas-axis: #FFFFFF;
      --canvas-accent: #444444;
      --canvas-empty: #333333;
      /* Panel VMS (simula LED; permanece oscuro en ambos temas) */
      --vms-display-bg: #0a0a0a;
      --vms-display-text: #ffb800;
      --space-xs: 4px;
      --space-sm: 8px;
      --space-md: 16px;
      --space-lg: 24px;
      --space-xl: 32px;
      --space-2xl: 48px;
      --space-3xl: 64px;
    }
    /* ---- Tema claro ---- */
    [data-theme="light"] {
      --black: #FFFFFF;
      --surface: #FAFAFA;
      --surface-raised: #F0F0F0;
      --border: #E4E4E4;
      --border-visible: #C4C4C4;
      --text-disabled: #A0A0A0;
      --text-secondary: #606060;
      --text-primary: #1A1A1A;
      --text-display: #000000;
      --accent: #B8141C;
      --accent-subtle: rgba(184,20,28,0.12);
      --success: #2E7D3C;
      --warning: #8C6510;
      --canvas-bg: #FFFFFF;
      --canvas-grid: #F0F0F0;
      --canvas-grid-strong: #D8D8D8;
      --canvas-text: #888888;
      --canvas-axis: #000000;
      --canvas-accent: #CCCCCC;
      --canvas-empty: #BBBBBB;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    html {
      overflow-x: hidden;
      max-width: 100vw;
    }
    body {
      font-family: "Space Grotesk", system-ui, sans-serif;
      background: var(--black);
      color: var(--text-primary);
      min-height: 100vh;
      overflow-x: hidden;
      width: 100%;
      max-width: 100vw;
    }
    .nd-shell {
      width: 100%;
      max-width: 1280px;
      margin: 0 auto;
      padding: var(--space-xl) var(--space-md) var(--space-2xl);
      overflow: hidden;
    }

    /* ---- Typography helpers ---- */
    .nd-eyebrow {
      font-family: "Space Mono", monospace;
      font-size: 11px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--text-secondary);
      overflow-wrap: break-word;
      word-break: break-word;
    }
    .nd-label {
      font-family: "Space Mono", monospace;
      font-size: 11px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--text-secondary);
      overflow-wrap: break-word;
      word-break: break-word;
    }
    .nd-meta {
      font-family: "Space Mono", monospace;
      font-size: 12px;
      color: var(--text-secondary);
      line-height: 1.6;
      overflow-wrap: break-word;
      word-break: break-word;
    }

    /* ---- Header ---- */
    .nd-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: var(--space-md);
      padding-bottom: var(--space-xl);
      border-bottom: 1px solid var(--border);
      margin-bottom: var(--space-2xl);
    }
    .nd-header > * { min-width: 0; }
    .nd-header-title {
      font-size: 18px;
      font-weight: 500;
      color: var(--text-display);
      margin-top: var(--space-sm);
    }
    .nd-header-right { text-align: right; min-width: 0; flex-shrink: 0; }
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
    /* Hijos directos del hero deben respetar el ancho del grid track */
    .nd-hero > * { min-width: 0; overflow: hidden; }
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
      max-width: 100%;
      overflow: hidden;
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
      min-width: 0;
      flex-shrink: 0;
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
      min-width: 0;
      overflow: hidden;
    }
    .nd-metric-value {
      font-family: "Space Grotesk", system-ui;
      font-size: 32px;
      font-weight: 400;
      color: var(--text-display);
      margin-top: var(--space-md);
      line-height: 1.1;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .nd-metric-note {
      font-family: "Space Mono", monospace;
      font-size: 11px;
      color: var(--text-disabled);
      margin-top: var(--space-sm);
      letter-spacing: 0.04em;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      max-width: 100%;
    }

    /* ---- Sections ---- */
    .nd-section {
      margin-bottom: var(--space-2xl);
      border: 1px solid var(--border);
      background: var(--surface);
      overflow: hidden;
    }
    .nd-section-header {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      padding: var(--space-md) var(--space-lg);
      border-bottom: 1px solid var(--border);
      gap: var(--space-sm);
      flex-wrap: wrap;
      overflow: hidden;
    }
    .nd-section-body { padding: var(--space-lg); overflow: hidden; }

    /* ---- Trend bars ---- */
    .nd-bars-wrap {
      /* canvas se adapta al ancho sin scroll */
    }
    #pulso-huelva, #pulso-cadiz { min-height: 80px; }
    #spd-chart-huelva, #spd-chart-cadiz { min-height: 200px; }
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
      overflow: hidden;
    }
    .nd-two-col > section {
      background: var(--surface);
      min-width: 0;
      overflow: hidden;
    }

    /* ---- VMS Panels ---- */
    .nd-vms-list { display: grid; gap: 1px; background: var(--border); overflow: hidden; }
    .nd-vms-item { background: var(--surface); padding: var(--space-lg); min-width: 0; overflow: hidden; }
    .nd-vms-header {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: var(--space-sm);
      flex-wrap: wrap;
      margin-bottom: var(--space-xs);
    }
    .nd-vms-name {
      font-size: 14px;
      font-weight: 500;
      color: var(--text-display);
      overflow-wrap: break-word;
      word-break: break-word;
      min-width: 0;
    }
    .nd-vms-km {
      font-family: "Space Mono", monospace;
      font-size: 11px;
      color: var(--text-secondary);
      white-space: nowrap;
    }
    .nd-vms-dir {
      font-family: "Space Mono", monospace;
      font-size: 11px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: var(--text-secondary);
      margin-bottom: var(--space-md);
      overflow-wrap: break-word;
      word-break: break-word;
    }
    .nd-vms-display {
      background: var(--vms-display-bg);
      border: 1px solid var(--border-visible);
      padding: var(--space-md);
      font-family: "Space Mono", monospace;
      font-size: 13px;
      font-weight: 700;
      text-transform: uppercase;
      text-align: center;
      color: var(--vms-display-text);
      line-height: 1.5;
      letter-spacing: 0.04em;
      overflow-wrap: break-word;
      word-break: break-word;
    }
    .nd-vms-pictos {
      display: flex;
      gap: var(--space-sm);
      flex-wrap: wrap;
      margin-top: var(--space-sm);
    }

    /* ---- Incidents list ---- */
    .nd-list { display: grid; gap: 1px; background: var(--border); overflow: hidden; }
    .nd-list-item { background: var(--surface); padding: var(--space-md) var(--space-lg); min-width: 0; overflow: hidden; }
    .nd-list-head {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: var(--space-sm);
      flex-wrap: wrap;
      margin-bottom: 4px;
    }
    .nd-list-title {
      font-size: 14px;
      font-weight: 500;
      color: var(--text-display);
      overflow-wrap: break-word;
      word-break: break-word;
      min-width: 0;
    }
    .nd-list-km {
      font-family: "Space Mono", monospace;
      font-size: 11px;
      color: var(--text-secondary);
      white-space: nowrap;
    }
    .nd-list-sub {
      font-family: "Space Mono", monospace;
      font-size: 11px;
      color: var(--text-secondary);
      margin-bottom: var(--space-sm);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      max-width: 100%;
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

    /* ---- Report buttons ---- */
    .nd-report-btn {
      font-family: "Space Mono", monospace;
      font-size: 11px;
      letter-spacing: 0.1em;
      padding: 10px 20px;
      cursor: pointer;
      border-radius: 2px;
      transition: opacity 0.15s;
    }
    .nd-report-btn:hover { opacity: 0.8; }
    .nd-report-btn:active { opacity: 0.5; }

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
      padding: var(--space-xl) var(--space-md);
      font-family: "Space Mono", monospace;
      font-size: 10px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: var(--text-disabled);
      text-align: center;
      overflow-wrap: break-word;
      word-break: break-word;
      max-width: 100%;
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
      flex-wrap: wrap;
      gap: 1px;
      background: var(--border);
      border: 1px solid var(--border);
      margin-bottom: var(--space-2xl);
      overflow: hidden;
    }
    .nd-tab {
      font-family: "Space Mono", monospace;
      font-size: 11px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      padding: 12px 20px;
      background: var(--surface);
      color: var(--text-secondary);
      border: none;
      cursor: pointer;
      transition: color 150ms, background 150ms;
      flex: 1 1 auto;
      text-align: center;
      white-space: nowrap;
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
      background: var(--surface) !important;
      border: 1px solid var(--border-visible) !important;
      border-radius: 0 !important;
      padding: 0 !important;
      box-shadow: none !important;
      color: var(--text-primary) !important;
    }
    .maplibregl-popup-tip { display: none !important; }
    .maplibregl-ctrl-group {
      background: var(--surface) !important;
      border: 1px solid var(--border-visible) !important;
      border-radius: 0 !important;
      box-shadow: none !important;
    }
    .maplibregl-ctrl-group button {
      background: var(--surface) !important;
      color: var(--text-secondary) !important;
    }
    .maplibregl-ctrl-group button:hover { background: var(--surface-raised) !important; color: var(--text-display) !important; }
    .maplibregl-ctrl-attrib { background: var(--surface-raised) !important; color: var(--text-disabled) !important; font-size: 9px !important; }

    /* ---- Direction cards (sentido Huelva / sentido Cádiz) ---- */
    .nd-directions {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 1px;
      background: var(--border);
      border: 1px solid var(--border);
      margin-bottom: var(--space-2xl);
    }
    .nd-direction-card {
      background: var(--surface);
      padding: var(--space-xl) var(--space-lg);
      display: flex;
      flex-direction: column;
      gap: var(--space-xs);
      min-width: 0;
      overflow: hidden;
    }
    .nd-direction-heading {
      display: flex;
      align-items: center;
      gap: var(--space-sm);
      font-family: "Space Mono", monospace;
      font-size: 11px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--text-secondary);
      margin-bottom: var(--space-sm);
    }
    .nd-direction-arrow {
      font-size: 16px;
      line-height: 1;
    }
    .nd-direction-speed {
      font-family: "Doto", "Space Mono", monospace;
      font-size: 80px;
      line-height: 1;
      letter-spacing: -0.02em;
      color: var(--text-display);
    }
    .nd-direction-speed-unit {
      font-family: "Space Mono", monospace;
      font-size: 11px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--text-secondary);
      margin-bottom: var(--space-sm);
    }
    .nd-direction-level {
      font-family: "Space Grotesk", system-ui;
      font-size: 22px;
      font-weight: 400;
      color: var(--text-display);
    }
    .nd-direction-bar-wrap {
      height: 3px;
      background: var(--border-visible);
      margin-top: var(--space-md);
      overflow: hidden;
    }
    .nd-direction-bar-fill {
      height: 100%;
      width: 0%;
      transition: width 0.7s ease, background 0.7s ease;
    }
    .nd-direction-sensors {
      font-family: "Space Mono", monospace;
      font-size: 10px;
      color: var(--text-disabled);
      margin-top: var(--space-sm);
      letter-spacing: 0.04em;
    }

    /* ---- Theme toggle ---- */
    .nd-theme-toggle {
      margin-top: var(--space-sm);
      font-family: "Space Mono", monospace;
      font-size: 10px;
      letter-spacing: 0.1em;
      padding: 6px 12px;
      background: var(--surface);
      color: var(--text-secondary);
      border: 1px solid var(--border-visible);
      cursor: pointer;
      transition: color 150ms, border-color 150ms, background 150ms;
    }
    .nd-theme-toggle:hover {
      color: var(--text-display);
      border-color: var(--text-primary);
    }

    /* ---- Responsive ---- */
    @media (max-width: 800px) {
      .nd-hero { grid-template-columns: 1fr; gap: var(--space-lg); }
      .nd-hero-right { text-align: left; align-items: flex-start; }
      .nd-display { font-size: 72px; }
      .nd-metrics { grid-template-columns: 1fr 1fr !important; }
      .nd-two-col { grid-template-columns: 1fr; }
      .nd-camera-grid { grid-template-columns: 1fr; }
      #nd-map { height: 400px !important; }
      #nd-map-se30 { height: 360px !important; }
      .nd-direction-speed { font-size: 64px; }
    }
    @media (max-width: 520px) {
      .nd-shell { padding: var(--space-md) var(--space-sm) var(--space-xl); }
      .nd-header { flex-direction: column; gap: var(--space-sm); }
      .nd-header-right { text-align: left; }
      .nd-display { font-size: 52px; }
      .nd-metrics { grid-template-columns: 1fr 1fr !important; }
      .nd-metric-value { font-size: 24px; }
      .nd-section-body { padding: var(--space-sm); }
      .nd-hero { margin-bottom: var(--space-xl); padding-bottom: var(--space-xl); }
      .nd-hero-score { gap: var(--space-sm); }
      .nd-directions { grid-template-columns: 1fr; }
      .nd-direction-speed { font-size: 72px; }
      .nd-direction-card { padding: var(--space-lg) var(--space-md); }
      #nd-map { height: 300px !important; }
      #nd-map-se30 { height: 280px !important; }
      .nd-level-badge { font-size: 22px; }
      .nd-footer { flex-direction: column; gap: var(--space-sm); }
      .nd-trend-legend { gap: var(--space-sm); padding: var(--space-sm); }
      .nd-vms-display { font-size: 11px; padding: var(--space-sm); }
      .nd-vms-item { padding: var(--space-md); }
      .nd-list-item { padding: var(--space-md); }
      .nd-section-header { padding: var(--space-sm) var(--space-md); }
      .nd-tab { padding: 10px 8px; font-size: 10px; letter-spacing: 0.02em; }
    }

    /* ============================================================
       TAB VISTA — nuevo diseño (Inter + JetBrains Mono)
    ============================================================ */
    #tab-nuevo {
      --nv-bg: oklch(0.17 0.006 260);
      --nv-surface: oklch(0.205 0.008 260);
      --nv-surface-2: oklch(0.235 0.009 260);
      --nv-border: oklch(0.28 0.01 260);
      --nv-border-strong: oklch(0.35 0.012 260);
      --nv-text: oklch(0.97 0.003 260);
      --nv-text-2: oklch(0.72 0.01 260);
      --nv-text-3: oklch(0.55 0.01 260);
      --nv-accent: oklch(0.7 0.14 255);
      --nv-ok: oklch(0.72 0.15 155);
      --nv-warn: oklch(0.8 0.16 85);
      --nv-alert: oklch(0.72 0.18 45);
      --nv-danger: oklch(0.68 0.2 25);
      --nv-shadow: 0 1px 2px rgba(0,0,0,0.3), 0 1px 8px rgba(0,0,0,0.2);
      --nv-shadow-lg: 0 2px 8px rgba(0,0,0,0.3), 0 12px 32px rgba(0,0,0,0.4);
      --nv-radius: 14px;
      --nv-led: #FFB300;
      font-family: 'Inter', system-ui, sans-serif;
      -webkit-font-smoothing: antialiased;
      letter-spacing: -0.01em;
      padding-bottom: 48px;
    }
    [data-theme="light"] #tab-nuevo {
      --nv-bg: oklch(0.99 0.003 80);
      --nv-surface: oklch(1 0 0);
      --nv-surface-2: oklch(0.975 0.003 80);
      --nv-border: oklch(0.92 0.004 80);
      --nv-border-strong: oklch(0.85 0.005 80);
      --nv-text: oklch(0.2 0.01 260);
      --nv-text-2: oklch(0.45 0.01 260);
      --nv-text-3: oklch(0.62 0.01 260);
      --nv-accent: oklch(0.55 0.15 255);
      --nv-ok: oklch(0.62 0.14 155);
      --nv-warn: oklch(0.72 0.15 85);
      --nv-alert: oklch(0.65 0.18 45);
      --nv-danger: oklch(0.58 0.2 25);
      --nv-shadow: 0 1px 2px oklch(0.2 0.01 260 / 0.04), 0 1px 8px oklch(0.2 0.01 260 / 0.03);
      --nv-shadow-lg: 0 2px 8px oklch(0.2 0.01 260 / 0.06), 0 12px 32px oklch(0.2 0.01 260 / 0.06);
    }
    #tab-nuevo .nv-mono { font-family: 'JetBrains Mono', ui-monospace, monospace; letter-spacing: -0.02em; }
    /* Hero */
    #tab-nuevo .nv-hero { background: var(--nv-surface); border: 1px solid var(--nv-border); border-radius: 20px; padding: 36px 40px 32px; box-shadow: var(--nv-shadow); margin-bottom: 32px; }
    @media (max-width: 720px) { #tab-nuevo .nv-hero { padding: 24px 22px; border-radius: 16px; } }
    #tab-nuevo .nv-hero-label { display: flex; align-items: center; gap: 8px; font-size: 12px; font-weight: 500; color: var(--nv-text-3); text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 14px; }
    #tab-nuevo .nv-hero-label-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--nv-text-3); }
    #tab-nuevo .nv-hero-grid { display: grid; grid-template-columns: 1.4fr 1fr; gap: 36px; align-items: center; }
    @media (max-width: 820px) { #tab-nuevo .nv-hero-grid { grid-template-columns: 1fr; gap: 28px; } }
    #tab-nuevo .nv-verdict { font-size: clamp(38px, 6vw, 68px); font-weight: 700; line-height: 0.95; letter-spacing: -0.04em; margin: 0 0 10px; }
    #tab-nuevo .nv-verdict-sub { font-size: 16px; color: var(--nv-text-2); line-height: 1.45; max-width: 38ch; }
    #tab-nuevo .nv-score-row { display: flex; align-items: baseline; gap: 18px; margin-top: 20px; }
    #tab-nuevo .nv-score-num { font-family: 'JetBrains Mono', monospace; font-size: 32px; font-weight: 600; letter-spacing: -0.04em; }
    #tab-nuevo .nv-score-meta { font-size: 13px; color: var(--nv-text-3); line-height: 1.4; }
    #tab-nuevo .nv-level-chip { display: inline-flex; align-items: center; padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; background: color-mix(in oklch, var(--nv-chip-color, var(--nv-ok)) 14%, transparent); color: var(--nv-chip-color, var(--nv-ok)); border: 1px solid color-mix(in oklch, var(--nv-chip-color, var(--nv-ok)) 28%, transparent); }
    /* Reversible */
    #tab-nuevo .nv-reversible { background: var(--nv-surface-2); border: 1px solid var(--nv-border); border-radius: 16px; padding: 24px; }
    #tab-nuevo .nv-rev-label { font-size: 11px; font-weight: 600; color: var(--nv-text-3); text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 14px; }
    #tab-nuevo .nv-rev-arrow-wrap { display: flex; align-items: center; gap: 16px; margin-bottom: 18px; }
    #tab-nuevo .nv-rev-arrow { width: 48px; height: 48px; border-radius: 50%; background: var(--nv-text); color: var(--nv-bg); display: grid; place-items: center; font-size: 22px; font-weight: 700; flex-shrink: 0; transition: transform .4s cubic-bezier(.5,0,.2,1); }
    #tab-nuevo .nv-rev-dir { font-size: 22px; font-weight: 600; letter-spacing: -0.02em; line-height: 1.15; }
    #tab-nuevo .nv-rev-dir-sub { font-size: 13px; color: var(--nv-text-2); margin-top: 2px; }
    #tab-nuevo .nv-conf-track { height: 4px; flex: 1; background: var(--nv-border); border-radius: 999px; overflow: hidden; }
    #tab-nuevo .nv-conf-fill { height: 100%; background: var(--nv-accent); border-radius: 999px; transition: width .6s; }
    #tab-nuevo .nv-rev-confidence { display: flex; align-items: center; gap: 10px; font-size: 12px; color: var(--nv-text-2); }
    /* Sections / cards */
    #tab-nuevo .nv-section { margin-top: 28px; }
    #tab-nuevo .nv-section-head { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 14px; gap: 12px; }
    #tab-nuevo .nv-section-title { font-size: 13px; font-weight: 600; color: var(--nv-text-3); text-transform: uppercase; letter-spacing: 0.1em; }
    #tab-nuevo .nv-section-aside { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--nv-text-3); }
    #tab-nuevo .nv-grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
    @media (max-width: 720px) { #tab-nuevo .nv-grid-2 { grid-template-columns: 1fr; } }
    #tab-nuevo .nv-card { background: var(--nv-surface); border: 1px solid var(--nv-border); border-radius: var(--nv-radius); padding: 22px; }
    /* Direction cards */
    #tab-nuevo .nv-dir-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
    #tab-nuevo .nv-dir-name { font-size: 12px; font-weight: 600; color: var(--nv-text-3); text-transform: uppercase; letter-spacing: 0.1em; }
    #tab-nuevo .nv-dir-city { font-size: 18px; font-weight: 600; letter-spacing: -0.02em; margin-top: 4px; }
    #tab-nuevo .nv-dir-badge { font-size: 10px; font-weight: 600; padding: 3px 8px; border-radius: 999px; background: var(--nv-accent); color: white; letter-spacing: 0.05em; text-transform: uppercase; }
    #tab-nuevo .nv-dir-speed { font-family: 'JetBrains Mono', monospace; font-size: 38px; font-weight: 600; letter-spacing: -0.04em; line-height: 1; margin-top: 6px; }
    #tab-nuevo .nv-dir-speed-unit { font-size: 14px; color: var(--nv-text-3); font-weight: 500; margin-left: 6px; letter-spacing: 0; }
    #tab-nuevo .nv-dir-meta { display: flex; gap: 18px; margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--nv-border); font-size: 12px; }
    #tab-nuevo .nv-dir-meta .nv-k { color: var(--nv-text-3); }
    #tab-nuevo .nv-dir-meta .nv-v { font-family: 'JetBrains Mono', monospace; color: var(--nv-text); margin-left: 4px; font-weight: 500; }
    #tab-nuevo .nv-speedbar { height: 4px; background: var(--nv-border); border-radius: 999px; margin-top: 12px; overflow: hidden; }
    #tab-nuevo .nv-speedbar-fill { height: 100%; border-radius: 999px; transition: width .8s cubic-bezier(.2,.8,.2,1); }
    /* Scene */
    #tab-nuevo .nv-scene-wrap { position: relative; aspect-ratio: 16 / 5.5; min-height: 180px; width: 100%; overflow: hidden; }
    @media (max-width: 600px) { #tab-nuevo .nv-scene-wrap { aspect-ratio: 16 / 8; } }
    #tab-nuevo #nv-sceneSvg { width: 100%; height: 100%; display: block; }
    #tab-nuevo .nv-scene-bar { display: flex; gap: 10px; padding: 10px 22px 18px; font-size: 11px; color: var(--nv-text-3); font-family: 'JetBrains Mono', monospace; border-top: 1px solid var(--nv-border); justify-content: space-between; flex-wrap: wrap; }
    #tab-nuevo .nv-scene-bar b { color: var(--nv-text); font-weight: 600; }
    /* Chart */
    #tab-nuevo .nv-chart-container { position: relative; height: 220px; width: 100%; }
    #tab-nuevo .nv-speed-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    @media (max-width: 720px) { #tab-nuevo .nv-speed-grid { grid-template-columns: 1fr; } }
    #tab-nuevo #nv-chartSvg { width: 100%; height: 100%; display: block; overflow: visible; }
    #tab-nuevo .nv-chart-legend { display: flex; gap: 18px; font-size: 11px; color: var(--nv-text-3); margin-top: 12px; flex-wrap: wrap; }
    #tab-nuevo .nv-chart-legend span { display: inline-flex; align-items: center; gap: 6px; }
    #tab-nuevo .nv-chart-legend i { width: 10px; height: 2px; border-radius: 2px; display: inline-block; }
    #tab-nuevo .nv-tooltip { position: absolute; pointer-events: none; opacity: 0; transition: opacity .15s; background: var(--nv-text); color: var(--nv-bg); padding: 8px 10px; border-radius: 8px; font-size: 12px; white-space: nowrap; transform: translate(-50%, -110%); z-index: 10; }
    /* VMS */
    #tab-nuevo .nv-vms-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 14px; }
    @media (max-width: 820px) { #tab-nuevo .nv-vms-grid { grid-template-columns: 1fr; } }
    #tab-nuevo .nv-vms { background: #0a0a0a; border: 1px solid #222; border-radius: 12px; padding: 20px 18px; }
    #tab-nuevo .nv-vms-meta { display: flex; justify-content: space-between; font-family: 'JetBrains Mono', monospace; font-size: 10px; color: #555; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 12px; }
    #tab-nuevo .nv-vms-screen { background: #000; border-radius: 6px; padding: 14px 16px; min-height: 90px; font-family: 'JetBrains Mono', monospace; font-weight: 600; font-size: 15px; letter-spacing: 0.12em; color: var(--nv-led); text-shadow: 0 0 6px #ffb30099, 0 0 14px #ffb30055; line-height: 1.5; white-space: pre-line; display: flex; align-items: center; }
    #tab-nuevo .nv-vms-screen.empty { color: #333; text-shadow: none; font-weight: 400; font-size: 12px; letter-spacing: 0.05em; }
    #tab-nuevo .nv-vms-footer { margin-top: 10px; font-family: 'JetBrains Mono', monospace; font-size: 10px; color: #666; display: flex; justify-content: space-between; }
    /* Incidents */
    #tab-nuevo .nv-incident-list { display: flex; flex-direction: column; gap: 10px; }
    #tab-nuevo .nv-incident { display: flex; gap: 14px; padding: 14px 16px; background: var(--nv-surface); border: 1px solid var(--nv-border); border-radius: 12px; align-items: flex-start; }
    #tab-nuevo .nv-inc-ic { width: 32px; height: 32px; border-radius: 8px; flex-shrink: 0; display: grid; place-items: center; background: color-mix(in oklch, var(--nv-inc-color, var(--nv-warn)) 15%, transparent); color: var(--nv-inc-color, var(--nv-warn)); }
    #tab-nuevo .nv-inc-main { flex: 1; min-width: 0; }
    #tab-nuevo .nv-inc-title { font-size: 14px; font-weight: 600; line-height: 1.3; }
    #tab-nuevo .nv-inc-meta { display: flex; gap: 12px; font-size: 12px; color: var(--nv-text-3); margin-top: 4px; flex-wrap: wrap; }
    #tab-nuevo .nv-inc-severity { font-size: 10px; font-weight: 600; padding: 2px 8px; border-radius: 999px; text-transform: uppercase; letter-spacing: 0.08em; background: color-mix(in oklch, var(--nv-inc-color, var(--nv-warn)) 15%, transparent); color: var(--nv-inc-color, var(--nv-warn)); }
    #tab-nuevo .nv-empty { padding: 32px; text-align: center; color: var(--nv-text-3); font-size: 13px; }
    /* Report */
    #tab-nuevo .nv-report-actions { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin-top: 16px; }
    @media (max-width: 560px) { #tab-nuevo .nv-report-actions { grid-template-columns: 1fr; } }
    #tab-nuevo .nv-report-btn { padding: 14px 16px; border-radius: 10px; border: 1px solid var(--nv-border); background: var(--nv-surface); font-family: 'Inter', system-ui, sans-serif; cursor: pointer; display: flex; flex-direction: column; gap: 4px; align-items: flex-start; transition: all .15s; color: var(--nv-text); }
    #tab-nuevo .nv-report-btn:hover { background: var(--nv-surface-2); border-color: var(--nv-border-strong); transform: translateY(-1px); }
    #tab-nuevo .nv-report-btn .nv-dir { font-size: 14px; font-weight: 600; }
    #tab-nuevo .nv-report-btn .nv-hint { font-size: 11px; color: var(--nv-text-3); }
    #tab-nuevo .nv-report-btn.success { background: color-mix(in oklch, var(--nv-ok) 12%, transparent); border-color: var(--nv-ok); }
    /* Range tabs */
    #tab-nuevo .nv-tabs { display: flex; gap: 2px; padding: 3px; background: var(--nv-surface-2); border: 1px solid var(--nv-border); border-radius: 10px; width: fit-content; }
    #tab-nuevo .nv-tab-btn { padding: 7px 14px; font-size: 13px; font-weight: 500; color: var(--nv-text-2); background: transparent; border: none; border-radius: 7px; cursor: pointer; transition: all .15s; font-family: 'Inter', system-ui, sans-serif; }
    #tab-nuevo .nv-tab-btn:hover { color: var(--nv-text); }
    #tab-nuevo .nv-tab-btn.active { background: var(--nv-surface); color: var(--nv-text); box-shadow: var(--nv-shadow); }
  </style>
</head>
<body>
  <div class="nd-shell">

    <!-- Header -->
    <header class="nd-header">
      <div>
        <div class="nd-eyebrow">Monitor Operativo · SE-30 km 10–12 · Ambos sentidos</div>
        <div class="nd-header-title">5Centenario</div>
      </div>
      <div class="nd-header-right">
        <div class="nd-status-indicator">
          <span class="nd-status-dot"></span>
          <span>Activo</span>
        </div>
        <div class="nd-eyebrow" id="generatedAt" style="margin-top:8px;">Sin datos</div>
        <button id="themeToggle" class="nd-theme-toggle" type="button"
                onclick="cycleTheme()" title="Cambiar tema (auto / claro / oscuro)">
          <span id="themeToggleIcon">AUTO</span>
        </button>
      </div>
    </header>

    <!-- Tab navigation -->
    <nav class="nd-tab-nav">
      <button class="nd-tab active" id="btn-estado" onclick="showTab('estado')">[ ESTADO ]</button>
      <button class="nd-tab" id="btn-velocidades" onclick="showTab('velocidades')">VELOCIDADES</button>
      <button class="nd-tab" id="btn-mapa" onclick="showTab('mapa')">MAPA</button>
      <button class="nd-tab" id="btn-se30" onclick="showTab('se30')">DETALLE</button>
      <button class="nd-tab" id="btn-historico" onclick="showTab('historico')">HIST&#211;RICO</button>
      <button class="nd-tab" id="btn-nuevo" onclick="showTab('nuevo')">VISTA &#9733;</button>
    </nav>

    <div id="tab-estado">

    <!-- Sentidos: tarjetas de intensidad por dirección -->
    <section class="nd-directions">
      <div class="nd-direction-card">
        <div class="nd-direction-heading">
          <span class="nd-direction-arrow">←</span>
          <span>Sentido Huelva</span>
        </div>
        <div class="nd-direction-speed" id="dir-pos-speed">--</div>
        <div class="nd-direction-speed-unit">km/h</div>
        <div class="nd-direction-level" id="dir-pos-level">Sin datos</div>
        <div class="nd-direction-bar-wrap"><div class="nd-direction-bar-fill" id="dir-pos-bar"></div></div>
        <div class="nd-direction-sensors" id="dir-pos-sensors"></div>
      </div>
      <div class="nd-direction-card">
        <div class="nd-direction-heading">
          <span class="nd-direction-arrow">→</span>
          <span>Sentido Cádiz</span>
        </div>
        <div class="nd-direction-speed" id="dir-neg-speed">--</div>
        <div class="nd-direction-speed-unit">km/h</div>
        <div class="nd-direction-level" id="dir-neg-level">Sin datos</div>
        <div class="nd-direction-bar-wrap"><div class="nd-direction-bar-fill" id="dir-neg-bar"></div></div>
        <div class="nd-direction-sensors" id="dir-neg-sensors"></div>
      </div>
    </section>

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
        <div id="reversibleObserved" class="nd-metric-note" style="margin-top:4px;"></div>
      </article>
      <article class="nd-metric-card">
        <div class="nd-label">Evidencia visible</div>
        <div id="evidenceCount" class="nd-metric-value">0</div>
        <div id="countsLine" class="nd-metric-note">Paneles 0 · Incidencias 0 · Cámaras 0</div>
      </article>
    </section>

    <!-- Reporte manual del reversible -->
    <section class="nd-section" style="margin-top:var(--space-lg);">
      <div class="nd-section-header">
        <span class="nd-label">Observaci&#243;n directa</span>
        <span class="nd-meta">&#191;C&#243;mo est&#225; el carril reversible ahora?</span>
      </div>
      <div class="nd-section-body" style="padding:var(--space-md) var(--space-lg);">
        <div style="display:flex;gap:var(--space-md);flex-wrap:wrap;align-items:center;">
          <button id="btn-report-huelva" class="nd-report-btn" style="background:#4A9E5C22;border:1px solid #4A9E5C;color:#4A9E5C;" onclick="reportReversible('positive')">&#8592; HUELVA</button>
          <button id="btn-report-cadiz"  class="nd-report-btn" style="background:#D4A84322;border:1px solid #D4A843;color:#D4A843;" onclick="reportReversible('negative')">&#8594; C&#193;DIZ</button>
          <button id="btn-report-none"   class="nd-report-btn" style="background:#55555522;border:1px solid #555555;color:#888888;" onclick="reportReversible('none')">SIN REVERSIBLE</button>
        </div>
        <input id="reportNote" type="text" maxlength="280" placeholder="Nota opcional (duda, transici&#243;n, contexto...)" style="margin-top:var(--space-sm);width:100%;padding:6px 8px;font-family:'Space Mono',monospace;font-size:11px;background:transparent;border:1px solid #222;color:var(--text-display);box-sizing:border-box;" />
        <div id="reportStatus" style="margin-top:var(--space-sm);font-family:'Space Mono',monospace;font-size:10px;color:#888;min-height:14px;"></div>
        <div id="recentReports" style="margin-top:var(--space-md);"></div>
      </div>
    </section>

    <!-- Pulso reciente — dos gráficos apilados por sentido -->
    <section class="nd-section">
      <div class="nd-section-header">
        <span class="nd-label">Pulso reciente</span>
        <span class="nd-meta">&#218;ltimas 6 h · por sentido</span>
      </div>
      <div class="nd-section-body" style="padding:0;">
        <div style="padding:var(--space-sm) var(--space-lg) 2px;font-family:'Space Mono',monospace;font-size:9px;letter-spacing:0.08em;color:#4A9E5C;">&#8592; HUELVA</div>
        <div class="nd-bars-wrap">
          <canvas id="pulso-huelva" style="display:block;width:100%;background:var(--canvas-bg);"></canvas>
        </div>
        <div style="padding:var(--space-sm) var(--space-lg) 2px;font-family:'Space Mono',monospace;font-size:9px;letter-spacing:0.08em;color:#D4A843;margin-top:var(--space-sm);">&#8594; C&#193;DIZ</div>
        <div class="nd-bars-wrap">
          <canvas id="pulso-cadiz" style="display:block;width:100%;background:var(--canvas-bg);"></canvas>
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
          <div class="nd-legend-color" style="background:var(--accent); opacity:0.7;"></div>Congesti&#243;n fuerte
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

      <!-- Dos sentidos: velocidad actual + retardo -->
      <section class="nd-metrics" style="margin-top:0;">
        <article class="nd-metric-card">
          <div class="nd-label">&#8592; Sentido Huelva · km 10&#8211;12</div>
          <div id="spd-huelva" class="nd-metric-value">-</div>
          <div id="spd-huelva-delay" class="nd-metric-note">km/h</div>
          <div id="spd-huelva-free" class="nd-metric-note" style="margin-top:2px;"></div>
        </article>
        <article class="nd-metric-card">
          <div class="nd-label">&#8594; Sentido C&#225;diz · km 12&#8211;10</div>
          <div id="spd-cadiz" class="nd-metric-value">-</div>
          <div id="spd-cadiz-delay" class="nd-metric-note">km/h</div>
          <div id="spd-cadiz-free" class="nd-metric-note" style="margin-top:2px;"></div>
        </article>
        <article class="nd-metric-card">
          <div class="nd-label">Fuente · Actualizaci&#243;n</div>
          <div class="nd-metric-value" style="font-size:20px;">TomTom</div>
          <div id="spd-collected-at" class="nd-metric-note">-</div>
          <div class="nd-metric-note" style="margin-top:2px;">Routing API · l&#237;mite 60 km/h</div>
        </article>
      </section>

      <!-- Speed history charts — uno por sentido -->
      <div class="nd-two-col" style="gap:0;">
        <section class="nd-section" style="border-right:1px solid var(--border);margin-bottom:0;">
          <div class="nd-section-header">
            <span class="nd-label" style="color:#4A9E5C;">&#8594; Huelva · Pulso reciente</span>
            <span class="nd-meta" id="spd-sensor-count">-</span>
          </div>
          <div class="nd-section-body" style="padding:0;">
            <canvas id="spd-chart-huelva" style="display:block;width:100%;background:var(--canvas-bg);"></canvas>
          </div>
        </section>
        <section class="nd-section" style="margin-bottom:0;">
          <div class="nd-section-header">
            <span class="nd-label" style="color:#D4A843;">&#8592; C&#225;diz · Pulso reciente</span>
            <span class="nd-meta">&#218;ltimas 6 h</span>
          </div>
          <div class="nd-section-body" style="padding:0;">
            <canvas id="spd-chart-cadiz" style="display:block;width:100%;background:var(--canvas-bg);"></canvas>
          </div>
        </section>
      </div>

    </div><!-- /tab-velocidades -->

    </div><!-- /tab-velocidades cierre para añadir mapa antes del footer -->

    <!-- Mapa TomTom sensors -->
    <div id="tab-mapa" style="display:none;">

      <section class="nd-section" style="margin-bottom:var(--space-2xl);">
        <div class="nd-section-header">
          <span class="nd-label">SE-30 km 10–12 · Sentido Huelva · Sensores TomTom</span>
          <span class="nd-meta" id="map-status">Cargando mapa...</span>
        </div>
        <div id="nd-map" style="height:560px;"></div>
      </section>

      <!-- Tabla resumen bajo el mapa -->
      <section class="nd-metrics" style="margin-bottom:0;">
        <article class="nd-metric-card">
          <div class="nd-label">&larr; Sentido Huelva · km 10&ndash;12</div>
          <div class="nd-metric-value" id="map-spd-huelva">-</div>
          <div class="nd-metric-note" id="map-delay-huelva">TomTom Routing</div>
        </article>
        <article class="nd-metric-card">
          <div class="nd-label">&rarr; Sentido C&aacute;diz · km 12&ndash;10</div>
          <div class="nd-metric-value" id="map-spd-cadiz">-</div>
          <div class="nd-metric-note" id="map-delay-cadiz">TomTom Routing</div>
        </article>
      </section>

    </div><!-- /tab-mapa -->

    <!-- SE-30 Completa -->
    <div id="tab-se30" style="display:none;">

      <!-- Loading / error banner -->
      <div id="se30-status" style="padding:var(--space-md) var(--space-lg);font-family:'Space Mono',monospace;font-size:11px;letter-spacing:0.06em;color:var(--text-secondary);border:1px solid var(--border);background:var(--surface);margin-bottom:var(--space-2xl);">
        Pulsa la pestaña para cargar datos en tiempo real de la SE-30...
      </div>

      <!-- Mapa km 10-12 sentido Huelva -->
      <section class="nd-section" style="margin-bottom:var(--space-2xl);">
        <div class="nd-section-header">
          <span class="nd-label">Mapa km 10–12 · Sentido Huelva · Sensores en tiempo real</span>
          <span class="nd-meta" id="se30-map-status">Esperando datos...</span>
        </div>
        <div id="nd-map-se30" style="height:520px;background:var(--black);"></div>
        <div class="nd-trend-legend" style="padding:var(--space-md) var(--space-lg);">
          <div class="nd-legend-item">
            <div class="nd-legend-color" style="background:var(--success);"></div>TomTom &gt;55 km/h
          </div>
          <div class="nd-legend-item">
            <div class="nd-legend-color" style="background:var(--warning);"></div>TomTom 30-55 km/h
          </div>
          <div class="nd-legend-item">
            <div class="nd-legend-color" style="background:var(--accent);"></div>TomTom &lt;30 km/h
          </div>
        </div>
      </section>

      <!-- Summary metrics -->
      <section class="nd-metrics" style="margin-bottom:var(--space-2xl);" id="se30-metrics">
        <article class="nd-metric-card">
          <div class="nd-label">Paneles VMS</div>
          <div id="se30-cnt-panels" class="nd-metric-value">-</div>
          <div class="nd-metric-note">DGT DATEX2</div>
        </article>
        <article class="nd-metric-card">
          <div class="nd-label">Incidencias</div>
          <div id="se30-cnt-incidents" class="nd-metric-value">-</div>
          <div class="nd-metric-note">DGT DATEX2 v3.6</div>
        </article>
        <article class="nd-metric-card">
          <div class="nd-label">Detectores DGT</div>
          <div id="se30-cnt-detectors" class="nd-metric-value">-</div>
          <div class="nd-metric-note">Flujo · velocidad</div>
        </article>
        <article class="nd-metric-card">
          <div class="nd-label">Sensores TomTom</div>
          <div id="se30-cnt-tomtom" class="nd-metric-value">-</div>
          <div class="nd-metric-note">Probe data GPS</div>
        </article>
      </section>

      <!-- Paneles VMS -->
      <section class="nd-section" style="margin-bottom:var(--space-2xl);">
        <div class="nd-section-header">
          <span class="nd-label">Paneles VMS activos · km 10–12</span>
          <span class="nd-meta">Ordenados por km · sentido Huelva</span>
        </div>
        <div id="se30-panels">
          <div class="nd-empty">[Sin datos cargados]</div>
        </div>
      </section>

      <!-- Detectores DGT -->
      <section class="nd-section" style="margin-bottom:var(--space-2xl);">
        <div class="nd-section-header">
          <span class="nd-label">Detectores DGT · km 10–12 · Sentido Huelva</span>
          <span class="nd-meta">Flujo · velocidad media · ocupación</span>
        </div>
        <div id="se30-detectors">
          <div class="nd-empty">[Sin datos cargados]</div>
        </div>
      </section>

      <!-- Incidencias -->
      <section class="nd-section" style="margin-bottom:var(--space-2xl);">
        <div class="nd-section-header">
          <span class="nd-label">Incidencias · km 10–12 · Sentido Huelva</span>
          <span class="nd-meta">Filtradas por tramo y bbox</span>
        </div>
        <div id="se30-incidents">
          <div class="nd-empty">[Sin datos cargados]</div>
        </div>
      </section>

      <!-- TomTom -->
      <section class="nd-section" style="margin-bottom:var(--space-2xl);">
        <div class="nd-section-header">
          <span class="nd-label">TomTom Flow · Puntos de medición</span>
          <span class="nd-meta">Último dato almacenado</span>
        </div>
        <div id="se30-tomtom">
          <div class="nd-empty">[Sin datos cargados]</div>
        </div>
      </section>

    </div><!-- /tab-se30 -->

    <!-- Histórico de velocidades diarias -->
    <div id="tab-historico" style="display:none;">
      <section class="nd-section" style="margin-bottom:var(--space-2xl);">
        <div class="nd-section-header">
          <span class="nd-label">Velocidades diarias · M&#237;nima y m&#225;xima por sentido</span>
          <span class="nd-meta" id="hist-status">Cargando...</span>
        </div>
        <div class="nd-section-body" style="padding:0;overflow-x:auto;">
          <table id="hist-table" style="width:100%;border-collapse:collapse;font-family:'Space Mono',monospace;font-size:12px;">
            <thead>
              <tr style="border-bottom:2px solid var(--border-visible);">
                <th style="padding:10px 16px;text-align:left;color:var(--text-secondary);font-weight:400;letter-spacing:0.06em;white-space:nowrap;">FECHA</th>
                <th style="padding:10px 16px;text-align:right;color:#4A9E5C;font-weight:400;letter-spacing:0.06em;white-space:nowrap;">&#8592; HUELVA M&#205;N</th>
                <th style="padding:10px 16px;text-align:right;color:#4A9E5C;font-weight:400;letter-spacing:0.06em;white-space:nowrap;">&#8592; HUELVA M&#193;X</th>
                <th style="padding:10px 16px;text-align:right;color:#4A9E5C;font-weight:400;letter-spacing:0.06em;white-space:nowrap;">&#8592; HUELVA MEDIA</th>
                <th style="padding:10px 16px;text-align:right;color:#D4A843;font-weight:400;letter-spacing:0.06em;white-space:nowrap;">&#8594; C&#193;DIZ M&#205;N</th>
                <th style="padding:10px 16px;text-align:right;color:#D4A843;font-weight:400;letter-spacing:0.06em;white-space:nowrap;">&#8594; C&#193;DIZ M&#193;X</th>
                <th style="padding:10px 16px;text-align:right;color:#D4A843;font-weight:400;letter-spacing:0.06em;white-space:nowrap;">&#8594; C&#193;DIZ MEDIA</th>
                <th style="padding:10px 16px;text-align:right;color:var(--text-secondary);font-weight:400;letter-spacing:0.06em;white-space:nowrap;">MUESTRAS</th>
              </tr>
            </thead>
            <tbody id="hist-tbody">
              <tr><td colspan="8" style="padding:24px 16px;text-align:center;color:var(--text-secondary);">Cargando datos...</td></tr>
            </tbody>
          </table>
        </div>
        <div style="padding:10px 16px;border-top:1px solid var(--border);">
          <span class="nd-meta">Velocidades en km/h · Las muestras son el total de ambos sentidos · El d&#237;a en curso se actualiza en tiempo real; los anteriores son definitivos</span>
        </div>
      </section>
    </div><!-- /tab-historico -->

    <!-- ===== TAB VISTA — nuevo diseño ===== -->
    <div id="tab-nuevo" style="display:none;">

      <!-- Hero -->
      <section class="nv-hero">
        <div class="nv-hero-label">
          <span class="nv-hero-label-dot" id="nv-verdictDot"></span>
          <span id="nv-verdictLabel">Estado actual</span>
        </div>
        <div class="nv-hero-grid">
          <div>
            <h2 class="nv-verdict" id="nv-verdict">Cargando&hellip;</h2>
            <p class="nv-verdict-sub" id="nv-verdictSub">Obteniendo datos del puente.</p>
            <div class="nv-score-row">
              <div class="nv-score-num" id="nv-scoreNum">&mdash;</div>
              <div class="nv-score-meta">
                <span class="nv-level-chip" id="nv-levelChip">&mdash;</span>
                <div style="margin-top:6px;">Puntuaci&#243;n de congestión · 0 = libre</div>
              </div>
            </div>
          </div>
          <div class="nv-reversible">
            <div class="nv-rev-label">Carril reversible</div>
            <div class="nv-rev-arrow-wrap">
              <div class="nv-rev-arrow" id="nv-revArrow">&mdash;</div>
              <div>
                <div class="nv-rev-dir" id="nv-revDir">Cargando&hellip;</div>
                <div class="nv-rev-dir-sub" id="nv-revSub"></div>
              </div>
            </div>
            <div class="nv-rev-confidence">
              <span class="nv-mono" id="nv-confLabel">&mdash;</span>
              <div class="nv-conf-track"><div class="nv-conf-fill" id="nv-confFill" style="width:0%"></div></div>
              <span style="flex-shrink:0">confianza</span>
            </div>
          </div>
        </div>
      </section>

      <!-- Animated bridge scene -->
      <section class="nv-section">
        <div class="nv-section-head">
          <div class="nv-section-title">El puente ahora</div>
          <div class="nv-section-aside" id="nv-sceneTempo">&mdash; km/h media</div>
        </div>
        <div class="nv-card" style="padding:0;overflow:hidden;">
          <div class="nv-scene-wrap">
            <canvas id="nv-sceneSvg" width="800" height="240"></canvas>
          </div>
          <div class="nv-scene-bar">
            <span>&larr; <b id="nv-sceneHuelvaCount">0</b> veh. sentido Huelva</span>
            <span>SE-30 &middot; km 10 &mdash;&mdash; km 12</span>
            <span><b id="nv-sceneCadizCount">0</b> veh. sentido C&aacute;diz &rarr;</span>
          </div>
        </div>
      </section>

      <!-- Speed cards -->
      <section class="nv-section">
        <div class="nv-section-head">
          <div class="nv-section-title">Velocidades por sentido</div>
          <div class="nv-section-aside">l&iacute;mite 60 km/h</div>
        </div>
        <div class="nv-grid-2">
          <div class="nv-card">
            <div class="nv-dir-head">
              <div>
                <div class="nv-dir-name">Sentido Huelva</div>
                <div class="nv-dir-city">&larr; Hacia Huelva</div>
              </div>
              <span class="nv-dir-badge" id="nv-badgeHuelva" style="display:none">Reversible</span>
            </div>
            <div><span class="nv-dir-speed" id="nv-speedHuelva">&mdash;</span><span class="nv-dir-speed-unit">km/h</span></div>
            <div class="nv-speedbar"><div class="nv-speedbar-fill" id="nv-barHuelva"></div></div>
            <div class="nv-dir-meta">
              <div><span class="nv-k">Libre</span><span class="nv-v" id="nv-freeHuelva">60</span></div>
              <div><span class="nv-k">Retardo</span><span class="nv-v" id="nv-delayHuelva">&mdash;</span></div>
              <div><span class="nv-k">km</span><span class="nv-v">10&rarr;12</span></div>
            </div>
          </div>
          <div class="nv-card">
            <div class="nv-dir-head">
              <div>
                <div class="nv-dir-name">Sentido C&aacute;diz</div>
                <div class="nv-dir-city">&rarr; Hacia C&aacute;diz</div>
              </div>
              <span class="nv-dir-badge" id="nv-badgeCadiz" style="display:none">Reversible</span>
            </div>
            <div><span class="nv-dir-speed" id="nv-speedCadiz">&mdash;</span><span class="nv-dir-speed-unit">km/h</span></div>
            <div class="nv-speedbar"><div class="nv-speedbar-fill" id="nv-barCadiz"></div></div>
            <div class="nv-dir-meta">
              <div><span class="nv-k">Libre</span><span class="nv-v" id="nv-freeCadiz">60</span></div>
              <div><span class="nv-k">Retardo</span><span class="nv-v" id="nv-delayCadiz">&mdash;</span></div>
              <div><span class="nv-k">km</span><span class="nv-v">12&rarr;10</span></div>
            </div>
          </div>
        </div>
      </section>

      <!-- Histórico de velocidad por sentido -->
      <section class="nv-section">
        <div class="nv-section-head">
          <div class="nv-section-title">Histórico de velocidad por sentido</div>
          <div class="nv-tabs" id="nv-rangeTabs">
            <button class="nv-tab-btn" data-nv-range="1">1h</button>
            <button class="nv-tab-btn" data-nv-range="6">6h</button>
            <button class="nv-tab-btn active" data-nv-range="24">24h</button>
          </div>
        </div>
        <div class="nv-speed-grid">
          <div class="nv-card" style="padding:22px;">
            <div style="font-size:12px;font-weight:600;color:var(--nv-text-3);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:12px;">&larr; Sentido Huelva</div>
            <div class="nv-chart-container" id="nv-chartHuelvaContainer">
              <svg id="nv-chartHuelvaSvg" preserveAspectRatio="none"></svg>
            </div>
          </div>
          <div class="nv-card" style="padding:22px;">
            <div style="font-size:12px;font-weight:600;color:var(--nv-text-3);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:12px;">Sentido C&aacute;diz &rarr;</div>
            <div class="nv-chart-container" id="nv-chartCadizContainer">
              <svg id="nv-chartCadizSvg" preserveAspectRatio="none"></svg>
            </div>
          </div>
        </div>
        <div class="nv-chart-legend" style="margin-top:14px;">
          <span><i style="background:#4A9E5C"></i>&ge; 55 km/h fluido</span>
          <span><i style="background:#D4A843"></i>30&ndash;55 km/h denso</span>
          <span><i style="background:#D71921"></i>&lt; 30 km/h retenciones</span>
        </div>
      </section>

      <!-- VMS panels -->
      <section class="nv-section">
        <div class="nv-section-head">
          <div class="nv-section-title">Paneles DGT en el tramo</div>
          <div class="nv-section-aside">SE-30</div>
        </div>
        <div class="nv-vms-grid" id="nv-vmsGrid"></div>
      </section>

      <!-- DGT Camera -->
      <section class="nv-section">
        <div class="nv-section-head">
          <div class="nv-section-title">Cámara DGT · km 13,5</div>
          <div class="nv-section-aside">Sentido Cádiz · próxima al puente</div>
        </div>
        <div class="nv-card" style="padding:14px;">
          <div style="position:relative;width:100%;border-radius:10px;overflow:hidden;background:#000;">
            <img id="nv-dgtCam" alt="Cámara DGT SE-30 km 13,5"
                 src="https://infocar.dgt.es/etraffic/data/camaras/1337.jpg"
                 style="width:100%;height:auto;display:block;"
                 onerror="this.style.display='none';this.nextElementSibling.style.display='flex';">
            <div style="display:none;align-items:center;justify-content:center;min-height:200px;color:var(--nv-text-3);font-family:'JetBrains Mono',monospace;font-size:12px;">
              cámara temporalmente no disponible
            </div>
          </div>
          <div style="display:flex;justify-content:space-between;font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--nv-text-3);text-transform:uppercase;letter-spacing:0.08em;margin-top:10px;">
            <span>SE-30 · PK 13+5</span>
            <span id="nv-dgtCamTime">&mdash;</span>
          </div>
        </div>
      </section>

      <!-- Incidents -->
      <section class="nv-section">
        <div class="nv-section-head">
          <div class="nv-section-title">Incidencias activas</div>
          <div class="nv-section-aside" id="nv-incCount">&mdash;</div>
        </div>
        <div class="nv-incident-list" id="nv-incidentList"></div>
      </section>

      <!-- Report -->
      <section class="nv-section">
        <div class="nv-card" style="padding:22px;">
          <div style="font-size:15px;font-weight:600;">&iquest;Est&aacute;s viendo el puente ahora mismo?</div>
          <div style="font-size:13px;color:var(--nv-text-2);margin-top:4px;">Ayúdanos a afinar la predicción del carril reversible. Tu reporte pesa más cuanto más reciente sea.</div>
          <div class="nv-report-actions">
            <button class="nv-report-btn" id="nv-btn-report-huelva" onclick="nvReportReversible('positive')">
              <span class="nv-dir">&rarr; Sentido Huelva</span>
              <span class="nv-hint">reversible abierto hacia Huelva</span>
            </button>
            <button class="nv-report-btn" id="nv-btn-report-cadiz" onclick="nvReportReversible('negative')">
              <span class="nv-dir">&larr; Sentido C&aacute;diz</span>
              <span class="nv-hint">reversible abierto hacia Cádiz</span>
            </button>
            <button class="nv-report-btn" id="nv-btn-report-none" onclick="nvReportReversible('none')">
              <span class="nv-dir">&mdash; Sin reversible</span>
              <span class="nv-hint">ambos sentidos normales</span>
            </button>
          </div>
          <input id="nv-reportNote" type="text" maxlength="280" placeholder="Nota opcional (duda, transici&oacute;n, contexto...)" style="margin-top:10px;width:100%;padding:8px 10px;font-family:'JetBrains Mono',monospace;font-size:12px;background:transparent;border:1px solid var(--nv-border);color:var(--nv-text);box-sizing:border-box;border-radius:6px;" />
          <div id="nv-reportStatus" style="margin-top:10px;font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--nv-text-3);min-height:14px;"></div>
        </div>
      </section>

    </div><!-- /tab-nuevo -->

    <!-- Footer -->
    <footer class="nd-footer">
      <span class="nd-eyebrow">Actualización automática cada 60 s</span>
      <span class="nd-eyebrow">SE-30 km 10–12 · Ambos sentidos · Sevilla</span>
    </footer>

  </div>

  <script>
    const stateLabels = {
      fluido: "Muy fluido",
      denso: "Fluido",
      retenciones: "Denso",
      congestion_fuerte: "Retenciones",
      colapso: "Circulación muy lenta",
      indeterminado: "Indeterminado",
      positive: "Sentido Huelva",
      negative: "Sentido Sevilla"
    };

    const incidentLabels = {
      roadClosed:                          "Carretera cortada",
      laneClosures:                        "Cierre de carriles",
      narrowLanes:                         "Carriles estrechos",
      singleAlternateLineTraffic:          "Paso alternativo",
      doNotUseSpecifiedLanesOrCarriageways:"Carril prohibido",
      lanesDeviated:                       "Desvío de carriles",
      newRoadworksLayout:                  "Nueva disposición por obras",
      roadworks:                           "Obras en calzada",
      weightRestrictionInOperation:        "Restricción de vehículos pesados",
      accident:                            "Accidente",
      poorRoadConditions:                  "Mal estado de la vía",
      maintenanceWorks:                    "Trabajos de mantenimiento",
      roadMaintenance:                     "Mantenimiento vial",
      slowTraffic:                         "Tráfico lento",
      heavyTraffic:                        "Tráfico intenso",
      queuingTraffic:                      "Cola de tráfico",
      stationaryTraffic:                   "Tráfico parado",
      trafficCongestion:                   "Congestión",
      trafficCongestionHeavy:              "Congestión fuerte",
      abnormalTraffic:                     "Tráfico anormal",
      unprotectedAccidentArea:             "Zona de accidente",
      vehicleOnFire:                       "Vehículo en llamas",
      obstructionOnRoad:                   "Obstáculo en calzada",
      objectOnRoad:                        "Objeto en calzada",
      animalOnRoad:                        "Animal en calzada",
      brokenDownVehicle:                   "Vehículo averiado",
      vehicleAbandonedOnRoad:              "Vehículo abandonado",
      largeLorry:                          "Vehículo especial (camión)",
      overtakingBanned:                    "Prohibido adelantar",
      speedLimit:                          "Limitación de velocidad",
      fog:                                 "Niebla",
      ice:                                 "Hielo en calzada",
      rain:                                "Lluvia intensa",
      strongWinds:                         "Viento fuerte",
      blizzard:                            "Nevada",
      generalNetworkManagement:            "Gestión de red viaria",
      doNotEnter:                          "Prohibido el acceso",
    };
    function incidentLabel(type) {
      if (!type) return "Incidencia";
      return incidentLabels[type] || type.replace(/([A-Z])/g, ' $1').trim();
    }
    const severityLabels = {
      highest: "Muy alta", HIGHEST: "Muy alta",
      high:    "Alta",     HIGH:    "Alta",
      medium:  "Media",    MEDIUM:  "Media",
      low:     "Baja",     LOW:     "Baja",
      lowest:  "Mínima",   LOWEST:  "Mínima",
      unknown: "Desconocida", UNKNOWN: "Desconocida",
    };
    function severityLabel(sev) {
      return severityLabels[sev] || sev || "—";
    }

    const byId = (id) => document.getElementById(id);

    // ---- Theme management ----
    // Modos: "auto" | "light" | "dark". Se persiste en localStorage.
    // En modo "auto", se elige claro si el dispositivo prefiere tema claro
    // O si la hora local está entre 07:00 y 20:00. En otro caso, oscuro.
    const THEME_KEY = 'vcentenario_theme';
    function getThemeMode() {
      const m = localStorage.getItem(THEME_KEY);
      return (m === 'light' || m === 'dark') ? m : 'auto';
    }
    function resolveAutoTheme() {
      try {
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
          return 'light';
        }
      } catch (_) { /* noop */ }
      const h = new Date().getHours();
      return (h >= 7 && h < 20) ? 'light' : 'dark';
    }
    function effectiveTheme(mode) {
      return mode === 'auto' ? resolveAutoTheme() : mode;
    }
    function applyTheme() {
      const mode = getThemeMode();
      const eff  = effectiveTheme(mode);
      document.documentElement.setAttribute('data-theme', eff);
      const icon = byId('themeToggleIcon');
      if (icon) {
        icon.textContent = mode === 'auto' ? ('AUTO · ' + eff.toUpperCase())
                                           : mode.toUpperCase();
      }
      // Si los mapas ya están creados, actualizar las teselas al tema nuevo
      try {
        const tiles = (typeof cartoTilesForTheme === 'function') ? cartoTilesForTheme() : null;
        const lineColor = eff === 'light' ? '#000000' : '#FFFFFF';
        if (tiles && typeof ndMap !== 'undefined' && ndMap) {
          const src = ndMap.getSource('carto-base');
          if (src && src.setTiles) src.setTiles(tiles);
          try { if (ndMap.getLayer('tramo-line')) ndMap.setPaintProperty('tramo-line', 'line-color', lineColor); } catch (_) {}
        }
        if (tiles && typeof ndMapSE30 !== 'undefined' && ndMapSE30) {
          const src2 = ndMapSE30.getSource('carto-base');
          if (src2 && src2.setTiles) src2.setTiles(tiles);
        }
      } catch (_) { /* noop */ }
    }
    function cycleTheme() {
      const order = ['auto', 'light', 'dark'];
      const cur = getThemeMode();
      const next = order[(order.indexOf(cur) + 1) % order.length];
      localStorage.setItem(THEME_KEY, next);
      applyTheme();
      // Re-render para que los canvas recojan los nuevos colores
      if (typeof loadDashboard === 'function') {
        loadDashboard().catch(() => {});
      }
    }
    // Aplicar tema ANTES de cualquier render, antes de DOMContentLoaded.
    applyTheme();
    // Si el modo es auto, reaccionar a cambios del dispositivo
    try {
      const mq = window.matchMedia('(prefers-color-scheme: light)');
      const mqHandler = () => {
        if (getThemeMode() === 'auto') {
          applyTheme();
          if (typeof loadDashboard === 'function') loadDashboard().catch(() => {});
        }
      };
      if (mq.addEventListener) mq.addEventListener('change', mqHandler);
      else if (mq.addListener) mq.addListener(mqHandler);
    } catch (_) { /* noop */ }
    // Revaluar el modo "auto" cada 15 min para que siga la hora del día
    setInterval(() => {
      if (getThemeMode() === 'auto') {
        const prev = document.documentElement.getAttribute('data-theme');
        applyTheme();
        const now = document.documentElement.getAttribute('data-theme');
        if (prev !== now && typeof loadDashboard === 'function') {
          loadDashboard().catch(() => {});
        }
      }
    }, 15 * 60 * 1000);

    // Lee una variable CSS del :root como string (para canvas drawing).
    function cssVar(name) {
      return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    }

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
      const dirMap = { positive: "HACIA HUELVA", negative: "HACIA SEVILLA" };
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
            <span class="nd-list-title">${escapeHtml(incidentLabel(incident.incident_type || incident.cause_type))}</span>
            <span class="nd-list-km">${escapeHtml(formatKm(incident.from_km ?? incident.to_km))}</span>
          </div>
          <div class="nd-list-sub">
            ${escapeHtml(incident.road || "-")} · ${escapeHtml(incident.direction || "sin dirección")}
            · ${escapeHtml(incident.municipality || incident.province || "sin municipio")}
          </div>
          <div class="nd-chips">
            <span class="${chipClass(incident.severity)}">${escapeHtml(severityLabel(incident.severity) || "sin severidad")}</span>
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
      const canvas = byId("trendBars");
      const ctx = canvas.getContext("2d");

      // Redimensionar canvas al tamaño real del contenedor (responsivo)
      const cssW = canvas.offsetWidth || canvas.parentElement?.clientWidth || window.innerWidth - 48 || 900;
      const minH = window.innerWidth < 600 ? 220 : 160;
      canvas.width  = Math.max(cssW, 200);
      canvas.height = minH;

      const W = canvas.width, H = canvas.height;
      const COL_BG     = cssVar('--canvas-bg')     || '#000000';
      const COL_EMPTY  = cssVar('--canvas-empty')  || '#333333';
      const COL_TEXT   = cssVar('--canvas-text')   || '#666666';
      const COL_GRID   = cssVar('--canvas-grid')   || '#1A1A1A';
      const COL_LEVEL_FLUIDO      = cssVar('--success') || '#4A9E5C';
      const COL_LEVEL_DENSO       = cssVar('--warning') || '#D4A843';
      const COL_LEVEL_RETENCIONES = cssVar('--accent')  || '#D71921';

      ctx.fillStyle = COL_BG;
      ctx.fillRect(0, 0, W, H);

      if (!states || states.length === 0) {
        ctx.fillStyle = COL_EMPTY;
        ctx.font = '700 12px "Space Mono"';
        ctx.textAlign = "left";
        ctx.fillText("[SIN HISTÓRICO]", 20, 40);
        return;
      }

      const pad = { top: 8, right: 8, bottom: 28, left: 8 };
      const w = W - pad.left - pad.right;
      const h = H - pad.top - pad.bottom;

      const levelColor = {
        fluido:            COL_LEVEL_FLUIDO,
        denso:             COL_LEVEL_DENSO,
        retenciones:       COL_LEVEL_RETENCIONES,
        congestion_fuerte: COL_LEVEL_RETENCIONES,
      };

      const maxScore = Math.max(...states.map(s => s.traffic_score || 0), 1);
      const n = states.length;
      const barW = Math.max(1, w / n);

      // Barras
      states.forEach((s, i) => {
        const score = s.traffic_score || 0;
        const barH = Math.max(2, (score / maxScore) * h);
        const x = pad.left + i * barW;
        const y = pad.top + h - barH;
        ctx.fillStyle = levelColor[s.traffic_level] || COL_TEXT;
        ctx.fillRect(x, y, Math.max(1, barW - 1), barH);
      });

      // Etiquetas horarias en el eje X — una por cada hora exacta del rango
      const times    = states.map(s => new Date(s.generated_at));
      const firstMs  = times[0].getTime();
      const lastMs   = times[times.length - 1].getTime();
      const spanMs   = lastMs - firstMs || 1;

      // Primera hora entera >= firstMs
      const firstHour = new Date(firstMs);
      firstHour.setMinutes(0, 0, 0);
      if (firstHour.getTime() < firstMs) firstHour.setHours(firstHour.getHours() + 1);

      ctx.fillStyle  = COL_TEXT;
      ctx.font       = '9px "Space Mono"';
      ctx.textAlign  = "center";
      ctx.strokeStyle = COL_GRID;
      ctx.lineWidth   = 1;

      // Saltar etiquetas si no hay espacio mínimo (44 px) para evitar solapamiento en móvil
      let lastLabelX = -999;
      for (let h2 = new Date(firstHour); h2.getTime() <= lastMs; h2.setHours(h2.getHours() + 1)) {
        const ratio = (h2.getTime() - firstMs) / spanMs;
        const x = pad.left + ratio * w;
        ctx.beginPath();
        ctx.moveTo(x, pad.top);
        ctx.lineTo(x, pad.top + h);
        ctx.stroke();
        if (x - lastLabelX >= 44) {
          const label = h2.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
          ctx.fillText(label, x, H - 4);
          lastLabelX = x;
        }
      }
    }

    function renderDirectionPulso(canvasId, history) {
      const canvas = byId(canvasId);
      if (!canvas) return;
      const ctx = canvas.getContext('2d');

      const cssW = canvas.offsetWidth || canvas.parentElement?.clientWidth || window.innerWidth - 48 || 900;
      const minH = window.innerWidth < 600 ? 90 : 80;
      canvas.width  = Math.max(cssW, 200);
      canvas.height = minH;

      const W = canvas.width, H = canvas.height;
      const COL_BG    = cssVar('--canvas-bg')    || '#000000';
      const COL_EMPTY = cssVar('--canvas-empty') || '#333333';
      const COL_TEXT  = cssVar('--canvas-text')  || '#666666';
      const COL_GRID  = cssVar('--canvas-grid')  || '#1A1A1A';
      const COL_FLUIDO      = cssVar('--success') || '#4A9E5C';
      const COL_DENSO       = cssVar('--warning') || '#D4A843';
      const COL_RETENCIONES = cssVar('--accent')  || '#D71921';

      ctx.fillStyle = COL_BG;
      ctx.fillRect(0, 0, W, H);

      const points = (history || [])
        .filter(r => r.average_speed != null)
        .sort((a, b) => a.collected_at.localeCompare(b.collected_at));

      if (points.length === 0) {
        ctx.fillStyle = COL_EMPTY;
        ctx.font = '700 12px "Space Mono"';
        ctx.textAlign = 'left';
        ctx.fillText('[SIN HISTÓRICO]', 20, 40);
        return;
      }

      function speedColor(spd) {
        if (spd >= 50) return COL_FLUIDO;        // fluido
        if (spd >= 36) return COL_DENSO;         // denso
        if (spd >= 20) return COL_RETENCIONES;   // retenciones
        return COL_RETENCIONES;                   // congestión fuerte
      }

      const pad = { top: 8, right: 8, bottom: 28, left: 8 };
      const w = W - pad.left - pad.right;
      const h = H - pad.top - pad.bottom;

      const freeFlow = 60;  // límite real del tramo SE-30 km 10-12
      const n = points.length;
      const barW = Math.max(1, w / n);

      points.forEach((p, i) => {
        // Barra representa congestión: velocidad baja → barra alta
        const congestion = Math.max(0, freeFlow - Math.min(p.average_speed, freeFlow));
        const barH = Math.max(2, (congestion / freeFlow) * h);
        const x = pad.left + i * barW;
        const y = pad.top + h - barH;
        ctx.fillStyle = speedColor(p.average_speed);
        ctx.fillRect(x, y, Math.max(1, barW - 1), barH);
      });

      // Etiquetas horarias en el eje X
      const times   = points.map(p => new Date(p.collected_at));
      const firstMs = times[0].getTime();
      const lastMs  = times[times.length - 1].getTime();
      const spanMs  = lastMs - firstMs || 1;

      const firstHour = new Date(firstMs);
      firstHour.setMinutes(0, 0, 0);
      if (firstHour.getTime() < firstMs) firstHour.setHours(firstHour.getHours() + 1);

      ctx.fillStyle   = COL_TEXT;
      ctx.font        = '9px "Space Mono"';
      ctx.textAlign   = 'center';
      ctx.strokeStyle = COL_GRID;
      ctx.lineWidth   = 1;
      let lastLabelX  = -999;
      for (let hh = new Date(firstHour); hh.getTime() <= lastMs; hh.setHours(hh.getHours() + 1)) {
        const ratio = (hh.getTime() - firstMs) / spanMs;
        const x = pad.left + ratio * w;
        ctx.beginPath(); ctx.moveTo(x, pad.top); ctx.lineTo(x, pad.top + h); ctx.stroke();
        if (x - lastLabelX >= 44) {
          ctx.fillText(hh.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' }), x, H - 4);
          lastLabelX = x;
        }
      }
    }

    function renderDirections(detectors) {
      if (!detectors || !detectors.length) return;

      function avgSpeed(arr) {
        const valid = arr.filter(d => d.average_speed != null && d.average_speed > 0);
        return valid.length ? valid.reduce((s, d) => s + d.average_speed, 0) / valid.length : null;
      }
      function avgDelay(arr) {
        const valid = arr.filter(d => d.vehicle_flow != null);
        return valid.length ? valid.reduce((s, d) => s + d.vehicle_flow, 0) / valid.length : null;
      }
      function speedInfo(spd) {
        if (spd === null) return { label: 'Sin datos', color: 'var(--text-disabled)', pct: 0 };
        // La barra representa intensidad de tráfico: velocidad baja → barra larga.
        // Tramos discretos no solapados para garantizar monotonicidad visual
        // (retenciones > denso > fluido), con interpolación dentro de cada tramo.
        if (spd >= 50) {
          // Fluido: 50–60 km/h → 30%–10%
          const pct = Math.round(30 - Math.min(Math.max(spd - 50, 0), 10) * 2);
          return { label: 'Fluido', color: 'var(--success)', pct };
        }
        if (spd >= 36) {
          // Denso: 36–50 km/h → 55%–35%
          const pct = Math.round(55 - (spd - 36) / 14 * 20);
          return { label: 'Denso', color: 'var(--warning)', pct };
        }
        if (spd >= 20) {
          // Retenciones: 20–36 km/h → 80%–60%
          const pct = Math.round(80 - (spd - 20) / 16 * 20);
          return { label: 'Retenciones', color: 'var(--accent)', pct };
        }
        // Congestión fuerte: 0–20 km/h → 100%–85%
        const pct = Math.round(100 - Math.max(spd, 0) / 20 * 15);
        return { label: 'Congestión fuerte', color: 'var(--accent)', pct };
      }
      // Inferir dirección desde el campo o desde el nombre del detector (fallback)
      function resolveDir(d) {
        if (d.direction) return d.direction;
        const id = (d.detector_id || '').toLowerCase();
        if (id.includes('cadiz') || id.includes('negativo')) return 'negative';
        if (id.includes('huelva') || id.includes('positivo')) return 'positive';
        return null;
      }

      const pos = detectors.filter(d => resolveDir(d) === 'positive');
      const neg = detectors.filter(d => resolveDir(d) === 'negative');

      const spdPos = avgSpeed(pos), spdNeg = avgSpeed(neg);
      const delayPos = avgDelay(pos), delayNeg = avgDelay(neg);
      const iPos = speedInfo(spdPos), iNeg = speedInfo(spdNeg);

      function update(pfx, spd, delay, count, info) {
        byId(pfx + '-speed').textContent = spd !== null ? Math.round(spd) : '--';
        const lvl = byId(pfx + '-level');
        lvl.textContent = info.label;
        lvl.style.color = info.color;
        byId(pfx + '-bar').style.width = info.pct + '%';
        byId(pfx + '-bar').style.background = info.color;
        byId(pfx + '-sensors').textContent = count
          ? count + ' sensor' + (count > 1 ? 'es' : '') + ' activo' + (count > 1 ? 's' : '')
            + (delay != null && delay > 0 ? ' · +' + Math.round(delay) + 's retardo' : '')
          : 'Sin sensores activos';
      }

      update('dir-pos', spdPos, delayPos, pos.length, iPos);
      update('dir-neg', spdNeg, delayNeg, neg.length, iNeg);
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
      renderDirections(data.detectors);
      renderPanels(data.panels);
      renderIncidents(data.incidents);
      renderCameras(data.cameras);
      renderObservedVsInferred(state, data.reversible_reports || []);
      const history = data.tomtom_speed_history || [];
      renderDirectionPulso('pulso-huelva', history.filter(r => r.detector_id === 'tomtom_route_huelva'));
      renderDirectionPulso('pulso-cadiz',  history.filter(r => r.detector_id === 'tomtom_route_cadiz'));
      renderRecentReports(data.reversible_reports || []);
      renderSpeedTab(data);
      renderMapTab(data);
      renderNuevo(data);
      if (latestRun && latestRun.warnings && latestRun.warnings.length > 0) {
        warningBox.style.display = "block";
        warningBox.innerHTML = latestRun.warnings.map((item) => escapeHtml(item)).join("<br>");
      } else {
        warningBox.style.display = "none";
        warningBox.textContent = "";
      }
    }

    const reportLabels = { positive: '← Huelva', negative: '→ Cádiz', none: 'Sin reversible' };
    const reportColors = { positive: '#4A9E5C', negative: '#D4A843', none: '#666666' };

    function renderObservedVsInferred(state, reports) {
      const el = byId('reversibleObserved');
      if (!reports || reports.length === 0) { el.textContent = ''; return; }
      const last = reports[0];
      if (!last || !last.reported_at) { el.textContent = ''; return; }
      // Calcular antigüedad
      const reportedUtc = new Date(last.reported_at + 'Z');
      const ageMin = Math.round((Date.now() - reportedUtc) / 60000);
      if (ageMin > 90) { el.textContent = ''; return; }  // Ignorar si muy antiguo
      const obsLabel = reportLabels[last.direction] || last.direction;
      const obsColor = reportColors[last.direction] || '#666';
      const inferred = state ? state.reversible_probable : null;
      let match = '';
      if (inferred && last.direction !== 'none') {
        if (inferred === last.direction) {
          match = ' <span style="color:#4A9E5C;">&#10003;</span>';
        } else if (inferred !== 'indeterminado') {
          match = ' <span style="color:#C0392B;">&#10007;</span>';
        }
      }
      el.innerHTML = `Obs. hace ${ageMin}&#160;min: <span style="color:${obsColor};">${escapeHtml(obsLabel)}</span>${match}`;
    }

    async function reportReversible(direction) {
      const statusEl = byId('reportStatus');
      const noteEl = byId('reportNote');
      const note = noteEl && noteEl.value ? noteEl.value.trim() : '';
      statusEl.textContent = 'Enviando...';
      try {
        const res = await fetch('/api/report-reversible', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ direction, note: note || undefined }),
        });
        if (!res.ok) throw new Error('Error ' + res.status);
        statusEl.style.color = reportColors[direction] || '#888';
        statusEl.textContent = `Registrado: ${reportLabels[direction]} · ${new Date().toLocaleTimeString('es-ES')}`;
        if (noteEl) noteEl.value = '';
        await loadDashboard();
      } catch (e) {
        statusEl.style.color = 'var(--accent)';
        statusEl.textContent = 'Error al enviar: ' + e.message;
      }
    }

    async function deleteReport(id) {
      const statusEl = byId('reportStatus');
      try {
        const res = await fetch('/api/report-reversible/' + id, { method: 'DELETE' });
        if (!res.ok) throw new Error('Error ' + res.status);
        statusEl.style.color = '#888';
        statusEl.textContent = 'Registro eliminado.';
        await loadDashboard();
      } catch (e) {
        statusEl.style.color = 'var(--accent)';
        statusEl.textContent = 'Error al eliminar: ' + e.message;
      }
    }

    function renderRecentReports(reports) {
      const el = byId('recentReports');
      const mono = 'Space Mono, monospace';
      if (!reports || reports.length === 0) {
        el.innerHTML = `<div style="font-family:${mono};font-size:10px;color:#444;">Sin observaciones registradas todav&#237;a.</div>`;
        return;
      }
      const rows = reports.map(r => {
        const color = reportColors[r.direction] || '#666';
        const label = reportLabels[r.direction] || r.direction;
        const dt = r.reported_at ? new Date(r.reported_at + 'Z').toLocaleString('es-ES', { timeZone: 'Europe/Madrid', hour12: false }) : '\u2014';
        const noteHtml = r.note ? `<div style="font-family:${mono};font-size:10px;color:#777;padding:2px 0 0 100px;font-style:italic;">&#8220;${escapeHtml(r.note)}&#8221;</div>` : '';
        return `<div style="padding:4px 0;border-bottom:1px solid #111;">
          <div style="display:flex;gap:var(--space-md);align-items:center;">
            <span style="font-family:${mono};font-size:11px;color:${color};min-width:100px;">${escapeHtml(label)}</span>
            <span style="font-family:${mono};font-size:10px;color:#555;flex:1;">${escapeHtml(dt)}</span>
            <button onclick="deleteReport(${r.id})" title="Eliminar este registro" style="background:none;border:none;cursor:pointer;color:#444;font-size:14px;line-height:1;padding:0 2px;" onmouseover="this.style.color='var(--accent)'" onmouseout="this.style.color='#444'">&#x2715;</button>
          </div>
          ${noteHtml}
        </div>`;
      });
      el.innerHTML = `<div style="font-family:${mono};font-size:9px;letter-spacing:0.08em;color:#444;margin-bottom:4px;">&#218;LTIMAS OBSERVACIONES</div>${rows.join('')}`;
    }

    let lastDashboardData = null;

    async function loadDashboard() {
      const response = await fetch("/api/dashboard");
      if (!response.ok) throw new Error("No se pudo cargar el dashboard");
      const data = await response.json();
      lastDashboardData = data;
      renderDashboard(data);
    }

    function redrawCanvases() {
      if (!lastDashboardData) return;
      const pulsoH = byId('pulso-huelva');
      const pulsoC = byId('pulso-cadiz');
      if ((pulsoH && pulsoH.offsetWidth > 0) || (pulsoC && pulsoC.offsetWidth > 0)) {
        const history = lastDashboardData.tomtom_speed_history || [];
        renderDirectionPulso('pulso-huelva', history.filter(r => r.detector_id === 'tomtom_route_huelva'));
        renderDirectionPulso('pulso-cadiz',  history.filter(r => r.detector_id === 'tomtom_route_cadiz'));
      }
      const spdH = byId('spd-chart-huelva');
      const spdC = byId('spd-chart-cadiz');
      if ((spdH && spdH.offsetWidth > 0) || (spdC && spdC.offsetWidth > 0)) {
        renderSpeedTab(lastDashboardData);
      }
    }

    let _resizeTimer;
    window.addEventListener('resize', () => {
      clearTimeout(_resizeTimer);
      _resizeTimer = setTimeout(redrawCanvases, 200);
    });



    // ---- Mapa MapLibre GL ----
    let ndMap = null;
    let ndMapMarkers = {};
    let ndMapLoaded = false;

    // Route endpoints: Huelva starts km10, Cádiz starts km12
    const ROUTE_POSITIONS = {
      'tomtom_route_huelva': [-5.986923, 37.343820],
      'tomtom_route_cadiz':  [-6.002909, 37.357216],
    };

    function sensorColor(d) {
      if (!d || d.average_speed == null) return '#666666';
      const isFreeFlow = d.free_flow_speed != null && Math.abs(d.average_speed - d.free_flow_speed) < 1;
      if (isFreeFlow) return '#666666';
      if (d.average_speed >= 55) return '#4A9E5C';
      if (d.average_speed >= 30) return '#D4A843';
      return '#D71921';
    }

    function loadMapLibreAndInit() {
      if (typeof maplibregl !== 'undefined') { _initMapNow(); return; }
      byId('map-status').textContent = 'Cargando librería...';
      const link = document.createElement('link');
      link.rel = 'stylesheet'; link.href = '/static/maplibre-gl.css';
      document.head.appendChild(link);
      const script = document.createElement('script');
      script.src = '/static/maplibre-gl.js';
      script.onload = () => _initMapNow();
      script.onerror = () => { byId('map-status').textContent = 'ERROR: no se pudo cargar /static/maplibre-gl.js'; };
      document.head.appendChild(script);
    }

    function initMap() {
      if (ndMap) { ndMap.resize(); return; }
      loadMapLibreAndInit();
    }

    function cartoTilesForTheme() {
      const isLight = document.documentElement.getAttribute('data-theme') === 'light';
      const variant = isLight ? 'light_all' : 'dark_all';
      return [
        `https://a.basemaps.cartocdn.com/${variant}/{z}/{x}/{y}.png`,
        `https://b.basemaps.cartocdn.com/${variant}/{z}/{x}/{y}.png`,
      ];
    }

    function _initMapNow() {
      const container = byId('nd-map');
      byId('map-status').textContent = 'Iniciando...';
      const isLight = document.documentElement.getAttribute('data-theme') === 'light';
      ndMap = new maplibregl.Map({
        container: 'nd-map',
        style: {
          version: 8,
          sources: {
            'carto-base': {
              type: 'raster',
              tiles: cartoTilesForTheme(),
              tileSize: 256,
              attribution: '© OpenStreetMap contributors © CARTO',
            }
          },
          layers: [{ id: 'carto-base-layer', type: 'raster', source: 'carto-base' }]
        },
        center: [-5.9950, 37.3505],
        zoom: 14,
        attributionControl: false,
      });
      ndMap.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
      ndMap.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right');
      ndMap.on('error', (e) => {
        byId('map-status').textContent = 'Error: ' + (e.error ? e.error.message : 'desconocido');
      });
      ndMap.on('load', () => {
        ndMapLoaded = true;
        byId('map-status').textContent = 'MapLibre GL · CARTO ' + (isLight ? 'Light' : 'Dark');
        // Dibujar tramo km 10-12
        ndMap.addSource('tramo', {
          type: 'geojson',
          data: {
            type: 'Feature',
            geometry: {
              type: 'LineString',
              coordinates: [
                [-5.986923, 37.343820],
                [-5.994916, 37.350518],
                [-6.002909, 37.357216],
              ]
            }
          }
        });
        ndMap.addLayer({
          id: 'tramo-line',
          type: 'line',
          source: 'tramo',
          paint: {
            'line-color': isLight ? '#000000' : '#FFFFFF',
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

      const detectors = data.detectors || [];
      const huelva = detectors.find(d => d.detector_id === 'tomtom_route_huelva');
      const cadiz  = detectors.find(d => d.detector_id === 'tomtom_route_cadiz');

      // Actualizar tarjetas resumen
      [
        { det: huelva, spdId: 'map-spd-huelva', noteId: 'map-delay-huelva' },
        { det: cadiz,  spdId: 'map-spd-cadiz',  noteId: 'map-delay-cadiz'  },
      ].forEach(({ det, spdId, noteId }) => {
        const spdEl  = byId(spdId);
        const noteEl = byId(noteId);
        if (!spdEl) return;
        if (det && det.average_speed != null) {
          spdEl.textContent = det.average_speed.toFixed(0) + ' km/h';
          spdEl.style.color = sensorColor(det);
          const delay = det.vehicle_flow != null ? `+${det.vehicle_flow}s retardo` : '';
          const free  = det.free_flow_speed != null ? ` · libre ${det.free_flow_speed.toFixed(0)} km/h` : '';
          if (noteEl) noteEl.textContent = (delay + free) || 'TomTom Routing';
        } else {
          spdEl.textContent = '-';
          spdEl.style.color = '';
          if (noteEl) noteEl.textContent = 'Sin datos';
        }
      });

      if (!ndMap || !ndMapLoaded) return;

      // Limpiar marcadores anteriores
      Object.values(ndMapMarkers).forEach(m => m.remove());
      ndMapMarkers = {};

      // Dibujar marcadores en los extremos del tramo
      [
        { det: huelva, id: 'tomtom_route_huelva', label: '\u2192 Huelva' },
        { det: cadiz,  id: 'tomtom_route_cadiz',  label: '\u2190 C\u00e1diz' },
      ].forEach(({ det, id, label }) => {
        const pos = ROUTE_POSITIONS[id];
        if (!pos) return;

        const color = sensorColor(det);
        const spd = det && det.average_speed != null ? det.average_speed.toFixed(0) : '--';
        const delay = det && det.vehicle_flow != null ? `+${det.vehicle_flow}s` : '';
        const ffsNote = det && det.free_flow_speed != null
          ? `<div style="color:var(--text-disabled);margin-top:2px;">libre ${det.free_flow_speed.toFixed(0)} km/h</div>`
          : '';

        const el = document.createElement('div');
        el.className = 'nd-map-marker';
        el.style.borderColor = color;
        el.style.color = color;
        el.style.width = '52px';
        el.style.height = '52px';
        el.style.fontSize = '13px';
        el.textContent = spd;

        const popup = new maplibregl.Popup({ offset: 12, closeButton: true, maxWidth: '200px' })
          .setHTML(`<div style="font-family:'Space Mono',monospace;font-size:11px;color:var(--text-primary);padding:12px 14px;line-height:1.6;">
            <div style="font-size:9px;letter-spacing:0.08em;text-transform:uppercase;color:var(--text-secondary);margin-bottom:6px;">${label}</div>
            <div style="font-size:24px;font-weight:700;color:${color};">${spd} <span style="font-size:12px;">km/h</span></div>
            <div style="color:var(--text-secondary);margin-top:2px;">${delay ? 'Retardo: ' + delay : 'Sin retardo'}</div>
            ${ffsNote}
          </div>`);

        const marker = new maplibregl.Marker({ element: el, anchor: 'center' })
          .setLngLat(pos)
          .setPopup(popup)
          .addTo(ndMap);

        ndMapMarkers[id] = marker;
      });
    }

    // ---- Histórico de velocidades diarias ----

    async function loadHistorico() {
      const status = document.getElementById('hist-status');
      status.textContent = 'Cargando...';
      try {
        const res = await fetch('/api/daily-stats');
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const rows = await res.json();
        renderHistorico(rows);
        const numDays = new Set(rows.map(r => r.date)).size;
        status.textContent = numDays + ' d\u00eda' + (numDays !== 1 ? 's' : '') + ' registrado' + (numDays !== 1 ? 's' : '');
        status.style.color = 'var(--success)';
      } catch (e) {
        status.textContent = 'Error: ' + e.message;
        status.style.color = 'var(--accent)';
      }
    }

    function fmtSpd(v) {
      if (v == null || isNaN(v)) return '\u2014';
      return parseFloat(v).toFixed(1) + ' km/h';
    }

    function fmtTime(isoStr) {
      if (!isoStr) return '';
      try {
        return new Date(isoStr).toLocaleTimeString('es-ES', { timeZone: 'Europe/Madrid', hour: '2-digit', minute: '2-digit' });
      } catch (e) { return ''; }
    }

    function spdCell(speed, time, color) {
      const t = fmtTime(time);
      return `<td style="padding:9px 16px;text-align:right;color:${color};">`
        + fmtSpd(speed)
        + (t ? `<div style="font-size:10px;color:var(--text-secondary);margin-top:1px;">${t}</div>` : '')
        + '</td>';
    }

    function renderHistorico(rows) {
      const tbody = document.getElementById('hist-tbody');
      if (!rows || rows.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" style="padding:24px 16px;text-align:center;color:var(--text-secondary);">Sin datos todav\u00eda.</td></tr>';
        return;
      }
      const todayStr = new Date().toLocaleDateString('sv-SE', { timeZone: 'Europe/Madrid' });
      const byDate = {};
      rows.forEach(r => {
        if (!byDate[r.date]) byDate[r.date] = {};
        byDate[r.date][r.direction] = r;
      });
      const dates = Object.keys(byDate).sort().reverse();
      const colH = '#4A9E5C';
      const colC = '#D4A843';
      let html = '';
      dates.forEach(date => {
        const isToday = date === todayStr;
        const h = byDate[date]['positive'] || {};
        const c = byDate[date]['negative'] || {};
        const samples = (h.sample_count || 0) + (c.sample_count || 0);
        const dateLabel = isToday
          ? `<span style="color:var(--text-primary)">${date}</span> <span style="color:var(--text-secondary);font-size:10px;">EN CURSO</span>`
          : `<span>${date}</span>`;
        const rowOpacity = isToday ? 'opacity:0.75;' : '';
        html += `<tr style="border-bottom:1px solid var(--border);${rowOpacity}">
          <td style="padding:9px 16px;white-space:nowrap;">${dateLabel}</td>
          ${spdCell(h.min_speed, h.min_speed_time, colH)}
          ${spdCell(h.max_speed, h.max_speed_time, colH)}
          <td style="padding:9px 16px;text-align:right;color:${colH};">${fmtSpd(h.avg_speed)}</td>
          ${spdCell(c.min_speed, c.min_speed_time, colC)}
          ${spdCell(c.max_speed, c.max_speed_time, colC)}
          <td style="padding:9px 16px;text-align:right;color:${colC};">${fmtSpd(c.avg_speed)}</td>
          <td style="padding:9px 16px;text-align:right;color:var(--text-secondary);">${samples}</td>
        </tr>`;
      });
      tbody.innerHTML = html;
    }

    function showTab(name) {
      document.getElementById('tab-estado').style.display = name === 'estado' ? '' : 'none';
      document.getElementById('tab-velocidades').style.display = name === 'velocidades' ? '' : 'none';
      document.getElementById('tab-mapa').style.display = name === 'mapa' ? '' : 'none';
      document.getElementById('tab-se30').style.display = name === 'se30' ? '' : 'none';
      document.getElementById('tab-historico').style.display = name === 'historico' ? '' : 'none';
      document.getElementById('tab-nuevo').style.display = name === 'nuevo' ? '' : 'none';
      document.getElementById('btn-estado').classList.toggle('active', name === 'estado');
      document.getElementById('btn-velocidades').classList.toggle('active', name === 'velocidades');
      document.getElementById('btn-mapa').classList.toggle('active', name === 'mapa');
      document.getElementById('btn-se30').classList.toggle('active', name === 'se30');
      document.getElementById('btn-historico').classList.toggle('active', name === 'historico');
      document.getElementById('btn-nuevo').classList.toggle('active', name === 'nuevo');
      if (name === 'mapa') requestAnimationFrame(initMap);
      if (name === 'se30') { loadSE30Data(); requestAnimationFrame(initMapSE30); }
      if (name === 'historico') loadHistorico();
      if (name === 'estado' || name === 'velocidades') requestAnimationFrame(redrawCanvases);
      if (name === 'nuevo') { requestAnimationFrame(() => { nv_renderChart(); nv_startScene(); }); }
      else { nv_stopScene(); }
    }

    // ---- SE-30 Completa ----
    let se30Loaded = false;
    let se30Loading = false;

    async function loadSE30Data() {
      if (se30Loading) return;
      se30Loading = true;
      const status = byId('se30-status');
      status.textContent = 'Consultando DGT DATEX2 y TomTom... (puede tardar unos segundos)';
      status.style.color = 'var(--text-secondary)';
      try {
        const res = await fetch('/api/se30');
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        renderSE30(data);
        se30Loaded = true;
        const ts = data.collected_at ? formatDate(data.collected_at) : 'ahora';
        const errKeys = Object.keys(data.errors || {});
        if (errKeys.length > 0) {
          status.textContent = 'Actualizado: ' + ts + ' · Errores en: ' + errKeys.join(', ');
          status.style.color = 'var(--warning)';
        } else {
          status.textContent = 'Actualizado: ' + ts + ' · Todos los feeds OK';
          status.style.color = 'var(--success)';
        }
      } catch (e) {
        status.textContent = 'Error al cargar datos SE-30: ' + e.message;
        status.style.color = 'var(--accent)';
      } finally {
        se30Loading = false;
      }
    }

    function renderSE30(data) {
      const panels = data.panels || [];
      const incidents = data.incidents || [];
      const detectors = data.detectors || [];
      const tomtom = data.tomtom || [];

      byId('se30-cnt-panels').textContent = String(panels.length);
      byId('se30-cnt-incidents').textContent = String(incidents.length);
      byId('se30-cnt-detectors').textContent = String(detectors.length);
      byId('se30-cnt-tomtom').textContent = String(tomtom.length);

      renderSE30Panels(panels);
      renderSE30Detectors(detectors);
      renderSE30Incidents(incidents);
      renderSE30Tomtom(tomtom);

      // Mapa: si ya está listo, pintar; si no, iniciarlo (pintará al cargar)
      if (ndMapSE30 && ndMapSE30Loaded) {
        renderSE30Map(data);
      } else {
        window._lastSE30Data = data;
        initMapSE30();
      }
    }

    function dirLabel(dir) {
      if (!dir) return 'AMBOS';
      const d = String(dir).toLowerCase();
      if (d === 'positive' || d.includes('crecient') || d.includes('huelva')) return '\u2192 Huelva';
      if (d === 'negative' || d.includes('decreci') || d.includes('sevilla')) return '\u2190 Sevilla';
      return escapeHtml(dir);
    }

    function speedColor(spd) {
      if (spd == null) return 'color:var(--text-disabled)';
      if (spd >= 55) return 'color:var(--success)';
      if (spd >= 30) return 'color:var(--warning)';
      return 'color:var(--accent)';
    }

    function renderSE30Panels(panels) {
      const root = byId('se30-panels');
      if (!panels.length) { root.innerHTML = '<div class="nd-empty">[Sin paneles VMS activos en la SE-30]</div>'; return; }
      const sorted = [...panels].sort((a, b) => (a.km ?? 999) - (b.km ?? 999));
      const dirMap = { positive: '\u2192 Huelva', negative: '\u2190 Sevilla' };
      root.innerHTML = '<div class="nd-vms-list">' + sorted.map(p => {
        const msg = (p.legends || []).map(l => escapeHtml(l)).join('<br>') || 'SIN MENSAJE';
        const pictos = (p.pictograms || []).map(x => '<span class="nd-tag warn">' + escapeHtml(x) + '</span>').join('');
        const dir = dirMap[p.direction] || escapeHtml(p.direction || 'Ambos sentidos');
        const km = p.km != null ? 'km ' + Number(p.km).toFixed(1) : 'km -';
        const name = escapeHtml(p.location_id || '-');
        return '<div class="nd-vms-item">' +
          '<div class="nd-vms-header"><span class="nd-vms-name">' + name + '</span><span class="nd-vms-km">' + escapeHtml(km) + '</span></div>' +
          '<div class="nd-vms-dir">' + dir + ' \xb7 ' + escapeHtml(p.status || 'Desconocido') + '</div>' +
          '<div class="nd-vms-display">' + msg + '</div>' +
          (pictos ? '<div class="nd-vms-pictos">' + pictos + '</div>' : '') +
          '</div>';
      }).join('') + '</div>';
    }

    function renderSE30Detectors(detectors) {
      const root = byId('se30-detectors');
      if (!detectors.length) { root.innerHTML = '<div class="nd-empty">[Sin lecturas de detectores DGT en la SE-30]</div>'; return; }
      const sorted = [...detectors].sort((a, b) => (a.km ?? 999) - (b.km ?? 999));
      const rows = sorted.map(d => {
        const spd = d.average_speed != null ? d.average_speed.toFixed(1) : '-';
        const flow = d.vehicle_flow != null ? d.vehicle_flow : '-';
        const occ = d.occupancy != null ? (d.occupancy * 100).toFixed(1) + '%' : '-';
        const sc = d.average_speed != null ? speedColor(d.average_speed) : '';
        const km = d.km != null ? Number(d.km).toFixed(1) : '-';
        const ts = d.measured_at ? formatDate(d.measured_at) : '-';
        return '<tr>' +
          '<td class="nd-meta" style="white-space:nowrap;">km ' + escapeHtml(km) + '</td>' +
          '<td class="nd-meta">' + escapeHtml(d.detector_id || '-') + '</td>' +
          '<td class="nd-meta" style="white-space:nowrap;">' + dirLabel(d.direction) + '</td>' +
          '<td class="nd-meta" style="' + sc + '">' + escapeHtml(spd) + ' km/h</td>' +
          '<td class="nd-meta">' + escapeHtml(String(flow)) + ' veh/h</td>' +
          '<td class="nd-meta">' + escapeHtml(occ) + '</td>' +
          '<td class="nd-meta" style="font-size:10px;color:var(--text-disabled);">' + escapeHtml(ts) + '</td>' +
          '</tr>';
      }).join('');
      root.innerHTML = '<div style="overflow-x:auto;">' +
        '<table style="width:100%;border-collapse:collapse;">' +
        '<thead><tr style="border-bottom:1px solid var(--border);">' +
        '<th class="nd-label" style="padding:8px 12px;text-align:left;">km</th>' +
        '<th class="nd-label" style="padding:8px 12px;text-align:left;">ID detector</th>' +
        '<th class="nd-label" style="padding:8px 12px;text-align:left;">Sentido</th>' +
        '<th class="nd-label" style="padding:8px 12px;text-align:left;">Velocidad</th>' +
        '<th class="nd-label" style="padding:8px 12px;text-align:left;">Flujo</th>' +
        '<th class="nd-label" style="padding:8px 12px;text-align:left;">Ocupaci\xf3n</th>' +
        '<th class="nd-label" style="padding:8px 12px;text-align:left;">Medido</th>' +
        '</tr></thead>' +
        '<tbody>' + rows + '</tbody></table></div>';
    }

    function renderSE30Incidents(incidents) {
      const root = byId('se30-incidents');
      if (!incidents.length) { root.innerHTML = '<div class="nd-empty">[Sin incidencias activas en la SE-30]</div>'; return; }
      const sorted = [...incidents].sort((a, b) => (a.from_km ?? a.to_km ?? 999) - (b.from_km ?? b.to_km ?? 999));
      root.innerHTML = '<div class="nd-list">' + sorted.map(inc => {
        const km = inc.from_km != null ? 'km ' + Number(inc.from_km).toFixed(1) + (inc.to_km != null ? '\u2013' + Number(inc.to_km).toFixed(1) : '') : (inc.to_km != null ? 'km ' + Number(inc.to_km).toFixed(1) : 'km -');
        const title = escapeHtml(incidentLabel(inc.incident_type || inc.cause_type));
        const dir = dirLabel(inc.direction);
        const muni = escapeHtml(inc.municipality || inc.province || '-');
        const sev = inc.severity || 'sin severidad';
        const sevClass = sev.toLowerCase().includes('high') ? 'alert' : sev.toLowerCase().includes('medium') ? 'warn' : '';
        const start = inc.start_time ? formatDate(inc.start_time) : '-';
        return '<div class="nd-list-item">' +
          '<div class="nd-list-head"><span class="nd-list-title">' + title + '</span><span class="nd-list-km">' + escapeHtml(km) + '</span></div>' +
          '<div class="nd-list-sub">SE-30 \xb7 ' + dir + ' \xb7 ' + muni + ' \xb7 Inicio: ' + escapeHtml(start) + '</div>' +
          '<div class="nd-chips">' +
          '<span class="nd-chip ' + sevClass + '">' + escapeHtml(sev) + '</span>' +
          (inc.validity_status ? '<span class="nd-chip">' + escapeHtml(inc.validity_status) + '</span>' : '') +
          (inc.source && inc.source !== 'dgt' ? '<span class="nd-chip">' + escapeHtml(inc.source) + '</span>' : '') +
          '</div></div>';
      }).join('') + '</div>';
    }

    function renderSE30Tomtom(tomtom) {
      const root = byId('se30-tomtom');
      if (!tomtom.length) { root.innerHTML = '<div class="nd-empty">[Sin datos TomTom almacenados \xb7 Configura VCENTENARIO_TOMTOM_API_KEY]</div>'; return; }
      const sorted = [...tomtom].sort((a, b) => {
        const aId = String(a.detector_id || '');
        const bId = String(b.detector_id || '');
        return aId.localeCompare(bId);
      });
      root.innerHTML = '<div class="nd-list">' + sorted.map(d => {
        const spd = d.average_speed != null ? d.average_speed.toFixed(1) + ' km/h' : '-';
        const ffs = d.free_flow_speed != null ? d.free_flow_speed.toFixed(0) + ' km/h' : '-';
        const flow = d.vehicle_flow != null ? '+' + d.vehicle_flow + 's retardo' : '-';
        const isFreeFlow = d.free_flow_speed != null && d.average_speed != null && Math.abs(d.average_speed - d.free_flow_speed) < 1;
        const sc = isFreeFlow ? 'color:var(--text-disabled)' : speedColor(d.average_speed);
        const ts = d.collected_at ? formatDate(d.collected_at) : '-';
        const freeFlowBadge = isFreeFlow ? ' <span class="nd-chip" style="font-size:9px;padding:2px 6px;border-color:var(--text-disabled);color:var(--text-disabled);">SIN DATOS REALES</span>' : '';
        return '<div class="nd-list-item">' +
          '<div class="nd-list-head">' +
          '<span class="nd-list-title" style="' + sc + '">' + escapeHtml(spd) + freeFlowBadge + '</span>' +
          '<span class="nd-list-km">' + escapeHtml(d.detector_id || '-') + '</span>' +
          '</div>' +
          '<div class="nd-list-sub">Libre: ' + escapeHtml(ffs) + ' \xb7 Retardo: ' + escapeHtml(flow) + ' \xb7 ' + escapeHtml(ts) + '</div>' +
          '</div>';
      }).join('') + '</div>';
    }

    function renderSpeedTab(data) {
      const detectors = data.detectors || [];
      const history = data.tomtom_speed_history || [];

      const huelva = detectors.find(d => d.detector_id === 'tomtom_route_huelva');
      const cadiz  = detectors.find(d => d.detector_id === 'tomtom_route_cadiz');

      function spdColor(spd) {
        if (spd == null) return '';
        if (spd >= 55) return 'color:var(--success)';
        if (spd >= 35) return 'color:var(--warning)';
        return 'color:var(--accent)';
      }

      function fillDir(prefix, det) {
        const spdEl = byId('spd-' + prefix);
        const delayEl = byId('spd-' + prefix + '-delay');
        const freeEl  = byId('spd-' + prefix + '-free');
        if (!det) {
          if (spdEl) spdEl.textContent = '-';
          if (delayEl) delayEl.textContent = 'Sin datos';
          return;
        }
        const spd = det.average_speed;
        const delaySec = det.vehicle_flow;  // campo reutilizado: retardo en segundos
        const freeSpd = det.free_flow_speed;
        if (spdEl) {
          spdEl.textContent = spd != null ? spd.toFixed(0) : '-';
          spdEl.style.cssText = spdColor(spd);
        }
        if (delayEl) {
          const delayTxt = delaySec != null && delaySec > 0
            ? `km/h \xb7 +${delaySec}s de retardo`
            : 'km/h \xb7 sin retardo';
          delayEl.textContent = delayTxt;
        }
        if (freeEl && freeSpd != null) {
          freeEl.textContent = `Velocidad libre: ${freeSpd.toFixed(0)} km/h`;
        }
      }

      fillDir('huelva', huelva);
      fillDir('cadiz',  cadiz);

      const withData = [huelva, cadiz].filter(Boolean);
      byId('spd-sensor-count').textContent = withData.length
        ? `${withData.length} ruta${withData.length > 1 ? 's' : ''} con datos en tiempo real`
        : 'Sin datos de ruta';
      if (withData.length > 0) {
        byId('spd-collected-at').textContent = formatDate(withData[0].collected_at);
      }

      // Gráficos de pulso — uno por sentido (colores siguen el tema)
      const colHuelva = cssVar('--success') || '#4A9E5C';
      const colCadiz  = cssVar('--warning') || '#D4A843';
      drawSpeedChart('spd-chart-huelva', history.filter(r => r.detector_id === 'tomtom_route_huelva'), colHuelva);
      drawSpeedChart('spd-chart-cadiz',  history.filter(r => r.detector_id === 'tomtom_route_cadiz'),  colCadiz);
    }

    function drawSpeedChart(canvasId, history, lineColor) {
      const canvas = byId(canvasId);
      if (!canvas) return;
      const ctx = canvas.getContext('2d');

      // Redimensionar canvas al tamaño real del contenedor (responsivo)
      const cssW = canvas.offsetWidth || canvas.parentElement?.clientWidth || window.innerWidth - 48 || 400;
      const minH = window.innerWidth < 600 ? 180 : 220;
      canvas.width  = Math.max(cssW, 120);
      canvas.height = minH;

      const W = canvas.width, H = canvas.height;
      const COL_BG     = cssVar('--canvas-bg')     || '#000000';
      const COL_EMPTY  = cssVar('--canvas-empty')  || '#333333';
      const COL_TEXT   = cssVar('--canvas-text')   || '#666666';
      const COL_GRID   = cssVar('--canvas-grid')   || '#1A1A1A';
      const COL_ACCENT = cssVar('--canvas-accent') || '#444444';
      const COL_LIMIT  = cssVar('--accent')        || '#D71921';
      const COL_LINE   = lineColor || (cssVar('--success') || '#4A9E5C');

      ctx.fillStyle = COL_BG;
      ctx.fillRect(0, 0, W, H);

      if (!history || history.length === 0) {
        ctx.fillStyle = COL_EMPTY;
        ctx.font = '700 11px "Space Mono"';
        ctx.textAlign = 'left';
        ctx.fillText('[SIN HISTÓRICO]', 16, 36);
        return;
      }

      const pad = { top: 24, right: 28, bottom: 32, left: 46 };
      const w = W - pad.left - pad.right;
      const h = H - pad.top - pad.bottom;

      const points = history
        .map(r => ({ t: r.collected_at, v: r.average_speed }))
        .filter(p => p.v != null)
        .sort((a, b) => a.t.localeCompare(b.t));

      const allTimes = points.map(p => p.t);

      if (points.length < 2) {
        ctx.fillStyle = COL_EMPTY;
        ctx.font = '700 11px "Space Mono"';
        ctx.textAlign = 'left';
        ctx.fillText('[DATOS INSUFICIENTES]', 16, 36);
        return;
      }

      const allSpeeds = points.map(p => p.v);
      const maxV = Math.max(...allSpeeds, 80);
      const minV = Math.min(...allSpeeds, 0);
      const range = maxV - minV || 1;

      // Grid
      ctx.strokeStyle = COL_GRID;
      ctx.lineWidth = 1;
      for (let i = 0; i <= 4; i++) {
        const y = pad.top + (h / 4) * i;
        ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(W - pad.right, y); ctx.stroke();
        ctx.fillStyle = COL_ACCENT;
        ctx.font = '9px "Space Mono"';
        ctx.textAlign = 'right';
        ctx.fillText((maxV - (range / 4) * i).toFixed(0), pad.left - 5, y + 3);
      }

      // Línea de límite 60 km/h
      if (60 >= minV && 60 <= maxV) {
        const yLimit = pad.top + h - ((60 - minV) / range) * h;
        ctx.strokeStyle = COL_LIMIT;
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.beginPath(); ctx.moveTo(pad.left, yLimit); ctx.lineTo(W - pad.right, yLimit); ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = COL_LIMIT;
        ctx.font = '9px "Space Mono"';
        ctx.textAlign = 'left';
        ctx.fillText('60', W - pad.right + 3, yLimit + 3);
      }

      // Línea de velocidad
      ctx.strokeStyle = COL_LINE;
      ctx.lineWidth = 1.5;
      ctx.lineJoin = 'miter';
      ctx.lineCap = 'square';
      ctx.beginPath();
      points.forEach((p, i) => {
        const x = pad.left + (i / (points.length - 1)) * w;
        const y = pad.top + h - ((p.v - minV) / range) * h;
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke();

      // Etiquetas eje X
      ctx.fillStyle = COL_TEXT;
      ctx.font = '9px "Space Mono"';
      ctx.textAlign = 'center';
      const maxLabels = Math.max(1, Math.floor(w / 44));
      const step = Math.max(1, Math.ceil(points.length / maxLabels));
      for (let i = 0; i < points.length; i += step) {
        const x = pad.left + (i / (points.length - 1)) * w;
        const label = new Date(points[i].t).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
        ctx.fillText(label, x, H - 4);
      }
    }

    // ---- Mapa SE-30 ----
    let ndMapSE30 = null;
    let ndMapSE30Loaded = false;
    let ndMapSE30Markers = {};

    function loadMapLibreSE30AndInit() {
      if (typeof maplibregl !== 'undefined') { _initMapSE30Now(); return; }
      // Reutilizar la carga existente si ya hay un script en camino
      if (document.querySelector('script[src="/static/maplibre-gl.js"]')) {
        const wait = () => typeof maplibregl !== 'undefined' ? _initMapSE30Now() : setTimeout(wait, 150);
        setTimeout(wait, 150);
        return;
      }
      byId('se30-map-status').textContent = 'Cargando librería...';
      const link = document.createElement('link');
      link.rel = 'stylesheet'; link.href = '/static/maplibre-gl.css';
      document.head.appendChild(link);
      const script = document.createElement('script');
      script.src = '/static/maplibre-gl.js';
      script.onload = () => _initMapSE30Now();
      script.onerror = () => { byId('se30-map-status').textContent = 'ERROR: no se pudo cargar maplibre-gl.js'; };
      document.head.appendChild(script);
    }

    function initMapSE30() {
      if (ndMapSE30) { ndMapSE30.resize(); return; }
      loadMapLibreSE30AndInit();
    }

    function _initMapSE30Now() {
      if (ndMapSE30) return;
      byId('se30-map-status').textContent = 'Iniciando mapa...';
      const isLight = document.documentElement.getAttribute('data-theme') === 'light';
      ndMapSE30 = new maplibregl.Map({
        container: 'nd-map-se30',
        style: {
          version: 8,
          sources: {
            'carto-base': {
              type: 'raster',
              tiles: cartoTilesForTheme(),
              tileSize: 256,
              attribution: '\xa9 OpenStreetMap contributors \xa9 CARTO',
            }
          },
          layers: [{ id: 'carto-base-layer', type: 'raster', source: 'carto-base' }]
        },
        center: [-5.9950, 37.3505],
        zoom: 14,
        attributionControl: false,
      });
      ndMapSE30.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
      ndMapSE30.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right');
      ndMapSE30.on('error', (e) => {
        byId('se30-map-status').textContent = 'Error: ' + (e.error ? e.error.message : 'desconocido');
      });
      ndMapSE30.on('load', () => {
        ndMapSE30Loaded = true;
        byId('se30-map-status').textContent = 'MapLibre GL \xb7 CARTO ' + (isLight ? 'Light' : 'Dark');
        if (window._lastSE30Data) renderSE30Map(window._lastSE30Data);
      });
    }

    function renderSE30Map(data) {
      window._lastSE30Data = data;
      if (!ndMapSE30 || !ndMapSE30Loaded) return;

      // Limpiar marcadores anteriores
      Object.values(ndMapSE30Markers).forEach(m => m.remove());
      ndMapSE30Markers = {};

      // ---- Marcadores TomTom ----
      const tomtom = data.tomtom || [];
      tomtom.forEach(d => {
        if (d.latitude == null || d.longitude == null) return;
        const color = sensorColor(d);
        const isFreeFlow = d.free_flow_speed != null && d.average_speed != null && Math.abs(d.average_speed - d.free_flow_speed) < 1;
        const spd = d.average_speed != null ? d.average_speed.toFixed(0) : '--';
        const isPuente = (d.detector_id || '').includes('km11');

        const el = document.createElement('div');
        el.className = 'nd-map-marker';
        el.style.borderColor = color;
        el.style.color = color;
        el.style.width = isPuente ? '52px' : '44px';
        el.style.height = isPuente ? '52px' : '44px';
        el.style.fontSize = isPuente ? '13px' : '11px';
        el.style.opacity = isFreeFlow ? '0.5' : '1';
        el.textContent = spd;

        const ffsNote = d.free_flow_speed != null
          ? '<div style="color:var(--text-disabled);margin-top:2px;">libre ' + d.free_flow_speed.toFixed(0) + ' km/h</div>' : '';
        const statusNote = isFreeFlow
          ? '<div style="color:var(--text-disabled);margin-top:4px;font-size:9px;letter-spacing:0.06em;">SIN DATO REAL</div>'
          : '<div style="color:var(--success);margin-top:4px;font-size:9px;letter-spacing:0.06em;">EN TIEMPO REAL</div>';
        const flowNote = d.vehicle_flow != null
          ? '<div style="color:var(--text-secondary);margin-top:2px;">retardo: +' + d.vehicle_flow + 's</div>' : '';

        const popup = new maplibregl.Popup({ offset: 12, closeButton: true, maxWidth: '220px' })
          .setHTML('<div style="font-family:\\'Space Mono\\',monospace;font-size:11px;color:var(--text-primary);padding:12px 14px;line-height:1.6;">' +
            '<div style="font-size:9px;letter-spacing:0.08em;text-transform:uppercase;color:var(--text-secondary);margin-bottom:6px;">' + escapeHtml(d.detector_id) + '</div>' +
            '<div style="font-size:22px;font-weight:700;color:' + color + ';">' + escapeHtml(spd) + ' <span style="font-size:11px;">km/h</span></div>' +
            ffsNote + statusNote + flowNote +
            '</div>');

        const marker = new maplibregl.Marker({ element: el, anchor: 'center' })
          .setLngLat([d.longitude, d.latitude])
          .setPopup(popup)
          .addTo(ndMapSE30);
        ndMapSE30Markers['tt_' + d.detector_id] = marker;
      });

      if (tomtom.length > 0) {
        byId('se30-map-status').textContent = 'MapLibre GL \xb7 ' + tomtom.length + ' TomTom';
      }
    }

    /* ============================================================
       TAB VISTA — nuevo diseño: datos + animación
    ============================================================ */
    const NV_LEVELS = {
      fluido:            { color: 'var(--nv-ok)',     label: 'MUY FLUIDO',  verdict: 'Circulación libre',       sub: 'El puente fluye con total normalidad. Velocidades próximas al límite en ambos sentidos.' },
      denso:             { color: 'var(--nv-ok)',     label: 'FLUIDO',      verdict: 'Tráfico fluido',          sub: 'Tráfico notable pero ágil. Puedes cruzar sin problema a buena velocidad.' },
      retenciones:       { color: 'var(--nv-warn)',   label: 'DENSO',       verdict: 'Tráfico denso',           sub: 'Velocidad reducida. Espera más tiempo del habitual para cruzar.' },
      congestion_fuerte: { color: 'var(--nv-alert)',  label: 'RETENCIONES', verdict: 'Retenciones',             sub: 'Velocidades muy bajas y paradas frecuentes. Considera una ruta alternativa.' },
      colapso:           { color: 'var(--nv-danger)', label: 'COLAPSO',     verdict: 'Circulación muy lenta',   sub: 'El puente está colapsado. Evítalo y busca alternativa urgente.' },
      cortado:           { color: 'var(--nv-danger)', label: 'CORTADO',     verdict: 'Puente cortado',          sub: 'El Puente del Centenario está cortado (obras), según los paneles de la DGT. No es un atasco: coge una ruta alternativa.' },
    };
    function nv_scoreToLevel(s) {
      if (s < 8)  return 'fluido';
      if (s < 20) return 'denso';
      if (s < 42) return 'retenciones';
      if (s < 70) return 'congestion_fuerte';
      return 'colapso';
    }
    const nv_state = { trendStates: [], speedHistH: [], speedHistC: [], chartRange: 24, sceneSpeedH: null, sceneSpeedC: null, sceneRev: 'indeterminado' };

    function renderNuevo(data) {
      if (!data || !data.state) return;
      const state = data.state;
      nv_state.trendStates = data.trend_states || data.recent_states || [];
      const speedHist = data.tomtom_speed_history || [];
      nv_state.speedHistH = speedHist.filter(r => r.detector_id === 'tomtom_route_huelva' && r.average_speed != null);
      nv_state.speedHistC = speedHist.filter(r => r.detector_id === 'tomtom_route_cadiz'  && r.average_speed != null);
      nv_state.sceneSpeedH = null;
      nv_state.sceneSpeedC = null;
      const detectors = data.detectors || [];
      detectors.forEach(d => {
        if (d.detector_id === 'tomtom_route_huelva') nv_state.sceneSpeedH = d.average_speed;
        if (d.detector_id === 'tomtom_route_cadiz')  nv_state.sceneSpeedC = d.average_speed;
      });
      nv_state.sceneRev = state.reversible_probable || 'indeterminado';
      nv_renderHero(state);
      nv_renderSpeeds(detectors);
      if (byId('tab-nuevo') && byId('tab-nuevo').style.display !== 'none') {
        nv_renderChart();
      }
      nv_renderVms(data.panels || []);
      nv_renderIncidents(data.incidents || []);
      nv_updateRevVisual();
    }

    function nv_renderHero(state) {
      const score = parseFloat(state.traffic_score) || 0;
      // El cierre del puente lo marca el servidor (traffic_level='cortado'); es
      // un estado propio que no se deduce del score, así que tiene prioridad.
      const key = (state.traffic_level === 'cortado') ? 'cortado' : nv_scoreToLevel(score);
      const lv = NV_LEVELS[key] || NV_LEVELS.colapso;
      const v = byId('nv-verdict'); if (v) v.textContent = lv.verdict;
      const sub = byId('nv-verdictSub'); if (sub) sub.textContent = lv.sub;
      const sn = byId('nv-scoreNum'); if (sn) sn.textContent = score.toFixed(1);
      const chip = byId('nv-levelChip');
      if (chip) { chip.textContent = lv.label; chip.style.setProperty('--nv-chip-color', lv.color); }
      const dot = byId('nv-verdictDot'); if (dot) dot.style.background = lv.color;
      const label = byId('nv-verdictLabel');
      if (label) label.textContent = 'Estado · ' + new Date().toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
      const rev = state.reversible_probable;
      const conf = parseFloat(state.confidence) || 0;
      const arrow = byId('nv-revArrow');
      const dir = byId('nv-revDir');
      const rsub = byId('nv-revSub');
      const badgeH = byId('nv-badgeHuelva');
      const badgeC = byId('nv-badgeCadiz');
      if (rev === 'positive') {
        if (arrow) { arrow.textContent = '→'; arrow.style.transform = 'scaleX(-1)'; }
        if (dir) dir.textContent = 'Sentido Huelva';
        if (rsub) rsub.textContent = 'Carril reversible — sentido Huelva';
        if (badgeH) badgeH.style.display = 'inline-flex';
        if (badgeC) badgeC.style.display = 'none';
      } else if (rev === 'negative') {
        if (arrow) { arrow.textContent = '→'; arrow.style.transform = 'none'; }
        if (dir) dir.textContent = 'Sentido Cádiz';
        if (rsub) rsub.textContent = 'Carril reversible — sentido Cádiz';
        if (badgeH) badgeH.style.display = 'none';
        if (badgeC) badgeC.style.display = 'inline-flex';
      } else {
        if (arrow) { arrow.textContent = '—'; arrow.style.transform = 'none'; }
        if (dir) dir.textContent = 'Indeterminado';
        if (rsub) rsub.textContent = 'Sin señal clara del carril reversible';
        if (badgeH) badgeH.style.display = 'none';
        if (badgeC) badgeC.style.display = 'none';
      }
      const confPct = Math.round(conf * 100);
      const confLabel = byId('nv-confLabel'); if (confLabel) confLabel.textContent = confPct + '%';
      const confFill = byId('nv-confFill'); if (confFill) confFill.style.width = confPct + '%';
    }

    function nv_renderSpeeds(detectors) {
      const h = detectors.find(d => d.detector_id === 'tomtom_route_huelva');
      const c = detectors.find(d => d.detector_id === 'tomtom_route_cadiz');
      const apply = (idSpd, idBar, idFree, idDelay, d) => {
        if (!d || d.average_speed == null) { const el = byId(idSpd); if (el) el.textContent = '—'; return; }
        const spd = Math.round(d.average_speed);
        const pct = Math.min(100, (spd / 60) * 100);
        const ratio = spd / 60;
        const color = ratio > 0.8 ? 'var(--nv-ok)' : ratio > 0.55 ? 'var(--nv-warn)' : ratio > 0.3 ? 'var(--nv-alert)' : 'var(--nv-danger)';
        const sp = byId(idSpd); if (sp) sp.textContent = spd;
        const bar = byId(idBar); if (bar) { bar.style.width = pct + '%'; bar.style.background = color; }
        const fr = byId(idFree); if (fr) fr.textContent = Math.round(d.free_flow_speed || 60);
        const dl = byId(idDelay); if (dl) dl.textContent = d.vehicle_flow != null ? '+' + d.vehicle_flow + 's' : '—';
      };
      apply('nv-speedHuelva', 'nv-barHuelva', 'nv-freeHuelva', 'nv-delayHuelva', h);
      apply('nv-speedCadiz',  'nv-barCadiz',  'nv-freeCadiz',  'nv-delayCadiz',  c);
    }

    function nv_speedColor(v) {
      if (v == null) return '#666666';
      if (v >= 55) return '#4A9E5C';
      if (v >= 30) return '#D4A843';
      return '#D71921';
    }

    function nv_drawSpeedChart(svgId, containerId, history) {
      const svg = byId(svgId);
      const container = byId(containerId);
      if (!svg || !container) return;
      const W = container.clientWidth || 400;
      const H = container.clientHeight || 220;
      const pad = { l: 36, r: 12, t: 8, b: 22 };
      svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
      svg.innerHTML = '';
      const NS = 'http://www.w3.org/2000/svg';
      const mk = (tag, attrs) => { const el = document.createElementNS(NS, tag); Object.entries(attrs).forEach(([k,v]) => el.setAttribute(k, v)); return el; };

      const hrs = nv_state.chartRange || 24;
      const cutoff = Date.now() - hrs * 3600 * 1000;
      const data = (history || [])
        .map(r => ({ v: parseFloat(r.average_speed), t: new Date(r.collected_at) }))
        .filter(p => !isNaN(p.v) && p.t.getTime() >= cutoff)
        .sort((a, b) => a.t - b.t);

      if (!data.length) {
        const t = mk('text', { x: W/2, y: H/2, 'text-anchor': 'middle', fill: 'var(--nv-text-3)', 'font-size': '11', 'font-family': 'JetBrains Mono, monospace' });
        t.textContent = 'sin datos en el rango'; svg.appendChild(t);
        return;
      }

      // Límite legal del tramo: 60 km/h. Cualquier valor por encima se ajusta visualmente al techo.
      const maxY = 60;
      const xp = (i) => pad.l + (i / Math.max(data.length - 1, 1)) * (W - pad.l - pad.r);
      const yp = (v) => pad.t + (1 - Math.min(v, maxY) / maxY) * (H - pad.t - pad.b);

      // Líneas de referencia: 30 km/h (denso) y 55 km/h (fluido)
      [{ v: 30, c: '#D71921' }, { v: 55, c: '#4A9E5C' }].forEach(th => {
        svg.appendChild(mk('line', { x1: pad.l, x2: W - pad.r, y1: yp(th.v), y2: yp(th.v), stroke: th.c, 'stroke-width': '1', 'stroke-dasharray': '3 3', opacity: '0.35' }));
      });
      // Línea del límite (60 km/h) en el techo
      svg.appendChild(mk('line', { x1: pad.l, x2: W - pad.r, y1: yp(60), y2: yp(60), stroke: 'var(--nv-text-3)', 'stroke-width': '1', opacity: '0.35' }));
      // Etiquetas eje Y
      [0, 30, 55, 60].forEach(v => {
        const t = mk('text', { x: pad.l - 8, y: yp(v) + 3, 'text-anchor': 'end', fill: 'var(--nv-text-3)', 'font-size': '10', 'font-family': 'JetBrains Mono, monospace' });
        t.textContent = v; svg.appendChild(t);
      });
      // Etiquetas eje X (4-6 marcas)
      const step = Math.max(1, Math.floor(data.length / 5));
      for (let i = 0; i < data.length; i += step) {
        const t = mk('text', { x: xp(i), y: H - 6, 'text-anchor': 'middle', fill: 'var(--nv-text-3)', 'font-size': '10', 'font-family': 'JetBrains Mono, monospace' });
        t.textContent = data[i].t.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' }); svg.appendChild(t);
      }

      // Color del trazo según velocidad actual
      const c = nv_speedColor(data[data.length - 1].v);
      const gradId = svgId + 'Grad';
      const defs = document.createElementNS(NS, 'defs');
      const lg = mk('linearGradient', { id: gradId, x1: '0', y1: '0', x2: '0', y2: '1' });
      lg.innerHTML = `<stop offset="0%" stop-color="${c}" stop-opacity="0.32"/><stop offset="100%" stop-color="${c}" stop-opacity="0"/>`;
      defs.appendChild(lg); svg.appendChild(defs);
      const pathD = data.map((p, i) => `${i === 0 ? 'M' : 'L'} ${xp(i)} ${yp(p.v)}`).join(' ');
      svg.appendChild(mk('path', { d: `${pathD} L ${xp(data.length - 1)} ${yp(0)} L ${xp(0)} ${yp(0)} Z`, fill: `url(#${gradId})` }));
      svg.appendChild(mk('path', { d: pathD, fill: 'none', stroke: c, 'stroke-width': '2', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }));
      const li = data.length - 1;
      svg.appendChild(mk('circle', { cx: xp(li), cy: yp(data[li].v), r: '4', fill: c, stroke: 'var(--nv-surface)', 'stroke-width': '2' }));
    }

    function nv_renderChart() {
      nv_drawSpeedChart('nv-chartHuelvaSvg', 'nv-chartHuelvaContainer', nv_state.speedHistH);
      nv_drawSpeedChart('nv-chartCadizSvg',  'nv-chartCadizContainer',  nv_state.speedHistC);
    }

    document.querySelectorAll('#nv-rangeTabs .nv-tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('#nv-rangeTabs .nv-tab-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        nv_state.chartRange = parseInt(btn.dataset.nvRange, 10);
        nv_renderChart();
      });
    });

    const NV_PICTO_LABELS = {
      trafficCongestion: 'Retenciones',
      slowTraffic: 'Tráfico lento',
      stationaryTraffic: 'Tráfico detenido',
      queuingTraffic: 'Colas',
      keepASafeDistance: 'Mantenga distancia',
      roadworks: 'Obras',
      accident: 'Accidente',
      roadClosed: 'Vía cortada',
      laneClosed: 'Carril cortado',
      reducedVisibility: 'Visibilidad reducida',
      fog: 'Niebla',
      icyRoads: 'Carretera helada',
      slipperyRoads: 'Calzada deslizante',
      strongWind: 'Viento fuerte',
      heavyRain: 'Lluvia intensa',
      snow: 'Nieve',
      animalsOnTheRoad: 'Animales en la vía',
      objectOnRoad: 'Objetos en la vía',
      pedestrian: 'Peatones',
      reduceSpeed: 'Reduzca velocidad',
      noOvertaking: 'Prohibido adelantar',
      heavyVehicleProhibited: 'Camiones prohibidos',
      diversion: 'Desvío',
      detour: 'Desvío',
      checkBrakes: 'Comprobar frenos',
      otherDanger: 'Peligro',
      generalWarning: 'Atención',
      dangerousSituation: 'Situación peligrosa',
      // Pictogramas vacíos / sin imagen — se filtran fuera
      blankVoid: '',
      noPictogram: '',
      empty: '',
    };

    function nv_picto2text(picts) {
      return (picts || [])
        .map(p => {
          if (p in NV_PICTO_LABELS) return NV_PICTO_LABELS[p];
          // Heurística para nombres CamelCase desconocidos: separar palabras
          return p ? p.replace(/([a-z])([A-Z])/g, '$1 $2').replace(/^./, c => c.toUpperCase()) : '';
        })
        .filter(Boolean);
    }

    // Transforma abreviaturas DGT en lenguaje natural.
    function nv_humanizeDgtText(s) {
      if (!s) return '';
      let t = s;
      // Mapeo de abreviaturas frecuentes
      const map = [
        [/\bSTDO\.?\s+/gi, 'sentido '],
        [/\bSENTIDO\s+/gi, 'sentido '],
        [/\bEN\s+SE-?30\b/gi, 'en SE-30'],
        [/\bA\s+(\d+)\s*KM\b/gi, 'a $1 km'],
        [/\bEN\s+(\d+)\s*KM\b/gi, 'en $1 km'],
        [/\bKM\s*(\d+)\s*->\s*(\d+)\b/gi, 'del km $1 al $2'],
      ];
      map.forEach(([re, rep]) => { t = t.replace(re, rep); });
      // Mantener la primera letra en mayúscula del fragmento
      t = t.trim();
      if (t) t = t.charAt(0).toUpperCase() + t.slice(1).toLowerCase();
      // Pero respetar siglas conocidas que deben ir en mayúscula
      t = t.replace(/\bse-30\b/gi, 'SE-30').replace(/\bkm\b/gi, 'km');
      return t;
    }

    function nv_renderVms(panels) {
      const grid = byId('nv-vmsGrid'); if (!grid) return;
      // Solo el primer mensaje por panel (los paneles rotan páginas pero la
      // información esencial es la misma; mostrar todas duplica el motivo).
      const byLoc = {};
      panels.forEach(p => { if (!byLoc[p.location_id]) byLoc[p.location_id] = p; });
      const knownIds = ['60514', '60833', '60516'];
      let list = knownIds.map(id => byLoc[id] || byLoc['GUID_PMV_' + id]).filter(Boolean);
      if (!list.length) list = Object.values(byLoc).slice(0, 3);
      if (!list.length) {
        grid.innerHTML = '<div style="grid-column:1/-1;padding:24px;text-align:center;color:var(--nv-text-3);font-size:13px;">Sin mensajes de panel en el tramo.</div>';
        return;
      }
      grid.innerHTML = list.map(p => {
        const reasons = nv_picto2text(p.pictograms);
        const locationParts = (p.legends || [])
          .flatMap(l => String(l).split('/'))
          .map(s => nv_humanizeDgtText(s))
          .filter(Boolean);
        // Detectar el sentido a partir del propio texto (puede ser opuesto al
        // lado físico del panel).
        const rawText = (p.legends || []).join(' ').toUpperCase();
        let dirText;
        let dirInferredFromText = false;
        if (rawText.includes('STDO. HUELVA') || rawText.includes('SENTIDO HUELVA') || rawText.includes('STDO HUELVA')) {
          dirText = 'SENTIDO HUELVA';
          dirInferredFromText = true;
        } else if (rawText.includes('STDO. CÁDIZ') || rawText.includes('SENTIDO CÁDIZ') || rawText.includes('STDO. CADIZ') || rawText.includes('STDO CADIZ')) {
          dirText = 'SENTIDO CÁDIZ';
          dirInferredFromText = true;
        } else {
          dirText = p.direction === 'positive' ? 'SENTIDO HUELVA' : p.direction === 'negative' ? 'SENTIDO CÁDIZ' : 'SE-30';
        }
        // Si el sentido ya aparece en el footer, lo quitamos del cuerpo del
        // mensaje para no repetirlo.
        const cleanLocation = locationParts.filter(s => !/^sentido /i.test(s));
        // Componer frase natural:
        //   "Retenciones · Mantenga distancia. En SE-30, en 1 km."
        const reasonPart = reasons.join(' · ');
        const locationPart = cleanLocation.join(', ');
        const sentence = [reasonPart, locationPart].filter(Boolean).join('. ');
        const text = sentence ? sentence + '.' : '';
        const kmText = p.km != null ? 'KM ' + parseFloat(p.km).toFixed(1) : '—';
        const idShort = String(p.location_id).replace(/^GUID_PMV_/, '');
        return `<div class="nv-vms"><div class="nv-vms-meta"><span>PANEL ${escapeHtml(idShort)}</span><span>${escapeHtml(kmText)}</span></div><div class="nv-vms-screen${text ? '' : ' empty'}">${text ? escapeHtml(text) : '— SIN MENSAJE —'}</div><div class="nv-vms-footer"><span>${escapeHtml(dirText)}</span><span>SE-30</span></div></div>`;
      }).join('');
    }

    const NV_INC_ICONS = {
      accident: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
      roadClosed: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/></svg>',
      roadworks: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="m14.7 6.3-1 1a2 2 0 0 0 0 2.8l1.3 1.3a2 2 0 0 0 2.8 0l1-1"/><path d="m2 22 3-3"/><path d="M17 22 7 12l3-3 10 10"/></svg>',
    };
    const NV_INC_COLORS = { high: 'var(--nv-danger)', HIGH: 'var(--nv-danger)', highest: 'var(--nv-danger)', HIGHEST: 'var(--nv-danger)', medium: 'var(--nv-alert)', MEDIUM: 'var(--nv-alert)', low: 'var(--nv-warn)', LOW: 'var(--nv-warn)', lowest: 'var(--nv-text-2)', LOWEST: 'var(--nv-text-2)' };

    function nv_renderIncidents(incidents) {
      const list = byId('nv-incidentList'); if (!list) return;
      const count = byId('nv-incCount');
      const active = incidents.filter(i => (i.validity_status || '') !== 'suspended');
      if (count) count.textContent = active.length ? active.length + ' activa' + (active.length > 1 ? 's' : '') : '0 activas';
      if (!active.length) { list.innerHTML = '<div class="nv-card nv-empty">Ninguna incidencia activa en el tramo. ✓</div>'; return; }
      list.innerHTML = active.slice(0, 8).map(inc => {
        const color = NV_INC_COLORS[inc.severity] || 'var(--nv-text-2)';
        const dirText = inc.direction === 'positive' ? 'Sentido Huelva' : inc.direction === 'negative' ? 'Sentido Cádiz' : 'Ambos';
        const icon = NV_INC_ICONS[inc.incident_type] || NV_INC_ICONS.accident;
        const km = inc.from_km != null ? `<span class="nv-mono">km ${parseFloat(inc.from_km).toFixed(1)}</span>` : '';
        return `<div class="nv-incident" style="--nv-inc-color:${color}"><div class="nv-inc-ic">${icon}</div><div class="nv-inc-main"><div class="nv-inc-title">${escapeHtml(incidentLabel(inc.incident_type))}</div><div class="nv-inc-meta"><span class="nv-inc-severity">${escapeHtml(severityLabel(inc.severity))}</span><span>${escapeHtml(dirText)}</span>${km}<span>${escapeHtml(inc.source || 'DGT')}</span></div></div></div>`;
      }).join('');
    }

    async function nvReportReversible(direction) {
      const statusEl = byId('nv-reportStatus');
      const noteEl = byId('nv-reportNote');
      const note = noteEl && noteEl.value ? noteEl.value.trim() : '';
      if (statusEl) { statusEl.style.color = 'var(--nv-text-3)'; statusEl.textContent = 'Enviando…'; }
      try {
        const res = await fetch('/api/report-reversible', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ direction, note: note || undefined }) });
        if (!res.ok) throw new Error('Error ' + res.status);
        const labels = { positive: '← Huelva', negative: '→ Cádiz', none: 'Sin reversible' };
        if (statusEl) { statusEl.style.color = 'var(--nv-ok)'; statusEl.textContent = 'Registrado: ' + (labels[direction] || direction) + ' · ' + new Date().toLocaleTimeString('es-ES'); }
        if (noteEl) noteEl.value = '';
        ['nv-btn-report-huelva', 'nv-btn-report-cadiz', 'nv-btn-report-none'].forEach(id => { const b = byId(id); if (b) b.classList.remove('success'); });
        const ids = { positive: 'nv-btn-report-huelva', negative: 'nv-btn-report-cadiz', none: 'nv-btn-report-none' };
        const ab = byId(ids[direction]); if (ab) { ab.classList.add('success'); setTimeout(() => ab.classList.remove('success'), 3000); }
        await loadDashboard();
      } catch (e) {
        if (statusEl) { statusEl.style.color = 'var(--nv-danger)'; statusEl.textContent = 'Error: ' + e.message; }
      }
    }

    /* ---- Bridge scene animation (Three.js WebGL) ---- */
    // Bridge Z axis: z=100=km10(near/right), z=-100=km12(far/left)
    // Bridge X axis: x=+5.2=Huelva(near camera), x=0=reversible, x=-5.2=Cádiz(far)
    // Traffic: Huelva km10→km12 = z decreases (fwd=true); Cádiz km12→km10 = z increases (fwd=false)
    const NV_VT_SCALE = 1 / 400; // km/h → t/s  (traversal time ≈ 400/kmh s)
    const nv_scene = { huelva: [], reversible: [], cadiz: [], lastTs: 0, raf: null };
    let nv3 = null;

    function nv_t_to_z(t)  { return 100 - 200 * t; }   // t=0→z=100(km10), t=1→z=-100(km12)
    function nv_lt_to_x(lt){ return 5.2 - 10.4 * lt; } // lt=0→x=+5.2(Huelva), lt=1→x=-5.2(Cádiz)

    function nv_updateRevVisual() { /* Three.js render loop handles it */ }

    function nv_spawnCar(dir, lt, speedKmh) {
      const rnd = Math.random();
      const type = rnd < 0.11 ? 'truck' : rnd < 0.18 ? 'moto' : 'car';
      const mult = type === 'truck' ? 0.72 : type === 'moto' ? 1.08 : 1.0;
      const kmh = Math.max(5, speedKmh * mult + (Math.random() - 0.5) * 8);
      const t = dir === 'huelva' ? 0.02 : 0.98;
      return { t, lt, vt: (dir === 'huelva' ? 1 : -1) * kmh * NV_VT_SCALE, type, color: nv_pickCarColor3d(type), brake: Math.random() < 0.06, brakeTimer: 1 + Math.random() * 2 };
    }

    function nv_pickCarColor3d(type) {
      const dk = document.documentElement.getAttribute('data-theme') !== 'light';
      if (type === 'truck') {
        const p = dk ? ['#3a4a5a','#4a3a3a','#3a4a3a','#5a4a2a'] : ['#6a7888','#886868','#688868','#887060'];
        return p[Math.floor(Math.random() * p.length)];
      }
      if (type === 'moto') return dk ? '#c0c0c0' : '#505050';
      const p = dk ? ['#d0d4de','#a8b0c2','#8088a0','#e0c4a0','#98c0dc','#dc9c9c','#b8dc98','#dcdca0']
                   : ['#d8dce8','#b0b8cc','#c8d8e8','#e8cca8','#a8c8e8','#e8b0b0','#b0e8b8','#e8e8a8'];
      return p[Math.floor(Math.random() * p.length)];
    }

    function nv3_ensure(isDark) {
      if (!window.THREE) return false;
      const T = window.THREE;
      const canvas = byId('nv-sceneSvg');
      if (!canvas) return false;
      if (!nv3) {
        const renderer = new T.WebGLRenderer({ canvas, antialias: true });
        renderer.setSize(800, 240, false);
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        const scene = new T.Scene();
        const cam = new T.PerspectiveCamera(40, 800 / 240, 0.5, 1500);
        cam.position.set(-105, 28, 0);
        cam.lookAt(0, 21, 0);
        const carGroup = new T.Group();
        scene.add(carGroup);
        // Object pool: 100 slots, each with body + cab + headlights + brake lights
        const unitGeo = new T.BoxGeometry(1, 1, 1);
        const litGeo  = new T.BoxGeometry(1, 1, 0.12);
        const pool = [];
        for (let i = 0; i < 100; i++) {
          const body = new T.Mesh(unitGeo, new T.MeshLambertMaterial({ color: 0xffffff }));
          const cab  = new T.Mesh(unitGeo, new T.MeshLambertMaterial({ color: 0xffffff }));
          const head = new T.Mesh(litGeo,  new T.MeshBasicMaterial({ color: 0xfff9c0 }));
          const rl   = new T.Mesh(litGeo,  new T.MeshBasicMaterial({ color: 0xff2a10 }));
          body.visible = cab.visible = head.visible = rl.visible = false;
          carGroup.add(body, cab, head, rl);
          pool.push({ body, cab, head, rl });
        }
        nv3 = { renderer, scene, cam, carGroup, pool, revLane: null, lastDark: null };
      }
      if (nv3.lastDark !== isDark) { nv3.lastDark = isDark; nv3_buildStatic(isDark); }
      return true;
    }

    function nv3_buildStatic(isDark) {
      const T = window.THREE;
      for (let i = nv3.scene.children.length - 1; i >= 0; i--) {
        const c = nv3.scene.children[i]; if (c !== nv3.carGroup) nv3.scene.remove(c);
      }
      nv3.scene.background = new T.Color(isDark ? 0x06090e : 0xc0d6ee);
      nv3.scene.fog = new T.Fog(isDark ? 0x060a12 : 0xb8d2ec, 220, 520);
      nv3.scene.add(new T.AmbientLight(0xffffff, isDark ? 0.68 : 0.90));
      const sun = new T.DirectionalLight(isDark ? 0xd8e4ff : 0xfff8e0, isDark ? 0.48 : 0.62);
      sun.position.set(-60, 100, 80); nv3.scene.add(sun);
      // Water
      const water = new T.Mesh(new T.PlaneGeometry(600, 500), new T.MeshBasicMaterial({ color: isDark ? 0x07101c : 0x7aa4c4 }));
      water.rotation.x = -Math.PI / 2; water.position.y = -1.65; nv3.scene.add(water);
      // Bridge deck
      nv3.scene.add(Object.assign(new T.Mesh(new T.BoxGeometry(15.6, 0.56, 500), new T.MeshLambertMaterial({ color: isDark ? 0x16202e : 0x2a3244 }))));
      // Lane dividers (4 lines = 3 lanes)
      const divMat = new T.MeshBasicMaterial({ color: isDark ? 0x263348 : 0x3c4c66 });
      [-7.8, -2.6, 2.6, 7.8].forEach(x => { const d = new T.Mesh(new T.BoxGeometry(0.18, 0.62, 500), divMat); d.position.set(x, 0.03, 0); nv3.scene.add(d); });
      // Reversible lane glow (blue overlay on center lane)
      nv3.revLane = new T.Mesh(new T.BoxGeometry(5.2, 0.02, 500), new T.MeshBasicMaterial({ color: 0x4a80ff, transparent: true, opacity: 0, depthWrite: false }));
      nv3.revLane.position.set(0, 0.3, 0); nv3.scene.add(nv3.revLane);
      // Pylons + cables (two pylons: near at z=56, far at z=-56)
      const pMat = new T.MeshLambertMaterial({ color: isDark ? 0x20304a : 0x202c3e });
      const lMat = new T.LineBasicMaterial({ color: isDark ? 0x3a4e7a : 0x6070a0, transparent: true, opacity: 0.6 });
      [{ z: 56, h: 44 }, { z: -56, h: 44 }].forEach(({ z, h }) => {
        const pylon = new T.Mesh(new T.BoxGeometry(1.5, h, 1.5), pMat.clone());
        pylon.position.set(0, h / 2 + 0.28, z); nv3.scene.add(pylon);
        const ty = h + 0.28, pts = [];
        [-88, -60, -36, -12, 12, 36, 60, 88].forEach(dz => {
          const cz = Math.max(-250, Math.min(250, z + dz));
          pts.push(0, ty, z,  7.8, 0.28, cz); // Huelva-side cable
          pts.push(0, ty, z, -7.8, 0.28, cz); // Cádiz-side cable
        });
        const geo = new T.BufferGeometry(); geo.setAttribute('position', new T.BufferAttribute(new Float32Array(pts), 3));
        nv3.scene.add(new T.LineSegments(geo, lMat.clone()));
      });
    }

    function nv3_renderCars(rev) {
      const T = window.THREE;
      // Hide all pool slots
      nv3.pool.forEach(p => { p.body.visible=false; p.cab.visible=false; p.head.visible=false; p.rl.visible=false; });
      // Collect all cars, Cádiz first (behind), then reversible, then Huelva (in front)
      const allCars = [
        ...nv_scene.cadiz.map(c => ({ ...c, fwd: false })),
        ...nv_scene.reversible.map(c => ({ ...c, fwd: rev === 'positive' })),
        ...nv_scene.huelva.map(c => ({ ...c, fwd: true })),
      ];
      let pi = 0;
      allCars.forEach(car => {
        if (pi >= nv3.pool.length) return;
        const p = nv3.pool[pi++];
        const cz = nv_t_to_z(car.t), cx = nv_lt_to_x(car.lt);
        const cL = car.type === 'truck' ? 8.5  : car.type === 'moto' ? 2.5  : 4.5;
        const cW = car.type === 'truck' ? 2.15 : car.type === 'moto' ? 0.78 : 1.75;
        const cH = car.type === 'truck' ? 2.2  : car.type === 'moto' ? 0.82 : 1.3;
        const cy = cH / 2 + 0.28;
        p.body.scale.set(cW, cH, cL); p.body.position.set(cx, cy, cz);
        p.body.material.color.set(car.color); p.body.visible = true;
        // Headlights (front in direction of travel; Huelva fwd=true → z decreases → front at lower z)
        const hlZ = cz + (car.fwd ? -cL/2 - 0.08 : cL/2 + 0.08);
        p.head.scale.set(cW * 0.55, cH * 0.28, 1); p.head.position.set(cx, cy + cH * 0.06, hlZ); p.head.visible = true;
        // Brake lights
        if (car.brake || Math.abs(car.vt) < 0.014) {
          const rlZ = cz + (car.fwd ? cL/2 + 0.08 : -cL/2 - 0.08);
          p.rl.scale.set(cW * 0.55, cH * 0.28, 1); p.rl.position.set(cx, cy + cH * 0.06, rlZ); p.rl.visible = true;
        }
        // Truck cab (brighter box at front)
        if (car.type === 'truck') {
          const cabZ = cz + (car.fwd ? -cL/2 + 1.5 : cL/2 - 1.5);
          p.cab.scale.set(cW, cH, 3.0); p.cab.position.set(cx, cy, cabZ);
          const cc = new T.Color(car.color); cc.multiplyScalar(1.22);
          p.cab.material.color.copy(cc); p.cab.visible = true;
        }
      });
      // Reversible lane glow
      if (nv3.revLane) nv3.revLane.material.opacity = (rev === 'positive' || rev === 'negative') ? 0.24 : 0;
    }

    function nv_stepScene(ts) {
      if (!nv_scene.lastTs) nv_scene.lastTs = ts;
      const dt = Math.min(0.08, (ts - nv_scene.lastTs) / 1000);
      nv_scene.lastTs = ts;
      const spdH = nv_state.sceneSpeedH != null ? nv_state.sceneSpeedH : 52;
      const spdC = nv_state.sceneSpeedC != null ? nv_state.sceneSpeedC : 50;
      const rev = nv_state.sceneRev;
      const densH = Math.max(0.25, Math.min(3.5, 18 / Math.max(spdH, 5)));
      const densC = Math.max(0.25, Math.min(3.5, 18 / Math.max(spdC, 5)));
      const canSpawnH   = () => !nv_scene.huelva.some(c => c.t < 0.07);
      const canSpawnC   = () => !nv_scene.cadiz.some(c => c.t > 0.93);
      const canSpawnRH  = () => !nv_scene.reversible.some(c => c.t < 0.07);
      const canSpawnRC  = () => !nv_scene.reversible.some(c => c.t > 0.93);
      if (Math.random() < densH * dt && canSpawnH()) nv_scene.huelva.push(nv_spawnCar('huelva', 0.0, spdH));
      if (Math.random() < densC * dt && canSpawnC()) nv_scene.cadiz.push(nv_spawnCar('cadiz', 1.0, spdC));
      if (rev === 'positive' && Math.random() < densH * 0.8 * dt && canSpawnRH()) nv_scene.reversible.push(nv_spawnCar('huelva', 0.5, spdH));
      else if (rev === 'negative' && Math.random() < densC * 0.8 * dt && canSpawnRC()) nv_scene.reversible.push(nv_spawnCar('cadiz', 0.5, spdC));
      const updateLane = (cars, dirSign) => {
        cars.sort((a, b) => dirSign > 0 ? b.t - a.t : a.t - b.t); // leader first
        for (let i = 0; i < cars.length; i++) {
          const c = cars[i], leader = cars[i - 1];
          let tv = Math.abs(c.vt);
          if (leader) { const gap = (leader.t - c.t) * dirSign; if (gap < 0.05) tv = Math.min(tv, Math.abs(leader.vt) * Math.max(0, gap / 0.05)); }
          if (c.brake) { c.brakeTimer -= dt; if (c.brakeTimer <= 0) c.brake = false; tv *= 0.3; }
          c.t += dirSign * tv * dt;
          if ((dirSign > 0 && c.t > 1.02) || (dirSign < 0 && c.t < -0.02)) cars.splice(i--, 1);
        }
      };
      updateLane(nv_scene.huelva, 1); updateLane(nv_scene.cadiz, -1);
      if (rev === 'positive') updateLane(nv_scene.reversible, 1);
      else if (rev === 'negative') updateLane(nv_scene.reversible, -1);
      else { for (let i = nv_scene.reversible.length - 1; i >= 0; i--) { const c = nv_scene.reversible[i]; c.t += c.vt * dt; if (c.t < -0.02 || c.t > 1.02) nv_scene.reversible.splice(i, 1); } }
      const capH = spdH < 20 ? 44 : 26, capC = spdC < 20 ? 44 : 26;
      if (nv_scene.huelva.length > capH) nv_scene.huelva.splice(0, nv_scene.huelva.length - capH);
      if (nv_scene.cadiz.length > capC) nv_scene.cadiz.splice(0, nv_scene.cadiz.length - capC);
      if (nv_scene.reversible.length > 22) nv_scene.reversible.splice(0, nv_scene.reversible.length - 22);
      // Render with Three.js
      const isDark = document.documentElement.getAttribute('data-theme') !== 'light';
      if (nv3_ensure(isDark)) { nv3_renderCars(rev); nv3.renderer.render(nv3.scene, nv3.cam); }
      const totalH = nv_scene.huelva.length + (rev === 'positive' ? nv_scene.reversible.length : 0);
      const totalC = nv_scene.cadiz.length  + (rev === 'negative' ? nv_scene.reversible.length : 0);
      const hc = byId('nv-sceneHuelvaCount'); if (hc) hc.textContent = totalH;
      const cc = byId('nv-sceneCadizCount'); if (cc) cc.textContent = totalC;
      const st = byId('nv-sceneTempo'); if (st) st.textContent = `H:${Math.round(spdH)} · C:${Math.round(spdC)} km/h`;
      nv_scene.raf = requestAnimationFrame(nv_stepScene);
    }

    function nv_startScene() {
      if (nv_scene.raf) return;
      if (!window.THREE) { setTimeout(nv_startScene, 200); return; }
      nv_scene.lastTs = 0;
      nv_scene.raf = requestAnimationFrame(nv_stepScene);
    }

    function nv_stopScene() {
      if (nv_scene.raf) { cancelAnimationFrame(nv_scene.raf); nv_scene.raf = null; }
      nv_scene.huelva = []; nv_scene.reversible = []; nv_scene.cadiz = [];
      if (nv3 && nv3.pool) { nv3.pool.forEach(p => { p.body.visible=false; p.cab.visible=false; p.head.visible=false; p.rl.visible=false; }); nv3.renderer.render(nv3.scene, nv3.cam); }
    }

    loadDashboard().catch((error) => {
      byId("heroDetail").textContent = `[ERROR] ${error.message}`;
    });
    window.setInterval(() => {
      loadDashboard().catch(() => {});
    }, 60000);

    // Refresco de la imagen de la cámara DGT cada 30 s. Añadimos un parámetro
    // único de cache-busting para forzar la recarga aunque el navegador cachee.
    function nv_refreshDgtCam() {
      const img = document.getElementById('nv-dgtCam');
      const stamp = document.getElementById('nv-dgtCamTime');
      if (!img) return;
      const url = 'https://infocar.dgt.es/etraffic/data/camaras/1337.jpg?t=' + Date.now();
      img.src = url;
      img.style.display = 'block';
      if (img.nextElementSibling) img.nextElementSibling.style.display = 'none';
      if (stamp) stamp.textContent = new Date().toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    }
    nv_refreshDgtCam();
    window.setInterval(nv_refreshDgtCam, 30000);
  </script>
</body>
</html>
"""


_FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="10" fill="#000000"/>
  <text x="32" y="48" font-family="'Inter','Arial',sans-serif" font-size="46" font-weight="800" fill="#D71921" text-anchor="middle">5</text>
</svg>"""


# --- Páginas de contenido estáticas -----------------------------------------
# Plantilla compartida para todas las páginas informativas (privacidad, guías,
# metodología, FAQ...). Cada una es una URL propia con texto original y
# navegación interna entre ellas: estructura que los buscadores indexan como
# contenido de valor, a diferencia de las pestañas dinámicas del dashboard.

_CONTENT_NAV_LINKS = (
    ("/", "Monitor"),
    ("/estado-semana", "Esta semana"),
    ("/puente", "El puente"),
    ("/carril-reversible", "Carril reversible"),
    ("/metodologia", "Cómo medimos"),
    ("/faq", "Preguntas frecuentes"),
    ("/sobre", "Sobre el sitio"),
    ("/privacidad", "Privacidad"),
)


def _content_page(slug: str, title: str, description: str, body: str) -> str:
    """Envuelve el cuerpo HTML de una página informativa en la plantilla común."""
    adsense_meta = (
        f'  <meta name="google-adsense-account" content="{ADSENSE_CLIENT_ID}">\n'
        if ADSENSE_CLIENT_ID
        else ""
    )
    nav = "\n".join(
        '      <a href="{href}"{cls}>{label}</a>'.format(
            href=href,
            label=label,
            cls=' aria-current="page" class="active"' if href == slug else "",
        )
        for href, label in _CONTENT_NAV_LINKS
    )
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="{description}">
{adsense_meta}  <link rel="icon" type="image/svg+xml" href="/favicon.svg">
  <link rel="canonical" href="https://5centenario.es{slug if slug != '/' else ''}">
  <title>{title} · 5centenario.es</title>
  <style>
    :root {{ --red: #B8141C; }}
    * {{ box-sizing: border-box; }}
    body {{ font-family: system-ui, -apple-system, sans-serif; max-width: 760px; margin: 0 auto; padding: 0 20px 64px; color: #1a1a1a; line-height: 1.7; }}
    nav.site {{ display: flex; flex-wrap: wrap; gap: 4px 18px; align-items: center; padding: 16px 0; margin-bottom: 8px; border-bottom: 1px solid #e6e6e6; font-size: 0.85rem; }}
    nav.site a {{ color: #555; text-decoration: none; }}
    nav.site a:hover {{ color: var(--red); }}
    nav.site a.active {{ color: var(--red); font-weight: 600; }}
    h1 {{ font-size: 1.7rem; margin: 28px 0 8px; line-height: 1.25; }}
    h2 {{ font-size: 1.15rem; margin-top: 36px; margin-bottom: 8px; }}
    h3 {{ font-size: 1rem; margin-top: 24px; margin-bottom: 6px; }}
    p, li {{ font-size: 0.97rem; color: #333; }}
    ul, ol {{ padding-left: 22px; }}
    li {{ margin-bottom: 6px; }}
    a {{ color: var(--red); }}
    .lead {{ font-size: 1.05rem; color: #222; }}
    .updated {{ font-size: 0.85rem; color: #999; margin-top: 0; }}
    table {{ width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 0.92rem; }}
    th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid #e6e6e6; vertical-align: top; }}
    th {{ color: #666; font-weight: 600; }}
    .note {{ background: #faf6f6; border-left: 3px solid var(--red); padding: 12px 16px; border-radius: 6px; margin: 18px 0; font-size: 0.92rem; }}
    footer {{ margin-top: 56px; padding-top: 18px; border-top: 1px solid #e6e6e6; font-size: 0.85rem; color: #888; }}
    footer a {{ color: #888; }}
  </style>
</head>
<body>
  <nav class="site">
{nav}
  </nav>
  {body}
  <footer>
    <p>5centenario.es · Monitor del tráfico del Puente del Centenario (SE-30, Sevilla). Proyecto personal e independiente, sin relación con la DGT, el Ministerio de Transportes ni TomTom.</p>
    <p><a href="/">Volver al monitor en tiempo real</a></p>
  </footer>
</body>
</html>"""


_PUENTE_BODY = """  <h1>El Puente del Centenario de Sevilla</h1>
  <p class="updated">Ficha informativa · actualizada en junio de 2026</p>
  <p class="lead">El Puente del Centenario es el gran puente atirantado que cruza la dársena del Guadalquivir al sur de Sevilla y une las dos orillas dentro de la circunvalación SE-30. Por él pasan más de <strong>100.000 vehículos al día</strong>, lo que lo convierte en uno de los puntos de tráfico más sensibles de toda Andalucía.</p>

  <h2>Datos básicos</h2>
  <table>
    <tr><th>Ubicación</th><td>SE-30, p.k. 10+000 a 12+000 · Sevilla</td></tr>
    <tr><th>Inauguración</th><td>15 de noviembre de 1991, dentro de las obras previas a la Exposición Universal de 1992</td></tr>
    <tr><th>Tipo</th><td>Puente atirantado sobre dos viaductos de acceso</td></tr>
    <tr><th>Vano atirantado</th><td>564 m de longitud, con un vano central de 265 m</td></tr>
    <tr><th>Tirantes</th><td>88 cables (22 pares por pila)</td></tr>
    <tr><th>Tráfico medio</th><td>Más de 100.000 vehículos/día, con cerca de un 9 % de pesados</td></tr>
  </table>

  <h2>Por qué se satura</h2>
  <p>El puente nació pequeño para la demanda que tendría. Ya en marzo de 1992, pocos meses después de abrirse, hubo que adoptar una solución de urgencia: eliminar la mediana de hormigón y los arcenes para habilitar un tercer carril por sentido. Pero en la zona atirantada central no cabían tres carriles por sentido, así que esa parte quedó con una configuración de <strong>2 carriles + 1 carril reversible + 2 carriles</strong>.</p>
  <p>Ese carril reversible es, desde entonces, el gran cuello de botella del puente: en hora punta concentra toda la presión de tráfico de la SE-30 en un único tramo de capacidad reducida.</p>

  <h2>Las obras de ampliación</h2>
  <p>En abril de 2021 se adjudicó el proyecto de <strong>sustitución de los 88 tirantes</strong> y ampliación de la plataforma. La idea de fondo es que, una vez instalada la nueva familia de tirantes que sostiene el tablero, se puedan retirar los antiguos y reaprovechar el espacio para llegar a una configuración final de <strong>tres carriles por sentido en toda la longitud del puente</strong>, eliminando así el cuello de botella del carril reversible.</p>
  <div class="note">Mientras esas obras avanzan, el carril reversible sigue en uso y su sentido puede cambiar a lo largo del día. Este sitio existe precisamente para estimar, a partir de datos públicos, en qué estado se encuentra el tráfico del tramo en cada momento.</div>

  <p>¿Quieres saber cómo funciona ese carril? Consulta la <a href="/carril-reversible">guía del carril reversible</a>. ¿Te interesa de dónde salen los datos? Mira <a href="/metodologia">cómo medimos el tráfico</a>. Y si quieres cifras concretas, el resumen de <a href="/estado-semana">cómo ha estado el tráfico esta semana</a> recoge las velocidades medias por sentido de los últimos días.</p>"""


_CARRIL_BODY = """  <h1>Cómo funciona el carril reversible del Puente del Centenario</h1>
  <p class="updated">Guía práctica · actualizada en junio de 2026</p>
  <p class="lead">En la zona atirantada del puente, la calzada se organiza como <strong>2 carriles + 1 carril reversible + 2 carriles</strong>. Ese carril central no pertenece de forma fija a ningún sentido: se asigna a la dirección con más tráfico en cada franja horaria para repartir mejor la capacidad.</p>

  <h2>Qué es un carril reversible</h2>
  <p>Un carril reversible es un carril que cambia de sentido de circulación según la hora del día. Cuando la mayoría del tráfico va en una dirección (por ejemplo, por la mañana hacia un lado y por la tarde hacia el otro), dedicarle un carril extra a ese sentido aumenta la capacidad sin necesidad de construir más calzada.</p>

  <h2>Cómo saber qué sentido está abierto</h2>
  <p>El sentido del carril reversible lo fijan los gestores de la vía y se señaliza sobre el propio puente con <strong>aspas rojas y flechas verdes</strong> en pórticos sobre cada carril:</p>
  <ul>
    <li><strong>Flecha verde (↓):</strong> el carril está abierto en tu sentido, puedes circular por él.</li>
    <li><strong>Aspa roja (✕):</strong> el carril está cerrado en tu sentido; no debes invadirlo porque puede tener tráfico de frente.</li>
  </ul>
  <div class="note"><strong>Norma de oro:</strong> haz caso siempre a la señalización luminosa del propio puente. Una estimación en una web —incluida esta— nunca sustituye a las aspas y flechas reales sobre la calzada.</div>

  <h2>Patrón habitual de uso</h2>
  <p>Como en casi todos los carriles reversibles urbanos, el reparto sigue el patrón de los desplazamientos diarios: más capacidad hacia el sentido de entrada a la ciudad por la mañana y hacia el de salida por la tarde. Aun así, el horario concreto puede variar por obras, incidentes o decisiones puntuales de tráfico, por lo que no publicamos un horario fijo: lo que hacemos es <a href="/metodologia">estimar el estado en tiempo real</a> a partir de la velocidad y los avisos de los paneles.</p>

  <h2>Cómo lo estima este sitio</h2>
  <p>No tenemos acceso directo al sistema de señalización del puente. Lo que hacemos es inferir el estado probable combinando varias señales públicas: la diferencia de velocidad entre ambos sentidos, los mensajes de los paneles informativos (VMS) de la DGT y las incidencias registradas en el tramo. El resultado se acompaña siempre de un <strong>nivel de confianza</strong>, porque es una estimación, no una lectura oficial.</p>
  <p>Puedes ver esa estimación, junto con la velocidad por sentido, en el <a href="/">monitor en tiempo real</a>.</p>"""


_METODOLOGIA_BODY = """  <h1>Cómo medimos el tráfico del puente</h1>
  <p class="updated">Metodología · actualizada en junio de 2026</p>
  <p class="lead">Este sitio no instala sensores propios ni tiene acceso interno a los sistemas de tráfico. Combina <strong>fuentes de datos públicas</strong> para estimar el estado del tramo SE-30 km 10–12 y lo resume en un nivel de congestión y una probabilidad de carril reversible, siempre con un indicador de confianza.</p>

  <h2>Fuentes de datos</h2>
  <table>
    <tr><th>Paneles VMS (DGT)</th><td>Mensajes de los paneles informativos del tramo, vía feed público DATEX2. Es la señal más directa de cortes, obras o reversibilidad activa.</td></tr>
    <tr><th>Incidencias (DGT)</th><td>Accidentes, cortes y retenciones publicados en el feed DATEX2 de incidencias.</td></tr>
    <tr><th>Velocidad (TomTom)</th><td>Se calculan dos rutas, una por sentido (hacia Huelva y hacia Cádiz), para estimar la velocidad media real frente a la velocidad en condiciones libres.</td></tr>
  </table>
  <div class="note">Los datos se refrescan aproximadamente cada 5 minutos. En un tramo tan corto (2 km), la velocidad media es sensible a eventos puntuales, por eso interpretamos las cifras como tendencia, no como medida exacta.</div>
  <p>Con esas lecturas elaboramos también un resumen de <a href="/estado-semana">cómo ha estado el tráfico esta semana</a>: velocidad media por sentido día a día y reparto de los niveles de congestión.</p>

  <h2>Cómo se calcula el estado</h2>
  <p>A partir de esas señales construimos una <strong>puntuación de tráfico</strong> (<em>traffic score</em>) que pondera cada fuente: palabras clave y pictogramas de los paneles, gravedad de las incidencias y la caída de velocidad respecto al flujo libre. La puntuación se normaliza para que no dependa de cuántos sensores estén activos en ese momento.</p>
  <p>Con esa puntuación clasificamos el tráfico en cuatro niveles:</p>
  <ul>
    <li><strong>Fluido</strong> — circulación normal, sin retenciones apreciables.</li>
    <li><strong>Denso</strong> — tráfico intenso pero en movimiento.</li>
    <li><strong>Retenciones</strong> — velocidad reducida y colas intermitentes.</li>
    <li><strong>Congestión fuerte</strong> — circulación muy lenta o detenida.</li>
  </ul>

  <h2>La estimación del carril reversible</h2>
  <p>El estado probable del <a href="/carril-reversible">carril reversible</a> se infiere combinando la presión de tráfico de cada sentido con una ventana temporal que evita que la predicción oscile de forma brusca. El resultado se ajusta con una línea base histórica que aprende de los patrones de las horas y días anteriores.</p>

  <h2>Limitaciones honestas</h2>
  <p>Es importante entenderlo bien:</p>
  <ul>
    <li>Es una <strong>estimación</strong>, no un dato oficial. La señalización del puente siempre manda.</li>
    <li>El tramo es corto, así que un solo vehículo lento puede mover la velocidad media varios km/h.</li>
    <li>Las fuentes públicas pueden tener retardos o quedarse temporalmente sin actualizar.</li>
  </ul>
  <p>Por eso cada estimación se muestra con un nivel de confianza. Cuando las fuentes no son fiables, lo decimos.</p>"""


_FAQ_BODY = """  <h1>Preguntas frecuentes</h1>
  <p class="updated">Actualizada en junio de 2026</p>
  <p class="lead">Dudas habituales sobre el Puente del Centenario, su carril reversible y cómo funciona este monitor de tráfico.</p>

  <h2>¿En qué sentido está ahora el carril reversible?</h2>
  <p>Mostramos una <strong>estimación</strong> del estado en el <a href="/">monitor en tiempo real</a>, basada en la velocidad por sentido y los avisos de los paneles. No es una lectura oficial: para circular, haz siempre caso a las aspas rojas y flechas verdes señalizadas sobre el propio puente. Más detalle en la <a href="/carril-reversible">guía del carril reversible</a>.</p>

  <h2>¿A qué hora cambia de sentido?</h2>
  <p>No publicamos un horario fijo porque puede variar por obras, incidentes o decisiones puntuales de tráfico. El reparto suele seguir el patrón de los desplazamientos diarios (entrada a la ciudad por la mañana, salida por la tarde), pero lo que ofrecemos es una estimación en tiempo real, no un calendario.</p>

  <h2>¿De dónde salen los datos?</h2>
  <p>De fuentes públicas: los paneles informativos (VMS) y las incidencias de la DGT mediante feeds DATEX2, y la velocidad por sentido a partir de la API de rutas de TomTom. Lo explicamos en detalle en <a href="/metodologia">cómo medimos el tráfico</a>.</p>

  <h2>¿Cada cuánto se actualiza?</h2>
  <p>Aproximadamente cada 5 minutos. La interfaz refresca la vista de forma automática mientras la tienes abierta.</p>

  <h2>¿Cómo ha estado el tráfico estos días?</h2>
  <p>Publicamos un resumen automático de <a href="/estado-semana">cómo ha estado el tráfico esta semana</a>, con la velocidad media de cada sentido día a día y el porcentaje de tiempo que el tramo ha estado fluido, denso o con retenciones. Se genera solo a partir de los datos registrados.</p>

  <h2>¿Por qué a veces el panel y la velocidad no coinciden?</h2>
  <p>Porque miden cosas distintas y pueden llevar retardos diferentes. Un panel puede seguir mostrando un aviso de obras antiguo mientras el tráfico ya circula con fluidez, o la velocidad puede caer por un incidente que aún no aparece en ningún feed. Por eso combinamos varias señales y mostramos un nivel de confianza.</p>

  <h2>¿Por qué se está ampliando el puente?</h2>
  <p>Para eliminar el cuello de botella del carril reversible. Las obras sustituyen los 88 tirantes y buscan una configuración final de tres carriles por sentido en toda la longitud. Lo contamos en la ficha de <a href="/puente">el Puente del Centenario</a>.</p>

  <h2>¿Este sitio es oficial?</h2>
  <p>No. Es un proyecto personal e independiente, sin relación con la DGT, el Ministerio de Transportes ni TomTom. Más información en <a href="/sobre">sobre el sitio</a>.</p>"""


_SOBRE_BODY = """  <h1>Sobre 5centenario.es</h1>
  <p class="updated">Actualizada en junio de 2026</p>
  <p class="lead">5centenario.es es un proyecto personal e independiente que monitoriza en tiempo real el tráfico del Puente del Centenario, en la SE-30 de Sevilla (km 10–12).</p>

  <h2>Por qué existe</h2>
  <p>El Puente del Centenario es uno de los puntos de tráfico más conflictivos de Sevilla, y su carril reversible hace que el estado de la circulación cambie a lo largo del día. La idea de este sitio es sencilla: reunir en un solo lugar, de forma clara, las señales públicas que ayudan a entender cómo está el tráfico del puente en cada momento, con una estimación del estado del carril reversible.</p>

  <h2>Cómo funciona</h2>
  <p>Recogemos datos abiertos de la DGT (paneles e incidencias) y de TomTom (velocidad por sentido), los combinamos y los resumimos en un nivel de congestión y una probabilidad de carril reversible. Todo el detalle está en <a href="/metodologia">cómo medimos el tráfico</a>.</p>

  <h2>Independencia</h2>
  <p>Este sitio <strong>no es oficial</strong> y no está afiliado a la DGT, al Ministerio de Transportes y Movilidad Sostenible ni a TomTom. Las marcas y datos citados pertenecen a sus respectivos titulares y se usan únicamente para identificar el origen de la información pública.</p>

  <h2>Aviso importante</h2>
  <div class="note">La información de este sitio es una <strong>estimación orientativa</strong> y puede contener errores o retardos. No debe usarse como única referencia para la conducción. Respeta siempre la señalización de la vía y las indicaciones de las autoridades de tráfico.</div>

  <h2>Contacto</h2>
  <p>¿Sugerencias, erratas o algo que no cuadra? Escríbenos a <a href="mailto:bis_ceros.7v@icloud.com">bis_ceros.7v@icloud.com</a>.</p>
  <p>Consulta también nuestra <a href="/privacidad">política de privacidad</a>.</p>"""


_PRIVACIDAD_BODY = """  <h1>Política de Privacidad</h1>
  <p class="updated">Última actualización: junio de 2026</p>

  <h2>Responsable</h2>
  <p>Este sitio web, <strong>5centenario.es</strong>, es un proyecto personal sin ánimo de lucro que monitoriza el tráfico en el Puente del Centenario (SE-30, Sevilla). No existe una entidad legal asociada. Para cualquier consulta: <a href="mailto:bis_ceros.7v@icloud.com">bis_ceros.7v@icloud.com</a></p>

  <h2>Datos que recogemos</h2>
  <p>Este sitio <strong>no recoge datos personales</strong> directamente. No hay formularios de registro, ni cuentas de usuario, ni seguimiento individualizado de visitantes.</p>
  <p>Nuestro servidor web registra automáticamente la dirección IP de cada petición en logs de acceso estándar. Estos logs se conservan durante un máximo de 30 días y se utilizan exclusivamente para diagnosticar errores.</p>

  <h2>Cookies y publicidad</h2>
  <p>Este sitio utiliza <strong>Google AdSense</strong> para mostrar publicidad. Google puede utilizar cookies para mostrar anuncios personalizados basados en tus visitas anteriores a este y otros sitios web.</p>
  <p>Puedes desactivar la publicidad personalizada de Google en: <a href="https://www.google.com/settings/ads" target="_blank" rel="noopener">google.com/settings/ads</a></p>
  <p>Para más información sobre cómo Google utiliza los datos: <a href="https://policies.google.com/technologies/partner-sites" target="_blank" rel="noopener">policies.google.com/technologies/partner-sites</a></p>

  <h2>Fuentes de datos de tráfico</h2>
  <p>Los datos de tráfico mostrados proceden de fuentes públicas:</p>
  <ul>
    <li>DGT (Dirección General de Tráfico) — feeds DATEX2 de acceso público</li>
    <li>TomTom Routing API — estimación de velocidad por sentido</li>
  </ul>
  <p>No se recogen, almacenan ni comparten datos de identificación de vehículos ni conductores.</p>

  <h2>Tus derechos</h2>
  <p>Dado que no procesamos datos personales identificables, no aplican los derechos de acceso, rectificación o eliminación de datos personales del RGPD. Si tienes dudas, contáctanos en <a href="mailto:bis_ceros.7v@icloud.com">bis_ceros.7v@icloud.com</a>.</p>"""


# Mapa ruta → página renderizada. Las rutas con y sin barra final apuntan aquí.
CONTENT_PAGES = {
    "/puente": _content_page(
        "/puente",
        "El Puente del Centenario de Sevilla",
        "Historia, datos técnicos y obras del Puente del Centenario (SE-30, Sevilla): un puente atirantado con más de 100.000 vehículos al día.",
        _PUENTE_BODY,
    ),
    "/carril-reversible": _content_page(
        "/carril-reversible",
        "Cómo funciona el carril reversible del Puente del Centenario",
        "Guía del carril reversible del Puente del Centenario: qué es, cómo saber qué sentido está abierto y cómo estimamos su estado.",
        _CARRIL_BODY,
    ),
    "/metodologia": _content_page(
        "/metodologia",
        "Cómo medimos el tráfico del Puente del Centenario",
        "Fuentes de datos (DGT, TomTom), cálculo de la puntuación de tráfico, niveles de congestión y limitaciones de este monitor.",
        _METODOLOGIA_BODY,
    ),
    "/faq": _content_page(
        "/faq",
        "Preguntas frecuentes",
        "Dudas habituales sobre el Puente del Centenario, su carril reversible y cómo funciona este monitor de tráfico en tiempo real.",
        _FAQ_BODY,
    ),
    "/sobre": _content_page(
        "/sobre",
        "Sobre el sitio y contacto",
        "Qué es 5centenario.es, por qué existe, su independencia respecto a la DGT y TomTom, y cómo contactar.",
        _SOBRE_BODY,
    ),
    "/privacidad": _content_page(
        "/privacidad",
        "Política de Privacidad",
        "Política de privacidad de 5centenario.es: datos que recogemos, cookies, publicidad de Google AdSense y tus derechos.",
        _PRIVACIDAD_BODY,
    ),
}


# --- Páginas dinámicas generadas a partir de nuestros propios datos ----------
# Contenido único y siempre fresco (se actualiza solo con la base de datos),
# a diferencia del set estático CONTENT_PAGES.

_WEEKDAY_NAMES_ES = (
    "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo",
)
_MONTH_NAMES_ES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)
# positive = ruta km10→km12 (hacia Huelva); negative = hacia Cádiz.
_DIRECTION_LABEL = {"positive": "hacia Huelva", "negative": "hacia Cádiz"}
_TRAFFIC_LEVEL_LABEL = {
    "fluido": "Fluido",
    "denso": "Denso",
    "retenciones": "Retenciones",
    "congestion_fuerte": "Congestión fuerte",
    "colapso": "Colapso",
    "cortado": "Puente cortado (obras)",
}


def _fmt_num(value: Optional[float], decimals: int = 1) -> str:
    """Formatea un número con coma decimal (estilo español)."""
    if value is None:
        return "—"
    return f"{value:.{decimals}f}".replace(".", ",")


def _now_local_text() -> str:
    now = datetime.now(ZoneInfo(LOCAL_TIMEZONE))
    return f"{now.day} de {_MONTH_NAMES_ES[now.month - 1]} de {now.year}, {now:%H:%M}"


def _render_estado_semana_body(storage) -> str:
    stats = storage.get_daily_speed_stats()
    states = storage.get_recent_states(7)

    by_date: dict[str, dict[str, dict]] = {}
    for row in stats:
        by_date.setdefault(row["date"], {})[row["direction"]] = row
    dates = sorted(by_date.keys(), reverse=True)[:7]

    if not dates:
        return (
            "  <h1>El tráfico del Puente del Centenario esta semana</h1>\n"
            '  <p class="lead">Todavía no hay suficientes datos registrados para '
            "generar el resumen semanal. Vuelve en unas horas.</p>\n"
            '  <p>Mientras tanto puedes consultar el <a href="/">monitor en tiempo '
            "real</a>.</p>"
        )

    # Medias ponderadas por nº de muestras, sobre la ventana mostrada.
    agg = {"positive": [0.0, 0], "negative": [0.0, 0]}
    week_min: dict[str, Optional[float]] = {"positive": None, "negative": None}
    week_max: dict[str, Optional[float]] = {"positive": None, "negative": None}
    for d in dates:
        for direction, r in by_date[d].items():
            if direction not in agg:
                continue
            if r["avg_speed"] is not None and r["sample_count"]:
                agg[direction][0] += r["avg_speed"] * r["sample_count"]
                agg[direction][1] += r["sample_count"]
            if r["min_speed"] is not None:
                cur = week_min[direction]
                week_min[direction] = r["min_speed"] if cur is None else min(cur, r["min_speed"])
            if r["max_speed"] is not None:
                cur = week_max[direction]
                week_max[direction] = r["max_speed"] if cur is None else max(cur, r["max_speed"])
    week_avg = {
        k: (v[0] / v[1] if v[1] else None) for k, v in agg.items()
    }

    # Reparto de niveles de tráfico en los últimos 7 días.
    level_counts: dict[str, int] = {}
    for st in states:
        lvl = st.get("traffic_level")
        if lvl:
            level_counts[lvl] = level_counts.get(lvl, 0) + 1
    total_states = sum(level_counts.values())

    today_local = datetime.now(ZoneInfo(LOCAL_TIMEZONE)).date().isoformat()

    def _date_label(date_str: str) -> str:
        try:
            dt = datetime.fromisoformat(date_str)
            return f"{_WEEKDAY_NAMES_ES[dt.weekday()]} {dt.day}/{dt.month:02d}"
        except ValueError:
            return date_str

    def _date_long(date_str: str) -> str:
        try:
            dt = datetime.fromisoformat(date_str)
            return f"{dt.day} de {_MONTH_NAMES_ES[dt.month - 1]}"
        except ValueError:
            return date_str

    # Rango cubierto (dates está ordenado de más reciente a más antiguo).
    window_text = f"del {_date_long(dates[-1])} al {_date_long(dates[0])} de {dates[0][:4]}"

    # Tabla por día.
    rows_html = []
    for d in dates:
        pos = by_date[d].get("positive", {})
        neg = by_date[d].get("negative", {})
        marker = (
            ' <span style="color:#B8141C;font-size:0.85em;white-space:nowrap;">· hoy, parcial</span>'
            if d == today_local
            else ""
        )
        rows_html.append(
            "    <tr>"
            f"<td>{_date_label(d)}{marker}</td>"
            f"<td>{_fmt_num(pos.get('avg_speed'))} <span style=\"color:#999\">({_fmt_num(pos.get('min_speed'),0)}–{_fmt_num(pos.get('max_speed'),0)})</span></td>"
            f"<td>{_fmt_num(neg.get('avg_speed'))} <span style=\"color:#999\">({_fmt_num(neg.get('min_speed'),0)}–{_fmt_num(neg.get('max_speed'),0)})</span></td>"
            "</tr>"
        )
    table_html = (
        "  <table>\n"
        "    <tr><th>Día</th><th>Hacia Huelva (km/h)</th><th>Hacia Cádiz (km/h)</th></tr>\n"
        + "\n".join(rows_html)
        + "\n  </table>"
    )

    # Reparto de niveles.
    level_html = ""
    if total_states:
        items = []
        for key in ("fluido", "denso", "retenciones", "congestion_fuerte", "colapso", "cortado"):
            if key in level_counts:
                pct = 100.0 * level_counts[key] / total_states
                items.append(
                    f"    <li><strong>{_TRAFFIC_LEVEL_LABEL[key]}:</strong> "
                    f"{_fmt_num(pct, 0)} % del tiempo</li>"
                )
        level_html = (
            "\n  <h2>Cómo de fluido ha estado el tráfico</h2>\n"
            f"  <p>Reparto del estado del tramo durante los últimos 7 días "
            f"({total_states} mediciones registradas):</p>\n"
            "  <ul>\n" + "\n".join(items) + "\n  </ul>"
        )

    return f"""  <h1>El tráfico del Puente del Centenario esta semana</h1>
  <p class="updated">Resumen automático · generado el {_now_local_text()}</p>
  <p class="lead">Velocidades medias por sentido en el tramo de la SE-30 (km 10–12) durante los últimos días, calculadas a partir de los datos que registra este monitor. Esta página se genera de forma automática y se actualiza sola.</p>
  <p><strong>Datos {window_text}.</strong> Los días cerrados son definitivos; el día de hoy es parcial y se recalcula cada pocos minutos hasta que termina la jornada.</p>

  <h2>Velocidad media de los últimos {len(dates)} días</h2>
  <ul>
    <li><strong>Sentido Huelva:</strong> {_fmt_num(week_avg['positive'])} km/h de media (entre {_fmt_num(week_min['positive'], 0)} y {_fmt_num(week_max['positive'], 0)} km/h).</li>
    <li><strong>Sentido Cádiz:</strong> {_fmt_num(week_avg['negative'])} km/h de media (entre {_fmt_num(week_min['negative'], 0)} y {_fmt_num(week_max['negative'], 0)} km/h).</li>
  </ul>
  <div class="note">El límite real del tramo es de 60 km/h. Una velocidad media bastante por debajo indica densidad o retenciones; recuerda que en 2 km de tramo un solo incidente puede mover la media varios km/h.</div>

  <h2>Detalle por día</h2>
  <p>Velocidad media de cada día y, entre paréntesis, el rango mínimo–máximo observado:</p>
{table_html}
{level_html}

  <p>¿De dónde salen estos números? Lo explicamos en <a href="/metodologia">cómo medimos el tráfico</a>. Para ver el estado ahora mismo, entra al <a href="/">monitor en tiempo real</a>, y para entender el carril central consulta la <a href="/carril-reversible">guía del carril reversible</a>.</p>"""


def _render_patrones_body(storage) -> str:
    profile = storage.observed_direction_profile(days=14)

    # Agrupar por día de la semana y comprimir horas consecutivas del mismo sentido.
    by_weekday: dict[int, list[tuple[int, str]]] = {}
    total_samples = 0
    for (weekday, hour), info in profile.items():
        by_weekday.setdefault(weekday, []).append((hour, info["direction"]))
        total_samples += int(info.get("sample_count", 0))

    if not by_weekday:
        return (
            "  <h1>Patrones por hora del carril reversible</h1>\n"
            '  <p class="lead">Todavía no hay suficientes observaciones para detectar '
            "un patrón horario fiable. Esta página se rellena automáticamente a medida "
            "que el monitor acumula datos.</p>\n"
            '  <p>Consulta mientras tanto la <a href="/carril-reversible">guía del carril '
            "reversible</a> y el <a href=\"/\">monitor en tiempo real</a>.</p>"
        )

    def _compress(hours_dir: list[tuple[int, str]]) -> list[tuple[int, int, str]]:
        # Fusiona horas del mismo sentido aunque falte algún slot intermedio:
        # se abre rango nuevo solo al cambiar de sentido.
        ranges: list[tuple[int, int, str]] = []
        for hour, direction in sorted(hours_dir):
            if ranges and ranges[-1][2] == direction:
                start, _, d = ranges[-1]
                ranges[-1] = (start, hour + 1, d)
            else:
                ranges.append((hour, hour + 1, direction))
        return ranges

    rows_html = []
    for weekday in range(7):
        if weekday not in by_weekday:
            continue
        ranges = _compress(by_weekday[weekday])
        franjas = ", ".join(
            f"{start:02d}:00–{end:02d}:00 {_DIRECTION_LABEL.get(d, d)}"
            for start, end, d in ranges
        )
        rows_html.append(
            f"    <tr><td><strong>{_WEEKDAY_NAMES_ES[weekday]}</strong></td><td>{franjas}</td></tr>"
        )
    table_html = (
        "  <table>\n"
        "    <tr><th>Día</th><th>Franjas con sentido predominante más rápido</th></tr>\n"
        + "\n".join(rows_html)
        + "\n  </table>"
    )

    return f"""  <h1>Patrones por hora del carril reversible</h1>
  <p class="updated">Análisis automático · generado el {_now_local_text()}</p>
  <p class="lead">A partir de las observaciones de los últimos 14 días, estimamos en qué franjas horarias circula más rápido cada sentido del puente. Como el sentido más fluido suele coincidir con el que tiene <strong>abierto el carril reversible</strong>, esto da una idea del horario habitual de apertura.</p>

  <h2>Franjas típicas por día de la semana</h2>
  <p>Para cada día, las franjas en las que un sentido ha circulado de forma sostenida más rápido que el otro (basado en {total_samples} comparaciones de velocidad):</p>
{table_html}

  <div class="note"><strong>Esto es una estimación, no un horario oficial.</strong> Se calcula a partir de diferencias de velocidad y puede verse afectada por obras, incidentes o días atípicos. Para circular, haz siempre caso a las aspas rojas y flechas verdes señalizadas sobre el propio puente.</div>

  <p>¿Cómo interpretamos que un sentido vaya más rápido? Lo contamos en la <a href="/carril-reversible">guía del carril reversible</a> y en <a href="/metodologia">cómo medimos el tráfico</a>. El estado ahora mismo está en el <a href="/">monitor en tiempo real</a>, y el resumen de velocidades en <a href="/estado-semana">el tráfico esta semana</a>.</p>"""


# Ruta dinámica → (título, meta description, función que construye el cuerpo).
_DATA_PAGES = {
    "/estado-semana": (
        "El tráfico del Puente del Centenario esta semana",
        "Resumen automático de velocidades por sentido y nivel de congestión del Puente del Centenario (SE-30, Sevilla) en los últimos días.",
        _render_estado_semana_body,
    ),
    # TODO(/patrones): en reserva. Tras corregir el offset (ahora usa el del
    # config, 1.0, no el 4.0 hardcodeado) el perfil ya no sale 93% Cádiz sino
    # ~25% Cádiz / 75% Huelva. Pero la señal de asimetría es intrínsecamente
    # débil (validada contra 32 reportes: ~69% acierto vs 62% base rate; 77%
    # solo cuando |diff|≥5 km/h), así que un reparto 75/25 sigue siendo poco
    # representativo de un reversible que alterna. Decisión de publicar pendiente
    # del usuario; si se reactiva, añadir la entrada de abajo:
    #   "/patrones": (
    #       "Patrones por hora del carril reversible del Puente del Centenario",
    #       "Franjas horarias en las que cada sentido del Puente del Centenario "
    #       "circula más rápido, estimadas a partir de 14 días de datos.",
    #       _render_patrones_body,
    #   ),
}

# Caché en memoria de las páginas dinámicas (evita golpear la BD en cada crawl).
_DYNAMIC_PAGE_TTL = 600.0
_dynamic_page_cache: dict[str, tuple[float, str]] = {}
_dynamic_page_lock = threading.Lock()


def _build_dynamic_page(path: str, storage) -> str:
    title, description, render = _DATA_PAGES[path]
    return _content_page(path, title, description, render(storage))


def _get_dynamic_page(path: str, storage) -> str:
    now = time.monotonic()
    with _dynamic_page_lock:
        cached = _dynamic_page_cache.get(path)
        if cached and cached[0] > now:
            return cached[1]
    html = _build_dynamic_page(path, storage)
    with _dynamic_page_lock:
        _dynamic_page_cache[path] = (now + _DYNAMIC_PAGE_TTL, html)
    return html


# URLs antiguas (set editorial retirado) → páginas vigentes. 301 para no
# romper enlaces que Google ya pudiera haber indexado.
_LEGACY_REDIRECTS = {
    "/sobre-el-puente": "/puente",
    "/como-funciona": "/metodologia",
    "/preguntas-frecuentes": "/faq",
}


_SITE_BASE_URL = "https://5centenario.es"

ROBOTS_TXT = f"""User-agent: *
Allow: /
Disallow: /admin
Disallow: /api/

Sitemap: {_SITE_BASE_URL}/sitemap.xml
"""


def _build_sitemap() -> str:
    urls = ["/"] + list(CONTENT_PAGES.keys()) + list(_DATA_PAGES.keys())
    entries = "\n".join(
        f"  <url><loc>{_SITE_BASE_URL}{path if path != '/' else '/'}</loc></url>"
        for path in urls
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entries}\n"
        "</urlset>\n"
    )


SITEMAP_XML = _build_sitemap()


def _build_public_page(admin_html: str) -> str:
    nav_marker = "    <!-- Tab navigation -->"
    vista_marker = "    <!-- ===== TAB VISTA — nuevo diseño ===== -->"
    i = admin_html.index(nav_marker)
    j = admin_html.index(vista_marker)
    trimmed = admin_html[:i] + admin_html[j:]
    trimmed = trimmed.replace(
        '<div id="tab-nuevo" style="display:none;">',
        '<div id="tab-nuevo">',
        1,
    )
    trimmed = trimmed.replace(
        "<title>5Centenario Monitor</title>",
        "<title>5Centenario · Puente del Centenario</title>",
        1,
    )
    # El bundle JS está diseñado para el dashboard completo y referencia elementos
    # de pestañas que aquí ya no existen; este proxy hace que document.getElementById
    # devuelva un stub no-op para IDs ausentes y evita romper render compartido.
    proxy_and_boot = """  <script>
    (function(){
      const _get = document.getElementById.bind(document);
      const _classList = { add: () => {}, remove: () => {}, toggle: () => {}, contains: () => false };
      const _rect = () => ({ width: 0, height: 0, top: 0, left: 0, right: 0, bottom: 0 });
      // Stub auto-encadenable: cualquier propiedad devuelve el propio stub y
      // también se puede invocar como función. Así `byId('x').getContext('2d').fillStyle = '#000'`
      // y `canvas.width = N` no rompen cuando el nodo real no existe en la vista pública.
      const _stub = new Proxy(function(){ return _stub; }, {
        get(_, k){
          if (k === 'classList') return _classList;
          if (k === 'getBoundingClientRect') return _rect;
          if (k === 'offsetWidth' || k === 'offsetHeight' || k === 'clientWidth' || k === 'clientHeight') return 0;
          if (k === 'textContent' || k === 'innerHTML' || k === 'value' || k === 'tagName' || k === 'nodeName') return '';
          if (k === 'children' || k === 'childNodes') return [];
          if (k === 'parentNode' || k === 'parentElement' || k === 'firstChild' || k === 'lastChild') return null;
          if (k === 'querySelector') return () => null;
          if (k === 'querySelectorAll') return () => [];
          if (k === 'contains') return () => false;
          if (k === Symbol.toPrimitive) return () => '';
          return _stub;
        },
        set: () => true,
        apply: () => _stub,
      });
      document.getElementById = function(id){ return _get(id) || _stub; };
    })();
    window.addEventListener('DOMContentLoaded', () => {
      if (typeof nv_startScene === 'function') { try { nv_startScene(); } catch(_){} }
    });
  </script>
"""
    script_anchor = "  <script>\n    const stateLabels"
    trimmed = trimmed.replace(script_anchor, proxy_and_boot + script_anchor, 1)

    # Inyectar SOLO la meta de verificación de propiedad. El script
    # adsbygoogle.js no se carga aquí porque, aun sin Auto Ads activado,
    # interfiere con el canvas y los listeners de visibilitychange.
    # El script se cargará junto a las unidades manuales cuando se añadan.
    if ADSENSE_CLIENT_ID:
        adsense_meta = (
            f'  <meta name="google-adsense-account" content="{ADSENSE_CLIENT_ID}">\n'
        )
        trimmed = trimmed.replace("</head>", adsense_meta + "</head>", 1)

    # Sección descriptiva. En móvil ocultamos el párrafo (queda en el DOM
    # para SEO) y mantenemos solo el h1 compacto. El título principal del
    # dashboard ya da contexto al usuario.
    about_block = """    <!-- Sección informativa para motores de búsqueda y visitantes -->
    <style>
      .nd-about { margin-bottom: var(--space-lg); font-family: 'Space Grotesk', system-ui, sans-serif; }
      .nd-about h1 { font-size: 1rem; font-weight: 700; color: var(--text-primary); margin-bottom: 6px; }
      .nd-about p { font-size: 0.85rem; color: var(--text-secondary); line-height: 1.6; }
      @media (max-width: 720px) {
        .nd-about { margin-bottom: var(--space-md); }
        .nd-about h1 { font-size: 0.85rem; font-weight: 600; color: var(--text-secondary); }
        .nd-about p { display: none; }
      }
    </style>
    <section class="nd-about">
      <h1>Monitor de tráfico · Puente del Centenario (SE-30, Sevilla)</h1>
      <p>
        Seguimiento en tiempo real del estado del tráfico en el <strong>Puente del Centenario</strong> (SE-30, km 10–12, Sevilla).
        Datos actualizados cada 5 minutos a partir de fuentes públicas de la DGT y TomTom.
        Se muestran velocidades por sentido (Huelva / Cádiz), nivel de congestión y estado estimado del
        <a href="/carril-reversible">carril reversible</a>.
        Consulta el resumen de <a href="/estado-semana">cómo ha estado el tráfico esta semana</a>,
        <a href="/metodologia">cómo medimos el tráfico</a>, la ficha del <a href="/puente">puente</a>
        o las <a href="/faq">preguntas frecuentes</a>.
      </p>
    </section>\n"""

    # Insertar sección descriptiva justo antes del header principal.
    # No insertamos unidades manuales: AdSense decide colocaciones via Auto Ads.
    trimmed = trimmed.replace(
        "    <!-- Header -->\n    <header class=\"nd-header\">",
        about_block + "    <!-- Header -->\n    <header class=\"nd-header\">",
        1,
    )

    # Tarjeta destacada hacia el resumen semanal. La vista pública es la pestaña
    # VISTA (clases nv-*); la insertamos tras el histórico de velocidad, justo
    # antes de los paneles VMS. No aparece en /admin (esa sección se recorta).
    week_cta = (
        "      <!-- CTA: resumen semanal -->\n"
        "      <section class=\"nv-section\">\n"
        "        <a href=\"/estado-semana\" class=\"nv-card\" style=\"display:flex;align-items:center;justify-content:space-between;gap:16px;text-decoration:none;color:inherit;border-left:3px solid var(--nv-accent);\">\n"
        "          <div>\n"
        "            <div style=\"font-size:14px;font-weight:600;color:var(--nv-accent);\">El tr&#225;fico esta semana</div>\n"
        "            <div style=\"font-size:13px;color:var(--nv-text-2);line-height:1.5;margin-top:6px;\">Velocidad media por sentido d&#237;a a d&#237;a y porcentaje de tiempo fluido, denso o con retenciones en los &#250;ltimos 7 d&#237;as.</div>\n"
        "          </div>\n"
        "          <div style=\"font-size:22px;color:var(--nv-accent);flex-shrink:0;\">&#8594;</div>\n"
        "        </a>\n"
        "      </section>\n\n"
    )
    trimmed = trimmed.replace(
        "      <!-- VMS panels -->",
        week_cta + "      <!-- VMS panels -->",
        1,
    )

    # Enlace privacidad en el footer
    old_footer = (
        "    <!-- Footer -->\n"
        "    <footer class=\"nd-footer\">\n"
        "      <span class=\"nd-eyebrow\">Actualización automática cada 60 s</span>\n"
        "      <span class=\"nd-eyebrow\">SE-30 km 10–12 · Ambos sentidos · Sevilla</span>\n"
        "    </footer>"
    )
    new_footer = (
        "    <!-- Footer -->\n"
        "    <footer class=\"nd-footer\">\n"
        "      <span class=\"nd-eyebrow\">Actualización automática cada 60 s</span>\n"
        "      <span class=\"nd-eyebrow\">SE-30 km 10–12 · Ambos sentidos · Sevilla</span>\n"
        "      <nav class=\"nd-eyebrow\" style=\"display:flex;flex-wrap:wrap;gap:6px 14px;\">\n"
        "        <a href=\"/estado-semana\" style=\"color:inherit;opacity:0.7;\">El tráfico esta semana</a>\n"
        "        <a href=\"/puente\" style=\"color:inherit;opacity:0.7;\">El puente</a>\n"
        "        <a href=\"/carril-reversible\" style=\"color:inherit;opacity:0.7;\">Carril reversible</a>\n"
        "        <a href=\"/metodologia\" style=\"color:inherit;opacity:0.7;\">Cómo medimos</a>\n"
        "        <a href=\"/faq\" style=\"color:inherit;opacity:0.7;\">Preguntas frecuentes</a>\n"
        "        <a href=\"/sobre\" style=\"color:inherit;opacity:0.7;\">Sobre el sitio</a>\n"
        "        <a href=\"/privacidad\" style=\"color:inherit;opacity:0.7;\">Privacidad</a>\n"
        "      </nav>\n"
        "    </footer>"
    )
    trimmed = trimmed.replace(old_footer, new_footer, 1)

    return trimmed


PUBLIC_PAGE = _build_public_page(HTML_PAGE)


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
                    self._send_html(PUBLIC_PAGE)
                    return
                content_path = parsed.path.rstrip("/") or "/"
                if content_path in CONTENT_PAGES:
                    self._send_html(CONTENT_PAGES[content_path])
                    return
                if content_path in _DATA_PAGES:
                    self._send_html(_get_dynamic_page(content_path, service.storage))
                    return
                if content_path in _LEGACY_REDIRECTS:
                    self._send_redirect(_LEGACY_REDIRECTS[content_path])
                    return
                if parsed.path in ("/favicon.svg", "/favicon.ico"):
                    body = _FAVICON_SVG.encode("utf-8")
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "image/svg+xml")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "public, max-age=86400")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if parsed.path == "/ads.txt":
                    if ADSENSE_CLIENT_ID:
                        pub_id = ADSENSE_CLIENT_ID.replace("ca-", "", 1)
                        body = f"google.com, {pub_id}, DIRECT, f08c47fec0942fa0\n"
                        self._send_text(body)
                    else:
                        self.send_error(HTTPStatus.NOT_FOUND, "ads.txt no configurado")
                    return
                if parsed.path == "/robots.txt":
                    self._send_text(ROBOTS_TXT)
                    return
                if parsed.path in ("/sitemap.xml", "/sitemap"):
                    self._send_xml(SITEMAP_XML)
                    return
                if parsed.path in ("/admin", "/admin/"):
                    self._send_html(HTML_PAGE, track=False)
                    return
                if parsed.path == "/api/dashboard":
                    self._send_json(service.dashboard_data())
                    return
                if parsed.path == "/api/se30":
                    self._send_json(service.se30_live_data())
                    return
                if parsed.path == "/api/daily-stats":
                    self._send_json(service.storage.get_daily_speed_stats())
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
                if parsed.path == "/api/report-reversible":
                    length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(length) if length else b"{}"
                    try:
                        payload = json.loads(body)
                    except Exception:
                        self._send_json({"error": "invalid json"}, status=400)
                        return
                    direction = payload.get("direction", "")
                    if direction not in ("positive", "negative", "none"):
                        self._send_json({"error": "direction must be positive, negative or none"}, status=400)
                        return
                    note = payload.get("note")
                    if note is not None and not isinstance(note, str):
                        self._send_json({"error": "note must be a string"}, status=400)
                        return
                    service.storage.insert_reversible_report(direction, note=note)
                    self._send_json({"ok": True, "direction": direction})
                    return
                self.send_error(HTTPStatus.NOT_FOUND, "Ruta no encontrada")

            def do_DELETE(self) -> None:
                parsed = urlparse(self.path)
                # /api/report-reversible/<id>
                import re as _re
                m = _re.match(r"^/api/report-reversible/(\d+)$", parsed.path)
                if m:
                    report_id = int(m.group(1))
                    deleted = service.storage.delete_reversible_report(report_id)
                    if deleted:
                        self._send_json({"ok": True, "id": report_id})
                    else:
                        self._send_json({"error": "not found"}, status=404)
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

            def _send_html(self, html: str, status: int = 200, track: bool = True) -> None:
                if track and UMAMI_WEBSITE_ID:
                    umami_tag = (
                        f'<script defer src="/umami/script.js"'
                        f' data-website-id="{UMAMI_WEBSITE_ID}"></script>\n'
                    )
                    html = html.replace("</head>", umami_tag + "</head>", 1)
                body = html.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self._send_common_headers()
                self.end_headers()
                self.wfile.write(body)

            def _send_text(self, text: str, status: int = 200) -> None:
                body = text.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self._send_common_headers()
                self.end_headers()
                self.wfile.write(body)

            def _send_redirect(self, location: str) -> None:
                self.send_response(HTTPStatus.MOVED_PERMANENTLY)
                self.send_header("Location", location)
                self.send_header("Content-Length", "0")
                self._send_common_headers()
                self.end_headers()

            def _send_xml(self, xml: str, status: int = 200) -> None:
                body = xml.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/xml; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
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
