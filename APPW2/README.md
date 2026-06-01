# APPW2 — Monitor Mati Villa Brisa (Windows)

Versión Windows del filtro Villa Brisa. Email hardcoded a `matildelopezcanete@gmail.com`.

## Diferencias vs APP2/ (Linux)

| | APP2/ | APPW2/ |
|---|---|---|
| OS | Linux LXC | Windows |
| Browser | headless + Xvfb | Chrome visible nativo |
| Stealth | playwright-stealth | no necesario |
| Instalación | install.sh | install.ps1 |

## Filtro

Solo reservas de: **Villa Brisa Beach & Grill House**

## Instalación

```powershell
cd APPW2
powershell -ExecutionPolicy Bypass -File install.ps1
notepad .env
```

## `.env`

```
CHEKIN_EMAIL=tu@email.com
CHEKIN_PASSWORD=tupassword
EMAIL_SENDER=remitente@gmail.com
EMAIL_PASSWORD=xxxx xxxx xxxx xxxx
HEADLESS=false
```

EMAIL_RECEIVER ignorado.

## Ejecución

```powershell
.\venv\Scripts\Activate.ps1
python chekin-monitor-mati.py
```

## Ficheros runtime (sufijo `_mati`)

| Fichero |
|---------|
| `chekin_tokens_mati.json` |
| `chekin_state_mati.json` |
| `chekin_report_mati.json` |
| `chekin_history_mati.json` |
