@echo off
setlocal EnableExtensions

:: ============================================================
::  GC-Bridge Server Setup (Scheduled Tasks)
::  Richtet Uvicorn + Caddy als geplante Aufgaben ein.
::  Muss als Administrator ausgefuehrt werden.
::
::  Warum Scheduled Tasks statt sc.exe Dienste?
::  sc.exe erwartet das Windows Service Control Manager Protokoll.
::  Python/Uvicorn und Caddy implementieren das nicht - der SCM
::  wartet auf eine Antwort, bekommt keine, und killt den Prozess.
::  Scheduled Tasks starten den Prozess direkt ohne SCM.
:: ============================================================

net session >nul 2>&1
if not "%errorlevel%"=="0" (
    echo [ERROR] Dieses Skript muss als Administrator ausgefuehrt werden.
    exit /b 1
)

for %%I in ("%~dp0..\..") do set "PROJECT_ROOT=%%~fI"
set "GC_BRIDGE_PORT=4711"
set "GC_BRIDGE_LAN_IP=10.0.0.5"
set "PROJECT_ROOT_SLASH=%PROJECT_ROOT:\=/%"
set "LOGDIR=%PROJECT_ROOT%\tmp\logs"

echo [INFO] === GC-Bridge Setup gestartet %date% %time% ===
echo [INFO] PROJECT_ROOT = %PROJECT_ROOT%
echo [INFO] Port = %GC_BRIDGE_PORT%
echo [INFO] LAN-IP = %GC_BRIDGE_LAN_IP%
echo.

:: --- Voraussetzungen pruefen ---
echo [INFO] Pruefe Voraussetzungen...
set "MISSING=0"
for %%F in (
    "deploy\caddy\caddy.exe"
    "deploy\windows\start-uvicorn.cmd"
    "deploy\windows\start-caddy.cmd"
    ".venv\Scripts\python.exe"
) do (
    if not exist "%PROJECT_ROOT%\%%~F" (
        echo [FEHLT] %PROJECT_ROOT%\%%~F
        set "MISSING=1"
    ) else (
        echo [OK]    %%~F
    )
)
if "%MISSING%"=="1" (
    echo.
    echo [ERROR] Fehlende Dateien. Setup abgebrochen.
    exit /b 2
)
echo.

:: --- Logverzeichnis ---
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

:: --- Caddyfile generieren ---
echo [INFO] Generiere Caddyfile...
(
    echo {
    echo     auto_https off
    echo     admin off
    echo     log {
    echo         output file %PROJECT_ROOT_SLASH%/tmp/logs/caddy-runtime.log {
    echo             roll_size 10mb
    echo             roll_keep 3
    echo         }
    echo         format console
    echo         level INFO
    echo     }
    echo }
    echo.
    echo :%GC_BRIDGE_PORT% {
    echo     reverse_proxy 127.0.0.1:8000
    echo     log {
    echo         output file %PROJECT_ROOT_SLASH%/tmp/logs/caddy-access.log {
    echo             roll_size 10mb
    echo             roll_keep 3
    echo         }
    echo         format console
    echo     }
    echo }
) > "%PROJECT_ROOT%\deploy\caddy\Caddyfile"
echo [OK]    Caddyfile geschrieben.
echo.

:: --- Caddyfile validieren ---
echo [INFO] Validiere Caddyfile...
"%PROJECT_ROOT%\deploy\caddy\caddy.exe" validate --config "%PROJECT_ROOT%\deploy\caddy\Caddyfile" --adapter caddyfile 2>&1
if errorlevel 1 (
    echo [ERROR] Caddyfile ist ungueltig. Setup abgebrochen.
    exit /b 3
)
echo [OK]    Caddyfile valide.
echo.

:: --- Reset ausfuehren ---
echo [INFO] Fuehre Reset durch...
call "%~dp0reset_server.bat"
if not "%errorlevel%"=="0" (
    echo [ERROR] Reset fehlgeschlagen.
    exit /b 4
)
echo.

:: --- Scheduled Tasks anlegen ---
echo [INFO] Lege geplante Aufgaben an...

:: Uvicorn Task - startet bei Systemstart
schtasks /Create /TN "GC-Bridge-Uvicorn" ^
    /SC ONSTART ^
    /RU SYSTEM ^
    /RL HIGHEST ^
    /TR "\"%PROJECT_ROOT%\deploy\windows\start-uvicorn.cmd\"" ^
    /F
if errorlevel 1 (
    echo [ERROR] Uvicorn-Aufgabe konnte nicht angelegt werden.
    exit /b 5
)
echo [OK]    Aufgabe GC-Bridge-Uvicorn angelegt.

:: Caddy Task - startet bei Systemstart mit 10s Verzoegerung (Uvicorn soll erst laufen)
schtasks /Create /TN "GC-Bridge-Caddy" ^
    /SC ONSTART ^
    /DELAY 0000:10 ^
    /RU SYSTEM ^
    /RL HIGHEST ^
    /TR "\"%PROJECT_ROOT%\deploy\windows\start-caddy.cmd\"" ^
    /F
if errorlevel 1 (
    echo [ERROR] Caddy-Aufgabe konnte nicht angelegt werden.
    exit /b 5
)
echo [OK]    Aufgabe GC-Bridge-Caddy angelegt.
echo.

:: --- Firewall ---
echo [INFO] Setze Firewall-Regel...
netsh advfirewall firewall add rule ^
    name="GC-Bridge Caddy %GC_BRIDGE_PORT%" ^
    dir=in action=allow protocol=TCP ^
    localport=%GC_BRIDGE_PORT% >nul
echo [OK]    Firewall-Regel fuer Port %GC_BRIDGE_PORT% gesetzt.
echo.

:: --- Jetzt starten ---
echo [INFO] Starte Uvicorn...
schtasks /Run /TN "GC-Bridge-Uvicorn"
if errorlevel 1 (
    echo [WARN]  Uvicorn-Aufgabe konnte nicht gestartet werden.
) else (
    echo [OK]    Uvicorn gestartet.
)

echo [INFO] Warte 5 Sekunden bis Uvicorn bereit ist...
timeout /t 5 /nobreak >nul

echo [INFO] Starte Caddy...
schtasks /Run /TN "GC-Bridge-Caddy"
if errorlevel 1 (
    echo [WARN]  Caddy-Aufgabe konnte nicht gestartet werden.
) else (
    echo [OK]    Caddy gestartet.
)

:: --- Verifikation ---
echo.
echo [INFO] Warte 5 Sekunden fuer Verifikation...
timeout /t 5 /nobreak >nul

echo.
echo [INFO] === Verifikation ===
echo.
echo Port 8000 (Uvicorn):
netstat -ano | findstr /R /C:":8000 .*LISTENING"
if errorlevel 1 echo [FEHLER] Kein Listener auf Port 8000!

echo.
echo Port %GC_BRIDGE_PORT% (Caddy):
netstat -ano | findstr /R /C:":%GC_BRIDGE_PORT% .*LISTENING"
if errorlevel 1 echo [FEHLER] Kein Listener auf Port %GC_BRIDGE_PORT%!

echo.
echo [INFO] HTTP-Test auf Uvicorn (127.0.0.1:8000)...
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri http://127.0.0.1:8000/admin/ -UseBasicParsing -TimeoutSec 5; Write-Host '[OK]    HTTP' $r.StatusCode } catch { Write-Host '[FEHLER]' $_.Exception.Message }"

echo.
echo [INFO] HTTP-Test auf Caddy (127.0.0.1:%GC_BRIDGE_PORT%)...
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri http://127.0.0.1:%GC_BRIDGE_PORT%/admin/ -UseBasicParsing -TimeoutSec 5; Write-Host '[OK]    HTTP' $r.StatusCode } catch { Write-Host '[FEHLER]' $_.Exception.Message }"

echo.
echo === Logdateien ===
echo Uvicorn stdout: %LOGDIR%\uvicorn.out.log
echo Uvicorn stderr: %LOGDIR%\uvicorn.err.log
echo Caddy runtime:  %LOGDIR%\caddy-runtime.log
echo Caddy access:   %LOGDIR%\caddy-access.log
echo Caddy stderr:   %LOGDIR%\caddy.err.log

echo.
echo [DONE] Setup abgeschlossen.
echo [INFO] URL: http://%GC_BRIDGE_LAN_IP%:%GC_BRIDGE_PORT%/admin/
echo.
echo [TIPP] Ausgabe speichern:  setup_server.bat > setup.txt 2>&1
echo [TIPP] Diagnose ausfuehren: check_server.bat > diagnose.txt 2>&1

endlocal
exit /b 0
