@echo off
setlocal EnableExtensions

:: ============================================================
::  GC-Bridge Server-Diagnose
::  Gibt alle relevanten Infos aus. Ausgabe kopieren und teilen.
:: ============================================================

for %%I in ("%~dp0..\..") do set "PROJECT_ROOT=%%~fI"
set "LOGDIR=%PROJECT_ROOT%\tmp\logs"

echo ================================================================
echo  GC-Bridge Server-Diagnose  %date% %time%
echo ================================================================
echo.

echo --- Projektverzeichnis ---
echo PROJECT_ROOT = %PROJECT_ROOT%
echo.

echo --- Dateien pruefen ---
for %%F in (
    "deploy\caddy\caddy.exe"
    "deploy\caddy\Caddyfile"
    "deploy\windows\start-uvicorn.cmd"
    ".venv\Scripts\python.exe"
) do (
    if exist "%PROJECT_ROOT%\%%~F" (
        echo [OK]    %%~F
    ) else (
        echo [FEHLT] %%~F
    )
)
echo.

echo --- Python / Uvicorn Version ---
if exist "%PROJECT_ROOT%\.venv\Scripts\python.exe" (
    "%PROJECT_ROOT%\.venv\Scripts\python.exe" --version 2>&1
    "%PROJECT_ROOT%\.venv\Scripts\python.exe" -m uvicorn --version 2>&1
) else (
    echo [FEHLT] .venv\Scripts\python.exe nicht gefunden
)
echo.

echo --- Caddy Version ---
if exist "%PROJECT_ROOT%\deploy\caddy\caddy.exe" (
    "%PROJECT_ROOT%\deploy\caddy\caddy.exe" version 2>&1
) else (
    echo [FEHLT] caddy.exe nicht gefunden
)
echo.

echo --- Registrierte Dienste (sc.exe) ---
for %%S in ("GC-Bridge-Uvicorn" "Caddy") do (
    echo.
    echo Dienst: %%~S
    sc.exe query %%~S 2>&1
)
echo.

echo --- Geplante Aufgaben ---
for %%T in ("GC-Bridge-Uvicorn" "GC-Bridge-Caddy" "GC-Bridge-Start-Uvicorn" "GC-Bridge-Start-Caddy") do (
    echo.
    echo Aufgabe: %%~T
    schtasks /Query /TN %%~T /V /FO LIST 2>&1
)
echo.

echo --- Ports pruefen (8000, 4711, 8080, 8081) ---
for %%P in (8000 4711 8080 8081) do (
    echo.
    echo Port %%P:
    netstat -ano | findstr /R /C:":%%P .*LISTENING"
    if errorlevel 1 echo   (kein Listener)
)
echo.

echo --- Firewall-Regeln (GC-Bridge) ---
netsh advfirewall firewall show rule name=all dir=in | findstr /I "GC-Bridge"
if errorlevel 1 echo   (keine GC-Bridge Regeln gefunden)
echo.

echo --- Logdateien ---
if not exist "%LOGDIR%" (
    echo [INFO] Logverzeichnis existiert nicht: %LOGDIR%
) else (
    echo Logverzeichnis: %LOGDIR%
    echo.
    for %%L in (
        uvicorn.out.log
        uvicorn.err.log
        caddy-runtime.log
        caddy-access.log
    ) do (
        if exist "%LOGDIR%\%%L" (
            echo === Letzte 20 Zeilen: %%L ===
            powershell -NoProfile -Command "Get-Content '%LOGDIR%\%%L' -Tail 20" 2>&1
            echo.
        ) else (
            echo [LEER]  %%L existiert nicht
        )
    )
)
echo.

echo --- Schnelltest: Uvicorn starten (5 Sekunden) ---
echo Starte Uvicorn zum Testen...
pushd "%PROJECT_ROOT%"
set "DJANGO_SETTINGS_MODULE=GC_Bridge_4.settings"
set "DJANGO_DEBUG=0"
start "" /B "%PROJECT_ROOT%\.venv\Scripts\python.exe" -m uvicorn GC_Bridge_4.asgi:application --host 127.0.0.1 --port 8000 --workers 1 > "%LOGDIR%\check-uvicorn.log" 2>&1
set "UVICORN_PID="
timeout /t 3 /nobreak >nul
for /f "tokens=5" %%I in ('netstat -ano ^| findstr /R /C:":8000 .*LISTENING"') do set "UVICORN_PID=%%I"
if defined UVICORN_PID (
    echo [OK]    Uvicorn laeuft auf Port 8000 (PID %UVICORN_PID%)
    echo         Teste HTTP-Antwort...
    powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri http://127.0.0.1:8000/admin/ -UseBasicParsing -TimeoutSec 5; Write-Host '[OK]    HTTP Status:' $r.StatusCode } catch { Write-Host '[FEHLER]' $_.Exception.Message }"
    taskkill /PID %UVICORN_PID% /F >nul 2>&1
) else (
    echo [FEHLER] Uvicorn konnte nicht gestartet werden.
    echo          Pruefe %LOGDIR%\check-uvicorn.log
    if exist "%LOGDIR%\check-uvicorn.log" (
        echo.
        echo === check-uvicorn.log ===
        type "%LOGDIR%\check-uvicorn.log"
    )
)
popd
echo.

echo ================================================================
echo  Diagnose abgeschlossen.
echo  Tipp: Ausgabe kopieren mit:
echo    check_server.bat > diagnose.txt 2>&1
echo ================================================================

endlocal
