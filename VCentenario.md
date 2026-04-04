# Investigación API DGT - Datos de Tráfico en Tiempo Real
> Investigación realizada el 4 de abril de 2026  
> Objetivo inicial: conocer el estado del carril reversible del Puente del Centenario (SE-30, Sevilla)

---

## 1. Infraestructura de datos de la DGT

### Servidor principal
```
https://infocar.dgt.es/datex2/
```

### Directorios raíz disponibles
```
https://infocar.dgt.es/datex2/dgt/         → Datos DGT (paneles, detectores, etc.)
https://infocar.dgt.es/datex2/dt-gv/       → Gobierno Vasco
https://infocar.dgt.es/datex2/lod/         → Datos enlazados
https://infocar.dgt.es/datex2/sct/         → Servei Català de Trànsit
https://infocar.dgt.es/datex2/v3/          → Nueva versión DATEX2 v3.6
```

### Árbol completo de endpoints DGT
```
/datex2/dgt/
├── MeasuredDataPublication/
│   └── detectores/
│       └── content.xml         → Datos en tiempo real de detectores de tráfico
├── PredefinedLocationsPublication/
│   ├── detectores/
│   │   └── content.xml         → Inventario de detectores (coordenadas, carretera, km)
│   ├── paneles/
│   │   └── content.xml         → Inventario de paneles VMS (coordenadas, carretera, km)
│   ├── radares/
│   ├── tramos_invive/
│   ├── tramosriesgomotos/
│   ├── tefiva/
│   └── caminoSantiago/
└── SituationPublication/
    ├── paneles/
    │   └── content.xml         → Estado actual de los paneles VMS (mensajes activos)
    └── all/                    → (vacío / no disponible actualmente)

/datex2/v3/dgt/
└── DevicePublication/
    └── camaras_datex2_v36.xml  → Inventario y URLs de cámaras de tráfico (DATEX2 v3.6)
```

### Portal NAP (Punto de Acceso Nacional)
```
https://nap.dgt.es/dataset       → Listado de todos los datasets disponibles
```

---

## 2. Fuentes de datos: detalle y uso

### 2.1 Paneles VMS - Estado en tiempo real
**URL:**
```
https://infocar.dgt.es/datex2/dgt/SituationPublication/paneles/content.xml
```
**Características:**
- Formato: DATEX2 XML
- Actualización: cada 2 minutos
- Licencia: Creative Commons Attribution (uso libre, también comercial)
- Cobertura: red estatal, excepto País Vasco y Cataluña
- Solo publica paneles con mensaje activo (los paneles en blanco aparecen sin `vmsLegend`)

**Estructura de un panel:**
```xml
<situation id="GUID_PMV__SE_30_0014_800_D_T01">
  <situationRecordCreationTime>2026-04-03T17:47:33+02:00</situationRecordCreationTime>
  <validityStatus>active</validityStatus>
  <overallStartTime>2026-04-03T17:47:33+02:00</overallStartTime>
  <predefinedLocationReference>GUID_PMV_60859</predefinedLocationReference>
  <datexPictogram>roadworks</datexPictogram>
  <vmsLegend>EN PUENTE/ CENTENARIO</vmsLegend>
</situation>
```

**Campos clave del ID:** `GUID_PMV__SE_30_0014_800_D_T01`
- `SE_30` → carretera
- `0014_800` → km 14.8
- `D` / `C` → dirección (D=negativa/Cádiz, C=positiva/Huelva probablemente)
- `T01` → panel 1

**Pictogramas posibles:**
- `blankVoid` → vacío
- `roadworks` → obras
- `maximumSpeedLimit` → límite de velocidad
- `accident` → accidente

**Script Python para filtrar paneles de la SE-30:**
```python
import requests
import xml.etree.ElementTree as ET

URL = "https://infocar.dgt.es/datex2/dgt/SituationPublication/paneles/content.xml"
NS = "http://datex2.eu/schema/1_0/1_0"

r = requests.get(URL)
root = ET.fromstring(r.content)

for sit in root.iter(f'{{{NS}}}situation'):
    sit_id = sit.get('id', '')
    if 'SE_30' in sit_id:
        legends = sit.findall(f'.//{{{NS}}}vmsLegend')
        pictograms = sit.findall(f'.//{{{NS}}}datexPictogram')
        texts = [l.text for l in legends if l.text]
        pics = [p.text for p in pictograms if p.text]
        if texts:
            print(f'ID: {sit_id}')
            print(f'Mensajes: {texts}')
            print(f'Pictogramas: {pics}')
```

---

### 2.2 Paneles VMS - Inventario (coordenadas)
**URL:**
```
https://infocar.dgt.es/datex2/dgt/PredefinedLocationsPublication/paneles/content.xml
```
**Uso:** cruzar el `predefinedLocationReference` de un panel con su ubicación GPS real.

**Script Python para obtener coordenadas de un panel:**
```python
import requests
import xml.etree.ElementTree as ET

URL = "https://infocar.dgt.es/datex2/dgt/PredefinedLocationsPublication/paneles/content.xml"
NS = "http://datex2.eu/schema/1_0/1_0"

GUID_BUSCAR = "GUID_PMV_60859"  # predefinedLocationReference del panel

r = requests.get(URL)
root = ET.fromstring(r.content)

for loc in root.iter():
    tag = loc.tag.split('}')[1] if '}' in loc.tag else loc.tag
    if tag == 'predefinedLocation' and loc.get('id') == GUID_BUSCAR:
        lat = loc.find(f'.//{{{NS}}}latitude')
        lon = loc.find(f'.//{{{NS}}}longitude')
        road = loc.find(f'.//{{{NS}}}roadNumber')
        km = loc.find(f'.//{{{NS}}}referencePointDistance')
        print(f'Carretera: {road.text}')
        print(f'Km: {float(km.text)/1000:.2f}')
        print(f'Lat: {lat.text}, Lon: {lon.text}')
```

**Paneles del Puente del Centenario (SE-30, km 13.5-14.3):**
| GUID | Km | Lat | Lon | Dirección |
|---|---|---|---|---|
| GUID_PMV_60621 | 14.3 | 37.372726 | -6.016794 | positiva |
| GUID_PMV_60859 | 14.2 | 37.372490 | -6.013175 | positiva (Blas Infante) |
| GUID_PMV_166911 | 13.55 | 37.367294 | -6.014398 | negativa |

---

### 2.3 Detectores de tráfico - Datos en tiempo real
**URL:**
```
https://infocar.dgt.es/datex2/dgt/MeasuredDataPublication/detectores/content.xml
```
**Características:**
- Tamaño: ~18MB
- Datos por detector: velocidad media, flujo (veh/h), ocupación (%)
- ⚠️ Algunos detectores llevan meses sin actualizar (averiados)

**Estructura:**
```xml
<siteMeasurements>
  <measurementSiteReference>GUID_DET_132943</measurementSiteReference>
  <measurementTimeDefault>2026-04-04T12:00:00+02:00</measurementTimeDefault>
  <averageVehicleSpeed>65.0</averageVehicleSpeed>
  <vehicleFlow>1200</vehicleFlow>
  <occupancy>12.0</occupancy>
</siteMeasurements>
```

**Script Python para consultar detectores específicos:**
```python
import requests
import xml.etree.ElementTree as ET

URL = "https://infocar.dgt.es/datex2/dgt/MeasuredDataPublication/detectores/content.xml"
NS = "http://datex2.eu/schema/1_0/1_0"

IDS = ['GUID_DET_132943', 'GUID_DET_132946']  # detectores del Centenario

r = requests.get(URL)
root = ET.fromstring(r.content)

for site in root.iter(f'{{{NS}}}siteMeasurements'):
    ref = site.find(f'.//{{{NS}}}measurementSiteReference')
    if ref is not None and ref.text in IDS:
        t     = site.find(f'.//{{{NS}}}measurementTimeDefault')
        speed = site.find(f'.//{{{NS}}}averageVehicleSpeed')
        flow  = site.find(f'.//{{{NS}}}vehicleFlow')
        occ   = site.find(f'.//{{{NS}}}occupancy')
        print(f'{ref.text} | {t.text} | {speed.text} km/h | {flow.text} veh/h | {occ.text}%')
```

**Detectores del Puente del Centenario:**
| ID | Km | Lat | Lon | Estado |
|---|---|---|---|---|
| GUID_DET_132943 | 14.1 | 37.369907 | -6.013525 | ❌ Sin datos desde jun 2025 |
| GUID_DET_132946 | 14.1 | 37.369907 | -6.013525 | ❌ Sin datos desde jun 2025 |
| GUID_DET_133803 | 14.3 | 37.372700 | -6.016792 | ❌ Sin datos desde jun 2025 |
| GUID_DET_133805 | 14.3 | 37.372700 | -6.016792 | ❌ Sin datos desde jun 2025 |
| GUID_DET_133806 | 14.3 | 37.372700 | -6.016792 | ❌ Sin datos desde jun 2025 |
| GUID_DET_133801 | 14.3 | 37.372700 | -6.016792 | ❌ Sin datos desde jun 2025 |
| GUID_DET_132918 | 14.1 | 37.370365 | -6.013441 | ❌ Sin datos desde jun 2025 |
| GUID_DET_132914 | 14.1 | 37.370365 | -6.013441 | ❌ Sin datos desde jun 2025 |

> Nota: Los 4 detectores en el km 14.3 con las mismas coordenadas probablemente son **uno por carril**, incluyendo el reversible. Actualmente todos averiados.

---

### 2.4 Inventario de detectores (coordenadas)
**URL:**
```
https://infocar.dgt.es/datex2/dgt/PredefinedLocationsPublication/detectores/content.xml
```
**Uso:** encontrar detectores por zona geográfica o carretera.

**Script para buscar detectores por coordenadas GPS:**
```python
import requests
import xml.etree.ElementTree as ET

URL = "https://infocar.dgt.es/datex2/dgt/PredefinedLocationsPublication/detectores/content.xml"
NS = "http://datex2.eu/schema/1_0/1_0"

# Zona del Puente del Centenario
LAT_MIN, LAT_MAX = 37.36, 37.38
LON_MIN, LON_MAX = -6.03, -6.00

r = requests.get(URL)
root = ET.fromstring(r.content)

for loc in root.iter():
    tag = loc.tag.split('}')[1] if '}' in loc.tag else loc.tag
    if tag == 'predefinedLocation':
        lat = loc.find(f'.//{{{NS}}}latitude')
        lon = loc.find(f'.//{{{NS}}}longitude')
        if lat is not None and lon is not None:
            la, lo = float(lat.text), float(lon.text)
            if LAT_MIN < la < LAT_MAX and LON_MIN < lo < LON_MAX:
                road = loc.find(f'.//{{{NS}}}roadNumber')
                km = loc.find(f'.//{{{NS}}}referencePointDistance')
                print(f'{loc.get("id")} | {road.text if road is not None else "-"} | km {float(km.text)/1000:.2f} | {la}, {lo}')
```

---

### 2.5 Cámaras de tráfico
**URL del inventario:**
```
https://nap.dgt.es/datex2/v3/dgt/DevicePublication/camaras_datex2_v36.xml
```
**Características:**
- Formato: DATEX2 v3.6 (namespace diferente al v1)
- Tamaño: ~3.6MB
- Contiene: ID, carretera, km, coordenadas GPS, URL de imagen JPG

**URL de imagen en tiempo real:**
```
https://infocar.dgt.es/etraffic/data/camaras/{ID}.jpg
```
Se actualiza cada pocos minutos.

**Script Python para buscar cámaras por zona:**
```python
import requests
import xml.etree.ElementTree as ET

URL = "https://nap.dgt.es/datex2/v3/dgt/DevicePublication/camaras_datex2_v36.xml"

ns = {
    'ns2': 'http://levelC/schema/3/faultAndStatus',
    'loc': 'http://levelC/schema/3/locationReferencing',
    'lse': 'http://levelC/schema/3/locationReferencingSpanishExtension',
    'fse': 'http://levelC/schema/3/faultAndStatusSpanishExtension'
}

LAT_MIN, LAT_MAX = 37.36, 37.38
LON_MIN, LON_MAX = -6.03, -6.00

r = requests.get(URL)
root = ET.fromstring(r.content)

for device in root.findall('.//ns2:device', ns):
    lat = device.find('.//loc:latitude', ns)
    lon = device.find('.//loc:longitude', ns)
    if lat is not None and lon is not None:
        la, lo = float(lat.text), float(lon.text)
        if LAT_MIN < la < LAT_MAX and LON_MIN < lo < LON_MAX:
            dev_id = device.get('id')
            road = device.find('.//loc:roadName', ns)
            km = device.find('.//lse:kilometerPoint', ns)
            url = device.find('.//{http://levelC/schema/3/faultAndStatusSpanishExtension}deviceUrl', ns)
            print(f'ID: {dev_id} | {road.text if road is not None else "-"} km {km.text if km is not None else "-"}')
            if url is not None:
                print(f'  Imagen: {url.text}')
```

**Cámaras del Puente del Centenario:**
| ID | Carretera | Km | Lat | Lon | Estado |
|---|---|---|---|---|---|
| 1337 | SE-30 | 13.5 | 37.366894 | -6.014183 | ✅ Activa (74KB, actualización ~2min) |
| 167841 | SE-30 | 13.1 | 37.365730 | -6.013131 | ❌ HTTP 404 |

> Nota: La cámara 1337 (PK 13+5 D) enfoca el acceso al puente, no el tramo atirantado. No se ve el carril reversible directamente.

---

## 3. Resumen: estado del carril reversible del Centenario

| Fuente | URL | Útil para reversible | Motivo |
|---|---|---|---|
| Paneles SE-30 | SituationPublication/paneles | ⚠️ Parcial | Solo publica incidencias activas, no estado operativo normal |
| Cámara 1337 | /etraffic/data/camaras/1337.jpg | ❌ No | No apunta al tramo atirantado |
| Detectores km 14 | MeasuredDataPublication/detectores | ❌ No | Sin datos desde junio 2025 (averiados) |

**Conclusión:** No existe fuente de datos pública que indique explícitamente el estado del carril reversible. Ese dato se gestiona internamente en el centro de control de tráfico de Sevilla.

---

## 4. Ideas de producto con los datos disponibles

### Monitor de incidencias del Centenario
Combinar:
1. Paneles SE-30 → detectar mensajes activos en km 13-15
2. Cámara 1337 → imagen visual del acceso
3. Bot Telegram → notificar cuando cambie el estado

```python
import requests
import xml.etree.ElementTree as ET
import time

PANELES_URL = "https://infocar.dgt.es/datex2/dgt/SituationPublication/paneles/content.xml"
CAMARA_URL  = "https://infocar.dgt.es/etraffic/data/camaras/1337.jpg"
NS = "http://datex2.eu/schema/1_0/1_0"
INTERVALO = 120  # segundos

estado_anterior = {}

while True:
    r = requests.get(PANELES_URL)
    root = ET.fromstring(r.content)
    estado_actual = {}

    for sit in root.iter(f'{{{NS}}}situation'):
        sit_id = sit.get('id', '')
        if 'SE_30' in sit_id:
            legends = [l.text for l in sit.findall(f'.//{{{NS}}}vmsLegend') if l.text]
            pics = [p.text for p in sit.findall(f'.//{{{NS}}}datexPictogram') if p.text]
            estado_actual[sit_id] = {'mensajes': legends, 'pictogramas': pics}

    # Detectar cambios
    for panel_id, datos in estado_actual.items():
        if panel_id not in estado_anterior or estado_anterior[panel_id] != datos:
            print(f"[CAMBIO] {panel_id}: {datos['mensajes']} {datos['pictogramas']}")
            # Aquí enviar notificación Telegram

    estado_anterior = estado_actual
    time.sleep(INTERVALO)
```

### API pública de paneles de Sevilla
Wrapper sobre los datos de la DGT que exponga solo los paneles de Sevilla en JSON limpio, con geolocalización y estado formateado. Monetizable con suscripción o ads.

---

## 5. Notas técnicas importantes

- **Usar siempre HTTPS**, no HTTP. La DGT redirige con 301 pero curl sin `-L` devuelve 0 bytes.
- El namespace de DATEX2 v1 es `http://datex2.eu/schema/1_0/1_0`
- El namespace de DATEX2 v3.6 es `http://levelC/schema/3/...` (múltiples sub-namespaces)
- Los feeds no requieren autenticación (acceso libre)
- Registrarse en nap.dgt.es permite recibir notificaciones de cambios o caídas del servicio
- El feed de detectores pesa ~18MB, parsear con `iterparse` para mayor eficiencia en producción

---

## 6. Referencias

| Recurso | URL |
|---|---|
| Portal NAP DGT | https://nap.dgt.es |
| Dataset paneles | https://nap.dgt.es/dataset/paneles-dgt-tiempo-real |
| Dataset cámaras v3.6 | https://nap.dgt.es/dataset/camaras-dgt-datex2-v3-6-nuevo |
| Mapa interactivo DGT | https://infocar.dgt.es/etraffic/ |
| Aviso legal DGT | https://www.dgt.es/contenido/aviso-legal/ |
