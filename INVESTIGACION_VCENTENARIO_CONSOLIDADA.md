# Informe Consolidado de Investigación: Proyecto VCentenario

Este documento unifica todas las investigaciones realizadas sobre las fuentes de datos de tráfico (DGT y TomTom) para la monitorización del Puente del V Centenario (SE-30, Sevilla).

---

## 1. Contexto y Objetivos
El objetivo principal es monitorizar en tiempo real el tráfico y el estado del carril reversible del Puente del Centenario. Debido a que los detectores físicos de la DGT en el puente están averiados desde junio de 2025, se han integrado fuentes alternativas (TomTom) y se ha expandido el radio de búsqueda de detectores funcionales.

---

## 2. Infraestructura de Datos de la DGT

### 2.1 Fuentes Disponibles
- **Servidor Principal**: `https://infocar.dgt.es/datex2/`
- **Punto de Acceso Nacional (NAP)**: `https://nap.dgt.es/`
- **Protocolo**: DATEX II (XML).

### 2.2 Paneles de Mensaje Variable (VMS)
- **URL Tiempo Real**: `https://infocar.dgt.es/datex2/dgt/SituationPublication/paneles/content.xml`
- **Uso**: Detectar mensajes activos sobre carriles reversibles u obras.
- **Paneles Clave**:
| GUID | Km | Lat / Lon | Ubicación |
|---|---|---|---|
| `60621` | 14.3 | 37.37, -6.01 | Acceso Norte |
| `60859` | 14.2 | 37.37, -6.01 | Blas Infante |
| `166911` | 13.5 | 37.36, -6.01 | Acceso Sur |

### 2.3 Cámaras de Tráfico (Webcams)
- **Inventario (v3.6)**: `https://nap.dgt.es/datex2/v3/dgt/DevicePublication/camaras_datex2_v36.xml`
- **Cámara Principal**: `1337` (KM 13.5) - Enfoca el acceso sur.
- **URL Imagen**: `https://infocar.dgt.es/etraffic/data/camaras/{ID}.jpg` (Actualización ~2 min).

### 2.4 Detectores de Tráfico (DGT)
- **Estado**: Los detectores situados directamente en el puente (KM 14.1 y 14.3) **no funcionan** desde junio de 2025.
- **Expansión de Cobertura**: Se han identificado detectores funcionales en puntos alejados para anticipar retenciones:
| Tramo | KM | ID | Utilidad |
|---|---|---|---|
| **Norte** | 8.8 | `131070` | Monitorizar acceso Huelva/A-49 |
| **Norte** | 12.1 | `133796` | Proximidad Tablada (Entrada) |
| **Sur** | 16.2 | `131165` | Salida Puerto (Salida) |
| **Sur** | 17.8 | `131267` | Enlace Cádiz/A-4 |

---

## 3. Integración de TomTom Traffic API

Debido a los fallos en los detectores de la DGT, la Traffic Flow API de TomTom se convierte en la fuente principal de velocidades.

### 3.1 Datos de Flujo (Real-time Flow)
- **Endpoint**: `https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json`
- **Parámetros**: `point={lat},{lon}`, `unit=KMPH`.
- **Métrica clave**: `currentSpeed / freeFlowSpeed`.

### 3.2 ⚠️ Calibración Crítica: Límite de 60 km/h
- **Discrepancia**: TomTom reporta un `freeFlowSpeed` de **78 km/h** para el puente.
- **Realidad**: El límite está fijado en **60 km/h** debido a radares de tramo y seguridad estructural.
- **Decisión**: Para el cálculo de congestión, se debe usar una constante de **60.0** como divisor, ignorando el dato de TomTom.

### 3.3 Incidentes y Contexto (TomTom Traffic Incidents)
A diferencia de los detectores de la DGT, la Incident Details API de TomTom permite conocer la **causa** de las retenciones en tiempo real:

| Tipo de Incidente | Valor para el Proyecto |
| :--- | :--- |
| `Accident` | Identifica colisiones. Crítico para alertas de seguridad. |
| `BrokenDownVehicle` | **Coche averiado**. Vital en el puente debido a sus carriles estrechos. |
| `Roadworks` | Obras o mantenimiento (frecuente por el cambio de tirantes). |
| `Jam` | Congestión por saturación (hora punta) sin causa externa. |

- **Longitud de la retención**: TomTom proporciona el campo `incidentLength`, que indica la extensión física del atasco en **metros**.
- **Métricas de impacto**:
  - `magnitudeOfDelay`: Gravedad del incidente (1: leve, 2: moderada, 3: alta, 4: bloqueo total).
  - `delay`: Tiempo de retraso adicional estimado en segundos.
- **Radares**: TomTom ofrece un servicio premium de `Speed Cameras` (fijos, móviles y tramo), aunque se recomienda usar el inventario oficial de la DGT para los puntos fijos.

---

## 4. Lógica de Inferencia del Carril Reversible

Dado que no hay una fuente que indique explícitamente el estado del carril reversible, se utiliza la **asimetría de velocidades**:

| Patrón Detectado | Inferencia Sugerida |
|---|---|
| Sur lento + Norte fluido | Reversible abierto hacia **Norte** (Mañana/Entrada) |
| Norte lento + Sur fluido | Reversible abierto hacia **Sur** (Tarde/Salida) |
| Ambos fluidos | Tráfico bajo, carril probablemente cerrado o neutro |

---

## 5. Resumen Comparativo (DGT vs TomTom)

| Característica | DGT (Prensa/NAP) | TomTom Traffic |
|---|---|---|
| **Velocidad** | ❌ Averiados en puente | ✅ Operativo 24/7 |
| **Paneles VMS** | ✅ Oficial (Mensajes) | ❌ No disponible |
| **Fotos Reales** | ✅ Cámara 1337 | ❌ No disponible |
| **Radares** | ✅ Inventario Oficial | ⚠️ Estimado/Crowdsourcido |
| **Incidencias** | ⚠️ Latencia 5-10 min | ✅ Alta frescura |

---

## 6. Recomendaciones Técnicas
1.  **Usar HTTPS** siempre para las peticiones a la DGT (redirige 301).
2.  **API Key TomTom**: Mantener en variable de entorno `VCENTENARIO_TOMTOM_API_KEY`.
3.  **Refresco**: Intervalo recomendado de 120-300 segundos para equilibrar frescura y cuotas (Tier gratuito TomTom: 2.500/día).

---
*Investigación consolidada para el proyecto VCentenario.*
