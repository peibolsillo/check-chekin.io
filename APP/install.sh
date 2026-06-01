#!/usr/bin/env bash
set -euo pipefail

# install.sh — auto-install chekin_monitor en Linux LXC (Debian/Ubuntu)
# Uso:
#   chmod +x install.sh && sudo ./install.sh

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

echo "============================================================"
echo "  Chekin Monitor — instalador Linux"
echo "  APP dir: $APP_DIR"
echo "============================================================"

# ── 1. Comprobar root ────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: ejecuta con sudo (necesita apt + playwright deps del sistema)"
    exit 1
fi

# ── 2. Dependencias del sistema ──────────────────────────────────
echo "[1/5] Instalando dependencias APT…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    python3 python3-venv python3-pip \
    xvfb xauth x11vnc xterm \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libpango-1.0-0 libcairo2 libasound2 libatspi2.0-0 \
    libxshmfence1 libgtk-3-0 \
    fonts-liberation fonts-noto-color-emoji \
    curl wget ca-certificates tzdata

# ── 2.5. Google Chrome real ──────────────────────────────────────
if ! command -v google-chrome >/dev/null 2>&1; then
    echo "Instalando Google Chrome stable…"
    wget -qO /tmp/chrome.deb \
        https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
    apt-get install -y -qq /tmp/chrome.deb || apt-get -f install -y -qq
    rm -f /tmp/chrome.deb
fi

# ── 3. venv + pip ────────────────────────────────────────────────
echo "[2/5] Creando venv Python…"
python3 -m venv venv
# shellcheck disable=SC1091
source venv/bin/activate
pip install --upgrade pip --quiet
echo "[3/5] Instalando paquetes Python…"
pip install --quiet playwright requests python-dotenv schedule pyvirtualdisplay playwright-stealth
pip install --quiet patchright || echo "    patchright opcional no instalado"

# ── 4. Chromium Playwright ───────────────────────────────────────
echo "[4/5] Descargando Chromium para Playwright…"
playwright install chromium

# ── 5. Setup .env ────────────────────────────────────────────────
echo "[5/5] Preparando .env…"
if [[ ! -f .env ]]; then
    cp .env.example .env
    chmod 600 .env
    echo ">>> COMPLETA .env con tus credenciales antes de ejecutar."
else
    echo "    .env ya existe (no sobreescribo)."
fi

# Permisos del directorio para usuario actual
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

  2. Captura inicial del token (PRIMERA VEZ, en máquina local con monitor):
       - Ejecuta en tu PC local con HEADLESS=false
       - Hace login manual en Chrome que abre el script
       - Copia el fichero chekin_tokens.json generado al servidor:
           scp chekin_tokens.json root@servidor:$APP_DIR/

  3. Ejecuta en este servidor:
       source $APP_DIR/venv/bin/activate
       python $APP_DIR/chekin_monitor.py

  4. Para arrancar como servicio (systemd):
       Ver $APP_DIR/chekin-monitor.service.example

EOF
