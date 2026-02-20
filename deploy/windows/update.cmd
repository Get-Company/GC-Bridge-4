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
if errorlevel 1 (
    echo [%DATE% %TIME%] ERROR: git checkout failed >> "%LOG_FILE%"
    exit /b 1
)

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
timeout /t 3 /nobreak > nul
schtasks /Run /TN "GC-Bridge-Uvicorn" >> "%LOG_FILE%" 2>&1

echo [%DATE% %TIME%] Deployment %DEPLOY_TAG% abgeschlossen >> "%LOG_FILE%"
exit /b 0
