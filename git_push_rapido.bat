@echo off
setlocal EnableExtensions EnableDelayedExpansion

echo ==========================================
echo   Git Push Rapido - projeto assinaturas
echo ==========================================
echo.

where git >nul 2>nul
if errorlevel 1 (
  echo [ERRO] Git nao encontrado no PATH.
  exit /b 1
)

set "MSG=%~1"
if "%MSG%"=="" (
  set /p MSG=Mensagem do commit: 
)
if "%MSG%"=="" (
  echo [ERRO] Mensagem de commit vazia.
  exit /b 1
)

git status --short
echo.

git add -A
if errorlevel 1 (
  echo [ERRO] Falha no git add.
  exit /b 1
)

git diff --cached --quiet
if not errorlevel 1 (
  echo [INFO] Nao ha alteracoes para commit.
  exit /b 0
)

git commit -m "%MSG%"
if errorlevel 1 (
  echo [ERRO] Falha no git commit.
  exit /b 1
)

git push origin main
if errorlevel 1 (
  echo [ERRO] Falha no git push.
  exit /b 1
)

echo.
echo [OK] Commit e push concluídos.
endlocal
