@echo off
setlocal EnableExtensions

:: ============================================================
::  GC-Bridge Log-Retention
::  Loescht Logdateien nach Retention-Tier.
::  daily   -> 8 Tage
::  weekly  -> 42 Tage
::  monthly -> 400 Tage
::  Legacy-Dateien direkt unter tmp\logs koennen optional mit N Tagen
::  bereinigt werden (Default: 14 Tage).
:: ============================================================

for %%I in ("%~dp0..\..") do set "APP_DIR=%%~fI"
set "LOG_ROOT=%APP_DIR%\tmp\logs"
set "LEGACY_RETENTION_DAYS=%~1"
if "%LEGACY_RETENTION_DAYS%"=="" set "LEGACY_RETENTION_DAYS=14"

if not exist "%LOG_ROOT%" exit /b 0

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='SilentlyContinue';" ^
  "$root='%LOG_ROOT%';" ^
  "$legacyDays=[int]'%LEGACY_RETENTION_DAYS%';" ^
  "$rules=@(" ^
  "  @{ Path=(Join-Path $root 'daily'); Days=8; Recurse=$true }," ^
  "  @{ Path=(Join-Path $root 'weekly'); Days=42; Recurse=$true }," ^
  "  @{ Path=(Join-Path $root 'monthly'); Days=400; Recurse=$true }," ^
  "  @{ Path=$root; Days=$legacyDays; Recurse=$false }" ^
  ");" ^
  "foreach ($rule in $rules) {" ^
  "  if (-not (Test-Path $rule.Path)) { continue }" ^
  "  $cutoff=(Get-Date).AddDays(-[int]$rule.Days);" ^
  "  if ($rule.Recurse) {" ^
  "    $items=Get-ChildItem -Path $rule.Path -File -Recurse -Filter '*.log*';" ^
  "  } else {" ^
  "    $items=Get-ChildItem -Path $rule.Path -File -Filter '*.log*';" ^
  "  }" ^
  "  $items | Where-Object { $_.LastWriteTime -lt $cutoff } | Remove-Item -Force" ^
  "}"

endlocal & exit /b 0
