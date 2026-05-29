#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
EXEC_SCRIPT="$SCRIPT_DIR/executar_assinaturas_semanal.sh"

chmod +x "$EXEC_SCRIPT"

(crontab -l 2>/dev/null | grep -v "executar_assinaturas_semanal.sh") | crontab - 2>/dev/null || true
(crontab -l 2>/dev/null; echo "0 8 * * 1 $EXEC_SCRIPT") | crontab -

echo ""
echo "========================================"
echo "  TAREFA AGENDADA COM SUCESSO!"
echo "========================================"
echo ""
echo "Nome: Analise Assinaturas Semanal"
echo "Horario: Toda segunda-feira as 08:00"
echo "Script: $EXEC_SCRIPT"
echo ""
echo "Para verificar: crontab -l"
echo "Para remover:   crontab -e"
