@echo off
setlocal EnableExtensions

:: ============================================================
::  Ensure + Start GC-Bridge-Log-Prune
::  - erstellt/aktualisiert den taeglichen Task idempotent
::  - startet ihn direkt einmal
:: ============================================================

for %%I in ("%~dp0..\..") do set "APP_DIR=%%~fI"
cd /d "%APP_DIR%" || exit /b 1

set "TASK_NAME=GC-Bridge-Log-Prune"
set "TASK_COMMAND=cmd.exe /c \"cd /d \"%APP_DIR%\" && deploy\\windows\\prune-logs.cmd 14\""

echo [INFO] Stelle Task "%TASK_NAME%" sicher...
schtasks /Create /TN "%TASK_NAME%" /SC DAILY /ST 02:15 /RU SYSTEM /RL HIGHEST /TR "%TASK_COMMAND%" /F >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Task "%TASK_NAME%" konnte nicht erstellt/aktualisiert werden.
    echo [HINT] Bitte in einer Administrator-CMD ausfuehren.
    exit /b 1
)

echo [INFO] Starte "%TASK_NAME%" einmal sofort...
schtasks /Run /TN "%TASK_NAME%" >nul 2>&1
if errorlevel 1 (
    echo [WARN]  Task "%TASK_NAME%" konnte nicht sofort gestartet werden.
    echo [OK]    Der taegliche Task ist trotzdem registriert.
    endlocal & exit /b 0
)

echo [OK]    Task "%TASK_NAME%" registriert und gestartet.
endlocal & exit /b 0
