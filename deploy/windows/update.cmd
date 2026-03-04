@echo off
setlocal

:: ============================================================
::  GC-Bridge Deployment Update Script
::  Wird vom GitHub Actions Self-Hosted Runner aufgerufen.
::  DEPLOY_TAG muss als Umgebungsvariable gesetzt sein.
:: ============================================================

set "APP_DIR=D:\GC-Bridge-4"
set "LOG_FILE=%APP_DIR%\tmp\logs\deploy.log"

cd /d "%APP_DIR%" || (
    echo [%DATE% %TIME%] ERROR: Cannot cd to %APP_DIR%
    exit /b 1
)

if not exist tmp\logs mkdir tmp\logs

echo [%DATE% %TIME%] ============================== >> "%LOG_FILE%"
echo [%DATE% %TIME%] Deploying %DEPLOY_TAG% >> "%LOG_FILE%"

if "%DEPLOY_TAG%"=="" (
    echo [%DATE% %TIME%] ERROR: DEPLOY_TAG is not set >> "%LOG_FILE%"
    echo ERROR: DEPLOY_TAG is not set
    exit /b 1
)

:: --- Code aktualisieren ---
echo [%DATE% %TIME%] git fetch --tags origin >> "%LOG_FILE%"
git fetch --tags origin >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo [%DATE% %TIME%] ERROR: git fetch failed >> "%LOG_FILE%"
    exit /b 1
)

echo [%DATE% %TIME%] git checkout -f %DEPLOY_TAG% >> "%LOG_FILE%"
git checkout -f %DEPLOY_TAG% >> "%LOG_FILE%" 2>&1
:: Bitdefender GravityZone blocks writes to .cmd files in deploy/windows/ and
:: causes git to exit with code 1 even when the checkout succeeded.
:: Verify success by checking the actual HEAD tag instead of trusting errorlevel.
for /f "delims=" %%T in ('git describe --exact-match --tags HEAD 2^>nul') do set "CURRENT_TAG=%%T"
if not "%CURRENT_TAG%"=="%DEPLOY_TAG%" (
    echo [%DATE% %TIME%] ERROR: git checkout failed, HEAD is at "%CURRENT_TAG%" not "%DEPLOY_TAG%" >> "%LOG_FILE%"
    exit /b 1
)
echo [%DATE% %TIME%] git checkout OK, HEAD verified at %DEPLOY_TAG% >> "%LOG_FILE%"
echo %DEPLOY_TAG%> "%APP_DIR%\VERSION"

:: --- Dependencies installieren ---
echo [%DATE% %TIME%] uv pip install -r requirements.txt >> "%LOG_FILE%"
uv pip install -r requirements.txt >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo [%DATE% %TIME%] ERROR: uv pip install failed >> "%LOG_FILE%"
    exit /b 1
)

:: --- Django Management ---
echo [%DATE% %TIME%] manage.py migrate >> "%LOG_FILE%"
.venv\Scripts\python.exe manage.py migrate --noinput >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo [%DATE% %TIME%] ERROR: migrate failed >> "%LOG_FILE%"
    exit /b 1
)

echo [%DATE% %TIME%] manage.py collectstatic >> "%LOG_FILE%"
.venv\Scripts\python.exe manage.py collectstatic --noinput >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo [%DATE% %TIME%] ERROR: collectstatic failed >> "%LOG_FILE%"
    exit /b 1
)

:: --- Uvicorn neustarten ---
echo [%DATE% %TIME%] Restarting Uvicorn... >> "%LOG_FILE%"
powershell -Command "Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }"  >> "%LOG_FILE%" 2>&1
ping 127.0.0.1 -n 4 >nul
schtasks /Run /TN "GC-Bridge-Uvicorn" >> "%LOG_FILE%" 2>&1

:: --- Scheduled Product Sync Task neu starten (falls vorhanden) ---
echo [%DATE% %TIME%] Refreshing scheduled task "GC-Bridge Scheduled Product Sync"... >> "%LOG_FILE%"
schtasks /Query /TN "GC-Bridge Scheduled Product Sync" >nul 2>&1
if errorlevel 1 (
    echo [%DATE% %TIME%] WARNING: Scheduled task "GC-Bridge Scheduled Product Sync" not found. >> "%LOG_FILE%"
) else (
    schtasks /End /TN "GC-Bridge Scheduled Product Sync" >> "%LOG_FILE%" 2>&1
    ping 127.0.0.1 -n 3 >nul
    schtasks /Run /TN "GC-Bridge Scheduled Product Sync" >> "%LOG_FILE%" 2>&1
)

echo [%DATE% %TIME%] Deployment %DEPLOY_TAG% abgeschlossen >> "%LOG_FILE%"
exit /b 0
