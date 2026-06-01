#!/usr/bin/env bash
# vnc-setup.sh — abre VNC para clicar Turnstile manual primera vez en LXC
#
# USO:
#   1. En LXC: ./vnc-setup.sh
#   2. En PC Windows: TightVNC/RealVNC viewer → conecta a IP_LXC:5900
#   3. En la sesión VNC, lanza:  python chekin_monitor.py
#   4. Cuando aparezca el checkbox Turnstile, clícalo
#   5. Login completa, perfil chrome_profile/ guarda cf_clearance
#   6. Próximas ejecuciones: auto sin VNC

set -e

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

if ! command -v x11vnc >/dev/null 2>&1; then
    echo "Instala primero:  apt install -y x11vnc xvfb xterm"
    exit 1
fi

# Mata sesión vieja si existe
pkill -f "Xvfb :99" 2>/dev/null || true
pkill -f "x11vnc.*:99" 2>/dev/null || true
sleep 1

echo "[1/3] Arrancando Xvfb display :99 (1280x900)…"
Xvfb :99 -screen 0 1280x900x24 -ac +extension RANDR &
sleep 2

echo "[2/3] Arrancando x11vnc en puerto 5900 (sin password — usa SSH tunnel)…"
x11vnc -display :99 -nopw -listen 0.0.0.0 -xkb -forever -shared -bg -o /tmp/x11vnc.log

# Lanzar xterm dentro del display para que VNC tenga algo visible inicialmente
DISPLAY=:99 xterm -geometry 80x24+10+10 -e "
cd $APP_DIR
source venv/bin/activate
echo ''
echo '============================================================'
echo '  Estás en la sesión VNC del LXC.'
echo '  Ejecuta:  python chekin_monitor.py'
echo '  Cuando aparezca checkbox Turnstile, clícalo.'
echo '============================================================'
bash
" &

IP=$(hostname -I | awk '{print $1}')
cat <<EOF

============================================================
  VNC listo
============================================================

Desde Windows:
  1. Abre TightVNC/RealVNC/UltraVNC viewer
  2. Conecta a:  $IP:5900
       (o por SSH tunnel — más seguro:
        ssh -L 5900:127.0.0.1:5900 root@$IP)
  3. Verás un xterm abierto en la sesión virtual
  4. Ejecuta dentro:  python chekin_monitor.py
  5. Clica el checkbox Turnstile cuando aparezca
  6. Cierra VNC cuando termine

Para parar el VNC: pkill x11vnc; pkill Xvfb
Log: /tmp/x11vnc.log

EOF
