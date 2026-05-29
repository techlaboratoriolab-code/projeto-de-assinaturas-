#!/bin/bash
set -e

PORT=8001
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "============================================================"
echo " Sistema de Analise de Assinaturas - Iniciando..."
echo "============================================================"

cd "$DIR"

# Encerra processo que já esteja usando a porta
PID=$(lsof -ti tcp:$PORT 2>/dev/null || true)
if [ -n "$PID" ]; then
    echo "[INFO] Backend em execucao na porta $PORT - PID $PID."
    echo "[INFO] Encerrando para aplicar atualizacoes..."
    kill -9 "$PID"
fi

# Build do frontend
echo "[BUILD] Compilando frontend React..."
cd frontend
npm install --silent
npm run build
cd ..
echo "[OK] Frontend pronto."

# Inicia o backend
echo "[OK] Iniciando servidor em http://localhost:$PORT"
echo ""
echo "Abra o navegador em: http://localhost:$PORT"
echo "Para parar: pressione Ctrl+C"
echo ""

.venv/bin/python api.py
