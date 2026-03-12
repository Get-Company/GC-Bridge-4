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

echo --- GitHub Runner Dienste (sc.exe) ---
for %%S in ("actions.runner.Get-Company-GC-Bridge-4.GC-Bridge-v4") do (
    echo.
    echo Dienst: %%~S
    sc.exe query %%~S 2>&1
)
echo.

echo --- Geplante Aufgaben ---
for %%T in ("GC-Bridge-Microtech-Worker" "GC-Bridge-Uvicorn" "GC-Bridge-Caddy") do (
    echo.
    echo Aufgabe: %%~T
    schtasks /Query /TN %%~T /V /FO LIST 2>&1
)
echo.
echo Aufgabe: GC-Bridge Scheduled Product Sync
schtasks /Query /TN "GC-Bridge Scheduled Product Sync" /V /FO LIST 2>&1
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

echo --- Django Admin-Test (eingeloggt) ---
pushd "%PROJECT_ROOT%"
"%PROJECT_ROOT%\.venv\Scripts\python.exe" "%PROJECT_ROOT%\deploy\windows\admin_test.py" 2>&1
if errorlevel 1 (
    echo [FEHLER] Admin-Seite liefert Fehler! Siehe Ausgabe oben.
) else (
    echo [OK]    Admin-Seite (eingeloggt) - HTTP 200
)
popd
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
        deploy.log
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

echo --- Schnelltest: HTTP-Erreichbarkeit ---
echo Teste HTTP-Antwort (kein Uvicorn-Neustart)...
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/' -UseBasicParsing -TimeoutSec 5 -MaximumRedirection 0; Write-Host '[OK]    HTTP' $r.StatusCode } catch { if ($_.Exception.Response) { $sc = [int]$_.Exception.Response.StatusCode; Write-Host '[INFO]  HTTP' $sc } else { Write-Host '[FEHLER]' $_.Exception.Message } }"
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:4711/' -UseBasicParsing -TimeoutSec 5 -MaximumRedirection 0; Write-Host '[OK]    HTTP' $r.StatusCode '(Caddy)' } catch { if ($_.Exception.Response) { $sc = [int]$_.Exception.Response.StatusCode; Write-Host '[INFO]  HTTP' $sc '(Caddy)' } else { Write-Host '[FEHLER]' $_.Exception.Message } }"
echo.

echo ================================================================
echo  Diagnose abgeschlossen.
echo  Tipp: Ausgabe kopieren mit:
echo    check_server.bat > diagnose.txt 2>&1
echo ================================================================

endlocal
