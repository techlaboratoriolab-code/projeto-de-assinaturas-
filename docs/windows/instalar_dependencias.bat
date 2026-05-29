@echo off
title Instalando dependencias...
set PYTHON="C:\Users\Windows 11\AppData\Local\Microsoft\WindowsApps\python3.13.exe"

echo ============================================================
echo  Instalando dependencias do projeto
echo ============================================================

%PYTHON% -m pip install --upgrade pip

%PYTHON% -m pip install ^
    boto3 ^
    PyMuPDF ^
    requests ^
    Pillow ^
    python-dotenv ^
    mysql-connector-python ^
    google-cloud-aiplatform ^
    selenium

echo ============================================================
echo  Instalacao concluida!
echo ============================================================

pause