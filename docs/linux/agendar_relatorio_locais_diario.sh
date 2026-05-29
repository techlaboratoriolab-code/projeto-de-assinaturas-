#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
EXEC_SCRIPT="$SCRIPT_DIR/executar_relatorio_locais_diario.sh"

chmod +x "$EXEC_SCRIPT"

(crontab -l 2>/dev/null | grep -v "executar_relatorio_locais_diario.sh") | crontab - 2>/dev/null || true
(crontab -l 2>/dev/null; echo "0 7 * * * $EXEC_SCRIPT") | crontab -

echo ""
echo "========================================"
echo "  TAREFA AGENDADA COM SUCESSO!"
echo "========================================"
echo ""
echo "Nome: Relatorio Diario Locais Faturamento"
echo "Horario: Todos os dias as 07:00"
echo "Script: $EXEC_SCRIPT"
echo ""
echo "Para verificar: crontab -l"
echo "Para remover:   crontab -e"
