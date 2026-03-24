@echo off
setlocal EnableExtensions EnableDelayedExpansion

:: ============================================================
::  GC-Bridge Reachability Diagnose
::  Prueft schrittweise, warum GC-Bridge nicht erreichbar ist.
::  Exitcode: 0 = lokal erreichbar, 1 = Fehler erkannt
:: ============================================================

for %%I in ("%~dp0..\..") do set "APP_DIR=%%~fI"
if not exist "%APP_DIR%\tmp\logs" mkdir "%APP_DIR%\tmp\logs"
call "%APP_DIR%\deploy\windows\prune-logs.cmd" 14 >nul 2>&1
for /f %%I in ('powershell -NoProfile -Command "(Get-Date).ToString('yyyy-MM-dd')"') do set "DATESTAMP=%%I"
set "DIAG_LOG_DIR=%APP_DIR%\tmp\logs\weekly\diagnose_reachability"
if not exist "%DIAG_LOG_DIR%" mkdir "%DIAG_LOG_DIR%"
set "LOG_FILE=%DIAG_LOG_DIR%\diagnose_reachability.%DATESTAMP%.log"

set "ERRORS=0"
set "WARNINGS=0"

set "PYTHON_OK=1"
set "CADDY_BIN_OK=1"
set "CADDY_CFG_OK=1"
set "LOG_PRUNE_TASK_OK=1"
set "UVICORN_TASK_OK=1"
set "CADDY_TASK_OK=1"
set "MICROTECH_WORKER_TASK_OK=1"
set "MICROTECH_WORKER_PROC_OK=0"
set "UVICORN_PORT_OK=0"
set "CADDY_PORT_OK=0"
set "UVICORN_HTTP_OK=0"
set "CADDY_HTTP_OK=0"
set "FIREWALL_OK=0"

call :header "GC-Bridge Diagnose %date% %time%"
call :log "Projektpfad: %APP_DIR%"

call :section "DATEIEN"
if exist "%APP_DIR%\.venv\Scripts\python.exe" (
    call :ok ".venv\\Scripts\\python.exe vorhanden"
) else (
    set "PYTHON_OK=0"
    call :err ".venv\\Scripts\\python.exe fehlt"
)

if exist "%APP_DIR%\deploy\caddy\caddy.exe" (
    call :ok "deploy\\caddy\\caddy.exe vorhanden"
) else (
    set "CADDY_BIN_OK=0"
    call :err "deploy\\caddy\\caddy.exe fehlt"
)

if exist "%APP_DIR%\deploy\caddy\Caddyfile" (
    call :ok "deploy\\caddy\\Caddyfile vorhanden"
) else (
    set "CADDY_CFG_OK=0"
    call :err "deploy\\caddy\\Caddyfile fehlt"
)

call :section "SCHEDULED TASKS"
schtasks /Query /TN "GC-Bridge-Log-Prune" >nul 2>&1
if errorlevel 1 (
    set "LOG_PRUNE_TASK_OK=0"
    call :warn "Task GC-Bridge-Log-Prune fehlt"
) else (
    call :ok "Task GC-Bridge-Log-Prune registriert"
)

schtasks /Query /TN "GC-Bridge-Microtech-Worker" >nul 2>&1
if errorlevel 1 (
    set "MICROTECH_WORKER_TASK_OK=0"
    call :err "Task GC-Bridge-Microtech-Worker fehlt"
) else (
    call :ok "Task GC-Bridge-Microtech-Worker registriert"
    call :task_running "GC-Bridge-Microtech-Worker"
    if errorlevel 1 (
        call :err "microtech_worker Prozess laeuft nicht"
    ) else (
        set "MICROTECH_WORKER_PROC_OK=1"
        call :ok "microtech_worker Prozess aktiv"
    )
)

schtasks /Query /TN "GC-Bridge-Uvicorn" >nul 2>&1
if errorlevel 1 (
    set "UVICORN_TASK_OK=0"
    call :err "Task GC-Bridge-Uvicorn fehlt"
) else (
    call :ok "Task GC-Bridge-Uvicorn registriert"
)

schtasks /Query /TN "GC-Bridge-Caddy" >nul 2>&1
if errorlevel 1 (
    set "CADDY_TASK_OK=0"
    call :err "Task GC-Bridge-Caddy fehlt"
) else (
    call :ok "Task GC-Bridge-Caddy registriert"
)

schtasks /Query /TN "GC-Bridge Scheduled Product Sync" >nul 2>&1
if errorlevel 1 (
    call :warn "Task GC-Bridge Scheduled Product Sync fehlt (optional)"
) else (
    call :ok "Task GC-Bridge Scheduled Product Sync registriert"
)

call :section "PORTS"
netstat -ano | findstr /R /C:":8000 .*LISTENING" >nul 2>&1
if errorlevel 1 (
    call :err "Port 8000 (Uvicorn) ist nicht aktiv"
) else (
    set "UVICORN_PORT_OK=1"
    call :ok "Port 8000 (Uvicorn) aktiv"
)

netstat -ano | findstr /R /C:":4711 .*LISTENING" >nul 2>&1
if errorlevel 1 (
    call :err "Port 4711 (Caddy) ist nicht aktiv"
) else (
    set "CADDY_PORT_OK=1"
    call :ok "Port 4711 (Caddy) aktiv"
)

call :section "HTTP CHECKS"
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/admin/' -UseBasicParsing -TimeoutSec 5; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if errorlevel 1 (
    call :err "http://127.0.0.1:8000/admin/ nicht erreichbar"
) else (
    set "UVICORN_HTTP_OK=1"
    call :ok "http://127.0.0.1:8000/admin/ erreichbar"
)

powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:4711/admin/' -UseBasicParsing -TimeoutSec 5; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if errorlevel 1 (
    call :err "http://127.0.0.1:4711/admin/ nicht erreichbar"
) else (
    set "CADDY_HTTP_OK=1"
    call :ok "http://127.0.0.1:4711/admin/ erreichbar"
)

call :section "FIREWALL"
netsh advfirewall firewall show rule name=all dir=in | findstr /I /C:"GC-Bridge Caddy 4711" >nul 2>&1
if errorlevel 1 (
    call :warn "Firewall-Regel 'GC-Bridge Caddy 4711' nicht gefunden"
) else (
    set "FIREWALL_OK=1"
    call :ok "Firewall-Regel fuer Port 4711 vorhanden"
)

call :section "URSACHENHINWEISE"
if "%PYTHON_OK%"=="0" (
    call :hint "Python-Umgebung fehlt. Loesung: im Projektordner 'uv sync' ausfuehren."
    goto :actions
)

if "%MICROTECH_WORKER_TASK_OK%"=="0" (
    call :hint "Task GC-Bridge-Microtech-Worker fehlt. Loesung: deploy\\windows\\ensure-microtech-worker-task.cmd ausfuehren."
    goto :actions
)

if "%MICROTECH_WORKER_PROC_OK%"=="0" (
    call :hint "Task ist registriert, aber Worker laeuft nicht. Loesung: deploy\\windows\\ensure-microtech-worker-task.cmd ausfuehren."
    goto :actions
)

if "%UVICORN_TASK_OK%"=="0" (
    call :hint "Task GC-Bridge-Uvicorn fehlt. Loesung: schtasks /Create fuer Uvicorn neu ausfuehren."
    goto :actions
)

if "%CADDY_TASK_OK%"=="0" (
    call :hint "Task GC-Bridge-Caddy fehlt. Loesung: schtasks /Create fuer Caddy neu ausfuehren."
    goto :actions
)

if "%UVICORN_PORT_OK%"=="0" (
    call :hint "Uvicorn laeuft nicht. Loesung: deploy\\windows\\start-server.cmd oder Task GC-Bridge-Uvicorn starten."
    goto :actions
)

if "%UVICORN_HTTP_OK%"=="0" (
    call :hint "Uvicorn-Port ist offen, aber Django antwortet nicht. Pruefe tmp\\logs\\weekly\\uvicorn\\uvicorn.err.<datum>.log auf Tracebacks."
    goto :actions
)

if "%CADDY_PORT_OK%"=="0" (
    call :hint "Caddy laeuft nicht. Pruefe deploy\\caddy\\caddy.exe und tmp\\logs\\weekly\\caddy\\caddy.err.<datum>.log."
    goto :actions
)

if "%CADDY_HTTP_OK%"=="0" (
    call :hint "Caddy-Port ist offen, aber Reverse Proxy antwortet nicht korrekt. Pruefe deploy\\caddy\\Caddyfile und die neuesten caddy.err-Logs."
    goto :actions
)

if "%FIREWALL_OK%"=="0" (
    call :hint "Lokal ist die App erreichbar, aber externe Clients koennen an Firewall scheitern. Regel fuer Port 4711 pruefen."
) else (
    call :ok "Lokal ist GC-Bridge erreichbar."
    call :log "Wenn nur externe Clients betroffen sind: Netzroute, DNS und LAN-Firewall pruefen."
)

:actions
call :section "SCHNELL-AKTIONEN"
call :log "1) Starten: deploy\\windows\\start-server.cmd"
call :log "2) Vollcheck: deploy\\windows\\health_check.cmd"
call :log "3) Tieferer Dump: deploy\\windows\\check_server.bat > diagnose.txt 2>&1"
call :log "4) Logs: tmp\\logs\\weekly\\uvicorn\\ und tmp\\logs\\weekly\\caddy\\"

call :header "ERGEBNIS: !ERRORS! Fehler / !WARNINGS! Warnungen"
call :log "Logdatei: %LOG_FILE%"

if !ERRORS! gtr 0 (
    if "%~1"=="" pause
    exit /b 1
)

if "%~1"=="" pause
exit /b 0

:ok
call :log "[OK]    %~1"
goto :eof

:warn
set /a WARNINGS+=1
call :log "[WARN]  %~1"
goto :eof

:err
set /a ERRORS+=1
call :log "[ERROR] %~1"
goto :eof

:hint
call :log "[HINT]  %~1"
goto :eof

:section
call :log ""
call :log "--- %~1 ---"
goto :eof

:header
call :log ""
call :log "================================================================"
call :log " %~1"
call :log "================================================================"
goto :eof

:task_running
schtasks /Query /TN "%~1" /V /FO LIST | findstr /I /C:"Running" /C:"Wird ausgef" >nul 2>&1
if not errorlevel 1 exit /b 0
exit /b 1

:log
echo %~1
echo %~1>>"%LOG_FILE%"
goto :eof
