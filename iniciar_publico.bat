@echo off
setlocal EnableExtensions EnableDelayedExpansion

set PORT=8001

cd /d "%~dp0"

for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
  echo [INFO] Backend ja em execucao na porta %PORT% - PID %%p.
  echo [INFO] Encerrando para aplicar atualizacoes...
  taskkill /PID %%p /F >nul 2>&1
)

echo ============================================================
echo  Iniciando ambiente publico (Backend + Ngrok)
echo ============================================================

set "NGROK_CMD="

if defined NGROK_EXE if exist "%NGROK_EXE%" set "NGROK_CMD=%NGROK_EXE%"
if not defined NGROK_CMD if exist "%~dp0ngrok.exe" set "NGROK_CMD=%~dp0ngrok.exe"
if not defined NGROK_CMD if exist "%LOCALAPPDATA%\ngrok\ngrok.exe" set "NGROK_CMD=%LOCALAPPDATA%\ngrok\ngrok.exe"
if not defined NGROK_CMD if exist "%LOCALAPPDATA%\Microsoft\WinGet\Packages" for /f "delims=" %%i in ('dir /b /s "%LOCALAPPDATA%\Microsoft\WinGet\Packages\ngrok.exe" 2^>nul') do if not defined NGROK_CMD set "NGROK_CMD=%%i"
if not defined NGROK_CMD if exist "%ProgramFiles%\ngrok\ngrok.exe" set "NGROK_CMD=%ProgramFiles%\ngrok\ngrok.exe"
if not defined NGROK_CMD if defined ProgramFiles(x86) if exist "%ProgramFiles(x86)%\ngrok\ngrok.exe" set "NGROK_CMD=%ProgramFiles(x86)%\ngrok\ngrok.exe"
if not defined NGROK_CMD for /f "delims=" %%i in ('where ngrok 2^>nul') do if not defined NGROK_CMD set "NGROK_CMD=%%i"

if not defined NGROK_CMD (
  echo [ERRO] ngrok nao encontrado.
  echo Defina NGROK_EXE com o caminho do executavel ou instale o ngrok oficial.
  echo Depois autentique: ngrok config add-authtoken SEU_TOKEN
  pause
  exit /b 1
)

for %%I in ("%NGROK_CMD%") do set "NGROK_SIZE=%%~zI"
if /i "%NGROK_CMD%"=="%LOCALAPPDATA%\Microsoft\WindowsApps\ngrok.exe" if "%NGROK_SIZE%"=="0" (
  echo [ERRO] O ngrok encontrado no PATH e um alias quebrado do WindowsApps:
  echo        %NGROK_CMD%
  echo Instale o executavel oficial do ngrok ou defina NGROK_EXE com o caminho correto.
  echo Exemplo: set "NGROK_EXE=C:\caminho\para\ngrok.exe"
  pause
  exit /b 1
)

echo [INFO] Usando ngrok: %NGROK_CMD%

for /f "tokens=2" %%p in ('tasklist ^| findstr /i "ngrok.exe"') do (
  echo [INFO] Encerrando ngrok antigo PID %%p...
  taskkill /PID %%p /F >nul 2>&1
)

echo [BUILD] Buildando frontend para garantir atualizacoes...
pushd frontend
call npm run build
if errorlevel 1 (
  echo [ERRO] Falha no build do frontend.
  popd
  pause
  exit /b 1
)
popd

echo [OK] Subindo backend na porta %PORT%...
start "Backend 8001" cmd /k "cd /d %~dp0 && .venv\Scripts\python.exe api.py"

echo [OK] Subindo ngrok para a porta %PORT%...
start "Ngrok 8001" cmd /k ""%NGROK_CMD%" http %PORT%"

echo [INFO] Aguardando ngrok publicar URL...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$url=''; for($i=0;$i -lt 20;$i++){ try { $r=Invoke-RestMethod -Uri 'http://127.0.0.1:4040/api/tunnels' -TimeoutSec 2; if($r.tunnels){ $https = $r.tunnels | Where-Object { $_.public_url -like 'https://*' } | Select-Object -First 1; if($https){ $url=$https.public_url; break } } } catch {}; Start-Sleep -Milliseconds 500 }; if($url){ Write-Host ('[URL PUBLICA] ' + $url) } else { Write-Host '[AVISO] Nao foi possivel ler a URL publica. Verifique a janela do ngrok.' }"

echo.
echo [DICA] Compartilhe a URL HTTPS do ngrok.
echo [DICA] Para encerrar tudo, rode: parar_publico.bat
echo.
pause
