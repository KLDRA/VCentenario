#!/usr/bin/env bash
# Instala Umami Analytics self-hosted y lo integra con el nginx de VCentenario.
# Uso: sudo ./analytics-setup.sh
# Después: visita /umami, crea el sitio, copia el website-id y añádelo a /etc/default/vcentenario.

set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Ejecuta como root o con sudo." >&2
  exit 1
fi

UMAMI_DIR="${UMAMI_DIR:-/opt/umami}"
UMAMI_PORT="${UMAMI_PORT:-3000}"
UMAMI_USER="umami"
VCENTENARIO_NGINX_CONF="${VCENTENARIO_NGINX_CONF:-/etc/nginx/sites-available/vcentenario.conf}"
ENV_FILE="${ENV_FILE:-/etc/default/vcentenario}"

# ── 1. Node.js 20 ──────────────────────────────────────────────────────────────
if ! command -v node >/dev/null 2>&1; then
  echo "Instalando Node.js 20..."
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
else
  echo "Node.js ya instalado: $(node --version)"
fi

# ── 2. PostgreSQL ───────────────────────────────────────────────────────────────
if ! command -v psql >/dev/null 2>&1; then
  echo "Instalando PostgreSQL..."
  apt-get install -y postgresql postgresql-contrib
fi

if ! systemctl is-active --quiet postgresql; then
  systemctl enable postgresql
  systemctl start postgresql
fi

# ── 3. Base de datos ────────────────────────────────────────────────────────────
DB_PASSWORD_FILE="/etc/umami-db-password"
if [[ -f "$DB_PASSWORD_FILE" ]]; then
  DB_PASSWORD=$(cat "$DB_PASSWORD_FILE")
  echo "Usando contraseña de BD existente."
else
  DB_PASSWORD=$(openssl rand -hex 20)
  echo "$DB_PASSWORD" > "$DB_PASSWORD_FILE"
  chmod 600 "$DB_PASSWORD_FILE"
fi

# Crea usuario y BD si no existen
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='${UMAMI_USER}'" \
  | grep -q 1 || sudo -u postgres psql -c "CREATE USER ${UMAMI_USER} WITH PASSWORD '${DB_PASSWORD}';"
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='umami'" \
  | grep -q 1 || sudo -u postgres psql -c "CREATE DATABASE umami OWNER ${UMAMI_USER};"

# ── 4. Usuario del sistema ──────────────────────────────────────────────────────
if ! id "$UMAMI_USER" >/dev/null 2>&1; then
  adduser --system --group --home "$UMAMI_DIR" --no-create-home "$UMAMI_USER"
fi

# ── 5. Clonar / actualizar Umami ────────────────────────────────────────────────
if [[ -d "$UMAMI_DIR/.git" ]]; then
  echo "Actualizando Umami en $UMAMI_DIR..."
  git -C "$UMAMI_DIR" pull --ff-only
else
  echo "Clonando Umami en $UMAMI_DIR..."
  git clone --depth 1 https://github.com/umami-software/umami "$UMAMI_DIR"
fi

# ── 6. Fichero de entorno de Umami ─────────────────────────────────────────────
APP_SECRET=$(openssl rand -hex 32)
cat > "${UMAMI_DIR}/.env" <<ENV
DATABASE_URL=postgresql://${UMAMI_USER}:${DB_PASSWORD}@localhost:5432/umami
APP_SECRET=${APP_SECRET}
BASE_PATH=/umami
PORT=${UMAMI_PORT}
NODE_ENV=production
ENV
chmod 600 "${UMAMI_DIR}/.env"

# ── 7. Instalar dependencias y compilar ─────────────────────────────────────────
chown -R "${UMAMI_USER}:${UMAMI_USER}" "$UMAMI_DIR"
echo "Instalando dependencias npm..."
cd "$UMAMI_DIR"
sudo -u "$UMAMI_USER" npm install --legacy-peer-deps
sudo -u "$UMAMI_USER" npm install prop-types react-aria-components --legacy-peer-deps
echo "Compilando Umami (puede tardar 1-2 minutos)..."
sudo -u "$UMAMI_USER" npm run build

# ── 8. Servicio systemd ─────────────────────────────────────────────────────────
NPM_BIN=$(which npm)
cat > /etc/systemd/system/umami.service <<EOF
[Unit]
Description=Umami Analytics
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=simple
User=${UMAMI_USER}
Group=${UMAMI_USER}
WorkingDirectory=${UMAMI_DIR}
EnvironmentFile=${UMAMI_DIR}/.env
ExecStart=${NPM_BIN} start
Restart=always
RestartSec=5
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable umami
systemctl restart umami

# ── 9. Nginx: añadir location /umami ───────────────────────────────────────────
if [[ -f "$VCENTENARIO_NGINX_CONF" ]] && ! grep -q "location /umami" "$VCENTENARIO_NGINX_CONF"; then
  python3 - "$VCENTENARIO_NGINX_CONF" "$UMAMI_PORT" <<'PYEOF'
import sys
conf_path, port = sys.argv[1], sys.argv[2]
with open(conf_path) as f:
    conf = f.read()
umami_block = f"""    location /umami {{
        proxy_pass http://127.0.0.1:{port};
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}

"""
conf = conf.replace("    location / {", umami_block + "    location / {", 1)
with open(conf_path, "w") as f:
    f.write(conf)
print("Nginx config actualizado.")
PYEOF
  nginx -t && systemctl reload nginx
fi

# ── 10. Resumen ─────────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════"
echo " Umami instalado correctamente"
echo "════════════════════════════════════════════════"
echo ""
echo "Dashboard: http://TU_SERVIDOR/umami"
echo "Login inicial: admin / umami  (¡cámbialo!)"
echo ""
echo "Pasos siguientes:"
echo "  1. Abre http://TU_SERVIDOR/umami y cambia la contraseña de admin"
echo "  2. Ve a Settings > Websites > Add website"
echo "  3. Copia el Website ID que genera Umami"
echo "  4. Añade a $ENV_FILE:"
echo "       VCENTENARIO_UMAMI_WEBSITE_ID=<website-id>"
echo "  5. sudo systemctl restart vcentenario"
echo ""
echo "El script de tracking se inyectará automáticamente en el dashboard público."
