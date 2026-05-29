# Script para agendar envio diario do resumo do sistema
# Execute este script como Administrador

$ScriptPath = "C:\Users\Windows 11\Desktop\analisar dor de assinatuas de guias\docs\executar_resumo_diario.bat"
$TaskName = "Resumo Diario Assinaturas"
$Description = "Envia diariamente as 17:00 um resumo do sistema para os numeros monitor"

$Action = New-ScheduledTaskAction -Execute $ScriptPath
$Trigger = New-ScheduledTaskTrigger -Daily -At "17:00"
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Highest
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
    Write-Host "Horario: Todos os dias as 17:00" -ForegroundColor Cyan
    Write-Host "Script: $ScriptPath" -ForegroundColor Cyan
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