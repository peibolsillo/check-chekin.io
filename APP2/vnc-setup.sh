#!/usr/bin/env bash
# vnc-setup.sh — VNC para clicar Turnstile manual (Mati Villa Brisa)

set -e

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

if ! command -v x11vnc >/dev/null 2>&1; then
    echo "Instala primero:  apt install -y x11vnc xvfb xterm"
    exit 1
fi

pkill -f "Xvfb :99" 2>/dev/null || true
pkill -f "x11vnc.*:99" 2>/dev/null || true
sleep 1

echo "[1/3] Arrancando Xvfb :99 (1280x900)…"
Xvfb :99 -screen 0 1280x900x24 -ac +extension RANDR &
sleep 2

echo "[2/3] Arrancando x11vnc en puerto 5900…"
x11vnc -display :99 -nopw -listen 0.0.0.0 -xkb -forever -shared -bg -o /tmp/x11vnc.log

DISPLAY=:99 xterm -geometry 80x24+10+10 -e "
cd $APP_DIR
source venv/bin/activate
echo ''
echo '============================================================'
echo '  Sesión VNC del LXC (Mati).'
echo '  Ejecuta:  python chekin-monitor-mati.py'
echo '  Clica checkbox Turnstile cuando aparezca.'
echo '============================================================'
bash
" &

IP=$(hostname -I | awk '{print $1}')
cat <<EOF

============================================================
  VNC listo
============================================================
  Desde Windows: conecta VNC viewer a $IP:5900
  (o SSH tunnel: ssh -L 5900:127.0.0.1:5900 root@$IP)
  En xterm: python chekin-monitor-mati.py
  Parar: pkill x11vnc; pkill Xvfb
============================================================
EOF
