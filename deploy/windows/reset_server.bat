@echo off
setlocal EnableExtensions

:: ============================================================
::  GC-Bridge Server Reset
::  Entfernt alle Dienste, Tasks, Firewall-Regeln und Prozesse.
::  Muss als Administrator ausgefuehrt werden.
:: ============================================================

net session >nul 2>&1
if not "%errorlevel%"=="0" (
    echo [ERROR] Dieses Skript muss als Administrator ausgefuehrt werden.
    exit /b 1
)

for %%I in ("%~dp0..\..") do set "PROJECT_ROOT=%%~fI"

echo [INFO] === GC-Bridge Reset gestartet %date% %time% ===

echo.
echo [INFO] Stoppe und entferne Windows-Dienste...
for %%S in ("GC-Bridge-Uvicorn" "Caddy") do (
    sc.exe query %%~S >nul 2>&1
    if not errorlevel 1 (
        echo        Stoppe %%~S...
        sc.exe stop %%~S >nul 2>&1
        timeout /t 3 /nobreak >nul
        echo        Entferne %%~S...
        sc.exe delete %%~S >nul 2>&1
        if errorlevel 1 (
            echo [WARN]  %%~S konnte nicht entfernt werden (evtl. noch in Benutzung).
        ) else (
            echo [OK]    %%~S entfernt.
        )
    ) else (
        echo [SKIP]  %%~S war nicht registriert.
    )
)

echo.
echo [INFO] Entferne geplante Aufgaben...
for %%T in ("GC-Bridge-Uvicorn" "GC-Bridge-Caddy" "GC-Bridge-Start-Uvicorn" "GC-Bridge-Start-Caddy") do (
    schtasks /Query /TN %%~T >nul 2>&1
    if not errorlevel 1 (
        schtasks /Delete /TN %%~T /F >nul 2>&1
        echo [OK]    Aufgabe %%~T entfernt.
    ) else (
        echo [SKIP]  Aufgabe %%~T war nicht vorhanden.
    )
)

echo.
echo [INFO] Entferne Firewall-Regeln...
for %%P in (4711 8081 8080) do (
    netsh advfirewall firewall delete rule name="GC-Bridge Caddy %%P" >nul 2>&1
)
echo [OK]    Firewall-Regeln entfernt.

echo.
echo [INFO] Beende Prozesse auf Ports 8000, 4711, 8080, 8081...
set "KILLED=0"
for %%P in (8000 4711 8080 8081) do (
    for /f "tokens=5" %%I in ('netstat -ano ^| findstr /R /C:":%%P .*LISTENING"') do (
        echo        Beende PID %%I (Port %%P)
        taskkill /PID %%I /F >nul 2>&1
        set "KILLED=1"
    )
)
if "%KILLED%"=="0" echo [SKIP]  Keine aktiven Listener gefunden.

echo.
echo [INFO] === Reset abgeschlossen %date% %time% ===
echo.
echo Naechster Schritt: setup_server.bat ausfuehren.

endlocal
exit /b 0
