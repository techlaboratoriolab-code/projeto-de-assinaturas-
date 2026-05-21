@echo off
setlocal EnableExtensions EnableDelayedExpansion

set PORT=8001

cd /d "%~dp0"

echo ============================================================
echo  Encerrando ambiente publico (Backend + Ngrok)
echo ============================================================

for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
  echo [INFO] Encerrando processo %%p na porta %PORT%...
  taskkill /PID %%p /F >nul 2>&1
)

for /f "tokens=2" %%p in ('tasklist ^| findstr /i "ngrok.exe"') do (
  echo [INFO] Encerrando ngrok PID %%p...
  taskkill /PID %%p /F >nul 2>&1
)

echo [OK] Ambiente encerrado.
pause
