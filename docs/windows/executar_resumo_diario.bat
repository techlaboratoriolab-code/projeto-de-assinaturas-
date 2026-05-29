@echo off
setlocal

cd /d "C:\Users\Windows 11\Desktop\analisar dor de assinatuas de guias"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "analisar_assinaturas_v3_vertexai.py" --enviar-resumo-diario
) else (
    python "analisar_assinaturas_v3_vertexai.py" --enviar-resumo-diario
)

endlocal