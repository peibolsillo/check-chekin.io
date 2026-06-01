#!/usr/bin/env bash
# bootstrap.sh — instalación completa Chekin Monitor en Linux LXC limpio
# Uso:
#   wget -O - https://raw.githubusercontent.com/peibolsillo/check-chekin.io/main/bootstrap.sh | sudo bash -s app
#   wget -O - https://raw.githubusercontent.com/peibolsillo/check-chekin.io/main/bootstrap.sh | sudo bash -s app-mati
#
# Argumentos:
#   app       → instala APP/ (monitor general)
#   app-mati  → instala APP2/ (filtro Villa Brisa, email Mati)
#   both      → instala ambos
#
# Sin argumentos → preguntar interactivo.

set -euo pipefail

REPO_URL="https://github.com/peibolsillo/check-chekin.io.git"
INSTALL_DIR="${INSTALL_DIR:-/opt}"
TARGET="${1:-}"

red()    { printf "\033[31m%s\033[0m\n" "$*"; }
green()  { printf "\033[32m%s\033[0m\n" "$*"; }
yellow() { printf "\033[33m%s\033[0m\n" "$*"; }
blue()   { printf "\033[34m%s\033[0m\n" "$*"; }

# ── 0. Root ──────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    red "ERROR: ejecuta como root o con sudo"
    exit 1
fi

# ── 1. Selección target ──────────────────────────────────────────
if [[ -z "$TARGET" ]]; then
    echo "¿Qué instalar?"
    echo "  1) app       (APP/ monitor general)"
    echo "  2) app-mati  (APP2/ filtro Villa Brisa → Mati)"
    echo "  3) both      (ambos)"
    read -rp "Selección [1/2/3]: " choice
    case "$choice" in
        1) TARGET="app" ;;
        2) TARGET="app-mati" ;;
        3) TARGET="both" ;;
        *) red "Opción inválida"; exit 1 ;;
    esac
fi

blue "============================================================"
blue "  Chekin Monitor — Bootstrap"
blue "  Target: $TARGET"
blue "  Dir base: $INSTALL_DIR"
blue "============================================================"

# ── 2. Comprobar red + DNS ───────────────────────────────────────
blue "[1/7] Comprobando red…"
if ! ping -c 1 -W 3 8.8.8.8 >/dev/null 2>&1; then
    red "Sin conexión IP. Configura la red del LXC en Proxmox primero."
    exit 1
fi
if ! ping -c 1 -W 3 github.com >/dev/null 2>&1; then
    yellow "DNS no resuelve. Añadiendo 8.8.8.8 a /etc/resolv.conf…"
    echo "nameserver 8.8.8.8"  >> /etc/resolv.conf
    echo "nameserver 1.1.1.1" >> /etc/resolv.conf
    if ! ping -c 1 -W 3 github.com >/dev/null 2>&1; then
        red "DNS sigue fallando. Revisa la red Proxmox."
        exit 1
    fi
fi
green "    Red OK."

# ── 3. Dependencias APT ──────────────────────────────────────────
blue "[2/7] apt update + dependencias del sistema…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    git curl wget ca-certificates tzdata sudo nano gnupg \
    python3 python3-venv python3-pip \
    xvfb xauth x11vnc xterm \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libpango-1.0-0 libcairo2 libasound2 libatspi2.0-0 \
    libxshmfence1 libgtk-3-0 \
    fonts-liberation fonts-noto-color-emoji

# Instalar Google Chrome real (no Chromium) — passes Cloudflare mejor
if ! command -v google-chrome >/dev/null 2>&1; then
    blue "    Instalando Google Chrome stable…"
    wget -qO /tmp/chrome.deb \
        https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
    apt-get install -y -qq /tmp/chrome.deb || apt-get -f install -y -qq
    rm -f /tmp/chrome.deb
fi
green "    APT deps + Chrome instalados."

# ── 4. Clonar repo ───────────────────────────────────────────────
blue "[3/7] Clonando repo…"
REPO_DIR="$INSTALL_DIR/check-chekin.io"
if [[ -d "$REPO_DIR/.git" ]]; then
    yellow "    Repo ya existe — git pull"
    cd "$REPO_DIR"
    git pull --ff-only || true
else
    git clone "$REPO_URL" "$REPO_DIR"
fi
green "    Repo en $REPO_DIR"

# ── 5. Función instalación por app ───────────────────────────────
install_app() {
    local src_dir="$1"     # ej. APP o APP2
    local dst_name="$2"    # ej. app o app-mati
    local main_script="$3" # ej. chekin_monitor.py
    local svc_name="$4"    # ej. chekin-monitor

    local target_dir="$INSTALL_DIR/$dst_name"

    blue "----- Instalando $src_dir → $target_dir -----"

    # Copiar contenido del subdir
    if [[ -d "$target_dir" ]]; then
        yellow "    $target_dir ya existe — sobreescribo ficheros (preservo .env y *.json runtime)"
        cp -r "$REPO_DIR/$src_dir/"*.py "$target_dir/" 2>/dev/null || true
        cp -r "$REPO_DIR/$src_dir/"*.sh "$target_dir/" 2>/dev/null || true
        cp -r "$REPO_DIR/$src_dir/"*.example "$target_dir/" 2>/dev/null || true
        cp "$REPO_DIR/$src_dir/README.md" "$target_dir/" 2>/dev/null || true
        cp "$REPO_DIR/$src_dir/.env.example" "$target_dir/" 2>/dev/null || true
    else
        cp -r "$REPO_DIR/$src_dir" "$target_dir"
    fi

    cd "$target_dir"

    # venv + pip
    blue "    [4/7] Creando venv…"
    python3 -m venv venv
    # shellcheck disable=SC1091
    source venv/bin/activate
    pip install --upgrade pip --quiet
    blue "    [5/7] Instalando paquetes Python…"
    pip install --quiet playwright requests python-dotenv schedule pyvirtualdisplay playwright-stealth
    pip install --quiet patchright || yellow "    patchright no instalado (no esencial)"

    blue "    [6/7] Instalando navegadores Playwright + Patchright…"
    playwright install chromium
    patchright install chromium 2>/dev/null || true

    # .env desde example
    if [[ ! -f .env ]]; then
        cp .env.example .env
        chmod 600 .env
        yellow "    .env creado — EDITA con tus credenciales"
    else
        green "    .env preservado."
    fi
    deactivate

    blue "    [7/7] Servicio systemd…"
    local svc_file="/etc/systemd/system/$svc_name.service"
    if [[ ! -f "$svc_file" ]]; then
        cat > "$svc_file" <<EOF
[Unit]
Description=Chekin Monitor ($dst_name)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$target_dir
ExecStart=$target_dir/venv/bin/python $target_dir/$main_script
Restart=on-failure
RestartSec=30
StandardOutput=append:/var/log/$svc_name.log
StandardError=append:/var/log/$svc_name.log

[Install]
WantedBy=multi-user.target
EOF
        systemctl daemon-reload
        yellow "    Servicio creado: $svc_file (NO arrancado todavía)"
    else
        green "    Servicio ya existe."
    fi

    green "    $dst_name instalado."
}

# ── 6. Ejecutar por target ───────────────────────────────────────
case "$TARGET" in
    app)
        install_app "APP"  "app"      "chekin_monitor.py"        "chekin-monitor"
        ;;
    app-mati)
        install_app "APP2" "app-mati" "chekin-monitor-mati.py"   "chekin-monitor-mati"
        ;;
    both)
        install_app "APP"  "app"      "chekin_monitor.py"        "chekin-monitor"
        install_app "APP2" "app-mati" "chekin-monitor-mati.py"   "chekin-monitor-mati"
        ;;
    *)
        red "Target desconocido: $TARGET"
        exit 1
        ;;
esac

# ── 7. Resumen final ─────────────────────────────────────────────
blue "============================================================"
green "  Instalación completada."
blue "============================================================"
cat <<EOF

Próximos pasos:

  1. Edita credenciales:
       nano $INSTALL_DIR/app/.env       # si instalaste 'app'
       nano $INSTALL_DIR/app-mati/.env  # si instalaste 'app-mati'

  2. Captura token inicial en tu PC LOCAL (no en este servidor):
       - En máquina con monitor, ejecuta el script con HEADLESS=false
       - Login manual en Chrome
       - Copia chekin_tokens*.json al servidor:
           scp chekin_tokens.json      root@IP:$INSTALL_DIR/app/
           scp chekin_tokens_mati.json root@IP:$INSTALL_DIR/app-mati/

  3. Arrancar servicios:
       systemctl enable --now chekin-monitor
       systemctl enable --now chekin-monitor-mati

  4. Logs:
       journalctl -u chekin-monitor -f
       tail -f /var/log/chekin-monitor.log

  5. Actualizar a futuro:
       cd $INSTALL_DIR/check-chekin.io && git pull
       # luego re-ejecutar este bootstrap o copiar el .py al dir destino

EOF
