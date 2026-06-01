#!/usr/bin/env bash
set -euo pipefail

# install.sh — auto-install chekin-monitor-mati en Linux LXC
# Variante Mati: solo Villa Brisa Beach & Grill House → matildelopezcanete@gmail.com

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

echo "============================================================"
echo "  Chekin Monitor MATI — instalador Linux"
echo "  APP dir: $APP_DIR"
echo "============================================================"

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: ejecuta con sudo"
    exit 1
fi

echo "[1/5] Instalando dependencias APT…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    python3 python3-venv python3-pip \
    xvfb xauth \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libpango-1.0-0 libcairo2 libasound2 libatspi2.0-0 \
    libxshmfence1 libgtk-3-0 \
    fonts-liberation fonts-noto-color-emoji \
    curl wget ca-certificates tzdata

echo "[2/5] Creando venv Python…"
python3 -m venv venv
# shellcheck disable=SC1091
source venv/bin/activate
pip install --upgrade pip --quiet
echo "[3/5] Instalando paquetes Python…"
pip install --quiet playwright requests python-dotenv schedule pyvirtualdisplay

echo "[4/5] Descargando Chromium para Playwright…"
playwright install chromium

echo "[5/5] Preparando .env…"
if [[ ! -f .env ]]; then
    cp .env.example .env
    chmod 600 .env
    echo ">>> COMPLETA .env con tus credenciales antes de ejecutar."
else
    echo "    .env ya existe (no sobreescribo)."
fi

REAL_USER="${SUDO_USER:-$USER}"
if [[ -n "$REAL_USER" && "$REAL_USER" != "root" ]]; then
    chown -R "$REAL_USER:$REAL_USER" "$APP_DIR"
fi

cat <<EOF

============================================================
  Instalación completada.
============================================================

Próximos pasos:

  1. Edita credenciales:
       nano $APP_DIR/.env

  2. Captura inicial del token (PRIMERA VEZ, máquina local):
       - Ejecuta en PC local con HEADLESS=false
       - Login manual en Chrome
       - scp chekin_tokens_mati.json root@servidor:$APP_DIR/

  3. Ejecuta:
       source $APP_DIR/venv/bin/activate
       python $APP_DIR/chekin-monitor-mati.py

EOF
