#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"

cd "$PROJECT_DIR"

echo "============================================================"
echo " Instalando dependencias do projeto"
echo "============================================================"

python3 -m pip install --upgrade pip

python3 -m pip install \
    boto3 \
    PyMuPDF \
    requests \
    Pillow \
    python-dotenv \
    mysql-connector-python \
    google-cloud-aiplatform \
    selenium

echo "============================================================"
echo " Instalacao concluida!"
echo "============================================================"
