@echo off
setlocal

:: ============================================================
::  GC-Bridge Caddy Starter
::  Wird von Scheduled Task "GC-Bridge-Caddy" aufgerufen.
::  Loggt stdout/stderr in separate Dateien.
:: ============================================================

cd /d %~dp0\..\.. || exit /b 1
if not exist tmp\logs mkdir tmp\logs

if not exist deploy\caddy\caddy.exe (
    echo [%date% %time%] caddy.exe nicht gefunden >> tmp\logs\caddy.err.log
    exit /b 2
)
if not exist deploy\caddy\Caddyfile (
    echo [%date% %time%] Caddyfile nicht gefunden >> tmp\logs\caddy.err.log
    exit /b 2
)

echo [%date% %time%] Caddy startet... >> tmp\logs\caddy.err.log
deploy\caddy\caddy.exe run --config deploy\caddy\Caddyfile --adapter caddyfile 2>> tmp\logs\caddy.err.log

set "RC=%ERRORLEVEL%"
echo [%date% %time%] Caddy beendet mit Code %RC% >> tmp\logs\caddy.err.log

endlocal & exit /b %RC%
