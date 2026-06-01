# install.ps1 — instalador Windows APPW2 (Mati - Villa Brisa)
# Uso:  powershell -ExecutionPolicy Bypass -File install.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Chekin Monitor MATI (APPW2) — instalador Windows" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

$pythonCmd = $null
foreach ($cmd in @("python", "py -3.12", "py -3", "py")) {
    try {
        $ver = & $cmd.Split()[0] $cmd.Split()[1..($cmd.Split().Length-1)] --version 2>&1
        if ($ver -match "Python 3\.") {
            $pythonCmd = $cmd
            Write-Host "[1/4] Python detectado: $ver" -ForegroundColor Green
            break
        }
    } catch {}
}
if (-not $pythonCmd) {
    Write-Host "ERROR: Python 3.x no encontrado." -ForegroundColor Red
    Write-Host "       winget install Python.Python.3.12" -ForegroundColor Yellow
    exit 1
}

Write-Host "[2/4] Creando venv…" -ForegroundColor Cyan
& $pythonCmd.Split()[0] $pythonCmd.Split()[1..($pythonCmd.Split().Length-1)] -m venv venv

Write-Host "[3/4] Instalando paquetes Python…" -ForegroundColor Cyan
& "venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
& "venv\Scripts\python.exe" -m pip install --quiet playwright requests python-dotenv schedule
& "venv\Scripts\python.exe" -m playwright install chromium

Write-Host "[4/4] Preparando .env…" -ForegroundColor Cyan
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "    .env creado — EDÍTALO con tus credenciales." -ForegroundColor Yellow
} else {
    Write-Host "    .env ya existe." -ForegroundColor Green
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  Instalación completada." -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Próximos pasos:" -ForegroundColor White
Write-Host "  1. Edita credenciales:   notepad .env"
Write-Host "  2. Activa venv:          .\venv\Scripts\Activate.ps1"
Write-Host "  3. Ejecuta:              python chekin-monitor-mati.py"
Write-Host ""
Write-Host "Email destino: matildelopezcanete@gmail.com (hardcoded)" -ForegroundColor Yellow
