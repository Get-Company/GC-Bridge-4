@echo off
setlocal EnableExtensions

net session >nul 2>&1
if not "%errorlevel%"=="0" (
    echo [ERROR] Dieses Skript muss als Administrator ausgefuehrt werden.
    exit /b 1
)

for %%I in ("%~dp0..\..") do set "PROJECT_ROOT=%%~fI"
set "GC_BRIDGE_PORT=4711"
set "GC_BRIDGE_LAN_IP=10.0.0.5"
set "PROJECT_ROOT_SLASH=%PROJECT_ROOT:\=/%"

if not exist "%PROJECT_ROOT%\deploy\caddy\caddy.exe" (
    echo [ERROR] Datei fehlt: %PROJECT_ROOT%\deploy\caddy\caddy.exe
    exit /b 2
)
if not exist "%PROJECT_ROOT%\deploy\windows\start-uvicorn.cmd" (
    echo [ERROR] Datei fehlt: %PROJECT_ROOT%\deploy\windows\start-uvicorn.cmd
    exit /b 2
)

if not exist "%PROJECT_ROOT%\tmp\logs" mkdir "%PROJECT_ROOT%\tmp\logs"

echo [INFO] Setze Caddyfile auf Port %GC_BRIDGE_PORT%...
(
    echo {
    echo     auto_https off
    echo     admin off
    echo     log {
    echo         output file %PROJECT_ROOT_SLASH%/tmp/logs/caddy-runtime.log
    echo         format console
    echo         level INFO
    echo     }
    echo }
    echo.
    echo :%GC_BRIDGE_PORT% {
    echo     reverse_proxy 127.0.0.1:8000
    echo     log {
    echo         output file %PROJECT_ROOT_SLASH%/tmp/logs/caddy-access.log
    echo         format console
    echo     }
    echo }
) > "%PROJECT_ROOT%\deploy\caddy\Caddyfile"

echo [INFO] Setze Reset durch...
call "%~dp0reset_server.bat"
if not "%errorlevel%"=="0" exit /b 3

echo [INFO] Lege Dienste an...
set "CADDY_BIN=%PROJECT_ROOT%\deploy\caddy\caddy.exe run --config %PROJECT_ROOT%\deploy\caddy\Caddyfile --adapter caddyfile"
sc.exe create Caddy binPath= "%CADDY_BIN%" start= auto
if not "%errorlevel%"=="0" exit /b 4
sc.exe description Caddy "GC-Bridge Caddy Reverse Proxy"
sc.exe failure Caddy reset= 86400 actions= restart/5000/restart/5000/restart/5000

set "UVICORN_BIN=%ComSpec% /c %PROJECT_ROOT%\deploy\windows\start-uvicorn.cmd"
sc.exe create GC-Bridge-Uvicorn binPath= "%UVICORN_BIN%" start= auto
if not "%errorlevel%"=="0" exit /b 4
sc.exe description GC-Bridge-Uvicorn "GC-Bridge Django Uvicorn"
sc.exe failure GC-Bridge-Uvicorn reset= 86400 actions= restart/5000/restart/5000/restart/5000

echo [INFO] Lege Scheduler-Aufgaben fuer Service-Start an...
schtasks /Create /TN "GC-Bridge-Start-Uvicorn" /SC ONSTART /DELAY 0000:20 /RU SYSTEM /RL HIGHEST /TR "sc.exe start GC-Bridge-Uvicorn" /F
if not "%errorlevel%"=="0" exit /b 5
schtasks /Create /TN "GC-Bridge-Start-Caddy" /SC ONSTART /DELAY 0000:30 /RU SYSTEM /RL HIGHEST /TR "sc.exe start Caddy" /F
if not "%errorlevel%"=="0" exit /b 5

echo [INFO] Setze Firewall-Regel fuer Port %GC_BRIDGE_PORT%...
netsh advfirewall firewall add rule name="GC-Bridge Caddy %GC_BRIDGE_PORT%" dir=in action=allow protocol=TCP localport=%GC_BRIDGE_PORT% >nul

echo [INFO] Starte Dienste...
sc.exe start GC-Bridge-Uvicorn >nul
sc.exe start Caddy >nul

echo [INFO] Status:
sc.exe query GC-Bridge-Uvicorn
sc.exe query Caddy

echo [DONE] Setup abgeschlossen.
echo [INFO] URL: http://%GC_BRIDGE_LAN_IP%:%GC_BRIDGE_PORT%/admin/
exit /b 0
