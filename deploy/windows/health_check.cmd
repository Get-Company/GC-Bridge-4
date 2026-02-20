@echo off
setlocal EnableExtensions EnableDelayedExpansion

:: ============================================================
::  GC-Bridge Health Check
::  Prueft alle kritischen Komponenten und schreibt Log.
::  Exitcode: 0 = alles OK, 1 = Fehler vorhanden
::
::  Aufruf:
::    deploy\windows\health_check.cmd
::    deploy\windows\health_check.cmd > con  (nur Konsole)
:: ============================================================

for %%I in ("%~dp0..\..") do set "APP_DIR=%%~fI"
set "LOG_FILE=%APP_DIR%\tmp\logs\health_check.log"
set "PYTHON=%APP_DIR%\.venv\Scripts\python.exe"
set "ERRORS=0"
set "WARNINGS=0"

if not exist "%APP_DIR%\tmp\logs" mkdir "%APP_DIR%\tmp\logs"

call :header "GC-Bridge Health Check  %date% %time%"

:: ============================================================
:: 1. Version
:: ============================================================
call :section "VERSION"
if exist "%APP_DIR%\VERSION" (
    set /p VER=<"%APP_DIR%\VERSION"
    call :ok "Deployed Version: !VER!"
) else (
    call :warn "VERSION-Datei nicht vorhanden (lokale Umgebung oder erstes Deployment)"
)

:: ============================================================
:: 2. Ports
:: ============================================================
call :section "PORTS"

netstat -ano | findstr /R /C:":8000 .*LISTENING" > nul 2>&1
if errorlevel 1 (call :err "Port 8000 - Uvicorn NICHT aktiv") else (call :ok "Port 8000 - Uvicorn aktiv")

netstat -ano | findstr /R /C:":4711 .*LISTENING" > nul 2>&1
if errorlevel 1 (call :err "Port 4711 - Caddy NICHT aktiv") else (call :ok "Port 4711 - Caddy aktiv")

:: ============================================================
:: 3. HTTP Checks
:: ============================================================
call :section "HTTP CHECKS"

powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/admin/' -UseBasicParsing -TimeoutSec 5; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" > nul 2>&1
if errorlevel 1 (call :err "http://127.0.0.1:8000/admin/ nicht erreichbar") else (call :ok "http://127.0.0.1:8000/admin/ - HTTP 200")

powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:4711/admin/' -UseBasicParsing -TimeoutSec 5; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" > nul 2>&1
if errorlevel 1 (call :err "http://127.0.0.1:4711/admin/ nicht erreichbar") else (call :ok "http://127.0.0.1:4711/admin/ - HTTP 200")

:: ============================================================
:: 4. Django
:: ============================================================
call :section "DJANGO"

pushd "%APP_DIR%"
"%PYTHON%" manage.py check > nul 2>&1
if errorlevel 1 (call :err "manage.py check - Fehler gefunden") else (call :ok "manage.py check - OK")

"%PYTHON%" manage.py migrate --check > nul 2>&1
if errorlevel 1 (call :warn "Unangewandte Migrationen vorhanden!") else (call :ok "Migrationen - aktuell")
popd

:: ============================================================
:: 5. Scheduled Tasks
:: ============================================================
call :section "SCHEDULED TASKS"

for %%T in ("GC-Bridge-Uvicorn" "GC-Bridge-Caddy" "GC-Bridge-Runner") do (
    schtasks /Query /TN %%T > nul 2>&1
    if errorlevel 1 (call :err "Task %%~T - nicht gefunden") else (call :ok "Task %%~T - registriert")
)

:: ============================================================
:: 6. GitHub Actions Runner
:: ============================================================
call :section "GITHUB ACTIONS RUNNER"

sc query "actions.runner.Get-Company-GC-Bridge-4.GC-Bridge-v4" > nul 2>&1
if errorlevel 1 (
    call :err "GitHub Actions Runner - Dienst nicht gefunden"
) else (
    sc query "actions.runner.Get-Company-GC-Bridge-4.GC-Bridge-v4" | findstr "RUNNING" > nul 2>&1
    if errorlevel 1 (call :warn "GitHub Actions Runner - nicht RUNNING") else (call :ok "GitHub Actions Runner - RUNNING")
)

:: ============================================================
:: 7. Festplatte
:: ============================================================
call :section "DISK SPACE"

for /f "tokens=*" %%G in ('powershell -NoProfile -Command "[math]::Round((Get-PSDrive D).Free / 1GB, 2)"') do set "FREE_GB=%%G"
powershell -NoProfile -Command "if ((Get-PSDrive D).Free / 1GB -lt 2) { exit 1 } else { exit 0 }" > nul 2>&1
if errorlevel 1 (
    call :warn "D:\ freier Speicher: !FREE_GB! GB - Warnung: unter 2 GB"
) else (
    call :ok "D:\ freier Speicher: !FREE_GB! GB"
)

:: ============================================================
:: 8. Logdateien auf Fehler pruefen (letzte 200 Zeilen)
:: ============================================================
call :section "LOGS (letzte 200 Zeilen)"

for %%L in (uvicorn.err.log caddy.err.log deploy.log) do (
    if exist "%APP_DIR%\tmp\logs\%%L" (
        for /f "tokens=*" %%C in ('powershell -NoProfile -Command "(Get-Content \"%APP_DIR%\tmp\logs\%%L\" -Tail 200 | Where-Object { $_ -match \"ERROR\" } | Measure-Object).Count"') do set "CNT=%%C"
        if !CNT! gtr 0 (
            call :warn "%%L - !CNT! ERROR-Eintraege in den letzten 200 Zeilen"
        ) else (
            call :ok "%%L - keine Fehler"
        )
    ) else (
        call :warn "%%L - Datei nicht vorhanden"
    )
)

:: ============================================================
:: Zusammenfassung
:: ============================================================
call :header "ERGEBNIS: !ERRORS! Fehler  /  !WARNINGS! Warnungen"
call :log "Log: %LOG_FILE%"
echo.

if !ERRORS! gtr 0 exit /b 1
exit /b 0

:: ============================================================
:: Subroutinen
:: ============================================================
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

:log
echo %~1
echo %~1 >> "%LOG_FILE%"
goto :eof
