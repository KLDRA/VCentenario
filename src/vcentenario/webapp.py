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
  </style>
</head>
<body>
  <div class="nd-shell">

    <!-- Header -->
    <header class="nd-header">
      <div>
        <div class="nd-eyebrow">Monitor Operativo · SE-30 km 10–12 · Sentido Huelva</div>
        <div class="nd-header-title">VCentenario</div>
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
    </nav>

    <div id="tab-estado">

    <!-- Sentidos: tarjetas de intensidad por dirección -->
    <section class="nd-directions">
      <div class="nd-direction-card">
        <div class="nd-direction-heading">
          <span class="nd-direction-arrow">→</span>
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
          <span class="nd-direction-arrow">←</span>
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
          <button id="btn-report-huelva" class="nd-report-btn" style="background:#4A9E5C22;border:1px solid #4A9E5C;color:#4A9E5C;" onclick="reportReversible('positive')">&#8594; HUELVA</button>
          <button id="btn-report-cadiz"  class="nd-report-btn" style="background:#D4A84322;border:1px solid #D4A843;color:#D4A843;" onclick="reportReversible('negative')">&#8592; C&#193;DIZ</button>
          <button id="btn-report-none"   class="nd-report-btn" style="background:#55555522;border:1px solid #555555;color:#888888;" onclick="reportReversible('none')">SIN REVERSIBLE</button>
        </div>
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
        <div style="padding:var(--space-sm) var(--space-lg) 2px;font-family:'Space Mono',monospace;font-size:9px;letter-spacing:0.08em;color:#4A9E5C;">&#8594; HUELVA</div>
        <div class="nd-bars-wrap">
          <canvas id="pulso-huelva" style="display:block;width:100%;background:var(--canvas-bg);"></canvas>
        </div>
        <div style="padding:var(--space-sm) var(--space-lg) 2px;font-family:'Space Mono',monospace;font-size:9px;letter-spacing:0.08em;color:#D4A843;margin-top:var(--space-sm);">&#8592; C&#193;DIZ</div>
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
          <div class="nd-label">&#8594; Sentido Huelva · km 10&#8211;12</div>
          <div id="spd-huelva" class="nd-metric-value">-</div>
          <div id="spd-huelva-delay" class="nd-metric-note">km/h</div>
          <div id="spd-huelva-free" class="nd-metric-note" style="margin-top:2px;"></div>
        </article>
        <article class="nd-metric-card">
          <div class="nd-label">&#8592; Sentido C&#225;diz · km 12&#8211;10</div>
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
          <div class="nd-label">&rarr; Sentido Huelva · km 10&ndash;12</div>
          <div class="nd-metric-value" id="map-spd-huelva">-</div>
          <div class="nd-metric-note" id="map-delay-huelva">TomTom Routing</div>
        </article>
        <article class="nd-metric-card">
          <div class="nd-label">&larr; Sentido C&aacute;diz · km 12&ndash;10</div>
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

    <!-- Footer -->
    <footer class="nd-footer">
      <span class="nd-eyebrow">Actualización automática cada 60 s</span>
      <span class="nd-eyebrow">SE-30 km 10–12 · Sentido Huelva · Sevilla</span>
    </footer>

  </div>

  <script>
    const stateLabels = {
      fluido: "Fluido",
      denso: "Denso",
      retenciones: "Retenciones",
      congestion_fuerte: "Congestión fuerte",
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
    };
    function incidentLabel(type) {
      return incidentLabels[type] || type || "Incidencia";
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
      if (latestRun && latestRun.warnings && latestRun.warnings.length > 0) {
        warningBox.style.display = "block";
        warningBox.innerHTML = latestRun.warnings.map((item) => escapeHtml(item)).join("<br>");
      } else {
        warningBox.style.display = "none";
        warningBox.textContent = "";
      }
    }

    const reportLabels = { positive: '→ Huelva', negative: '← Cádiz', none: 'Sin reversible' };
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
      statusEl.textContent = 'Enviando...';
      try {
        const res = await fetch('/api/report-reversible', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ direction }),
        });
        if (!res.ok) throw new Error('Error ' + res.status);
        statusEl.style.color = reportColors[direction] || '#888';
        statusEl.textContent = `Registrado: ${reportLabels[direction]} · ${new Date().toLocaleTimeString('es-ES')}`;
        // Recarga el dashboard para mostrar el nuevo reporte
        await loadDashboard();
      } catch (e) {
        statusEl.style.color = 'var(--accent)';
        statusEl.textContent = 'Error al enviar: ' + e.message;
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
        return `<div style="display:flex;gap:var(--space-md);align-items:baseline;padding:4px 0;border-bottom:1px solid #111;">
          <span style="font-family:${mono};font-size:11px;color:${color};min-width:100px;">${escapeHtml(label)}</span>
          <span style="font-family:${mono};font-size:10px;color:#555;">${escapeHtml(dt)}</span>
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

    function showTab(name) {
      document.getElementById('tab-estado').style.display = name === 'estado' ? '' : 'none';
      document.getElementById('tab-velocidades').style.display = name === 'velocidades' ? '' : 'none';
      document.getElementById('tab-mapa').style.display = name === 'mapa' ? '' : 'none';
      document.getElementById('tab-se30').style.display = name === 'se30' ? '' : 'none';
      document.getElementById('btn-estado').classList.toggle('active', name === 'estado');
      document.getElementById('btn-velocidades').classList.toggle('active', name === 'velocidades');
      document.getElementById('btn-mapa').classList.toggle('active', name === 'mapa');
      document.getElementById('btn-se30').classList.toggle('active', name === 'se30');
      if (name === 'mapa') requestAnimationFrame(initMap);
      if (name === 'se30') { loadSE30Data(); requestAnimationFrame(initMapSE30); }
      // Redibujar canvas al mostrar la pestaña (offsetWidth es 0 cuando estaba oculto)
      if (name === 'estado' || name === 'velocidades') requestAnimationFrame(redrawCanvases);
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
                if parsed.path == "/api/se30":
                    self._send_json(service.se30_live_data())
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
                    service.storage.insert_reversible_report(direction)
                    self._send_json({"ok": True, "direction": direction})
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
