# Calibración del carril reversible — Puente del Centenario

Este documento recoge las hipótesis actuales del modelo de inferencia y las preguntas concretas que los datos de observación directa deberían responder. Revisarlo cuando haya acumuladas **2–4 semanas** de reportes.

---

## Qué registra el sistema

Cada vez que el usuario pulsa un botón en el dashboard, se guarda en la tabla `reversible_reports`:

| Campo | Valor |
|---|---|
| `reported_at` | Timestamp UTC del momento de la observación |
| `direction` | `positive` (→ Huelva), `negative` (← Cádiz) o `none` |

En ese mismo instante, la tabla `detector_readings` tiene las velocidades TomTom para las dos rutas (`tomtom_route_huelva`, `tomtom_route_cadiz`). Y `bridge_state` tiene la predicción del modelo.

---

## Consultas SQL para calibrar

### 1. ¿Con qué diferencia de velocidad se abre para cada sentido?

```sql
SELECT
  r.direction AS observado,
  AVG(h.average_speed - c.average_speed) AS diff_huelva_menos_cadiz,
  AVG(h.average_speed) AS vel_huelva,
  AVG(c.average_speed) AS vel_cadiz,
  COUNT(*) AS n
FROM reversible_reports r
JOIN detector_readings h
  ON h.detector_id = 'tomtom_route_huelva'
  AND h.collected_at = (
    SELECT MAX(d.collected_at) FROM detector_readings d
    WHERE d.detector_id = 'tomtom_route_huelva'
      AND d.collected_at <= datetime(r.reported_at)
  )
JOIN detector_readings c
  ON c.detector_id = 'tomtom_route_cadiz'
  AND c.collected_at = h.collected_at
WHERE r.direction IN ('positive', 'negative')
GROUP BY r.direction;
```

**Qué buscar:** si `direction=positive` siempre aparece cuando `vel_huelva > vel_cadiz` (o al revés), confirma o invierte la lógica de asimetría. Ajustar `TOMTOM_ASYMMETRY_THRESHOLD` al valor de `diff_huelva_menos_cadiz` observado.

---

### 2. ¿El modelo acierta?

```sql
SELECT
  r.direction AS observado,
  bs.reversible_probable AS inferido,
  CASE WHEN r.direction = bs.reversible_probable THEN 'correcto' ELSE 'error' END AS resultado,
  bs.confidence,
  COUNT(*) AS n
FROM reversible_reports r
JOIN bridge_state bs
  ON bs.generated_at = (
    SELECT MAX(b.generated_at) FROM bridge_state b
    WHERE b.generated_at <= datetime(r.reported_at)
  )
WHERE r.direction != 'none'
GROUP BY resultado, r.direction, bs.reversible_probable
ORDER BY resultado, n DESC;
```

**Qué buscar:** si `resultado=error` predomina para un sentido concreto, la señal está invertida o el peso del reporte anterior del usuario está dominando incorrectamente.

---

### 3. ¿A qué horas se abre cada sentido?

```sql
SELECT
  direction,
  strftime('%w', reported_at) AS dia_semana,   -- 0=domingo, 1=lunes...
  strftime('%H', reported_at) AS hora_utc,
  COUNT(*) AS n
FROM reversible_reports
WHERE direction IN ('positive', 'negative')
GROUP BY direction, dia_semana, hora_utc
ORDER BY n DESC;
```

**Qué buscar:** franjas horarias con ≥3 observaciones del mismo sentido → candidatas para añadir a `VCENTENARIO_REVERSIBLE_SCHEDULE`.

---

### 4. ¿El retardo TomTom (`vehicle_flow`) es útil?

```sql
SELECT
  r.direction AS observado,
  AVG(h.vehicle_flow) AS retardo_huelva_seg,
  AVG(c.vehicle_flow) AS retardo_cadiz_seg,
  COUNT(*) AS n
FROM reversible_reports r
JOIN detector_readings h ON h.detector_id = 'tomtom_route_huelva'
  AND h.collected_at = (
    SELECT MAX(d.collected_at) FROM detector_readings d
    WHERE d.detector_id = 'tomtom_route_huelva'
      AND d.collected_at <= datetime(r.reported_at)
  )
JOIN detector_readings c ON c.detector_id = 'tomtom_route_cadiz'
  AND c.collected_at = h.collected_at
WHERE r.direction IN ('positive', 'negative')
GROUP BY r.direction;
```

**Qué buscar:** si el sentido congestionado siempre tiene retardo > X segundos, ese umbral puede convertirse en señal directa en `score_detectors`.

---

## Umbrales actuales (a revisar)

| Constante | Valor actual | Qué medir para ajustar |
|---|---|---|
| `TOMTOM_ASYMMETRY_THRESHOLD` | 8.0 km/h | Consulta 1: diferencia media al cambiar sentido |
| `TOMTOM_ASYMMETRY_MAX_WEIGHT` | 8.0 | Consulta 2: ¿el modelo acierta sin señal de usuario? |
| `TOMTOM_JUMP_THRESHOLD` | 7.0 km/h | Consulta 1: variación entre lectura previa y actual al abrir |
| `TOMTOM_JUMP_MAX_WEIGHT` | 5.0 | Consulta 2: peso suficiente para dominar sobre persistencia |
| `TOMTOM_HISTORY_WINDOW` | 4 lecturas (~20 min) | Consulta 1: cuántas lecturas antes del cambio ya reflejan el patrón |

---

## Procedimiento de revisión

1. Ejecutar las consultas sobre la BD: `VCENTENARIO_DB_PATH` (por defecto `var/traffic.db`).
2. Comparar con los umbrales de la tabla anterior.
3. Actualizar las constantes en `src/vcentenario/inference.py` (bloque `# TomTom reversible inference thresholds`).
4. Si hay patrones horarios claros (consulta 3), añadirlos a `VCENTENARIO_REVERSIBLE_SCHEDULE`.
5. Reiniciar el servicio: `sudo systemctl restart vcentenario.service`.

Con **~30 observaciones** repartidas entre distintos días y horas ya hay suficiente señal para las consultas 1 y 3. Para la consulta 2 (accuracy) conviene esperar a tener al menos 15 observaciones sin reporte reciente activo (para que el modelo prediga solo, sin que el peso del usuario lo domine).
