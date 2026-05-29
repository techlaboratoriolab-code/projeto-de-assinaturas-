#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
LOG_FILE="$PROJECT_DIR/docs/log_backup.txt"

cd "$PROJECT_DIR"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Iniciando backup automatico..." >> "$LOG_FILE"

if [ -f "$PROJECT_DIR/.venv/bin/python" ]; then
    "$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/docs/backup_Por_data.py" >> "$LOG_FILE" 2>&1
else
    python3 "$PROJECT_DIR/docs/backup_Por_data.py" >> "$LOG_FILE" 2>&1
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup finalizado." >> "$LOG_FILE"
