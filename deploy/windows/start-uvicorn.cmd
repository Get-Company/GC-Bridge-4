@echo off
setlocal

set DJANGO_SETTINGS_MODULE=GC_Bridge_4.settings
if "%DJANGO_DEBUG%"=="" set DJANGO_DEBUG=0
if "%DJANGO_ALLOWED_HOSTS%"=="" set DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
if "%DJANGO_CSRF_TRUSTED_ORIGINS%"=="" set DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost:8080,http://127.0.0.1:8080

cd /d %~dp0\..\..
call .venv\Scripts\uvicorn.exe GC_Bridge_4.asgi:application --host 127.0.0.1 --port 8000 --workers 2

endlocal
