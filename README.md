# check-chekin.io

Monitor automático reservas Chekin.io. Detecta cuando todos huéspedes completan formularios y envía notificación email.

## Apps

| Carpeta | Descripción | Email destino |
|---------|-------------|---------------|
| `APP/`  | Monitor general (todos apartamentos) | configurable en `.env` |
| `APP2/` | Solo Villa Brisa Beach & Grill House | matildelopezcanete@gmail.com (hardcoded) |

## Características

- Login automatizado Chekin (WordPress + ERF + Cloudflare Turnstile)
- API Chekin v4 (`a.chekin.io/api/v4/...`) con refresh token
- Detección reserva → COMPLETE → email con resumen formateado
- HTML email con:
  - Reserva nueva COMPLETE → **fondo verde**
  - Reserva más próxima por apartamento → **marco amarillo**
  - Huésped BEBÉ → **texto rojo**
- Histórico cambios en `chekin_history.json`
- Reintento cada 30 min

## Instalación local (Windows / desktop)

```powershell
pip install playwright requests python-dotenv schedule
playwright install chromium
copy .env.example .env
# Editar .env con credenciales
python chekin_monitor.py
```

Primera ejecución abre Chrome para login manual. Tokens guardados en `chekin_tokens.json`.

## Instalación servidor Linux (Proxmox LXC)

LXC Debian/Ubuntu recomendado.

```bash
# En tu PC local: capturar tokens iniciales primero
cd APP/
# (en local con HEADLESS=false ejecuta chekin_monitor.py)
# tras login manual genera chekin_tokens.json

# Subir al servidor LXC
scp -r APP/ root@servidor:/opt/check-chekin.io/

# En el servidor LXC
ssh root@servidor
cd /opt/check-chekin.io/APP
chmod +x install.sh
sudo ./install.sh

# Editar credenciales
nano .env

# Lanzar como servicio systemd
cp chekin-monitor.service.example /etc/systemd/system/chekin-monitor.service
systemctl daemon-reload
systemctl enable --now chekin-monitor
journalctl -u chekin-monitor -f
```

Para APP2 (mati): mismo flow en `/opt/check-chekin.io/APP2/`.

## Estructura ficheros runtime

| Fichero | Descripción |
|---------|-------------|
| `chekin_tokens.json`  | access + refresh token (5 días vida) |
| `chekin_state.json`   | estado última consulta (para detectar cambios) |
| `chekin_report.json`  | último informe completo |
| `chekin_history.json` | append-only log de cambios |
| `chekin_debug.png`    | captura navegador si falla login |

## Renovar token caducado

Si pasados 5 días el refresh_token caduca:
1. En tu PC local, vuelve a ejecutar `python chekin_monitor.py` con HEADLESS=false
2. Login manual en Chrome
3. Copia nuevo `chekin_tokens.json` al servidor

Mientras llega ese momento, recibirás un email de error.

## Actualizar repo

```bash
cd /opt/check-chekin.io
git pull
systemctl restart chekin-monitor
```

## Requisitos

- Python 3.10+
- Cuenta Chekin activa
- Gmail con App Password (https://myaccount.google.com/apppasswords) para SMTP
