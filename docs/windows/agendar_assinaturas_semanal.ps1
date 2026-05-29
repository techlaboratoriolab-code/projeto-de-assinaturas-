# Script para agendar analise semanal de assinaturas (log de motivos)
# Execute este script como Administrador

$ScriptPath = "C:\Users\Windows 11\Desktop\analisar dor de assinatuas de guias\executar_assinaturas_semanal.bat"
$TaskName = "Analise Assinaturas Semanal"
$Description = "Executa semanalmente a analise de assinaturas e gera log de motivos"

# Acao: executar o .bat
$Action = New-ScheduledTaskAction -Execute $ScriptPath

# Gatilho: semanal, toda segunda-feira as 08:00
$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At "08:00"

# Executa com privilegio elevado no usuario atual
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Highest

# Configuracoes adicionais
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

try {
    $ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($ExistingTask) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Tarefa existente removida" -ForegroundColor Yellow
    }

    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Description $Description

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  TAREFA AGENDADA COM SUCESSO!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "Nome da tarefa: $TaskName" -ForegroundColor Cyan
    Write-Host "Horario: Toda segunda-feira as 08:00" -ForegroundColor Cyan
    Write-Host "Script: $ScriptPath" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Para verificar: Abra o 'Agendador de Tarefas' do Windows" -ForegroundColor Yellow
    Write-Host ""
}
catch {
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
