@echo off
:: Backup automático WhatsApp - Agendado para 19h todo dia

cd /d "C:\Users\Windows 11\Desktop\analisar dor de assinatuas de guias\docs"

echo [%date% %time%] Iniciando backup automatico... >> "C:\Users\Windows 11\Desktop\analisar dor de assinatuas de guias\docs\log_backup.txt"

"C:\Users\Windows 11\AppData\Local\Microsoft\WindowsApps\python.exe" "C:\Users\Windows 11\Desktop\analisar dor de assinatuas de guias\docs\backup_Por_data.py" >> "C:\Users\Windows 11\Desktop\analisar dor de assinatuas de guias\docs\log_backup.txt" 2>&1

echo [%date% %time%] Backup finalizado. >> "C:\Users\Windows 11\Desktop\analisar dor de assinatuas de guias\docs\log_backup.txt"
