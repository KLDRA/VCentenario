#!/usr/bin/env bash

set -euo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")" && pwd)}"
VENV_BIN_DIR="${VENV_BIN_DIR:-$APP_DIR/.venv/bin}"
PYTHON_BIN="${PYTHON_BIN:-$VENV_BIN_DIR/python3}"
BOOTSTRAP_PYTHON="${BOOTSTRAP_PYTHON:-python3}"
INSTALL_DEV_DEPS="${INSTALL_DEV_DEPS:-0}"
INSTALL_VISION_DEPS="${INSTALL_VISION_DEPS:-0}"
SERVICE_NAME="${SERVICE_NAME:-vcentenario}"
SERVICE_USER="${SERVICE_USER:-${SUDO_USER:-$USER}}"
SERVICE_GROUP="${SERVICE_GROUP:-$SERVICE_USER}"
APP_HOST="${APP_HOST:-127.0.0.1}"
APP_PORT="${APP_PORT:-5000}"
PUBLIC_PORT="${PUBLIC_PORT:-8088}"
SERVER_NAME="${SERVER_NAME:-_}"
ENV_FILE="${ENV_FILE:-/etc/default/${SERVICE_NAME}}"
SVC_FILE="${SVC_FILE:-/etc/systemd/system/${SERVICE_NAME}.service}"
NGINX_AVAILABLE_DIR="${NGINX_AVAILABLE_DIR:-/etc/nginx/sites-available}"
NGINX_ENABLED_DIR="${NGINX_ENABLED_DIR:-/etc/nginx/sites-enabled}"
NGINX_CONF="${NGINX_CONF:-$NGINX_AVAILABLE_DIR/${SERVICE_NAME}.conf}"
PYTHONPATH_VALUE="${PYTHONPATH_VALUE:-src}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Este script debe ejecutarse como root o con sudo." >&2
  exit 1
fi

if ! command -v "$BOOTSTRAP_PYTHON" >/dev/null 2>&1; then
  echo "No se encontró el intérprete base $BOOTSTRAP_PYTHON" >&2
  exit 1
fi

mkdir -p "$NGINX_AVAILABLE_DIR" "$NGINX_ENABLED_DIR"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Creando entorno virtual en $APP_DIR/.venv..."
  "$BOOTSTRAP_PYTHON" -m venv "$APP_DIR/.venv"
fi

echo "Actualizando pip, setuptools y wheel..."
"$PYTHON_BIN" -m pip install --upgrade pip setuptools wheel

INSTALL_TARGET="."
if [[ "$INSTALL_DEV_DEPS" == "1" && "$INSTALL_VISION_DEPS" == "1" ]]; then
  INSTALL_TARGET=".[dev,vision]"
elif [[ "$INSTALL_DEV_DEPS" == "1" ]]; then
  INSTALL_TARGET=".[dev]"
elif [[ "$INSTALL_VISION_DEPS" == "1" ]]; then
  INSTALL_TARGET=".[vision]"
fi

echo "Instalando proyecto $INSTALL_TARGET ..."
(
  cd "$APP_DIR"
  "$PYTHON_BIN" -m pip install -e "$INSTALL_TARGET"
)

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Creando plantilla de entorno en $ENV_FILE..."
  cat > "$ENV_FILE" <<EOF
# Variables de entorno para VCentenario
PYTHONPATH=$PYTHONPATH_VALUE
VCENTENARIO_DB_PATH=$APP_DIR/var/vcentenario.db
VCENTENARIO_SNAPSHOTS_DIR=$APP_DIR/var/snapshots
VCENTENARIO_ENABLE_REFRESH_ENDPOINT=false
# VCENTENARIO_REFRESH_TOKEN=cambia-este-token
VCENTENARIO_REFRESH_MIN_INTERVAL_SECONDS=120
EOF
fi

echo "Creando servicio systemd en $SVC_FILE..."
cat > "$SVC_FILE" <<EOF
[Unit]
Description=Monitor MVP del Puente del Centenario
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_GROUP
WorkingDirectory=$APP_DIR
EnvironmentFile=-$ENV_FILE
Environment=PYTHONPATH=$PYTHONPATH_VALUE
ExecStart=$PYTHON_BIN -m vcentenario.cli serve --host $APP_HOST --port $APP_PORT
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=read-only
ReadWritePaths=$APP_DIR/var
UMask=027

[Install]
WantedBy=multi-user.target
EOF

echo "Recargando y reiniciando $SERVICE_NAME..."
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo "Escribiendo configuración Nginx en $NGINX_CONF..."
cat > "$NGINX_CONF" <<EOF
server {
    listen $PUBLIC_PORT;
    server_name $SERVER_NAME;
    client_max_body_size 1m;

    location / {
        proxy_pass http://$APP_HOST:$APP_PORT;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }
}
EOF

ln -sfn "$NGINX_CONF" "$NGINX_ENABLED_DIR/${SERVICE_NAME}.conf"

echo "Validando y recargando Nginx..."
nginx -t
systemctl reload nginx

echo "Despliegue completado."
echo "Servicio: $SERVICE_NAME"
echo "Aplicación interna: http://$APP_HOST:$APP_PORT"
echo "Puerto público: $PUBLIC_PORT"
echo "Archivo de entorno: $ENV_FILE"
