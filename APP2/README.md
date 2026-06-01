# APP2 — Monitor Mati (Villa Brisa)

Variante: solo reservas **Villa Brisa Beach & Grill House**. Email hardcoded `matildelopezcanete@gmail.com`.

## Diferencias vs APP/

| | APP/ | APP2/ |
|---|---|---|
| Filtro apartamento | ninguno | `Villa Brisa Beach & Grill House` |
| Email destino | `.env` `EMAIL_RECEIVER` | hardcoded `matildelopezcanete@gmail.com` |
| Ficheros runtime | `chekin_*.json` | `chekin_*_mati.json` |
| Script | `chekin_monitor.py` | `chekin-monitor-mati.py` |

## Instalación Linux LXC

```bash
chmod +x install.sh
sudo ./install.sh
nano .env
```

## `.env`

```
CHEKIN_EMAIL=tu@email.com
CHEKIN_PASSWORD=tupassword
EMAIL_SENDER=remitente@gmail.com
EMAIL_PASSWORD=xxxx xxxx xxxx xxxx
HEADLESS=true
```

EMAIL_RECEIVER ignorado.

## Primera ejecución (captura token)

1. PC local `HEADLESS=false` → Chrome abre, login manual
2. `chekin_tokens_mati.json` generado
3. `scp chekin_tokens_mati.json root@servidor:/opt/check-chekin.io/APP2/`

## Systemd

```bash
cp chekin-monitor-mati.service.example /etc/systemd/system/chekin-monitor-mati.service
systemctl daemon-reload
systemctl enable --now chekin-monitor-mati
journalctl -u chekin-monitor-mati -f
```
