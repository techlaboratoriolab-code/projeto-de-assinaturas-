@echo off
setlocal EnableExtensions EnableDelayedExpansion

set PORT=8001

echo ============================================================
echo  Sistema de Analise de Assinaturas - Iniciando...
echo ============================================================

cd /d "%~dp0"

for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
    echo [INFO] Backend em execucao na porta %PORT% - PID %%p.
    echo [INFO] Encerrando para aplicar atualizacoes...
    taskkill /PID %%p /F >nul 2>&1
)

echo [BUILD] Compilando frontend React...
cd frontend
call npm run build
if errorlevel 1 (
    echo [ERRO] Falha no build do frontend.
    cd ..
    goto END
)
cd ..

echo [OK] Frontend pronto.
echo [OK] Iniciando servidor em http://localhost:%PORT%
echo.
echo Abra o navegador em: http://localhost:%PORT%
echo Para parar: pressione Ctrl+C
echo.

.venv\Scripts\python.exe api.py

:END
pause
