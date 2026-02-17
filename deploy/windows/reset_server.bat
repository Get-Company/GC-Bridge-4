@echo off
setlocal EnableExtensions

net session >nul 2>&1
if not "%errorlevel%"=="0" (
    echo [ERROR] Dieses Skript muss als Administrator ausgefuehrt werden.
    exit /b 1
)

echo [INFO] Stoppe und entferne Dienste...
for %%S in ("GC-Bridge-Uvicorn" "Caddy") do (
    sc.exe stop %%~S >nul 2>&1
    sc.exe delete %%~S >nul 2>&1
)

echo [INFO] Entferne geplante Aufgaben...
for %%T in ("GC-Bridge-Uvicorn" "GC-Bridge-Caddy" "GC-Bridge-Start-Uvicorn" "GC-Bridge-Start-Caddy") do (
    schtasks /Delete /TN %%~T /F >nul 2>&1
)

echo [INFO] Entferne bekannte Firewall-Regeln...
for %%P in (4711 8081 8080) do (
    netsh advfirewall firewall delete rule name="GC-Bridge Caddy %%P" >nul 2>&1
)

echo [DONE] Reset abgeschlossen.
exit /b 0
