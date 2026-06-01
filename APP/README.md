# APP — Monitor general

Monitor general reservas Chekin. Todos apartamentos. Email a destinatario configurable.

## Instalación

### Linux LXC (Proxmox)
```bash
chmod +x install.sh
sudo ./install.sh
nano .env
```

### Windows local
```powershell
pip install playwright requests python-dotenv schedule
playwright install chromium
copy .env.example .env
python chekin_monitor.py
```

## `.env`

```
CHEKIN_EMAIL=tu@email.com
CHEKIN_PASSWORD=tupassword
EMAIL_SENDER=remitente@gmail.com
EMAIL_PASSWORD=xxxx xxxx xxxx xxxx
EMAIL_RECEIVER=destino@gmail.com
HEADLESS=true
```

## Primera ejecución (captura token)

1. PC local con `HEADLESS=false` → Chrome abre, login manual
2. `chekin_tokens.json` generado
3. Copiar al servidor: `scp chekin_tokens.json root@servidor:/opt/check-chekin.io/APP/`

## Systemd

```bash
cp chekin-monitor.service.example /etc/systemd/system/chekin-monitor.service
systemctl daemon-reload
systemctl enable --now chekin-monitor
journalctl -u chekin-monitor -f
```
