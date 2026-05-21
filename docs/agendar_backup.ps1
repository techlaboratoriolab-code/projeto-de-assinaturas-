# Script para agendar o backup diario as 19h (horario de Brasilia)
# Execute este script como Administrador

$ScriptPath = "C:\Users\Windows 11\Desktop\analisar dor de assinatuas de guias\docs\executar_backup.bat"
$TaskName = "Backup WhatsApp Diario"
$Description = "Executa backup do WhatsApp todos os dias as 19h"

# Criar a acao (executar o .bat)
$Action = New-ScheduledTaskAction -Execute $ScriptPath

# Criar o gatilho (diariamente as 19:00)
$Trigger = New-ScheduledTaskTrigger -Daily -At "19:00"

# Configurar para executar independente do usuario estar logado
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Highest

# Configuracoes adicionais
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

# Registrar a tarefa agendada
try {
    # Verificar se a tarefa ja existe e remove-la
    $ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($ExistingTask) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Tarefa existente removida" -ForegroundColor Yellow
    }
    
    # Registrar nova tarefa
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Description $Description
    
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  TAREFA AGENDADA COM SUCESSO!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "Nome da tarefa: $TaskName" -ForegroundColor Cyan
    Write-Host "Horario: Todos os dias as 19:00" -ForegroundColor Cyan
    Write-Host "Script: $ScriptPath" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Para verificar: Abra o 'Agendador de Tarefas' do Windows" -ForegroundColor Yellow
    Write-Host ""
    
} catch {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "  ERRO AO CRIAR TAREFA!" -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "Erro: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "Certifique-se de executar este script como Administrador!" -ForegroundColor Yellow
}

Write-Host "Pressione qualquer tecla para fechar..."
$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
