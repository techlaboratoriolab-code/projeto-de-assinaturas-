#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"

cd "$PROJECT_DIR"

if [ -f ".venv/bin/python" ]; then
    .venv/bin/python analisar_assinaturas_v3_vertexai.py --semanal --apenas-log-motivos
else
    python3 analisar_assinaturas_v3_vertexai.py --semanal --apenas-log-motivos
fi
