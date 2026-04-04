# VCentenario

MVP en Python para monitorizar el entorno del Puente del Centenario con fuentes publicas de la DGT. El proyecto recoge:

- paneles VMS activos en la zona de la SE-30
- incidencias DATEX2 v3.6 cercanas al puente
- inventario de camaras y snapshots de las camaras cercanas
- un estado agregado del puente con una inferencia inicial de `trafico_puente` y `reversible_probable`

La salida del proyecto es una **estimacion operativa**, no una fuente oficial del estado del carril reversible.

## Fuentes

- Paneles DGT tiempo real: `https://infocar.dgt.es/datex2/dgt/SituationPublication/paneles/content.xml`
- Inventario de paneles: `https://infocar.dgt.es/datex2/dgt/PredefinedLocationsPublication/paneles/content.xml`
- Incidencias DGT DATEX2 v3.6: `https://nap.dgt.es/datex2/v3/dgt/SituationPublication/datex2_v36.xml`
- Inventario de camaras: `https://nap.dgt.es/datex2/v3/dgt/DevicePublication/camaras_datex2_v36.xml`

## Requisitos

- Python 3.9+

## Instalacion

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Extras opcionales:

```bash
pip install -e .[dev]
pip install -e .[vision]
```

Si no quieres instalarlo en editable, tambien puedes ejecutar con `PYTHONPATH=src`.

## Uso rapido

Inicializar la base SQLite:

```bash
PYTHONPATH=src python3 -m vcentenario.cli init-db
```

Recoger una tanda de datos y calcular el estado:

```bash
PYTHONPATH=src python3 -m vcentenario.cli run-once --json
```

Ver el ultimo estado guardado:

```bash
PYTHONPATH=src python3 -m vcentenario.cli latest-state
```

Limpiar historico antiguo:

```bash
PYTHONPATH=src python3 -m vcentenario.cli cleanup --vacuum
```

Levantar la app web:

```bash
PYTHONPATH=src python3 -m vcentenario.cli serve --host 0.0.0.0 --port 8080
```

Luego abre `http://localhost:8080` o la IP del servidor si lo ejecutas en remoto.

## Publicacion en GitHub

Antes de publicar el repositorio:

- revisa que `var/`, `.venv/`, logs y snapshots no se hayan versionado
- no subas tokens ni secretos de despliegue
- el modelo `yolov8n.pt` se trata como artefacto local y no se versiona por defecto
- corrige cualquier dato operativo local antes de hacer el primer commit

## Salida

Ejemplo de salida JSON:

```json
{
  "traffic_level": "denso",
  "traffic_score": 42.0,
  "reversible_probable": "negative",
  "confidence": 0.41,
  "official": false
}
```

## Como funciona

El sistema combina varias senales:

- mensajes VMS activos alrededor del km 13-15 de la SE-30
- incidencias en la SE-30 dentro del entorno del puente
- disponibilidad de camaras y cambios entre snapshots

La inferencia del reversible es deliberadamente conservadora:

- `positive` / `negative` corresponden a la direccion DATEX2 `directionRelative`
- si no hay evidencia suficiente, el sistema devuelve `indeterminado`
- la confianza solo sube cuando coinciden varias senales en el mismo sentido

## Robustez Operativa

- Las peticiones HTTP tienen reintentos con backoff para errores temporales.
- `run-once` ahora tolera fallos parciales: si cae una fuente, el resto sigue procesandose.
- Cada ejecucion guarda un resumen de fuentes, contadores y avisos en SQLite.
- El servicio limpia historico antiguo automaticamente para evitar crecimiento indefinido de la base y de `var/snapshots`.

## Configuracion por entorno

Variables utiles:

- `VCENTENARIO_DB_PATH`
- `VCENTENARIO_SNAPSHOTS_DIR`
- `VCENTENARIO_REQUEST_TIMEOUT`
- `VCENTENARIO_HTTP_MAX_RETRIES`
- `VCENTENARIO_HTTP_RETRY_BACKOFF_SECONDS`
- `VCENTENARIO_ENABLE_REFRESH_ENDPOINT`
- `VCENTENARIO_REFRESH_TOKEN`
- `VCENTENARIO_REFRESH_MIN_INTERVAL_SECONDS`
- `VCENTENARIO_KEEP_STATES`
- `VCENTENARIO_KEEP_COLLECTION_RUNS`
- `VCENTENARIO_KEEP_BATCHES`
- `VCENTENARIO_KEEP_SNAPSHOTS_PER_CAMERA`
- `VCENTENARIO_ENABLE_VISION`
- `VCENTENARIO_YOLO_MODEL_PATH`
- `VCENTENARIO_USER_AGENT`

Ejemplo:

```bash
export VCENTENARIO_HTTP_MAX_RETRIES=3
export VCENTENARIO_KEEP_SNAPSHOTS_PER_CAMERA=48
PYTHONPATH=src python3 -m vcentenario.cli run-once --json
```

## Limitaciones actuales

- No existe una fuente publica oficial con el estado del carril reversible.
- Los detectores DGT de la zona no estan integrados en este MVP porque la investigacion previa sugiere datos obsoletos.
- La metrica de camaras es basica: mide disponibilidad y cambio visual entre snapshots, no conteo de vehiculos.
- La equivalencia de `positive` y `negative` con los sentidos fisicos del puente puede ajustarse mas adelante en configuracion.
- La UI sigue siendo una app server-side muy compacta; la API y el frontend aun viven en el mismo modulo.

## Produccion

El dashboard puede exponerse detras de Nginx, pero la recogida manual queda desactivada por defecto. Si necesitas habilitarla:

```bash
export VCENTENARIO_ENABLE_REFRESH_ENDPOINT=true
export VCENTENARIO_REFRESH_TOKEN='token-largo-y-aleatorio'
```

Las peticiones a `POST /api/refresh` deben enviar:

```text
Authorization: Bearer <token>
```

Ademas, el endpoint aplica un intervalo minimo configurable entre refrescos para reducir abuso.

### Despliegue rapido

El script [`deploy.sh`](/home/kldra/descargas/VCentenario/deploy.sh) ahora:

- crea `.venv` si no existe
- instala el proyecto y extras opcionales
- genera un `EnvironmentFile` para systemd en `/etc/default/vcentenario`
- endurece la unidad systemd con restricciones basicas
- configura Nginx como proxy inverso

Ejemplo:

```bash
sudo APP_HOST=127.0.0.1 APP_PORT=5000 PUBLIC_PORT=8088 ./deploy.sh
```

Si quieres instalar dependencias de desarrollo o vision durante el bootstrap:

```bash
sudo INSTALL_DEV_DEPS=1 INSTALL_VISION_DEPS=1 ./deploy.sh
```

## Estructura

- [`src/vcentenario/cli.py`](/home/kldra/descargas/VCentenario/src/vcentenario/cli.py)
- [`src/vcentenario/service.py`](/home/kldra/descargas/VCentenario/src/vcentenario/service.py)
- [`src/vcentenario/inference.py`](/home/kldra/descargas/VCentenario/src/vcentenario/inference.py)
- [`src/vcentenario/storage.py`](/home/kldra/descargas/VCentenario/src/vcentenario/storage.py)
- [`src/vcentenario/collectors/panels.py`](/home/kldra/descargas/VCentenario/src/vcentenario/collectors/panels.py)
- [`src/vcentenario/collectors/incidents.py`](/home/kldra/descargas/VCentenario/src/vcentenario/collectors/incidents.py)
- [`src/vcentenario/collectors/cameras.py`](/home/kldra/descargas/VCentenario/src/vcentenario/collectors/cameras.py)

## Siguientes pasos recomendados

- integrar una segunda fuente de trafico por tramo o intensidad
- calibrar los pesos de inferencia con historico real
- mejorar la metrica visual de camaras con OpenCV
- anadir reglas horarias y persistencia temporal para el reversible
- exponer autenticacion o rate limiting si el dashboard se publica en Internet
- separar frontend/API en modulos distintos si la interfaz sigue creciendo
