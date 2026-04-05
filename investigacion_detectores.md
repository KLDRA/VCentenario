# Informe de Investigación: Expansión de Cobertura de Detectores (SE-30)

Se ha realizado una investigación para identificar puntos de control de tráfico adicionales en la SE-30, más allá de los límites inmediatos del Puente del V Centenario, con el objetivo de monitorizar los accesos y salidas.

## 📋 Resumen del Radio de Búsqueda
- **Eje:** SE-30 (Sevilla)
- **Rango:** KM 4.0 al KM 25.0 (Cubre ±10 km desde el centro del puente)
- **Fuente de datos:** **DGT (Dirección General de Tráfico)** - Punto de Acceso Nacional (NAP)
- **Protocolo:** DATEX II (XML)
- **URLs Oficiales:**
    - **Inventario:** `https://infocar.dgt.es/datex2/dgt/PredefinedLocationsPublication/detectores/content.xml`
    - **Tiempo Real:** `https://infocar.dgt.es/datex2/dgt/MeasuredDataPublication/detectores/content.xml`

---

## 📍 Puntos de Control Identificados (SE-30)

| Tramo | KM | Ubicación Clave | ID Representativo | Distancia |
| :--- | :--- | :--- | :--- | :--- |
| **Norte (Acceso)** | 4.1 | Enlace A-66 (Mérida) | `GUID_DET_131102` | ~10 km |
| **Norte (Acceso)** | 8.8 | Enlace A-49 (Huelva) | `GUID_DET_131070` | ~5 km |
| **Norte (Proximidad)** | 12.1 | Tablada / Recinto Ferial | `GUID_DET_133796` | ~2 km |
| **PUENTE** | 14.1 | Estructura Principal | `GUID_DET_132943` | 0 km |
| **Sur (Salida)** | 16.2 | Puerto / Avda. de la Raza | `GUID_DET_131165` | ~2 km |
| **Sur (Salida)** | 17.8 | Enlace A-4 (Cádiz) | `GUID_DET_131267` | ~4 km |
| **Sur (Salida)** | 23.2 | Enlace A-92 (Málaga/Granada) | `GUID_DET_131824` | ~9 km |

---

## 📊 Muestra de Datos en Tiempo Real
*Consulta realizada el domingo 05/04/2026 a las 12:08:17*

| KM | ID | Velocidad | Flujo (Veh/h) | Ocupación | Observación |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 12.1 | `132407` | **41.0 km/h** | 1440 | 24% | **Lento/Congestión** |
| 14.1 | `132946` | **54.0 km/h** | 1260 | 13% | Estable |
| 16.2 | `131137` | **77.0 km/h** | 1860 | 16% | Fluido |
| 17.8 | `131279` | **61.0 km/h** | 1680 | 100% | Fluido / Estable |

### Análisis de Frescura de Datos
El feed de la DGT ha demostrado una latencia muy baja:
- **Timestamp de Publicación:** `12:07:09`
- **Timestamp de Medición:** `12:05:00` (Delta de ~2-4 minutos).

---

## 🎯 Conclusiones y Beneficios para el Proyecto

1.  **Detección Anticipada:** El sistema puede identificar retenciones en el KM 12.1 antes de que impacten físicamente en el Puente del Centenario, lo que permitiría lanzar alertas preventivas.
2.  **Validación del Carril Reversible:** Al comparar el flujo del KM 12.1 (entrada) con el del KM 16.2 (salida), se puede estimar con mayor precisión el sentido predominante de la congestión.
3.  **Filtrado de Ruido:** Permite distinguir entre una retención local en el puente (p. ej. por un accidente) y un colapso generalizado de la SE-30.

---
*Investigación documentada para el proyecto VCentenario.*
