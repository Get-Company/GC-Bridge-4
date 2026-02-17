@echo off
setlocal

:: ============================================================
::  GC-Bridge Uvicorn Starter
::  Wird von Scheduled Task "GC-Bridge-Uvicorn" aufgerufen.
::  Loggt stdout/stderr in separate Dateien.
:: ============================================================

cd /d %~dp0\..\.. || exit /b 1
if not exist tmp\logs mkdir tmp\logs

if "%GC_BRIDGE_PUBLIC_PORT%"=="" set GC_BRIDGE_PUBLIC_PORT=4711
if "%GC_BRIDGE_LAN_IP%"=="" set GC_BRIDGE_LAN_IP=10.0.0.5

set DJANGO_SETTINGS_MODULE=GC_Bridge_4.settings
if "%DJANGO_DEBUG%"=="" set DJANGO_DEBUG=0
if "%DJANGO_ALLOWED_HOSTS%"=="" set DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,%GC_BRIDGE_LAN_IP%
if "%DJANGO_CSRF_TRUSTED_ORIGINS%"=="" set DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost:%GC_BRIDGE_PUBLIC_PORT%,http://127.0.0.1:%GC_BRIDGE_PUBLIC_PORT%,http://%GC_BRIDGE_LAN_IP%:%GC_BRIDGE_PUBLIC_PORT%
if "%DJANGO_USE_X_FORWARDED_HOST%"=="" set DJANGO_USE_X_FORWARDED_HOST=1
if "%DJANGO_USE_X_FORWARDED_PROTO%"=="" set DJANGO_USE_X_FORWARDED_PROTO=0

if not exist .venv\Scripts\python.exe (
    echo [%date% %time%] python.exe nicht gefunden >> tmp\logs\uvicorn.err.log
    exit /b 2
)

echo [%date% %time%] Uvicorn startet... >> tmp\logs\uvicorn.err.log
.venv\Scripts\python.exe -m uvicorn GC_Bridge_4.asgi:application --host 127.0.0.1 --port 8000 --workers 1 >> tmp\logs\uvicorn.out.log 2>> tmp\logs\uvicorn.err.log

set "RC=%ERRORLEVEL%"
echo [%date% %time%] Uvicorn beendet mit Code %RC% >> tmp\logs\uvicorn.err.log

endlocal & exit /b %RC%
