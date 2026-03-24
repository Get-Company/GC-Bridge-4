@echo off
setlocal

:: ============================================================
::  GC-Bridge Caddy Starter
::  Wird von Scheduled Task "GC-Bridge-Caddy" aufgerufen.
::  Loggt stdout/stderr in separate Dateien.
:: ============================================================

cd /d %~dp0\..\.. || exit /b 1
if not exist tmp\logs mkdir tmp\logs
call deploy\windows\prune-logs.cmd 14 >nul 2>&1
for /f %%I in ('powershell -NoProfile -Command "(Get-Date).ToString('yyyy-MM-dd')"') do set "DATESTAMP=%%I"
set "CADDY_ERR_DIR=tmp\logs\weekly\caddy"
if not exist "%CADDY_ERR_DIR%" mkdir "%CADDY_ERR_DIR%"
set "CADDY_ERR_LOG=%CADDY_ERR_DIR%\caddy.err.%DATESTAMP%.log"

if not exist deploy\caddy\caddy.exe (
    echo [%date% %time%] caddy.exe nicht gefunden >> "%CADDY_ERR_LOG%"
    exit /b 2
)
if not exist deploy\caddy\Caddyfile (
    echo [%date% %time%] Caddyfile nicht gefunden >> "%CADDY_ERR_LOG%"
    exit /b 2
)

echo [%date% %time%] Caddy startet... >> "%CADDY_ERR_LOG%"
deploy\caddy\caddy.exe run --config deploy\caddy\Caddyfile --adapter caddyfile 2>> "%CADDY_ERR_LOG%"

set "RC=%ERRORLEVEL%"
echo [%date% %time%] Caddy beendet mit Code %RC% >> "%CADDY_ERR_LOG%"

endlocal & exit /b %RC%
