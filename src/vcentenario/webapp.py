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


HTML_PAGE = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>VCentenario Monitor</title>
  <style>
    :root {
      --bg: #f5efe1;
      --panel: rgba(255, 252, 245, 0.84);
      --panel-strong: #fff8eb;
      --ink: #1f2a2e;
      --muted: #5f6c71;
      --accent: #0f766e;
      --accent-soft: #d8efe8;
      --alert: #c2410c;
      --warn: #b45309;
      --good: #15803d;
      --line: rgba(31, 42, 46, 0.12);
      --shadow: 0 18px 40px rgba(68, 60, 40, 0.12);
      --radius: 22px;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(15, 118, 110, 0.18), transparent 34%),
        radial-gradient(circle at top right, rgba(194, 65, 12, 0.14), transparent 28%),
        linear-gradient(180deg, #f9f3e6 0%, var(--bg) 100%);
      min-height: 100vh;
    }
    .shell {
      max-width: 1280px;
      margin: 0 auto;
      padding: 28px 20px 40px;
    }
    .hero {
      display: grid;
      gap: 18px;
      grid-template-columns: 1.5fr 1fr;
      align-items: stretch;
      margin-bottom: 24px;
    }
    .card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      backdrop-filter: blur(10px);
    }
    .hero-main {
      padding: 28px;
      position: relative;
      overflow: hidden;
    }
    .hero-main::after {
      content: "";
      position: absolute;
      inset: auto -40px -60px auto;
      width: 220px;
      height: 220px;
      border-radius: 999px;
      background: radial-gradient(circle, rgba(15,118,110,0.18), transparent 70%);
    }
    .eyebrow {
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--accent);
      font-size: 12px;
      font-weight: 700;
      margin-bottom: 10px;
    }
    h1 {
      margin: 0;
      font-size: clamp(32px, 6vw, 56px);
      line-height: 0.92;
      max-width: 10ch;
    }
    .hero-copy {
      margin-top: 16px;
      max-width: 56ch;
      color: var(--muted);
      font-size: 15px;
      line-height: 1.5;
    }
    button {
      border: 0;
      border-radius: 999px;
      padding: 13px 18px;
      font: inherit;
      cursor: pointer;
      transition: transform 120ms ease, opacity 120ms ease, background 120ms ease;
    }
    button:hover { transform: translateY(-1px); }
    button:disabled { opacity: 0.65; cursor: wait; transform: none; }
    .btn-primary { background: var(--accent); color: white; }
    .btn-secondary { background: var(--accent-soft); color: var(--ink); }
    .hero-side {
      padding: 24px;
      display: grid;
      gap: 16px;
      align-content: space-between;
      background:
        linear-gradient(180deg, rgba(255,248,235,0.95) 0%, rgba(244,240,228,0.85) 100%);
    }
    .status-badge {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(15, 118, 110, 0.1);
      width: fit-content;
      font-weight: 700;
    }
    .status-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: var(--accent);
      box-shadow: 0 0 0 6px rgba(15, 118, 110, 0.12);
    }
    .mini-grid, .grid {
      display: grid;
      gap: 18px;
    }
    .mini-grid {
      grid-template-columns: repeat(3, minmax(0, 1fr));
      margin-bottom: 18px;
    }
    .metric {
      padding: 18px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 20px;
      box-shadow: var(--shadow);
    }
    .metric-label {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: var(--muted);
    }
    .metric-value {
      margin-top: 10px;
      font-size: clamp(26px, 4vw, 40px);
      font-weight: 800;
    }
    .metric-note {
      margin-top: 8px;
      font-size: 14px;
      color: var(--muted);
    }
    .grid {
      grid-template-columns: 1fr;
    }
    .panel-section {
      padding: 22px;
    }
    .section-head {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 12px;
      margin-bottom: 16px;
    }
    h2 {
      margin: 0;
      font-size: 21px;
    }
    .subtle {
      color: var(--muted);
      font-size: 14px;
    }
    .timeline {
      display: grid;
      gap: 10px;
    }
    .trend-shell {
      position: relative;
      min-height: 164px;
    }
    .timeline-bar {
      display: grid;
      grid-template-columns: repeat(16, minmax(0, 1fr));
      gap: 8px;
      align-items: end;
      min-height: 180px;
      padding: 18px 0 0;
      position: relative;
      z-index: 1;
    }
    .timeline-bar.wide-chart {
      min-height: 220px;
    }
    .trend-thresholds {
      position: absolute;
      inset: 0 0 22px 0;
      pointer-events: none;
      z-index: 0;
    }
    .trend-line {
      position: absolute;
      left: 0;
      right: 0;
      border-top: 1px dashed rgba(31, 42, 46, 0.18);
    }
    .trend-line span {
      position: absolute;
      right: 0;
      top: -10px;
      padding-left: 8px;
      background: linear-gradient(180deg, rgba(255, 252, 245, 0), rgba(255, 252, 245, 0.92) 42%, rgba(255, 252, 245, 0.92));
      color: var(--muted);
      font-size: 10px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }
    .bar-wrap {
      display: grid;
      gap: 8px;
      justify-items: center;
    }
    .bar {
      width: 100%;
      border-radius: 14px 14px 6px 6px;
      background: linear-gradient(180deg, #0f766e, #134e4a);
      min-height: 12px;
      align-self: end;
    }
    .bar.level-fluido {
      background: linear-gradient(180deg, #2f9e44, #237032);
    }
    .bar.level-denso {
      background: linear-gradient(180deg, #d97706, #b45309);
    }
    .bar.level-retenciones {
      background: linear-gradient(180deg, #ea580c, #c2410c);
    }
    .bar.level-congestion_fuerte {
      background: linear-gradient(180deg, #dc2626, #991b1b);
    }
    .bar-label {
      font-size: 11px;
      color: var(--muted);
      text-align: center;
    }
    .bar-score {
      font-size: 10px;
      color: var(--muted);
      text-align: center;
      line-height: 1;
    }
    .trend-legend {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 4px;
    }
    .legend-pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 10px;
      border-radius: 999px;
      background: rgba(255,255,255,0.65);
      border: 1px solid var(--line);
      color: var(--muted);
      font-size: 12px;
    }
    .legend-dot {
      width: 10px;
      height: 10px;
      border-radius: 999px;
    }
    .list {
      display: grid;
      gap: 12px;
    }
    .item {
      padding: 14px 16px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.5);
    }
    .item-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 8px;
      font-weight: 700;
    }
    .chips {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 10px;
    }
    .chip {
      padding: 6px 10px;
      border-radius: 999px;
      font-size: 12px;
      background: rgba(15,118,110,0.1);
      color: var(--ink);
    }
    .chip.warn { background: rgba(180, 83, 9, 0.14); }
    .chip.alert { background: rgba(194, 65, 12, 0.14); }
    .chip.good { background: rgba(21, 128, 61, 0.12); }
    .evidence-item {
      display: flex;
      gap: 12px;
      align-items: flex-start;
      padding: 12px 14px;
      border-radius: 14px;
      background: #ffffff;
      border: 1px solid var(--line);
      line-height: 1.4;
    }
    .evidence-icon {
      font-size: 18px;
      flex-shrink: 0;
    }
    .vms-container {
      display: grid;
      gap: 14px;
    }
    .vms-item {
      padding: 18px;
      border-radius: var(--radius);
      border: 1px solid var(--line);
      background: var(--panel);
      box-shadow: var(--shadow);
    }
    .vms-panel {
      margin-top: 12px;
      background: #0d0d0d;
      color: #ffb800;
      padding: 14px;
      border-radius: 12px;
      font-family: "Courier New", Courier, monospace;
      font-weight: 800;
      text-transform: uppercase;
      text-align: center;
      border: 2px solid #222;
      box-shadow: inset 0 0 10px rgba(0,0,0,0.5);
      line-height: 1.4;
      font-size: 14px;
    }
    .vms-pictos {
      display: flex;
      justify-content: center;
      gap: 12px;
      margin-top: 8px;
    }
    .camera-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }
    .camera {
      overflow: hidden;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: #fffdf8;
    }
    .camera img {
      display: block;
      width: 100%;
      aspect-ratio: 16 / 10;
      object-fit: cover;
      background: linear-gradient(135deg, #d8efe8, #efe2c8);
    }
    .camera-body {
      padding: 14px;
    }
    .camera-title {
      font-weight: 800;
      margin-bottom: 6px;
    }
    .camera-meta {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
    }
    .empty {
      padding: 18px;
      border: 1px dashed var(--line);
      border-radius: 18px;
      color: var(--muted);
      background: rgba(255,255,255,0.42);
    }
    .footer-note {
      margin-top: 18px;
      color: var(--muted);
      font-size: 13px;
    }
    .warning-box {
      margin-top: 18px;
      padding: 14px 16px;
      border-radius: 16px;
      border: 1px solid rgba(180, 83, 9, 0.25);
      background: rgba(180, 83, 9, 0.08);
      color: #7c2d12;
      display: none;
      line-height: 1.45;
    }
    @media (max-width: 980px) {
      .hero, .grid { grid-template-columns: 1fr; }
      .mini-grid, .camera-grid { grid-template-columns: 1fr; }
      .shell { padding: 18px 14px 28px; }
      .hero-main, .hero-side, .panel-section, .metric { padding: 18px; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <div class="card hero-main">
        <div class="eyebrow">Monitor Operativo</div>
        <h1>Puente del Centenario</h1>
        <p class="hero-copy">
          Vista sencilla para entender el estado del puente, las señales activas de DGT
          y la inferencia del carril reversible sin perder de vista la confianza real de la estimación.
        </p>
        <div class="metric-note" style="margin-top:22px;">Actualización automática del servidor cada 5 minutos. La página se refresca sola para mostrar el último estado guardado.</div>
        <div id="runWarnings" class="warning-box"></div>
      </div>
      <div class="card hero-side">
        <div>
          <div class="status-badge">
            <span class="status-dot"></span>
            <span id="generatedAt">Sin datos</span>
          </div>
        </div>
        <div>
          <div class="subtle">Lectura actual</div>
          <div id="heroSummary" class="metric-value" style="font-size:34px; margin-top:8px;">Esperando datos</div>
          <div id="heroDetail" class="metric-note">Ejecuta una recogida para poblar el panel.</div>
        </div>
      </div>
    </section>

    <section class="mini-grid">
      <article class="metric">
        <div class="metric-label">Tráfico del puente</div>
        <div id="trafficLevel" class="metric-value">-</div>
        <div id="trafficScore" class="metric-note">Score -</div>
      </article>
      <article class="metric">
        <div class="metric-label">Carril reversible</div>
        <div id="reversibleState" class="metric-value">-</div>
        <div id="reversibleConfidence" class="metric-note">Confianza -</div>
      </article>
      <article class="metric">
        <div class="metric-label">Evidencia visible</div>
        <div id="evidenceCount" class="metric-value">0</div>
        <div id="countsLine" class="metric-note">Paneles 0 · Incidencias 0 · Cámaras 0</div>
      </article>
    </section>

    <section class="grid">
      <div class="card panel-section">
        <div class="section-head">
          <h2>Pulso Reciente</h2>
          <div class="subtle">Últimas ejecuciones guardadas</div>
        </div>
        <div class="timeline">
          <div class="trend-shell">
            <div class="trend-thresholds">
              <div class="trend-line" style="bottom:25%;"><span>Denso</span></div>
              <div class="trend-line" style="bottom:58.33%;"><span>Retenciones</span></div>
              <div class="trend-line" style="bottom:100%;"><span>Congestión</span></div>
            </div>
            <div id="trendBars" class="timeline-bar wide-chart"></div>
          </div>
          <div class="trend-legend">
            <span class="legend-pill"><span class="legend-dot" style="background:#237032;"></span>Fluido</span>
            <span class="legend-pill"><span class="legend-dot" style="background:#b45309;"></span>Denso</span>
            <span class="legend-pill"><span class="legend-dot" style="background:#c2410c;"></span>Retenciones</span>
            <span class="legend-pill"><span class="legend-dot" style="background:#991b1b;"></span>Congestión fuerte</span>
          </div>
          <div class="footer-note">Cada barra representa un estado guardado. El color indica la etiqueta inferida y las líneas marcan los umbrales del score.</div>
        </div>
      </div>
    </section>

    <section class="grid" style="margin-top:18px;">
      <div class="card panel-section">
        <div class="section-head">
          <h2>Paneles Activos</h2>
          <div class="subtle">Mensajes VMS de la zona</div>
        </div>
        <div id="panelsList" class="vms-container"></div>
      </div>
      <div class="card panel-section">
        <div class="section-head">
          <h2>Incidencias Cercanas</h2>
          <div class="subtle">Eventos DATEX2 filtrados por entorno</div>
        </div>
        <div id="incidentsList" class="list"></div>
      </div>
    </section>

    <section class="card panel-section" style="margin-top:18px;">
      <div class="section-head">
        <h2>Cámaras</h2>
        <div class="subtle">Último snapshot disponible por cámara</div>
      </div>
      <div id="cameraGrid" class="camera-grid"></div>
    </section>
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
      return date.toLocaleString("es-ES", {
        dateStyle: "medium",
        timeStyle: "short"
      });
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
      const value = String(label || "").toLowerCase();
      if (value.includes("high") || value.includes("alert") || value.includes("closed")) return "chip alert";
      if (value.includes("medium") || value.includes("warn") || value.includes("retencion")) return "chip warn";
      if (value.includes("200")) return "chip good";
      return "chip";
    }

    function translateEvidence(key) {
      if (!key) return "";
      const parts = key.split(":");
      const type = parts[0];

      if (type === "panel") {
        const loc = parts[1] || "DGT";
        const msg = parts[2] || "Mensaje activo";
        return { icon: "🏛️", text: `Los paneles en <b>${escapeHtml(loc)}</b> muestran: <i>"${escapeHtml(msg)}"</i>` };
      }
      if (type === "incident") {
        const road = parts[1] || "-";
        const cause = parts[2] || "Incidencia";
        return { icon: "⚠️", text: `Incidencia detectada en la <b>${escapeHtml(road)}</b> por <b>${escapeHtml(cause)}</b>` };
      }
      if (type === "camera") {
        if (parts[1] === "visual-change") return { icon: "📸", text: "Se detectan cambios visuales importantes en las imágenes de las cámaras." };
        if (parts[1] === "unavailable") return { icon: "🔌", text: `Hay <b>${parts[2]}</b> cámaras que no están enviando señal actualmente.` };
        if (parts[1] === "vehicles") return { icon: "🚗", text: `Se han detectado un total de <b>${parts[2]}</b> vehículos en el área del puente.` };
      }
      if (type === "reversible") {
        if (parts[1] === "no-directional-signal") return { icon: "❓", text: "No hay evidencia clara de dirección en los mensajes de los paneles." };
        if (parts[1] === "pressure") {
          const dir = parts[2] === "positive" ? "Cádiz" : "Sevilla";
          return { icon: "⬆️", text: `Fuerte tendencia de tráfico hacia <b>${dir}</b> (presión ${parts[3]}).` };
        }
        if (parts[1] === "panel-hits") return { icon: "✅", text: `Hay <b>${parts[2]}</b> paneles que confirman el sentido de la marcha.` };
        if (parts[1] === "incident-hits") return { icon: "🧐", text: `Hay <b>${parts[2]}</b> incidencias que coinciden con el flujo predominante.` };
        if (parts[1] === "low-asymmetry") return { icon: "⚖️", text: "Los datos de ambos sentidos son muy similares; precaución con la estimación." };
      }
      return { icon: "🔍", text: escapeHtml(key) };
    }

    function renderEvidence(evidence) {
      const root = byId("evidenceList");
      if (!evidence || evidence.length === 0) {
        root.innerHTML = '<div class="empty">Todavía no hay evidencia persistida.</div>';
        return;
      }
      root.innerHTML = evidence.map((entry) => {
        const { icon, text } = translateEvidence(entry);
        return `
          <div class="evidence-item">
            <span class="evidence-icon">${icon}</span>
            <span>${text}</span>
          </div>
        `;
      }).join("");
    }

    function renderPanels(panels) {
      const root = byId("panelsList");
      if (!panels || panels.length === 0) {
        root.innerHTML = '<div class="empty">No hay paneles activos registrados en la última ejecución.</div>';
        return;
      }
      root.innerHTML = panels.map((panel) => {
        const title = escapeHtml(panel.location_name || panel.location_id);
        const km = escapeHtml(formatKm(panel.km));
        const dirLabel = panel.direction === "positive" ? "⬆️ Hacia Cádiz" : (panel.direction === "negative" ? "⬇️ Hacia Sevilla" : "↔️ Ambos sentidos");
        const msg = (panel.legends || []).join("<br>");
        const pictos = (panel.pictograms || []).map((p) => `<span class="chip warn">${escapeHtml(p)}</span>`).join("");

        return `
          <div class="vms-item">
            <div class="item-head">
              <span style="font-size:16px;">🏛️ <b>${title}</b></span>
              <span class="subtle">${km}</span>
            </div>
            <div style="font-size:13px; margin-top:4px;" class="subtle">
              ${dirLabel} · Estado: <b>${escapeHtml(panel.status || "Desconocido")}</b>
            </div>
            <div class="vms-panel">
              ${msg || 'NO HAY MENSAJE ACTIVO'}
            </div>
            ${pictos ? `<div class="vms-pictos">${pictos}</div>` : ""}
          </div>
        `;
      }).join("");
    }

    function renderIncidents(incidents) {
      const root = byId("incidentsList");
      if (!incidents || incidents.length === 0) {
        root.innerHTML = '<div class="empty">No hay incidencias cercanas en la última recogida.</div>';
        return;
      }
      root.innerHTML = incidents.map((incident) => `
        <div class="item">
          <div class="item-head">
            <span>${escapeHtml(incident.incident_type || incident.cause_type || "Incidencia")}</span>
            <span>${escapeHtml(formatKm(incident.from_km ?? incident.to_km))}</span>
          </div>
          <div class="subtle">
            ${escapeHtml(incident.road || "-")} · ${escapeHtml(incident.direction || "sin dirección")}
            · ${escapeHtml(incident.municipality || incident.province || "sin municipio")}
          </div>
          <div class="chips">
            <span class="${chipClass(incident.severity)}">${escapeHtml(incident.severity || "sin severidad")}</span>
            <span class="chip">${escapeHtml(incident.validity_status || "sin estado")}</span>
          </div>
        </div>
      `).join("");
    }

    function renderCameras(cameras) {
      const root = byId("cameraGrid");
      if (!cameras || cameras.length === 0) {
        root.innerHTML = '<div class="empty">No hay cámaras inventariadas todavía.</div>';
        return;
      }
      root.innerHTML = cameras.map((camera) => {
        const hasImage = camera.http_status === 200 && camera.image_path;
        const imageUrl = hasImage ? `/snapshots/${encodeURIComponent(camera.image_path.split('/').pop())}` : "";
        return `
          <article class="camera">
            ${hasImage
              ? `<img src="${imageUrl}" alt="Cámara ${escapeHtml(camera.camera_id)}">`
              : `<div style="aspect-ratio:16/10; display:grid; place-items:center; color:#5f6c71; background:linear-gradient(135deg, #e8dcc3, #e7f1ec);">Sin snapshot disponible</div>`}
            <div class="camera-body">
              <div class="camera-title">Cámara ${escapeHtml(camera.camera_id)}</div>
              <div class="camera-meta">
                ${escapeHtml(camera.road || "-")} · ${escapeHtml(formatKm(camera.km))} · ${escapeHtml(camera.direction || "sin dirección")}<br>
                ${camera.vehicle_count != null ? `<b>🚗 ${camera.vehicle_count} vehículos</b><br>` : ""}
                HTTP ${escapeHtml(camera.http_status ?? "-")} · ${escapeHtml(camera.last_modified || camera.fetched_at || "sin fecha")}
              </div>
            </div>
          </article>
        `;
      }).join("");
    }

    function renderTrend(states) {
      const root = byId("trendBars");
      if (!states || states.length === 0) {
        root.innerHTML = '<div class="empty" style="grid-column:1/-1;">Todavía no hay histórico suficiente.</div>';
        return;
      }
      const maxScore = Math.max(...states.map((item) => item.traffic_score || 0), 1);
      root.innerHTML = states.map((item) => {
        const height = Math.max(12, Math.round(((item.traffic_score || 0) / maxScore) * 96));
        const label = new Date(item.generated_at).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
        const levelClass = `level-${escapeHtml(item.traffic_level || "fluido")}`;
        return `
          <div class="bar-wrap">
            <div class="bar-score">${escapeHtml(item.traffic_score ?? "-")}</div>
            <div class="bar ${levelClass}" title="${escapeHtml(item.traffic_level)} · ${escapeHtml(item.traffic_score)}" style="height:${height}px;"></div>
            <div class="bar-label">${escapeHtml(label)}</div>
          </div>
        `;
      }).join("");
    }

    function renderDashboard(data) {
      const state = data.state;
      const latestRun = data.latest_run;
      const warningBox = byId("runWarnings");
      if (!state) {
        byId("generatedAt").textContent = "Sin ejecuciones";
        byId("heroSummary").textContent = "Sin datos";
        byId("heroDetail").textContent = "Esperando a la primera ejecución automática.";
        warningBox.style.display = "none";
        return;
      }
      byId("generatedAt").textContent = `Última lectura · ${formatDate(state.generated_at)}`;
      byId("heroSummary").textContent = stateLabels[state.traffic_level] || state.traffic_level;
      byId("heroDetail").textContent = `Reversible: ${stateLabels[state.reversible_probable] || state.reversible_probable} · ${formatConfidence(state.confidence)} · ${formatForecast(state.forecast)}`;
      byId("trafficLevel").textContent = stateLabels[state.traffic_level] || state.traffic_level;
      byId("trafficScore").textContent = `Score ${state.traffic_score}`;
      byId("reversibleState").textContent = stateLabels[state.reversible_probable] || state.reversible_probable;
      byId("reversibleConfidence").textContent = `${formatConfidence(state.confidence)} · ${formatForecast(state.forecast)}`;
      byId("evidenceCount").textContent = String((state.evidence || []).length);
      const sampleCount = state.learning_context && state.learning_context.sample_count != null
        ? ` · muestras franja ${state.learning_context.sample_count}`
        : "";
      byId("countsLine").textContent = `Paneles ${data.panels.length} · Incidencias ${data.incidents.length} · Cámaras ${data.cameras.length}${sampleCount}`;
      renderEvidence(state.evidence);
      renderPanels(data.panels);
      renderIncidents(data.incidents);
      renderCameras(data.cameras);
      renderTrend(data.recent_states);
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

    loadDashboard().catch((error) => {
      byId("heroDetail").textContent = `Error inicial: ${error.message}`;
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
