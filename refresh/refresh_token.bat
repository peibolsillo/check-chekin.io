@echo off
title CHEKIN.IO - Renovar Token
color 0A
cd /d %~dp0

echo ====================================================
echo   CHEKIN.IO - Renovacion de Token de Acceso
echo ====================================================
echo.
echo Verificando dependencias Python...
pip install requests playwright paramiko python-dotenv --quiet --disable-pip-version-check
if %errorlevel% neq 0 (
    echo.
    echo ERROR: pip no disponible.
    echo Asegurate de tener Python instalado y en el PATH.
    pause
    exit /b 1
)

echo Verificando Chromium...
playwright install chromium --quiet

echo.
echo ====================================================
echo   Iniciando captura de token...
echo ====================================================
echo.

python refresh_token.py

if %errorlevel% neq 0 (
    echo.
    echo ERROR: El proceso fallo. Revisa los mensajes anteriores.
    pause
    exit /b 1
)
