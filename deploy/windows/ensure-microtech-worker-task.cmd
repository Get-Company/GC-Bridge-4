@echo off
setlocal EnableExtensions EnableDelayedExpansion

:: ============================================================
::  Ensure + Start GC-Bridge-Microtech-Worker
::  - erstellt/aktualisiert den Task idempotent
::  - startet den Task mit Retry
::  - verifiziert anhand der Runtime-JSON, dass der Worker laeuft
:: ============================================================

for %%I in ("%~dp0..\..") do set "APP_DIR=%%~fI"
cd /d "%APP_DIR%" || exit /b 1

set "TASK_NAME=GC-Bridge-Microtech-Worker"
set "PYTHON_EXE=%APP_DIR%\.venv\Scripts\python.exe"
set "MANAGE_PY=%APP_DIR%\manage.py"
set "TASK_COMMAND=%PYTHON_EXE% %MANAGE_PY% microtech_worker"
set "RUNTIME_DIR=%APP_DIR%\tmp\runtime"

if not exist "%PYTHON_EXE%" (
    echo [ERROR] %PYTHON_EXE% nicht gefunden.
    exit /b 1
)

if not exist "%MANAGE_PY%" (
    echo [ERROR] %MANAGE_PY% nicht gefunden.
    exit /b 1
)

:: Wenn bereits eine Runtime-JSON existiert, laeuft der Worker schon – nichts tun.
if exist "%RUNTIME_DIR%\microtech_worker__*.json" (
    echo [OK]    microtech_worker laeuft bereits (Runtime-JSON gefunden).
    endlocal & exit /b 0
)

echo [INFO] Stelle Task "%TASK_NAME%" sicher...
schtasks /Create /TN "%TASK_NAME%" /SC ONSTART /RU SYSTEM /RL HIGHEST /TR "%TASK_COMMAND%" /F >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Task "%TASK_NAME%" konnte nicht erstellt/aktualisiert werden.
    echo [HINT] Bitte in einer Administrator-CMD ausfuehren.
    exit /b 1
)

set "START_OK=0"
for /L %%R in (1,1,3) do (
    echo [INFO] Starte "%TASK_NAME%" - Versuch %%R/3...
    schtasks /Run /TN "%TASK_NAME%" >nul 2>&1

    :: Django-Startup + COM-Connect braucht 10-15 Sekunden – laenger warten.
    echo [INFO] Warte 15 Sekunden auf Worker-Startup...
    ping 127.0.0.1 -n 16 >nul

    call :worker_runtime_running
    if not errorlevel 1 (
        set "START_OK=1"
        goto :done
    )
    echo [WARN] Runtime-JSON noch nicht vorhanden, Versuch %%R/3 gescheitert.
)

:done
if "%START_OK%"=="1" (
    echo [OK]    microtech_worker laeuft (Runtime-JSON gefunden).
    endlocal & exit /b 0
)

echo [ERROR] microtech_worker laeuft nicht nach 3 Versuchen.
echo [HINT]  Log pruefen: %APP_DIR%\tmp\logs\microtech_worker.log
schtasks /Query /TN "%TASK_NAME%" /V /FO LIST
endlocal & exit /b 1

:: Pruefen ob eine microtech_worker Runtime-JSON existiert
:worker_runtime_running
if not exist "%RUNTIME_DIR%\microtech_worker__*.json" exit /b 1
exit /b 0
