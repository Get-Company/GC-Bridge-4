@echo off
setlocal EnableExtensions

:: ============================================================
::  GC-Bridge Log-Retention
::  Loescht Logdateien in tmp\logs, die aelter als N Tage sind.
::  Standard: 14 Tage
:: ============================================================

for %%I in ("%~dp0..\..") do set "APP_DIR=%%~fI"
set "LOG_DIR=%APP_DIR%\tmp\logs"
set "RETENTION_DAYS=%~1"
if "%RETENTION_DAYS%"=="" set "RETENTION_DAYS=14"

if not exist "%LOG_DIR%" exit /b 0

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='SilentlyContinue';" ^
  "$root='%LOG_DIR%';" ^
  "$days=[int]'%RETENTION_DAYS%';" ^
  "$cutoff=(Get-Date).AddDays(-$days);" ^
  "Get-ChildItem -Path $root -File -Filter '*.log*' | Where-Object { $_.LastWriteTime -lt $cutoff } | Remove-Item -Force"

endlocal & exit /b 0
