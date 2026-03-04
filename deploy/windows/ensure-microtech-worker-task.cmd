@echo off
setlocal EnableExtensions EnableDelayedExpansion

:: ============================================================
::  Ensure + Start GC-Bridge-Microtech-Worker
::  - erstellt/aktualisiert den Task idempotent
::  - startet den Task mit Retry
::  - verifiziert, dass ein microtech_worker-Prozess laeuft
:: ============================================================

for %%I in ("%~dp0..\..") do set "APP_DIR=%%~fI"
cd /d "%APP_DIR%" || exit /b 1

set "TASK_NAME=GC-Bridge-Microtech-Worker"
set "PYTHON_EXE=%APP_DIR%\.venv\Scripts\python.exe"
set "MANAGE_PY=%APP_DIR%\manage.py"
set "TASK_COMMAND=%PYTHON_EXE% %MANAGE_PY% microtech_worker"

if not exist "%PYTHON_EXE%" (
    echo [ERROR] %PYTHON_EXE% nicht gefunden.
    exit /b 1
)

if not exist "%MANAGE_PY%" (
    echo [ERROR] %MANAGE_PY% nicht gefunden.
    exit /b 1
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
    ping 127.0.0.1 -n 3 >nul

    call :task_running "%TASK_NAME%"
    if not errorlevel 1 (
        set "START_OK=1"
        goto :done
    )
)

:done
if "%START_OK%"=="1" (
    echo [OK]    Task "%TASK_NAME%" laeuft.
    endlocal & exit /b 0
)

echo [ERROR] Task "%TASK_NAME%" wurde angestossen, aber microtech_worker laeuft nicht.
schtasks /Query /TN "%TASK_NAME%" /V /FO LIST
endlocal & exit /b 1

:task_running
schtasks /Query /TN "%~1" /V /FO LIST | findstr /I /C:"Running" /C:"Wird ausgef" >nul 2>&1
if not errorlevel 1 exit /b 0
exit /b 1
