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
set "PYTHON=%APP_DIR%\.venv\Scripts\python.exe"
set "ERRORS=0"
set "WARNINGS=0"

if not exist "%APP_DIR%\tmp\logs" mkdir "%APP_DIR%\tmp\logs"
call "%APP_DIR%\deploy\windows\prune-logs.cmd" 14 >nul 2>&1
for /f %%I in ('powershell -NoProfile -Command "(Get-Date).ToString('yyyy-MM-dd')"') do set "DATESTAMP=%%I"
set "HEALTH_LOG_DIR=%APP_DIR%\tmp\logs\weekly\health_check"
if not exist "%HEALTH_LOG_DIR%" mkdir "%HEALTH_LOG_DIR%"
set "LOG_FILE=%HEALTH_LOG_DIR%\health_check.%DATESTAMP%.log"

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
"%PYTHON%" "%APP_DIR%\deploy\windows\admin_test.py" > "%TEMP%\hc_admin.txt" 2>&1
if errorlevel 1 (
    call :err "Django Admin (eingeloggt) - Fehler!"
    for /f "usebackq delims=" %%L in ("%TEMP%\hc_admin.txt") do call :log "       %%L"
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

call :resolve_latest_log "%APP_DIR%\tmp\logs\daily\uvicorn" "uvicorn.out.*.log" UVICORN_OUT_LOG
call :resolve_latest_log "%APP_DIR%\tmp\logs\weekly\uvicorn" "uvicorn.err.*.log" UVICORN_ERR_LOG
call :resolve_latest_log "%APP_DIR%\tmp\logs\weekly\caddy" "caddy.err.*.log" CADDY_ERR_LOG
call :resolve_latest_log "%APP_DIR%\tmp\logs\monthly\deploy" "deploy.*.log" DEPLOY_LOG
call :resolve_latest_log "%APP_DIR%\tmp\logs\weekly\health_check" "health_check.*.log" HEALTH_CHECK_LOG

:: Der taegliche Uvicorn-stdout ist die beste Quelle fuer 500er aus dem laufenden Webprozess.
if defined UVICORN_OUT_LOG (
    for /f "tokens=*" %%C in ('powershell -NoProfile -Command "(Get-Content \"%UVICORN_OUT_LOG%\" -Tail 200 | Where-Object { $_ -match \"500 Internal Server Error\" } | Measure-Object).Count"') do set "CNT500=%%C"
    if !CNT500! gtr 0 (
        call :err "uvicorn.out - !CNT500! Eintraege mit '500 Internal Server Error' in den letzten 200 Zeilen"
    ) else (
        call :ok "uvicorn.out - keine 500er"
    )
) else (
    call :warn "uvicorn.out - keine aktuelle Datei gefunden"
)

call :check_log_for_errors "%UVICORN_ERR_LOG%" "uvicorn.err"
call :check_log_for_errors "%CADDY_ERR_LOG%" "caddy.err"
call :check_log_for_errors "%DEPLOY_LOG%" "deploy"
call :check_log_for_errors "%HEALTH_CHECK_LOG%" "health_check"

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

:resolve_latest_log
set "%~3="
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "$dir='%~1'; $pattern='%~2'; if (Test-Path $dir) { $file=Get-ChildItem -Path $dir -File -Filter $pattern | Sort-Object LastWriteTime -Descending | Select-Object -First 1; if ($file) { Write-Host $file.FullName } }"`) do set "%~3=%%P"
goto :eof

:check_log_for_errors
if "%~1"=="" (
    call :warn "%~2 - Datei nicht vorhanden"
    goto :eof
)
for /f "tokens=*" %%C in ('powershell -NoProfile -Command "(Get-Content \"%~1\" -Tail 200 | Where-Object { $_ -match \"ERROR\" } | Measure-Object).Count"') do set "CNT=%%C"
if !CNT! gtr 0 (
    call :warn "%~2 - !CNT! ERROR-Eintraege in den letzten 200 Zeilen"
) else (
    call :ok "%~2 - keine Fehler"
)
goto :eof

:log
echo %~1
echo %~1 >> "%LOG_FILE%"
goto :eof
