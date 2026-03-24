@echo off
setlocal EnableExtensions

:: ============================================================
::  GC-Bridge One-Click Start
::  Startet Uvicorn und Caddy ueber geplante Tasks.
:: ============================================================

for %%I in ("%~dp0..\..") do set "APP_DIR=%%~fI"
cd /d "%APP_DIR%" || exit /b 1

set "NO_PAUSE=0"
if /I "%~1"=="--no-pause" set "NO_PAUSE=1"

set "ERR=0"

echo [INFO] Starte GC-Bridge Dienste...

echo [INFO] -> Stelle Task GC-Bridge-Log-Prune sicher und starte ihn
call "%APP_DIR%\deploy\windows\ensure-log-prune-task.cmd"
if errorlevel 1 (
    echo [ERROR] Task GC-Bridge-Log-Prune konnte nicht sichergestellt/gestartet werden.
    set "ERR=1"
)

timeout /t 2 /nobreak >nul

echo [INFO] -> Stelle Task GC-Bridge-Microtech-Worker sicher und starte ihn
call "%APP_DIR%\deploy\windows\ensure-microtech-worker-task.cmd"
if errorlevel 1 (
    echo [ERROR] Task GC-Bridge-Microtech-Worker konnte nicht sichergestellt/gestartet werden.
    set "ERR=1"
)

timeout /t 2 /nobreak >nul

echo [INFO] -> Starte Task GC-Bridge-Uvicorn
schtasks /Run /TN "GC-Bridge-Uvicorn" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Task GC-Bridge-Uvicorn konnte nicht gestartet werden.
    set "ERR=1"
)

timeout /t 5 /nobreak >nul

echo [INFO] -> Starte Task GC-Bridge-Caddy
schtasks /Run /TN "GC-Bridge-Caddy" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Task GC-Bridge-Caddy konnte nicht gestartet werden.
    set "ERR=1"
)

timeout /t 2 /nobreak >nul

set "UVICORN_PORT_OK=0"
set "CADDY_PORT_OK=0"

netstat -ano | findstr /R /C:":8000 .*LISTENING" >nul 2>&1
if not errorlevel 1 set "UVICORN_PORT_OK=1"

netstat -ano | findstr /R /C:":4711 .*LISTENING" >nul 2>&1
if not errorlevel 1 set "CADDY_PORT_OK=1"

if "%UVICORN_PORT_OK%"=="1" (
    echo [OK]    Port 8000 (Uvicorn) aktiv.
) else (
    echo [WARN]  Port 8000 ist nicht aktiv.
    set "ERR=1"
)

if "%CADDY_PORT_OK%"=="1" (
    echo [OK]    Port 4711 (Caddy) aktiv.
) else (
    echo [WARN]  Port 4711 ist nicht aktiv.
    set "ERR=1"
)

echo.
echo [INFO] Wenn etwas nicht erreichbar ist: deploy\windows\diagnose_reachability.cmd starten.

if "%NO_PAUSE%"=="0" pause

if "%ERR%"=="1" (
    endlocal & exit /b 1
)

endlocal & exit /b 0
