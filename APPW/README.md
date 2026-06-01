# APPW — Monitor general (Windows)

Versión Windows del monitor general. Chrome visible, sin Xvfb.

## Diferencias vs APP/ (Linux)

| | APP/ | APPW/ |
|---|---|---|
| OS | Linux LXC | Windows |
| Browser | headless + Xvfb | Chrome visible nativo |
| Display | virtual (Xvfb) | real |
| Stealth | playwright-stealth | no necesario |
| Instalación | install.sh | install.ps1 |

## Instalación

```powershell
cd APPW
powershell -ExecutionPolicy Bypass -File install.ps1
notepad .env
```

Si Python no instalado, primero:

```powershell
winget install Python.Python.3.12
```

## Configuración `.env`

```
CHEKIN_EMAIL=tu@email.com
CHEKIN_PASSWORD=tupassword
EMAIL_SENDER=remitente@gmail.com
EMAIL_PASSWORD=xxxx xxxx xxxx xxxx
EMAIL_RECEIVER=destino@gmail.com
HEADLESS=false
```

App password Gmail: https://myaccount.google.com/apppasswords

## Ejecución

```powershell
.\venv\Scripts\Activate.ps1
python chekin_monitor.py
```

O directo sin activar venv:

```powershell
.\venv\Scripts\python.exe chekin_monitor.py
```

Primera vez: Chrome se abre, hace login automático (auto-fill + auto-click), captura tokens, cierra.

Después: usa refresh_token. Reabre Chrome solo cuando refresh caduque (~5 días).

## Background (sigue corriendo tras cerrar terminal)

```powershell
Start-Process pwsh -ArgumentList "-NoProfile","-WindowStyle","Hidden","-Command","cd '$PWD'; .\venv\Scripts\python.exe chekin_monitor.py" -WindowStyle Hidden
```

Para pararlo: `Get-Process python | Stop-Process`

## Ficheros runtime

| Fichero | Descripción |
|---------|-------------|
| `chekin_tokens.json`  | access + refresh token |
| `chekin_state.json`   | estado última consulta |
| `chekin_report.json`  | último informe |
| `chekin_history.json` | log cambios |
| `chekin_debug.png`    | captura navegador si falla |
