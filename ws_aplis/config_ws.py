"""
Configurações do WebService - Integração APLIS + Autentique
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ==================== APLIS API ====================
APLIS_BASE_URL = os.getenv("APLIS_BASE_URL") or os.getenv("APLIS_URL") or "https://seu-laboratorio.aplis.inf.br"
APLIS_API_URL = f"{APLIS_BASE_URL.rstrip('/')}/api/integracao.php"
APLIS_LOGOUT_URL = f"{APLIS_BASE_URL.rstrip('/')}/api/logout.php"
APLIS_API_VER = 2

APLIS_USER = os.getenv("APLIS_USER", "")
APLIS_PASS = os.getenv("APLIS_PASS") or os.getenv("APLIS_PASSWORD") or ""
APLIS_ID_LABORATORIO = int(os.getenv("APLIS_ID_LABORATORIO", "1"))

# Tipo de imagem para GUIA ASSINADA no seu ambiente APLIS: 15.
# Mantido fixo para evitar anexar como "documento" (5) ou "guia autorizada" (16).
APLIS_TIPO_IMAGEM_GUIA = 15

# ==================== AUTENTIQUE ====================
AUTENTIQUE_API_URL = "https://api.autentique.com.br/v2"
AUTENTIQUE_TOKEN = os.getenv("AUTENTIQUE_TOKEN", "")

# Token secreto que o Autentique envia no header para validar o webhook
AUTENTIQUE_WEBHOOK_SECRET = os.getenv("AUTENTIQUE_WEBHOOK_SECRET", "")

# ==================== SERVIDOR ====================
WS_HOST = os.getenv("WS_HOST", "0.0.0.0")
WS_PORT = int(os.getenv("WS_PORT", "8000"))

# ==================== STORAGE LOCAL ====================
IS_VERCEL = os.getenv("VERCEL") == "1"
DATA_DIR_WS = "/tmp" if IS_VERCEL else os.path.dirname(__file__)

PASTA_GUIAS_ASSINADAS = os.getenv(
    "PASTA_GUIAS_ASSINADAS",
    os.path.join(DATA_DIR_WS, "guias_assinadas")
)

# ==================== BANCO DE DADOS SIMPLES (JSON) ====================
# Arquivo JSON que mapeia requisicao -> documento Autentique
DB_PATH = os.path.join(DATA_DIR_WS, "db_assinaturas.json")
