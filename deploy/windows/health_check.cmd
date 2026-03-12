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
:: 3. HTTP Checks (ohne Redirect-Following fuer echten Status)
:: ============================================================
call :section "HTTP CHECKS"

powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/' -UseBasicParsing -TimeoutSec 5 -MaximumRedirection 0; Write-Host $r.StatusCode; exit 0 } catch { if ($_.Exception.Response) { Write-Host ([int]$_.Exception.Response.StatusCode); exit ([int]$_.Exception.Response.StatusCode) } else { exit 1 } }" > "%TEMP%\hc_8000.txt" 2>&1
set /p HC_8000=<"%TEMP%\hc_8000.txt"
if "!HC_8000!"=="200" (call :ok "http://127.0.0.1:8000/ - HTTP 200") else if "!HC_8000!"=="302" (call :ok "http://127.0.0.1:8000/ - HTTP 302 (Redirect)") else (call :err "http://127.0.0.1:8000/ - HTTP !HC_8000!")

powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:4711/' -UseBasicParsing -TimeoutSec 5 -MaximumRedirection 0; Write-Host $r.StatusCode; exit 0 } catch { if ($_.Exception.Response) { Write-Host ([int]$_.Exception.Response.StatusCode); exit ([int]$_.Exception.Response.StatusCode) } else { exit 1 } }" > "%TEMP%\hc_4711.txt" 2>&1
set /p HC_4711=<"%TEMP%\hc_4711.txt"
if "!HC_4711!"=="200" (call :ok "http://127.0.0.1:4711/ - HTTP 200") else if "!HC_4711!"=="302" (call :ok "http://127.0.0.1:4711/ - HTTP 302 (Redirect)") else (call :err "http://127.0.0.1:4711/ - HTTP !HC_4711!")

:: ============================================================
:: 4. Django
:: ============================================================
call :section "DJANGO"

pushd "%APP_DIR%"
"%PYTHON%" manage.py check > nul 2>&1
if errorlevel 1 (call :err "manage.py check - Fehler gefunden") else (call :ok "manage.py check - OK")

"%PYTHON%" manage.py migrate --check > nul 2>&1
if errorlevel 1 (call :warn "Unangewandte Migrationen vorhanden!") else (call :ok "Migrationen - aktuell")

:: Admin-Seite mit eingeloggtem User testen (faengt 500er die nur bei Login auftreten)
"%PYTHON%" -c "import django,os;os.environ.setdefault('DJANGO_SETTINGS_MODULE','GC_Bridge_4.settings');django.setup();from django.test import Client;from django.contrib.auth import get_user_model;u=get_user_model().objects.filter(is_superuser=True).first();c=Client();c.force_login(u) if u else None;r=c.get('/admin/');print(r.status_code);exit(0 if r.status_code<400 else 1)" > "%TEMP%\hc_admin.txt" 2> "%TEMP%\hc_admin_err.txt"
if errorlevel 1 (
    set /p ADMIN_STATUS=<"%TEMP%\hc_admin.txt"
    call :err "Django Admin (eingeloggt) - HTTP !ADMIN_STATUS!"
    call :log "       Traceback:"
    for /f "usebackq delims=" %%L in ("%TEMP%\hc_admin_err.txt") do call :log "       %%L"
) else (
    call :ok "Django Admin (eingeloggt) - HTTP 200"
)
popd

:: ============================================================
:: 5. Scheduled Tasks
:: ============================================================
call :section "SCHEDULED TASKS"

for %%T in ("GC-Bridge-Uvicorn" "GC-Bridge-Caddy") do (
    schtasks /Query /TN %%T > nul 2>&1
    if errorlevel 1 (call :err "Task %%~T - nicht gefunden") else (call :ok "Task %%~T - registriert")
)
schtasks /Query /TN "GC-Bridge-Microtech-Worker" > nul 2>&1
if errorlevel 1 (
    call :err "Task GC-Bridge-Microtech-Worker - nicht gefunden"
) else (
    call :ok "Task GC-Bridge-Microtech-Worker - registriert"
    call :task_running "GC-Bridge-Microtech-Worker"
    if errorlevel 1 (
        call :err "Task GC-Bridge-Microtech-Worker - Prozess nicht aktiv"
    ) else (
        call :ok "Task GC-Bridge-Microtech-Worker - Prozess aktiv"
    )
)
schtasks /Query /TN "GC-Bridge Scheduled Product Sync" > nul 2>&1
if errorlevel 1 (
    call :warn "Task GC-Bridge Scheduled Product Sync - nicht gefunden (optional)"
) else (
    call :ok "Task GC-Bridge Scheduled Product Sync - registriert"
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

:: uvicorn.out.log separat auf 500-Eintraege pruefen
if exist "%APP_DIR%\tmp\logs\uvicorn.out.log" (
    for /f "tokens=*" %%C in ('powershell -NoProfile -Command "(Get-Content \"%APP_DIR%\tmp\logs\uvicorn.out.log\" -Tail 200 | Where-Object { $_ -match \"500 Internal Server Error\" } | Measure-Object).Count"') do set "CNT500=%%C"
    if !CNT500! gtr 0 (
        call :err "uvicorn.out.log - !CNT500! Eintraege mit '500 Internal Server Error' in den letzten 200 Zeilen"
    ) else (
        call :ok "uvicorn.out.log - keine 500er"
    )
) else (
    call :warn "uvicorn.out.log - Datei nicht vorhanden"
)

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

:task_running
schtasks /Query /TN "%~1" /V /FO LIST | findstr /I /C:"Running" /C:"Wird ausgef" > nul 2>&1
if not errorlevel 1 exit /b 0
exit /b 1

:log
echo %~1
echo %~1 >> "%LOG_FILE%"
goto :eof
