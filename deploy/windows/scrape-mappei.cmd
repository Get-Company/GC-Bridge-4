@echo off
setlocal

:: ============================================================
::  GC-Bridge Mappei Price Scraper
::  Wird von Scheduled Task "GC-Bridge-Mappei-Scrape" aufgerufen.
::  Laeuft taeglich um 20:00 Uhr und loggt nach tmp\logs\weekly\mappei.
:: ============================================================

cd /d %~dp0\..\.. || exit /b 1
if not exist tmp\logs mkdir tmp\logs
for /f %%I in ('powershell -NoProfile -Command "(Get-Date).ToString('yyyy-MM-dd')"') do set "DATESTAMP=%%I"
set "MAPPEI_LOG_DIR=tmp\logs\weekly\mappei"
if not exist "%MAPPEI_LOG_DIR%" mkdir "%MAPPEI_LOG_DIR%"
set "MAPPEI_LOG=%MAPPEI_LOG_DIR%\scrape-mappei.%DATESTAMP%.log"

set DJANGO_SETTINGS_MODULE=GC_Bridge_4.settings
if "%DJANGO_DEBUG%"=="" set DJANGO_DEBUG=0

if not exist .venv\Scripts\python.exe (
    echo [%date% %time%] python.exe nicht gefunden >> "%MAPPEI_LOG%"
    exit /b 2
)

echo [%date% %time%] Mappei Scraper startet... >> "%MAPPEI_LOG%"
.venv\Scripts\python.exe manage.py scrape_mappei >> "%MAPPEI_LOG%" 2>&1

set "RC=%ERRORLEVEL%"
echo [%date% %time%] Mappei Scraper beendet mit Code %RC% >> "%MAPPEI_LOG%"

endlocal & exit /b %RC%
