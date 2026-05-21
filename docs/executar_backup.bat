@echo off
chcp 65001 >nul
title Backup WhatsApp - Execução Diária

echo ========================================
echo   Backup WhatsApp - Iniciando...
echo ========================================
echo.
echo Data/Hora: %date% %time%
echo.

cd /d "%~dp0"

set "UMAMI_ENABLED=true"
set "UMAMI_URL=https://umamilab.ngrok.dev"
set "UMAMI_WEBSITE_ID=d10aa39d-ed40-4a69-8810-7fe9668d7eea"
set "UMAMI_HOSTNAME=waha-backup-diario.local"
set "UMAMI_EVENT_URL=/backup-whatsapp"

"%~dp0..\.venv\Scripts\python.exe" "%~dp0backup_Por_data.py" --modo automatico

echo.
echo ========================================
echo   Backup finalizado!
echo ========================================
echo.

exit
