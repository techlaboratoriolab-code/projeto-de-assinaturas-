#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"

cd "$PROJECT_DIR"

export UMAMI_ENABLED=true
export UMAMI_URL=https://umamilab.ngrok.dev
export UMAMI_WEBSITE_ID=d10aa39d-ed40-4a69-8810-7fe9668d7eea
export UMAMI_HOSTNAME=waha-backup-diario.local
export UMAMI_EVENT_URL=/backup-whatsapp

if [ -f "$PROJECT_DIR/.venv/bin/python" ]; then
    PYTHON="$PROJECT_DIR/.venv/bin/python"
else
    PYTHON="python3"
fi

echo "========================================"
echo "  Backup WhatsApp - Iniciando..."
echo "========================================"
echo ""
echo "Data/Hora: $(date)"
echo ""

"$PYTHON" "$PROJECT_DIR/docs/backup_Por_data.py" --modo automatico

echo ""
echo "========================================"
echo "  Backup finalizado!"
echo "========================================"
echo ""
