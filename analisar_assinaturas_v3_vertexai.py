import os
import sys
import csv
import argparse
import base64
import boto3
import time
import json
import requests
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter
from PIL import Image
from dotenv import load_dotenv
import mysql.connector
from google.oauth2 import service_account
from google.auth.transport.requests import Request as GoogleAuthRequest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC                                        ###SO RODAR AQUI PARA MOSTRAR PARA O MARIO  FUI EMBORA 3 MIN PRO UBER MAN  
from selenium.common.exceptions import NoSuchElementException, TimeoutException

try:
    import pymupdf as fitz  # PyMuPDF >= 1.24
except ImportError:
    import fitz  # Compatibilidade com versões antigas

try:
    # Evita UnicodeEncodeError no Windows quando stdout/stderr estão em cp1252 (ex.: via pipe/API).
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

EXIT_CODE_NO_DATA = 2

def _safe_console_text(value):
    """Normaliza texto para a codificacao do console atual sem quebrar execucao."""
    text = str(value)
    encoding = getattr(sys.stdout, 'encoding', None) or 'utf-8'
    try:
        return text.encode(encoding, errors='replace').decode(encoding, errors='replace')
    except Exception:
        return text.encode('utf-8', errors='replace').decode('utf-8', errors='replace')

load_dotenv()

# configurações do banco de dados
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': int(os.getenv('DB_PORT', '3306')),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD'),
    'database': os.getenv('DB_NAME')
}
#acesso aos  bakcups da aws s3
AWS_ACCESS_KEY = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
AWS_REGION = os.getenv('AWS_REGION', 'sa-east-1')
S3_BUCKET_NAME = os.getenv('S3_BUCKET_NAME', 'aplis2')
# diretórios locais
IS_VERCEL = os.getenv('VERCEL') == '1'
BASE_DIR = os.path.dirname(__file__)
DATA_DIR = '/tmp' if IS_VERCEL else BASE_DIR

if IS_VERCEL:
    DIRETORIO_IMAGENS = os.path.join('/tmp', 'IMAGENS AWS')
    DIRETORIO_RELATORIOS = os.path.join('/tmp', 'relatorios')
else:
    DIRETORIO_IMAGENS = os.getenv('DIRETORIO_IMAGENS', os.path.join(DATA_DIR, 'IMAGENS AWS'))
    DIRETORIO_RELATORIOS = os.getenv('DIRETORIO_RELATORIOS', os.path.join(DATA_DIR, 'relatorios'))
ARQUIVO_TELEFONES_OVERRIDE = os.path.join(DIRETORIO_RELATORIOS, 'faturamento_telefones_overrides.json')
ARQUIVO_REQUISICOES_PROCESSADAS = os.path.join(DIRETORIO_RELATORIOS, 'faturamento_requisicoes_processadas_manual.txt')
# Lista de convenios para buscar (somente os 3 solicitados)
CONVENIOS = [1000, 1001, 1091]
TIPO_IMAGEM = int(os.getenv('TIPO_IMAGEM', 16))
LIMITE_REGISTROS = int(os.getenv('LIMITE_REGISTROS', 15))
# login aplis
APLIS_URL = os.getenv('APLIS_URL', 'https://lab.aplis.inf.br/')
APLIS_USER = os.getenv('APLIS_USER')
APLIS_PASSWORD = os.getenv('APLIS_PASSWORD')
# credenciais Autentique
AUTENTIQUE_API_URL = "https://api.autentique.com.br/v2/graphql"
AUTENTIQUE_TOKEN = os.getenv('AUTENTIQUE_TOKEN')
# Telefones de teste - configuraveis via env
def _normalizar_lista_telefones(raw_value):
    telefones = []
    vistos = set()
    for parte in str(raw_value or '').split(','):
        tel = ''.join(filter(str.isdigit, parte))
        if not tel or tel in vistos:
            continue
        vistos.add(tel)
        telefones.append(tel)
    return telefones

TELEFONE_WAHA = ''.join(filter(str.isdigit, os.getenv('TELEFONE_WAHA', '556192127911')))
_TELEFONES_WAHA_TESTE_DEFAULT = ','.join(filter(None, [TELEFONE_WAHA, '556139634027']))
TELEFONES_WAHA_TESTE = _normalizar_lista_telefones(
    os.getenv('TELEFONES_WAHA_TESTE', _TELEFONES_WAHA_TESTE_DEFAULT)
)
if TELEFONE_WAHA and TELEFONE_WAHA not in TELEFONES_WAHA_TESTE:
    TELEFONES_WAHA_TESTE.insert(0, TELEFONE_WAHA)
TELEFONE_AUTENTIQUE = os.getenv('TELEFONE_AUTENTIQUE')
TELEFONE_AUTENTIQUE_TESTE = ''.join(filter(str.isdigit, os.getenv('TELEFONE_AUTENTIQUE_TESTE', '')))

def _telefone_autentique_teste():
    """Retorna telefone de teste para Autentique no formato esperado (+55...)."""
    if TELEFONE_AUTENTIQUE_TESTE:
        return TELEFONE_AUTENTIQUE_TESTE

    # Fallback: deriva a partir do primeiro numero WAHA de teste.
    tel = TELEFONES_WAHA_TESTE[0] if TELEFONES_WAHA_TESTE else TELEFONE_WAHA
    if not tel and TELEFONE_AUTENTIQUE:
        tel = ''.join(filter(str.isdigit, TELEFONE_AUTENTIQUE))
    # Se vier sem o 9 (12 digitos com DDI 55), insere apos DDI+DDD
    if len(tel) == 12 and tel.startswith('55'):
        tel = tel[:4] + '9' + tel[4:]
    return tel
# Modo teste: redireciona TODAS as mensagens WAHA para os numeros configurados
# Lê do env var (controlado pela API) ou config.json, padrão True
def _ler_modo_teste():
    _env = os.getenv('MODO_TESTE')
    if _env is not None:
        return _env.lower() == 'true'
    _cfg = os.path.join(os.path.dirname(__file__), 'config.json')
    if os.path.exists(_cfg):
        import json as _json
        try:
            return _json.loads(open(_cfg).read()).get('modo_teste', True)
        except Exception:
            pass
    return True

def _ler_criar_tarefa_aplis():
    _env = os.getenv('CRIAR_TAREFA_APLIS')
    if _env is not None:
        return _env.lower() == 'true'
    return False

MODO_TESTE = _ler_modo_teste()
CRIAR_TAREFA_APLIS = _ler_criar_tarefa_aplis()
# Mantem reenvio habilitado por padrao para evitar queda artificial na fila entre execucoes.
FATURAMENTO_PERMITIR_REENVIO = os.getenv('FATURAMENTO_PERMITIR_REENVIO', 'true').lower() == 'true'
# Evita remover automaticamente requisicoes sem telefone da fila (causava reducao progressiva do total).
FATURAMENTO_PERSISTIR_SEM_TELEFONE_SKIP = os.getenv('FATURAMENTO_PERSISTIR_SEM_TELEFONE_SKIP', 'false').lower() == 'true'
JANELA_REENVIO_HORAS = int(os.getenv('FATURAMENTO_JANELA_REENVIO_HORAS', '24'))
FATURAMENTO_TESTE_MAX_REQUISICOES = int(os.getenv('FATURAMENTO_TESTE_MAX_REQUISICOES', '1'))
FATURAMENTO_LOTE_ENVIO_REQUISICOES = int(os.getenv('FATURAMENTO_LOTE_ENVIO_REQUISICOES', '50'))
MODO_TESTE_CONFIRMACAO_GLOBAL = os.getenv('MODO_TESTE_CONFIRMACAO_GLOBAL', 'false').lower() == 'true'
WAHA_TIMEOUT_CONFIRMACAO_SEG = int(os.getenv('WAHA_TIMEOUT_CONFIRMACAO_SEG', '900'))
WAHA_TIMEOUT_CONFIRMACAO_SEG_TESTE = int(os.getenv('WAHA_TIMEOUT_CONFIRMACAO_SEG_TESTE', '120'))
EXIGIR_LIBERACAO_OPERADOR_TESTE = os.getenv('EXIGIR_LIBERACAO_OPERADOR_TESTE', 'true').lower() == 'true'
WAHA_TIMEOUT_LIBERACAO_OPERADOR_SEG = int(os.getenv('WAHA_TIMEOUT_LIBERACAO_OPERADOR_SEG', '180'))
FATURAMENTO_TELEFONES_BLOQUEADOS_RAW = os.getenv('FATURAMENTO_TELEFONES_BLOQUEADOS', '')
# WAHA API keys + webhook
WAHA_URL = os.getenv('WAHA_URL', 'http://localhost:4300')
WAHA_SESSION = os.getenv('WAHA_SESSION', 'TIBOT')
WAHA_API_KEY = os.getenv('WAHA_API_KEY')

# Umami (sistema de assinaturas)
UMAMI_ASSINATURAS_ENABLED = os.getenv(
    'UMAMI_ASSINATURAS_ENABLED',
    os.getenv('UMAMI_ENABLED', 'true')
).lower() == 'true'
UMAMI_ASSINATURAS_URL = os.getenv(
    'UMAMI_ASSINATURAS_URL',
    os.getenv('UMAMI_URL', 'https://umamilab.ngrok.dev')
).rstrip('/')
UMAMI_ASSINATURAS_WEBSITE_ID = os.getenv(
    'UMAMI_ASSINATURAS_WEBSITE_ID',
    os.getenv('UMAMI_WEBSITE_ID', 'e72b67a1-f69b-4579-b41a-d88a8f310b20')
)
UMAMI_ASSINATURAS_HOSTNAME = os.getenv(
    'UMAMI_ASSINATURAS_HOSTNAME',
    os.getenv('UMAMI_HOSTNAME', 'relatorio-assinatura.local')
)
UMAMI_ASSINATURAS_EVENT_URL = os.getenv('UMAMI_ASSINATURAS_EVENT_URL', '/sistema-assinaturas')
# Numeros monitor: recebem apenas resumo diario do sistema
_TELEFONES_MONITOR_DEFAULT = '556139634027,5561992127911'
TELEFONES_MONITOR_PRODUCAO = [
    t.strip() for t in
    os.getenv('TELEFONES_MONITOR_PRODUCAO', _TELEFONES_MONITOR_DEFAULT).split(',')
    if t.strip()
]


def enviar_evento_umami_assinaturas(nome_evento, dados=None):
    if not UMAMI_ASSINATURAS_ENABLED:
        return

    if not UMAMI_ASSINATURAS_URL or not UMAMI_ASSINATURAS_WEBSITE_ID or not UMAMI_ASSINATURAS_HOSTNAME:
        print("[UMAMI] Configuracao incompleta para sistema de assinaturas.")
        return

    payload = {
        'type': 'event',
        'payload': {
            'website': UMAMI_ASSINATURAS_WEBSITE_ID,
            'hostname': UMAMI_ASSINATURAS_HOSTNAME,
            'screen': '1920x1080',
            'language': 'pt-BR',
            'url': UMAMI_ASSINATURAS_EVENT_URL,
            'name': nome_evento,
            'data': dados or {}
        }
    }

    try:
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.post(
            f"{UMAMI_ASSINATURAS_URL}/api/send",
            json=payload,
            headers=headers,
            timeout=15
        )
        response.raise_for_status()
        print(f"[UMAMI] Evento enviado: {nome_evento}")
    except Exception as e:
        print(f"[UMAMI] Falha ao enviar evento: {e}")
# Nomes dos convenios identificação das requisições
CONVENIOS_NOMES = {
    1000: "ASSEFAZ",
    1001: "BRADESCO",
    1091: "PM"
}
S3_PREFIXOS = {
    "0040": "lab/Arquivos/Foto/0040/",
    "0085": "lab/Arquivos/Foto/0085/",
    "0100": "lab/Arquivos/Foto/0100/",
    "0101": "lab/Arquivos/Foto/0101/",
    "0200": "lab/Arquivos/Foto/0200/",
    "0031": "lab/Arquivos/Foto/0031/",
    "0102": "lab/Arquivos/Foto/0102/",
    "0103": "lab/Arquivos/Foto/0103/",
    "0300": "lab/Arquivos/Foto/0300/",
    "8511": "lab/Arquivos/Foto/8511/",
    "0032": "lab/Arquivos/Foto/0032/",
    "0049": "lab/Arquivos/Foto/0049/"
}
# Inicializa Vertex AI via REST (sem grpc)
VERTEX_DISPONIVEL = False
VERTEX_CREDENTIALS = None
GOOGLE_CLOUD_PROJECT = os.getenv('GOOGLE_CLOUD_PROJECT', 'spry-catcher-449921-h8')
VERTEX_LOCATION = os.getenv('VERTEX_LOCATION', 'us-central1')
VERTEX_MODEL = os.getenv('VERTEX_MODEL', 'gemini-2.5-pro')
VERTEX_FALLBACK_MODEL = os.getenv('VERTEX_FALLBACK_MODEL', 'gemini-2.5-flash')
VERTEX_TIMEOUT_SEC = int(os.getenv('VERTEX_TIMEOUT_SEC', '120'))
VERTEX_MAX_RETRIES = int(os.getenv('VERTEX_MAX_RETRIES', '4'))
VERTEX_RETRY_BASE_SEC = float(os.getenv('VERTEX_RETRY_BASE_SEC', '2'))
VERTEX_SCOPES = ['https://www.googleapis.com/auth/cloud-platform']

def _load_vertex_credentials():
    raw_json = (
        os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON')
        or os.getenv('GOOGLE_APPLICATION_CREDENTIALS_JSON')
        or ''
    ).strip()
    raw_b64 = (
        os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON_BASE64')
        or os.getenv('GOOGLE_APPLICATION_CREDENTIALS_BASE64')
        or ''
    ).strip()
    cred_path = (os.getenv('GOOGLE_APPLICATION_CREDENTIALS') or '').strip()

    if raw_json:
        info = json.loads(raw_json)
        return service_account.Credentials.from_service_account_info(info, scopes=VERTEX_SCOPES)

    if raw_b64:
        decoded = base64.b64decode(raw_b64).decode('utf-8')
        info = json.loads(decoded)
        return service_account.Credentials.from_service_account_info(info, scopes=VERTEX_SCOPES)

    if cred_path:
        if cred_path.lstrip().startswith('{'):
            info = json.loads(cred_path)
            return service_account.Credentials.from_service_account_info(info, scopes=VERTEX_SCOPES)
        if os.path.exists(cred_path):
            return service_account.Credentials.from_service_account_file(cred_path, scopes=VERTEX_SCOPES)

    raise FileNotFoundError(
        "Credencial Google nao encontrada. Configure GOOGLE_SERVICE_ACCOUNT_JSON, "
        "GOOGLE_SERVICE_ACCOUNT_JSON_BASE64 ou um caminho valido em GOOGLE_APPLICATION_CREDENTIALS."
    )

try:
    print("[INFO] Inicializando Vertex AI (REST - sem grpc)...")
    VERTEX_CREDENTIALS = _load_vertex_credentials()
    VERTEX_CREDENTIALS.refresh(GoogleAuthRequest())
    VERTEX_DISPONIVEL = True
    print("[OK] Vertex AI REST configurado!")
except Exception as e:
    print(f"[AVISO] Vertex AI REST indisponivel neste ambiente: {e}")
    print("[AVISO] Sem IA disponivel. A analise sera marcada como ERRO_ANALISE_ASSINATURA.")
# GraphQL Query para consultar status de assinatura de um documento
GET_DOCUMENT_STATUS_QUERY = """
query GetDocumentStatus($id: UUID!) {
    document(id: $id) {
        id
        name
        created_at
        signatures {
            signed_at
            action { name }
        }
    }
}
"""

# GraphQL Mutation para criar documento
CREATE_DOCUMENT_MUTATION = """
mutation CreateDocumentMutation(
  $document: DocumentInput!,
  $signers: [SignerInput!]!,
  $file: Upload!
) {
  createDocument(
    document: $document,
    signers: $signers,
    file: $file
  ) {
    id
    name
    created_at
    signatures {
      public_id
      name
      email
      action { name }
      link { short_link }
    }
  }
}
"""

def _verificar_assinado_autentique(doc_id):
    """Consulta a API Autentique e retorna True se o documento já foi assinado."""
    if not AUTENTIQUE_TOKEN or not doc_id:
        return None
    try:
        headers = {"Authorization": f"Bearer {AUTENTIQUE_TOKEN}"}
        payload = {"query": GET_DOCUMENT_STATUS_QUERY, "variables": {"id": doc_id}}
        resp = requests.post(AUTENTIQUE_API_URL, headers=headers, json=payload, timeout=30)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if 'errors' in data:
            return None
        doc = data.get('data', {}).get('document')
        if not doc:
            return None
        sigs = doc.get('signatures') or []
        return any(s.get('signed_at') for s in sigs)
    except Exception:
        return None


def enviar_lembretes_nao_assinados(horas_minimas=24):
    """Percorre CSVs de documentos enviados e manda lembrete para quem ainda não assinou após horas_minimas."""
    print(f"\n{'='*80}")
    print(f"[LEMBRETE] VERIFICANDO DOCUMENTOS NAO ASSINADOS (>{horas_minimas}h)")
    print(f"{'='*80}\n")

    agora = datetime.now()
    enviados = 0
    ignorados_assinados = 0
    ignorados_recentes = 0
    erros = 0

    vistos = set()  # evita duplicatas por requisição no mesmo lote

    for row in _iterar_csv_relatorios('documentos_autentique_producao_*.csv') or []:
        cod_req = _normalizar_cod_requisicao(row.get('CodRequisicao'))
        doc_id = row.get('DocumentoID', '').strip()
        telefone = (row.get('Telefone') or '').strip()
        nome_paciente = (row.get('NomPaciente') or '').strip()
        created_at_str = (row.get('created_at') or row.get('DataEnvio') or '').strip()

        if not cod_req or not doc_id or not telefone:
            continue

        if cod_req in vistos:
            continue
        vistos.add(cod_req)

        # Verifica se passou o tempo mínimo desde o envio
        if created_at_str:
            try:
                for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
                    try:
                        dt_envio = datetime.strptime(created_at_str[:19], fmt)
                        break
                    except ValueError:
                        continue
                else:
                    dt_envio = None
                if dt_envio and (agora - dt_envio).total_seconds() < horas_minimas * 3600:
                    ignorados_recentes += 1
                    continue
            except Exception:
                pass

        # Consulta Autentique
        assinado = _verificar_assinado_autentique(doc_id)
        if assinado is True:
            ignorados_assinados += 1
            print(f"  [OK] Req {cod_req} ja assinada — sem lembrete necessario")
            continue
        if assinado is None:
            erros += 1
            print(f"  [AVISO] Req {cod_req} — nao foi possivel verificar status no Autentique")

        # Normaliza telefone
        telefone_limpo = _normalizar_telefone_whatsapp(telefone)
        if not telefone_limpo:
            print(f"  [AVISO] Req {cod_req} — telefone invalido: {telefone}")
            continue

        primeiro_nome = _primeiro_nome_paciente(nome_paciente) if nome_paciente else 'Sr.(a)'

        mensagem_lembrete = f"""Olá, Sr.(a) *{primeiro_nome}*, tudo bem?

Passando para lembrar da assinatura da guia do seu exame.

Seu exame é prioridade para nós, mas dependemos dessa assinatura para dar continuidade ao processo.

*Laboratório LAB*"""

        print(f"  [LEMBRETE] Req {cod_req} → {telefone_limpo} ({primeiro_nome})")
        if enviar_mensagem_waha(telefone_limpo, mensagem_lembrete):
            enviados += 1
        else:
            print(f"  [ERRO] Falha ao enviar lembrete para {telefone_limpo}")

    print(f"\n[LEMBRETE] Lembretes enviados: {enviados}")
    if ignorados_assinados:
        print(f"[LEMBRETE] Ja assinados (ignorados): {ignorados_assinados}")
    if ignorados_recentes:
        print(f"[LEMBRETE] Enviados ha menos de {horas_minimas}h (ignorados): {ignorados_recentes}")
    if erros:
        print(f"[LEMBRETE] Erros ao verificar status: {erros}")


def _registrar_log_wa(telefone_original, telefone_destino, status, mensagem='', erro=''):
    """Registra eventos de WhatsApp (envio e recebimento) em CSV diário."""
    try:
        if not os.path.exists(DIRETORIO_RELATORIOS):
            os.makedirs(DIRETORIO_RELATORIOS)

        arquivo = os.path.join(DIRETORIO_RELATORIOS, f"whatsapp_enviadas_{datetime.now().strftime('%Y%m%d')}.csv")
        existe = os.path.exists(arquivo)
        campos = ['DataHora', 'TelefoneOriginal', 'TelefoneDestino', 'ModoTeste', 'Status', 'Mensagem', 'Erro']

        with open(arquivo, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=campos)
            if not existe:
                writer.writeheader()
            writer.writerow({
                'DataHora': datetime.now().isoformat(timespec='seconds'),
                'TelefoneOriginal': telefone_original,
                'TelefoneDestino': telefone_destino,
                'ModoTeste': 'SIM' if MODO_TESTE else 'NAO',
                'Status': status,
                'Mensagem': str(mensagem or '').replace('\n', ' ').strip(),
                'Erro': str(erro or '').strip(),
            })
    except Exception:
        pass

def enviar_mensagem_waha(telefone, mensagem):
    """Envia mensagem de texto via WAHA WhatsApp"""
    try:
        if not WAHA_API_KEY:
            print("  [ERRO] WAHA_API_KEY nao configurada no ambiente")
            _registrar_log_wa(telefone, telefone, 'ERRO', mensagem=mensagem, erro='WAHA_API_KEY ausente')
            return False

        # Garante formato correto (apenas números)
        telefone_limpo = ''.join(filter(str.isdigit, telefone))
        telefone_original = telefone_limpo
        destinos = [telefone_limpo]

        if MODO_TESTE:
            destinos = TELEFONES_WAHA_TESTE or ([TELEFONE_WAHA] if TELEFONE_WAHA else [])
            print(f"  [TESTE] Redirecionando de {telefone_limpo} -> {', '.join(destinos)}")

        if not destinos:
            print("  [ERRO] Nenhum numero de destino configurado para envio WAHA")
            _registrar_log_wa(telefone_original, '', 'ERRO_DESTINO', mensagem=mensagem, erro='sem_destino_waha')
            return False

        url = f"{WAHA_URL}/api/sendText"

        headers = {
            "Content-Type": "application/json",
            "X-Api-Key": WAHA_API_KEY
        }
        resultados = []
        for destino in destinos:
            payload = {
                "session": WAHA_SESSION,
                "chatId": f"{destino}@c.us",
                "text": mensagem
            }
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            if response.status_code in (200, 201):
                _registrar_log_wa(telefone_original, destino, 'ENVIADA', mensagem=mensagem)
                resultados.append(True)
            else:
                print(f"  [ERRO] WAHA HTTP {response.status_code} para {destino}: {response.text[:200]}")
                _registrar_log_wa(telefone_original, destino, 'ERRO_HTTP', mensagem=mensagem, erro=f"HTTP {response.status_code}")
                resultados.append(False)

        if resultados and not all(resultados):
            print("  [AVISO] Nem todos os numeros de teste receberam a mensagem WAHA")

        return any(resultados)
    except requests.exceptions.ConnectionError:
        print(f"  [ERRO] Não foi possível conectar ao WAHA em {WAHA_URL}")
        _registrar_log_wa(telefone, telefone, 'ERRO_CONEXAO', mensagem=mensagem, erro=f"Falha conexao em {WAHA_URL}")
        return False
    except Exception as e:
        print(f"  [ERRO] Exceção ao enviar mensagem WAHA: {e}")
        _registrar_log_wa(telefone, telefone, 'ERRO_EXCECAO', mensagem=mensagem, erro=str(e))
        import traceback
        traceback.print_exc()
        return False

def _parse_datetime_flexible(valor):
    if not valor:
        return None
    texto = str(valor).strip()
    if not texto:
        return None
    for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.strptime(texto[:19], fmt)
        except ValueError:
            continue
    return None


def _enviar_resumo_monitor(mensagem):
    """Envia resumo diario para os numeros monitor configurados."""
    if not TELEFONES_MONITOR_PRODUCAO:
        return 0
    enviados = 0
    for tel_monitor in TELEFONES_MONITOR_PRODUCAO:
        try:
            if enviar_mensagem_waha(tel_monitor, mensagem):
                enviados += 1
        except Exception as e:
            print(f"  [AVISO] Falha ao enviar resumo para {tel_monitor}: {e}")
    return enviados


def enviar_resumo_diario_monitoramento(data_referencia=None):
    """Gera e envia resumo diario do sistema para os numeros monitor."""
    data_ref = data_referencia or datetime.now().date()
    print(f"\n{'='*80}")
    print(f"[RESUMO] GERANDO RESUMO DIARIO DE {data_ref.strftime('%d/%m/%Y')}")
    print(f"{'='*80}\n")

    docs_do_dia = []
    for row in _iterar_csv_relatorios('documentos_autentique_producao_*.csv') or []:
        dt_envio = _parse_datetime_flexible(row.get('created_at') or row.get('DataEnvio'))
        if dt_envio and dt_envio.date() == data_ref:
            docs_do_dia.append(row)

    enviados_hoje = len(docs_do_dia)
    assinados_hoje = 0
    pendentes_hoje = 0
    falhas_status = 0

    for row in docs_do_dia:
        doc_id = (row.get('DocumentoID') or '').strip()
        assinado = _verificar_assinado_autentique(doc_id)
        if assinado is True:
            assinados_hoje += 1
        elif assinado is False:
            pendentes_hoje += 1
        else:
            falhas_status += 1

    log_dia = os.path.join(DIRETORIO_RELATORIOS, f"whatsapp_enviadas_{data_ref.strftime('%Y%m%d')}.csv")
    lembretes_enviados = 0
    telefones_invalidos = 0
    telefones_bloqueados = 0
    erros_waha = 0

    if os.path.exists(log_dia):
        try:
            with open(log_dia, 'r', encoding='utf-8', newline='') as f:
                for row in csv.DictReader(f):
                    status = (row.get('Status') or '').strip().upper()
                    mensagem = (row.get('Mensagem') or '').strip()
                    if status == 'ENVIADA' and 'Passando para lembrar da assinatura da guia do seu exame.' in mensagem:
                        lembretes_enviados += 1
                    if status == 'TELEFONE_INVALIDO':
                        telefones_invalidos += 1
                    if status == 'TELEFONE_BLOQUEADO':
                        telefones_bloqueados += 1
                    if status.startswith('ERRO'):
                        erros_waha += 1
        except Exception as e:
            print(f"[AVISO] Nao foi possivel ler log diario do WhatsApp: {e}")

    mensagem_resumo = (
        f"*Resumo diario do sistema*\n"
        f"Data: {data_ref.strftime('%d/%m/%Y')}\n\n"
        f"Documentos enviados hoje: {enviados_hoje}\n"
        f"Documentos assinados: {assinados_hoje}\n"
        f"Documentos pendentes: {pendentes_hoje}\n"
        f"Falhas na consulta de status: {falhas_status}\n"
        f"Lembretes enviados hoje: {lembretes_enviados}\n"
        f"Telefones invalidos: {telefones_invalidos}\n"
        f"Telefones bloqueados: {telefones_bloqueados}\n"
        f"Erros WAHA: {erros_waha}"
    )

    enviados_monitor = _enviar_resumo_monitor(mensagem_resumo)
    print(mensagem_resumo)
    print(f"\n[RESUMO] Resumo enviado para {enviados_monitor}/{len(TELEFONES_MONITOR_PRODUCAO)} numero(s) monitor")

def _iterar_logs_whatsapp():
    """Itera logs CSV de WhatsApp do mais novo para o mais antigo."""
    if not os.path.exists(DIRETORIO_RELATORIOS):
        return
    base = Path(DIRETORIO_RELATORIOS)
    arquivos = sorted(base.glob('whatsapp_enviadas_*.csv'), key=lambda p: p.stat().st_mtime, reverse=True)
    for arq in arquivos:
        try:
            with open(arq, 'r', encoding='utf-8', newline='') as f:
                rows = list(csv.DictReader(f))
            for row in reversed(rows):
                yield row
        except Exception:
            continue

def _normalizar_cod_requisicao(valor):
    return ''.join(ch for ch in str(valor or '') if ch.isdigit())

def _deduplicar_por_requisicao(itens, campo='CodRequisicao', contexto='processamento'):
    """Remove itens duplicados pela requisicao para evitar envios repetidos."""
    unicos = []
    vistos = set()
    duplicados = 0

    for item in itens or []:
        req = _normalizar_cod_requisicao(item.get(campo) if isinstance(item, dict) else None)
        if not req:
            continue
        if req in vistos:
            duplicados += 1
            continue
        vistos.add(req)
        unicos.append(item)

    if duplicados > 0:
        print(f"[INFO] Duplicidades removidas em {contexto}: {duplicados} registro(s) da mesma requisicao.")

    return unicos

def _primeiro_nome_paciente(nome_completo):
    nome = str(nome_completo or '').strip()
    if not nome:
        return 'Paciente'
    return nome.split()[0]

def _normalizar_telefone_whatsapp(telefone):
    """Normaliza telefone BR para o padrão de JID do WhatsApp:
    - DDD <= 28 (SP/RJ/ES): Mantém ou adiciona o 9º dígito (13 dígitos com 55).
    - DDD > 28 (Outros estados/DF): Remove o 9º dígito (12 dígitos com 55).
    """
    tel = ''.join(ch for ch in str(telefone or '') if ch.isdigit())
    if not tel:
        return None

    # Remove prefixo internacional extra (00) quando presente.
    if tel.startswith('00'):
        tel = tel[2:]

    # Remove DDI para validar no formato nacional (DDD + numero local).
    if tel.startswith('55'):
        nacional = tel[2:]
    else:
        nacional = tel

    # Aceita DDD + 8 ou 9 dígitos (10 ou 11 no formato nacional).
    if len(nacional) not in (10, 11):
        return None

    ddd = nacional[:2]
    numero_local = nacional[2:]

    # DDD válido no Brasil (11..99).
    if not ddd.isdigit() or int(ddd) < 11 or int(ddd) > 99:
        return None

    ddd_int = int(ddd)
    if ddd_int <= 28:
        # SP, RJ, ES -> Exige 9 dígitos para celular
        if len(numero_local) == 8 and numero_local[0] in '6789':
            numero_local = '9' + numero_local
    else:
        # Outras regiões (incluindo DF/61) -> JID do WhatsApp usa 8 dígitos
        if len(numero_local) == 9 and numero_local.startswith('9'):
            numero_local = numero_local[1:]

    # Evita números obviamente inválidos
    if len(numero_local) == 8 and len(set(numero_local[-8:])) == 1:
        return None

    return f"55{ddd}{numero_local}"

def _carregar_telefones_bloqueados_env():
    """Carrega lista de telefones bloqueados para envio (separados por virgula)."""
    bloqueados = set()
    raw = str(FATURAMENTO_TELEFONES_BLOQUEADOS_RAW or '').strip()
    if not raw:
        return bloqueados

    for parte in raw.split(','):
        tel = ''.join(ch for ch in str(parte or '') if ch.isdigit())
        if not tel:
            continue
        bloqueados.add(tel)
        if tel.startswith('55') and len(tel) > 2:
            bloqueados.add(tel[2:])
        elif len(tel) in (10, 11):
            bloqueados.add(f"55{tel}")
    return bloqueados

TELEFONES_BLOQUEADOS_ENV = _carregar_telefones_bloqueados_env()

def _carregar_telefones_override():
    """Carrega telefones manuais por requisicao (definidos via painel de faturamento)."""
    if not os.path.exists(ARQUIVO_TELEFONES_OVERRIDE):
        return {}
    try:
        with open(ARQUIVO_TELEFONES_OVERRIDE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}

        normalizados = {}
        for req, tel in data.items():
            req_n = _normalizar_cod_requisicao(req)
            tel_n = _normalizar_telefone_whatsapp(tel)
            if req_n and tel_n:
                normalizados[req_n] = tel_n
        return normalizados
    except Exception:
        return {}

def _confirmacao_sim_recente_por_logs(telefone_limpo, janela_minutos=30):
    """Fallback para modo teste: aceita SIM recente já capturado nos logs WAHA."""
    limite = datetime.now() - timedelta(minutes=max(1, int(janela_minutos)))
    tel = ''.join(filter(str.isdigit, telefone_limpo or ''))

    for row in _iterar_logs_whatsapp() or []:
        status = (row.get('Status') or '').strip().upper()
        if not status.startswith('RECEBIDA_SIM'):
            continue

        tel_row = ''.join(filter(str.isdigit, row.get('TelefoneDestino') or row.get('TelefoneOriginal') or ''))
        if tel and tel_row and tel_row != tel:
            continue

        dt_txt = row.get('DataHora') or ''
        try:
            dt = datetime.fromisoformat(dt_txt)
        except Exception:
            dt = None
        if dt and dt >= limite:
            return True
    return False

def _confirmacao_enviada_recente(cod_req, telefone_limpo, janela_horas=24):
    """Evita spam: verifica se já foi enviada mensagem recente para a mesma requisição/telefone."""
    limite = datetime.now() - timedelta(hours=max(1, int(janela_horas)))
    marcador = f"REQ_AVISO:{_normalizar_cod_requisicao(cod_req)}"
    telefone_alvo = ''.join(filter(str.isdigit, telefone_limpo or ''))

    # Permite reenvio quando o histórico anterior foi para números padrão de teste.
    numeros_teste = set()
    for tel_waha_teste in TELEFONES_WAHA_TESTE:
        if tel_waha_teste:
            numeros_teste.add(tel_waha_teste)
    tel_autentique_teste = ''.join(filter(str.isdigit, _telefone_autentique_teste() or ''))
    if tel_autentique_teste:
        numeros_teste.add(tel_autentique_teste)

    for row in _iterar_logs_whatsapp() or []:
        status = (row.get('Status') or '').strip().upper()
        if status != 'AVISO_ASSINATURA':
            continue

        msg = row.get('Mensagem') or ''
        if marcador not in msg:
            continue

        tel_dest = ''.join(filter(str.isdigit, row.get('TelefoneDestino') or ''))

        # Se o envio anterior foi roteado para número padrão de teste, não bloqueia envio real.
        if tel_dest in numeros_teste and tel_dest != telefone_alvo:
            continue

        if tel_dest != telefone_alvo:
            continue

        dt_txt = row.get('DataHora') or ''
        try:
            dt = datetime.fromisoformat(dt_txt)
        except Exception:
            dt = None
        if dt and dt >= limite:
            return True

    return False

def _iterar_csv_relatorios(pattern):
    """Itera linhas de arquivos CSV do diretório de relatórios do mais novo para o mais antigo."""
    if not os.path.exists(DIRETORIO_RELATORIOS):
        return

    base = Path(DIRETORIO_RELATORIOS)
    arquivos = sorted(base.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    for arq in arquivos:
        try:
            with open(arq, 'r', encoding='utf-8', newline='') as f:
                for row in csv.DictReader(f):
                    yield row
        except Exception:
            continue

def _carregar_requisicoes_documentos_enviados():
    """Retorna conjunto de requisições já processadas via documento enviado ou marcação manual."""
    requisicoes = set()

    for row in _iterar_csv_relatorios('documentos_autentique_producao_*.csv') or []:
        cod_req = _normalizar_cod_requisicao(row.get('CodRequisicao'))
        if cod_req:
            requisicoes.add(cod_req)

    if os.path.exists(ARQUIVO_REQUISICOES_PROCESSADAS):
        try:
            with open(ARQUIVO_REQUISICOES_PROCESSADAS, 'r', encoding='utf-8') as f:
                for linha in f:
                    cod_req = _normalizar_cod_requisicao(linha.strip())
                    if cod_req:
                        requisicoes.add(cod_req)
        except Exception as e:
            print(f"[AVISO] Nao foi possivel ler arquivo manual de requisicoes processadas: {e}")

    return requisicoes

def carregar_requisicoes_alvo_arquivo(caminho_arquivo):
    """Carrega conjunto de requisicoes alvo a partir de arquivo (tabulado ou texto)."""
    path = Path(caminho_arquivo)
    if not path.exists():
        print(f"[ERRO] Arquivo de requisicoes alvo nao encontrado: {path}")
        return set()

    alvo = set()
    with open(path, 'r', encoding='utf-8') as f:
        for linha in f:
            s = linha.strip()
            if not s:
                continue
            if s.lower().startswith('paciente') and 'registro' in s.lower():
                continue

            if '\t' in s:
                partes = [p.strip() for p in s.split('\t') if p.strip()]
                if len(partes) >= 2:
                    req = ''.join(ch for ch in partes[1] if ch.isdigit())
                    if req:
                        alvo.add(req)
                continue

            import re
            m = re.search(r'(\d{13})', s)
            if m:
                alvo.add(m.group(1))

    print(f"[FATURAMENTO] Requisicoes alvo carregadas: {len(alvo)}")
    return alvo
def aguardar_confirmacao_waha(telefone, timeout=300):
    """Aguarda confirmação do usuário via WhatsApp em tempo real"""
    from urllib.parse import quote
    try:
        telefone_limpo = ''.join(filter(str.isdigit, telefone))
        timeout_seg = int(timeout or 0)
        sem_timeout = timeout_seg <= 0

        if MODO_TESTE:
            print(f"  [TESTE] Aguardando resposta de {TELEFONE_WAHA} (em vez de {telefone_limpo})")
            telefone_limpo = TELEFONE_WAHA

        chat_id = f"{telefone_limpo}@c.us"
        chat_id_encoded = quote(chat_id, safe='')
        url = f"{WAHA_URL}/api/{WAHA_SESSION}/chats/{chat_id_encoded}/messages"
        if sem_timeout:
            print(f"[INFO] Aguardando resposta de {telefone_limpo} (sem timeout)...")
        else:
            print(f"[INFO] Aguardando resposta de {telefone_limpo} (timeout: {timeout_seg}s)...")
        headers = {
            "Content-Type": "application/json",
            "X-Api-Key": WAHA_API_KEY
        }
        inicio = time.time()
        inicio_int = int(inicio)
        ultima_status = time.time()
        mensagens_registradas = set()
        while True:
            if (not sem_timeout) and ((time.time() - inicio) >= timeout_seg):
                break
            try:
                response = requests.get(url, headers=headers, params={"limit": 20, "downloadMedia": "false"}, timeout=10)
                if response.status_code == 200:
                    for msg in response.json():
                        if not msg.get('fromMe', True):
                            texto_raw = (msg.get('body') or msg.get('text') or '').strip()
                            texto = texto_raw.upper()

                            try:
                                ts_msg = int(msg.get('timestamp', 0))
                            except Exception:
                                ts_msg = 0

                            msg_uid = f"{ts_msg}|{texto_raw}"
                            if msg_uid not in mensagens_registradas:
                                mensagens_registradas.add(msg_uid)

                                status_recebido = 'RECEBIDA_TEXTO'
                                if texto in ['SIM', 'S', 'YES', 'Y']:
                                    status_recebido = 'RECEBIDA_SIM'
                                elif texto in ['NAO', 'NÃO', 'N', 'NO']:
                                    status_recebido = 'RECEBIDA_NAO'

                                if ts_msg < inicio_int:
                                    status_recebido = f"{status_recebido}_FORA_JANELA"

                                _registrar_log_wa(
                                    telefone_original=telefone_limpo,
                                    telefone_destino=telefone_limpo,
                                    status=status_recebido,
                                    mensagem=texto_raw,
                                )

                            if ts_msg >= inicio_int:
                                if texto in ['SIM', 'S', 'YES', 'Y']:
                                    print(f"[OK] Confirmação recebida: '{texto}'")
                                    return True
                                elif texto in ['NAO', 'NÃO', 'N', 'NO']:
                                    print(f"[INFO] Negativa recebida: '{texto}'")
                                    return False
                else:
                    print(f"[AVISO] WAHA messages HTTP {response.status_code}")
                time.sleep(3)
                if (time.time() - ultima_status) >= 30:
                    if sem_timeout:
                        print("[INFO] Aguardando resposta... (sem timeout)")
                    else:
                        restante = int(max(0, timeout_seg - (time.time() - inicio)))
                        print(f"[INFO] Aguardando resposta... ({restante}s restantes)")
                    ultima_status = time.time()
            except requests.exceptions.Timeout:
                time.sleep(5)
                continue
            except Exception as e:
                print(f"[AVISO] Erro ao verificar mensagens: {e}")
                time.sleep(5)
                continue

        print(f"[AVISO] Timeout atingido ({timeout_seg}s). Nenhuma confirmação recebida.")
        return False

    except Exception as e:
        print(f"[ERRO] Erro ao aguardar confirmação WAHA: {e}")
        import traceback
        traceback.print_exc()
        return False

def aguardar_liberacao_operador_waha(cod_req, timeout=180):
    """No modo teste, exige comando explicito do operador para liberar envio ao Autentique."""
    from urllib.parse import quote
    try:
        cod_req_txt = str(cod_req or '').strip()
        telefone_limpo = ''.join(filter(str.isdigit, TELEFONE_WAHA))
        chat_id = f"{telefone_limpo}@c.us"
        chat_id_encoded = quote(chat_id, safe='')
        url = f"{WAHA_URL}/api/{WAHA_SESSION}/chats/{chat_id_encoded}/messages"
        headers = {
            "Content-Type": "application/json",
            "X-Api-Key": WAHA_API_KEY
        }

        print(f"[TESTE] Aguardando LIBERAR {cod_req_txt} do operador ({telefone_limpo}) por ate {timeout}s...")
        inicio = time.time()
        inicio_int = int(inicio)
        mensagens_registradas = set()

        while (time.time() - inicio) < timeout:
            try:
                response = requests.get(url, headers=headers, params={"limit": 30, "downloadMedia": "false"}, timeout=10)
                if response.status_code == 200:
                    for msg in response.json():
                        if msg.get('fromMe', True):
                            continue

                        texto_raw = (msg.get('body') or msg.get('text') or '').strip()
                        texto = ' '.join(texto_raw.upper().split())
                        try:
                            ts_msg = int(msg.get('timestamp', 0))
                        except Exception:
                            ts_msg = 0

                        msg_uid = f"{ts_msg}|{texto_raw}"
                        if msg_uid in mensagens_registradas:
                            continue
                        mensagens_registradas.add(msg_uid)

                        if ts_msg < inicio_int:
                            continue

                        if texto == f"LIBERAR {cod_req_txt}":
                            _registrar_log_wa(telefone_limpo, telefone_limpo, 'RECEBIDA_LIBERAR', mensagem=texto_raw)
                            print(f"[OK] Operador liberou envio da Req {cod_req_txt}.")
                            return True

                        if texto in (f"PULAR {cod_req_txt}", f"NEGAR {cod_req_txt}", f"NAO {cod_req_txt}", f"NÃO {cod_req_txt}"):
                            _registrar_log_wa(telefone_limpo, telefone_limpo, 'RECEBIDA_PULAR', mensagem=texto_raw)
                            print(f"[INFO] Operador negou/pulou envio da Req {cod_req_txt}.")
                            return False

                time.sleep(3)
            except requests.exceptions.Timeout:
                time.sleep(4)
                continue
            except Exception as e:
                print(f"[AVISO] Falha ao aguardar liberacao do operador: {e}")
                time.sleep(4)

        print(f"[AVISO] Timeout aguardando liberacao do operador para Req {cod_req_txt}.")
        return False
    except Exception as e:
        print(f"[ERRO] Erro ao aguardar liberacao do operador: {e}")
        return False

def converter_imagem_para_pdf(caminho_imagem):
    """Converte imagem JPG/JPEG/PNG para PDF"""
    try:
        extensao = os.path.splitext(caminho_imagem)[1].upper()

        if extensao not in ['.JPG', '.JPEG', '.PNG']:
            return caminho_imagem  # Já é PDF ou outro formato

        # Cria caminho do PDF temporário
        caminho_pdf = caminho_imagem.rsplit('.', 1)[0] + '_converted.pdf'

        # Abre a imagem e converte para PDF
        img = Image.open(caminho_imagem)

        # Converte para RGB se necessário (PNG com transparência)
        if img.mode in ('RGBA', 'LA', 'P'):
            rgb_img = Image.new('RGB', img.size, (255, 255, 255))
            rgb_img.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = rgb_img

        # Salva como PDF
        img.save(caminho_pdf, 'PDF', resolution=100.0, quality=95)
        print(f"    [OK] Imagem convertida para PDF: {os.path.basename(caminho_pdf)}")

        return caminho_pdf

    except Exception as e:
        print(f"    [ERRO] Falha ao converter imagem para PDF: {e}")
        return None

def enviar_documento_autentique_whatsapp(caminho_arquivo, cod_requisicao, nome_paciente, telefone):
    """Envia documento para assinatura via WhatsApp usando Autentique"""
    arquivo_temp = None
    try:
        if not AUTENTIQUE_TOKEN:
            print("    [ERRO] AUTENTIQUE_TOKEN nao configurado no ambiente")
            return None

        if not os.path.exists(caminho_arquivo):
            print(f"    [ERRO] Arquivo não encontrado: {caminho_arquivo}")
            return None

        # Converte imagem para PDF se necessário
        extensao = os.path.splitext(caminho_arquivo)[1].upper()
        if extensao in ['.JPG', '.JPEG', '.PNG']:
            print(f"    [INFO] Detectado arquivo de imagem, convertendo para PDF...")
            caminho_pdf = converter_imagem_para_pdf(caminho_arquivo)
            if not caminho_pdf:
                return None
            arquivo_temp = caminho_pdf  # Marca para deletar depois
        else:
            caminho_pdf = caminho_arquivo

        # Formata telefone para Autentique (precisa do +55)
        if MODO_TESTE:
            telefone_autentique = f"+{_telefone_autentique_teste()}"
            print(f"    [TESTE] Redirecionando Autentique para {telefone_autentique}")
        else:
            telefone_limpo = ''.join(filter(str.isdigit, telefone))
            if telefone_limpo.startswith('55') and len(telefone_limpo) == 13:
                telefone_autentique = f"+{telefone_limpo}"
            elif len(telefone_limpo) == 11:
                telefone_autentique = f"+55{telefone_limpo}"
            else:
                telefone_autentique = f"+{telefone_limpo}"


        nome_documento = f"Requisicao_{cod_requisicao}_Assinatura"

        headers = {"Authorization": f"Bearer {AUTENTIQUE_TOKEN}"}

        variables = {
            "document": {"name": nome_documento},
            "signers": [{
                "name": nome_paciente,
                "phone": telefone_autentique,
                "delivery_method": "DELIVERY_METHOD_WHATSAPP",
                "action": "SIGN"
            }],
            "file": None
        }

        operations = {
            "query": CREATE_DOCUMENT_MUTATION,
            "variables": variables
        }

        file_map = {"0": ["variables.file"]}

        with open(caminho_pdf, 'rb') as pdf_file:
            files = {
                'operations': (None, json.dumps(operations), 'application/json'),
                'map': (None, json.dumps(file_map), 'application/json'),
                '0': (os.path.basename(caminho_pdf), pdf_file, 'application/pdf')
            }

            response = requests.post(
                AUTENTIQUE_API_URL,
                headers=headers,
                files=files,
                timeout=60
            )


            if response.status_code == 200:
                resultado = response.json()

                if 'errors' in resultado:
                    print(f"    [ERRO] Erro na API Autentique:")
                    for erro in resultado['errors']:
                        msg = erro.get('message', 'Erro desconhecido')
                        print(f"      Mensagem: {msg}")

                        # Mostra mais detalhes do erro se houver
                        if 'extensions' in erro:
                            print(f"      Extensions: {erro['extensions']}")
                        if 'path' in erro:
                            print(f"      Path: {erro['path']}")

                        # Mostra o erro completo
                        print(f"      [DEBUG] Erro completo: {json.dumps(erro, indent=2)}")
                    return None

                if 'data' in resultado and 'createDocument' in resultado['data']:
                    doc = resultado['data']['createDocument']
                    print(f"    [OK] Documento enviado! ID: {doc['id']}")
                    print(f"    📱 WhatsApp: {telefone}")

                    # Limpa arquivo temporário se foi criado
                    if arquivo_temp and os.path.exists(arquivo_temp):
                        try:
                            os.remove(arquivo_temp)
                            print(f"    [INFO] Arquivo temporário removido")
                        except:
                            pass

                    return doc

            print(f"    [ERRO] HTTP {response.status_code}: {response.text[:500]}")

            # Limpa arquivo temporário em caso de erro
            if arquivo_temp and os.path.exists(arquivo_temp):
                try:
                    os.remove(arquivo_temp)
                except:
                    pass

            return None

    except Exception as e:
        print(f"    [ERRO] Exceção ao enviar documento: {e}")

        # Limpa arquivo temporário em caso de exceção
        if arquivo_temp and os.path.exists(arquivo_temp):
            try:
                os.remove(arquivo_temp)
            except:
                pass

        return None

def buscar_requisicoes_sem_assinatura(data_inicial, data_final):
    """Busca requisições no banco (APENAS TIPO 16!)"""
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)
        print(f"[OK] Conectado ao banco: {DB_CONFIG['database']}")

        convenio_placeholders = ', '.join(['%s'] * len(CONVENIOS))

        # Query modificada: busca requisições que TÊM tipo 16 MAS NÃO TÊM tipo 15
        query = """
            SELECT
                r.CodRequisicao,
                r.CodPaciente,
                p.NomPaciente,
                ri.NomArquivo,
                ri.Tipo,
                r.IdLocalOrigem,
                COALESCE(NULLIF(TRIM(fi.NomFantasia), ''), NULLIF(TRIM(fi.RazaoSocial), '')) AS NomLocalOrigem,
                r.DtaSolicitacao,
                r.IdConvenio
            FROM requisicao r
            INNER JOIN requisicaoimagem ri ON r.IdRequisicao = ri.IdRequisicao
            LEFT JOIN paciente p ON r.CodPaciente = p.CodPaciente
            LEFT JOIN fatinstituicao fi ON fi.IdInstituicao = r.IdLocalOrigem
            WHERE ri.Tipo = 16
              AND ri.Inativo = 0
              AND NOT EXISTS (
                  SELECT 1
                  FROM requisicaoimagem ri2
                  WHERE ri2.IdRequisicao = r.IdRequisicao
                    AND ri2.Tipo = 15
                    AND ri2.Inativo = 0
              )
              AND r.IdConvenio IN (""" + convenio_placeholders + """)
        """

        params = list(CONVENIOS)

        # Filtra por DtaSolicitacao (DtaImg esta NULL para este tipo)
        if data_inicial and data_final:
            query += " AND DATE(r.DtaSolicitacao) BETWEEN %s AND %s"
            params.extend([data_inicial, data_final])

        query += " ORDER BY r.DtaSolicitacao DESC, r.CodRequisicao"
        query += f" LIMIT {LIMITE_REGISTROS}"

        cursor.execute(query, params)
        resultados = cursor.fetchall()

        if not resultados:
            if data_inicial and data_final:
                print(f"\n[AVISO] Nenhuma requisicao encontrada para o periodo informado!")
                print(f"[INFO] Verifique se existem requisicoes com Tipo 16 nesse periodo")
            else:
                print(f"\n[AVISO] Nenhuma requisicao encontrada para os criterios informados!")

        cursor.close()
        conn.close()

        return resultados

    except mysql.connector.Error as e:
        print(f"[ERRO] Erro MySQL: {e}")
        return []

def buscar_requisicoes_sem_assinatura_por_lista(requisicoes_alvo):
    """Busca requisicoes sem assinatura diretamente pela lista alvo (ignora periodo)."""
    if not requisicoes_alvo:
        return []

    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)
        print(f"[OK] Conectado ao banco: {DB_CONFIG['database']}")

        req_placeholders = ', '.join(['%s'] * len(requisicoes_alvo))

        query = """
            SELECT
                r.CodRequisicao,
                r.CodPaciente,
                p.NomPaciente,
                ri.NomArquivo,
                ri.Tipo,
                r.IdLocalOrigem,
                COALESCE(NULLIF(TRIM(fi.NomFantasia), ''), NULLIF(TRIM(fi.RazaoSocial), '')) AS NomLocalOrigem,
                r.DtaSolicitacao,
                r.IdConvenio
            FROM requisicao r
            INNER JOIN requisicaoimagem ri ON r.IdRequisicao = ri.IdRequisicao
            LEFT JOIN paciente p ON r.CodPaciente = p.CodPaciente
            LEFT JOIN fatinstituicao fi ON fi.IdInstituicao = r.IdLocalOrigem
            WHERE ri.Tipo = 16
              AND ri.Inativo = 0
              AND NOT EXISTS (
                  SELECT 1
                  FROM requisicaoimagem ri2
                  WHERE ri2.IdRequisicao = r.IdRequisicao
                    AND ri2.Tipo = 15
                    AND ri2.Inativo = 0
              )
              AND r.CodRequisicao IN (""" + req_placeholders + """)
            ORDER BY r.DtaSolicitacao DESC, r.CodRequisicao
        """

        params = list(requisicoes_alvo)
        cursor.execute(query, params)
        resultados = cursor.fetchall()

        cursor.close()
        conn.close()
        return resultados
    except mysql.connector.Error as e:
        print(f"[ERRO] Erro MySQL (lista alvo): {e}")
        return []

def buscar_telefones_paciente(cod_paciente):
    """Busca telefones do paciente"""
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)

        query = """
            SELECT NumTelefone
            FROM telefone
            WHERE Origem = 1 AND CodOrigem = %s
        """

        cursor.execute(query, [cod_paciente])
        resultados = cursor.fetchall()

        cursor.close()
        conn.close()

        # Retorna lista de números
        return [r['NumTelefone'] for r in resultados]

    except mysql.connector.Error as e:
        print(f"[ERRO] Erro ao buscar telefones: {e}")
        return []

def criar_tarefas_aplis_selenium(lista_requisicoes):
    """Cria tarefas no Aplis usando Selenium para pacientes sem telefone"""
    if not lista_requisicoes:
        print("[INFO] Nenhuma tarefa para criar no Aplis")
        return

    if not APLIS_USER or not APLIS_PASSWORD:
        print("[ERRO] APLIS_USER/APLIS_PASSWORD nao configurados no ambiente. Nao foi possivel criar tarefas.")
        return

    print(f"\n{'='*80}")
    print(f"[APLIS] CRIACAO DE TAREFAS VIA SELENIUM")
    print(f"{'='*80}")
    print(f"Total de tarefas a criar: {len(lista_requisicoes)}\n")

    options = webdriver.ChromeOptions()
    options.add_argument('--start-maximized')
    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 30)
    tarefas_criadas = 0

    def _tarefa_confirmada():
        """Considera tarefa confirmada quando o modal de edição é fechado."""
        try:
            WebDriverWait(driver, 6).until(
                EC.invisibility_of_element_located((By.XPATH, "//*[@id='_taReq']"))
            )
            return True
        except Exception:
            return False

    try:
        # Login no Aplis
        driver.get(APLIS_URL)
        print("[APLIS] Aguardando carregamento do site...")
        time.sleep(5)

        # Clica no botão de aceitar política ANTES do login
        try:
            print("[APLIS] Clicando no botao de politica...")
            btn_politica = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#divLoginPolitica > div > div.btn > input[type=button]")))
            driver.execute_script("arguments[0].click();", btn_politica)
            time.sleep(2)
            print("[OK] Botao de politica clicado")
        except Exception as e:
            print(f"[AVISO] Botao de politica nao encontrado (pode ja ter sido aceito): {e}")

        print("[APLIS] Realizando login...")
        campo_login = wait.until(EC.visibility_of_element_located((By.XPATH, "//*[@id='login']")))
        driver.execute_script("arguments[0].scrollIntoView(true);", campo_login)
        time.sleep(2)
        campo_login.clear()
        campo_login.send_keys(APLIS_USER)
        time.sleep(2)

        campo_senha = wait.until(EC.visibility_of_element_located((By.XPATH, "//*[@id='senha']")))
        campo_senha.clear()
        campo_senha.send_keys(APLIS_PASSWORD)
        time.sleep(2)
        campo_senha.send_keys(Keys.ENTER)
        time.sleep(5)
        print("[OK] Login realizado com sucesso")

        # Fecha popup/modal DEPOIS do login
        try:
            print("[APLIS] Fechando popup pos-login...")
            btn_fechar_popup = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "body > div:nth-child(63) > div.ui-dialog-titlebar.ui-corner-all.ui-widget-header.ui-helper-clearfix.ui-draggable-handle > button")))
            driver.execute_script("arguments[0].click();", btn_fechar_popup)
            time.sleep(2)
            print("[OK] Popup fechado")
        except Exception as e:
            print(f"[AVISO] Popup pos-login nao encontrado: {e}")

        # Navega para area de tarefas
        print("[APLIS] Navegando para area de tarefas...")
        try:
            header = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[@id='divHeader']/div[1]")))
            driver.execute_script("arguments[0].click();", header)
            time.sleep(3)
        except Exception:
            print("[AVISO] Header nao clicado (continuando)")

        area_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[@id='divAreas']/ul/li[2]/a")))
        driver.execute_script("arguments[0].scrollIntoView(true);", area_btn)
        time.sleep(2)
        driver.execute_script("arguments[0].click();", area_btn)
        time.sleep(3)

        # Muda para nova aba se abriu
        if len(driver.window_handles) > 1:
            driver.switch_to.window(driver.window_handles[-1])

        time.sleep(5)
        print("[OK] Area de tarefas aberta")

        # Funcao auxiliar para clicar no botao Novo
        def clicar_botao_novo():
            """Tenta abrir modal de nova tarefa"""
            try:
                # Tenta executar funcao cmdNova diretamente
                resultado = driver.execute_script("""
                    if (typeof cmdNova === 'function') {
                        cmdNova();
                        return 'EXECUTADO_CMD_NOVA';
                    }

                    // Tenta encontrar botao visivel com texto "Novo"
                    var botoes = document.querySelectorAll('a, button, div, span');
                    for (var i = 0; i < botoes.length; i++) {
                        var btn = botoes[i];
                        var texto = (btn.textContent || btn.innerText || '').trim().toLowerCase();
                        if (texto === 'novo' && btn.offsetWidth > 0 && btn.offsetHeight > 0) {
                            btn.click();
                            return 'CLICADO_BOTAO_NOVO';
                        }
                    }

                    // Tenta por ID ou classe
                    var btn = document.getElementById('a_nov') ||
                             document.querySelector('.nov') ||
                             document.querySelector('[onclick*="cmdNova"]');
                    if (btn) {
                        btn.click();
                        return 'CLICADO_ID_CLASS';
                    }

                    return 'NAO_ENCONTRADO';
                """)

                if 'CLICADO' in str(resultado) or 'EXECUTADO' in str(resultado):
                    time.sleep(2)
                    try:
                        WebDriverWait(driver, 3).until(
                            EC.presence_of_element_located((By.XPATH, "//*[@id='_taReq']"))
                        )
                        return True
                    except TimeoutException:
                        return False

                return False
            except Exception as e:
                print(f"[ERRO] Erro ao clicar botao Novo: {e}")
                return False

        # Cria tarefas para cada requisicao
        for req_info in lista_requisicoes:
            cod_req = req_info['CodRequisicao']
            cod_paciente = req_info['CodPaciente']
            id_convenio = req_info['IdConvenio']

            print(f"\n[TAREFA] Conv {id_convenio} | Req {cod_req} | Paciente {cod_paciente}")

            # Abre modal de nova tarefa
            if not clicar_botao_novo():
                print("  [ERRO] Nao foi possivel abrir modal. Pulando...")
                continue

            time.sleep(2)

            # Preenche campo requisicao
            try:
                campo_req = wait.until(EC.visibility_of_element_located((By.XPATH, "//*[@id='_taReq']")))
                driver.execute_script("arguments[0].scrollIntoView(true);", campo_req)
                time.sleep(1)
                campo_req.clear()
                campo_req.send_keys(cod_req)
                time.sleep(1)
                print("  [OK] Requisicao preenchida")
            except Exception as e:
                print(f"  [ERRO] Erro ao preencher requisicao: {e}")
                continue

            # Clica no botão de tipo (necessário para habilitar dropdown de setor)
            try:
                print("  [INFO] Clicando no botao de tipo...")
                btn_tipo = driver.find_element(By.CSS_SELECTOR, "#_taTpd2")
                driver.execute_script("arguments[0].scrollIntoView(true);", btn_tipo)
                time.sleep(0.5)
                driver.execute_script("arguments[0].click();", btn_tipo)
                time.sleep(1)
                print("  [OK] Botao de tipo clicado")
            except Exception as e:
                print(f"  [AVISO] Erro ao clicar botao de tipo: {e}")

            # Seleciona setor "Admissao"
            try:
                resultado = driver.execute_script("""
                    var dropdown = document.getElementById('_taSet');
                    if (dropdown && dropdown.tagName === 'SELECT') {
                        var options = dropdown.options;
                        for (var i = 0; i < options.length; i++) {
                            var texto = options[i].text.toLowerCase();
                            if (texto.includes('admiss')) {
                                dropdown.selectedIndex = i;
                                dropdown.value = options[i].value;
                                dropdown.dispatchEvent(new Event('change', { bubbles: true }));
                                return 'SETOR_SELECIONADO';
                            }
                        }
                    }
                    return 'SETOR_NAO_ENCONTRADO';
                """)

                if 'SELECIONADO' in str(resultado):
                    print("  [OK] Setor 'Admissao' selecionado")
                else:
                    print("  [AVISO] Setor nao selecionado automaticamente")

                time.sleep(1)
            except Exception as e:
                print(f"  [AVISO] Erro ao selecionar setor: {e}")

            # Preenche mensagem
            try:
                nome_convenio = CONVENIOS_NOMES.get(id_convenio, f"Conv {id_convenio}")
                mensagem = f"PACIENTE SEM TELEFONE - Cadastrar telefone da requisição {cod_req} - Convenio {nome_convenio}"

                resultado = driver.execute_script("""
                    var msg = arguments[0];
                    var textarea = document.getElementById('_taMsg') || document.querySelector('textarea');
                    if (textarea) {
                        textarea.value = msg;
                        textarea.dispatchEvent(new Event('input', { bubbles: true }));
                        textarea.dispatchEvent(new Event('change', { bubbles: true }));
                        return 'MENSAGEM_PREENCHIDA';
                    }
                    return 'TEXTAREA_NAO_ENCONTRADO';
                """, mensagem)

                if 'PREENCHIDA' in str(resultado):
                    print("  [OK] Mensagem preenchida")
                else:
                    print("  [AVISO] Mensagem nao preenchida")

                time.sleep(1)
            except Exception as e:
                print(f"  [AVISO] Erro ao preencher mensagem: {e}")

            # Confirma tarefa - USANDO SELETOR ESPECÍFICO
            try:
                print("  [INFO] Tentando clicar no botao de confirmar...")

                # Primeiro tenta pelo seletor CSS específico fornecido
                try:
                    confirm_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR,
                        "body > div:nth-child(19) > div.ui-dialog-buttonpane.ui-widget-content.ui-helper-clearfix > div > button:nth-child(1) > span.ui-button-icon.ui-icon.ui-icon-check")))
                    driver.execute_script("arguments[0].scrollIntoView(true);", confirm_btn)
                    time.sleep(0.5)
                    driver.execute_script("arguments[0].click();", confirm_btn)
                    print("  [OK] Botao clicado via CSS selector especifico")
                except Exception:
                    # Fallback: tenta clicar no botão pai
                    confirm_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR,
                        "body > div:nth-child(19) > div.ui-dialog-buttonpane.ui-widget-content.ui-helper-clearfix > div > button:nth-child(1)")))
                    driver.execute_script("arguments[0].scrollIntoView(true);", confirm_btn)
                    time.sleep(0.5)
                    driver.execute_script("arguments[0].click();", confirm_btn)
                    print("  [OK] Botao clicado via CSS selector do botao pai")

                time.sleep(1.5)
                if not _tarefa_confirmada():
                    raise Exception("Clique executado, mas modal nao fechou (confirmacao nao detectada)")

                tarefas_criadas += 1
                print("  [OK] Tarefa criada com sucesso!")

            except Exception as e:
                print(f"  [ERRO] Nao foi possivel confirmar tarefa: {e}")
                print(f"  [INFO] Tentando metodo alternativo...")

                # Método alternativo: busca por texto ou classe
                try:
                    confirm_btn = driver.find_element(By.XPATH,
                        "//button[contains(@class,'btn-primary') or contains(@class,'ui-button') and (contains(.,'Salvar') or contains(.,'Confirmar') or contains(.,'OK'))]")
                    driver.execute_script("arguments[0].scrollIntoView(true);", confirm_btn)
                    time.sleep(0.5)
                    driver.execute_script("arguments[0].click();", confirm_btn)

                    time.sleep(1.5)
                    if not _tarefa_confirmada():
                        raise Exception("Metodo alternativo clicou, mas modal nao fechou")

                    tarefas_criadas += 1
                    print("  [OK] Tarefa criada com metodo alternativo!")
                except Exception as e2:
                    print(f"  [ERRO] Metodo alternativo falhou: {e2}")
                    # Tenta fechar modal
                    try:
                        close_btn = driver.find_element(By.XPATH,
                            "//button[contains(.,'Cancelar') or contains(.,'Fechar') or contains(@class,'close')]")
                        driver.execute_script("arguments[0].click();", close_btn)
                        time.sleep(0.5)
                    except Exception:
                        pass

        print(f"\n{'='*80}")
        print(f"[RESUMO] Tarefas criadas: {tarefas_criadas}/{len(lista_requisicoes)}")
        print(f"{'='*80}")

        manter_aberto = os.getenv('MANTER_NAVEGADOR_APLIS', 'false').lower() == 'true'
        if manter_aberto and sys.stdin and sys.stdin.isatty():
            print("\n[APLIS] Navegador permanecera aberto para verificacao...")
            input("Pressione ENTER para fechar o navegador e continuar... ")

    except Exception as e:
        print(f"[ERRO] Erro geral na criacao de tarefas: {e}")
        manter_aberto = os.getenv('MANTER_NAVEGADOR_APLIS', 'false').lower() == 'true'
        if manter_aberto and sys.stdin and sys.stdin.isatty():
            print("\n[APLIS] Navegador permanecera aberto para debug...")
            input("Pressione ENTER para fechar o navegador... ")
    finally:
        try:
            print("[APLIS] Fechando navegador...")
            driver.quit()
            print("[OK] Navegador fechado!")
        except Exception:
            pass

def criar_cliente_s3():
    """Cria cliente S3"""
    return boto3.client(
        's3',
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY,
        region_name=AWS_REGION
    )

def baixar_imagem_s3(s3_client, nome_arquivo, cod_requisicao):
    """Baixa imagem do S3"""
    try:
        prefix = next((p for p in S3_PREFIXOS.keys() if cod_requisicao.startswith(p)), None)
        if not prefix:
            return False

        nome_sem_extensao = os.path.splitext(nome_arquivo)[0]
        s3_folder = S3_PREFIXOS[prefix]
        extensoes = ['.jpg', '.jpeg', '.png', '.pdf', '.JPG', '.JPEG', '.PNG', '.PDF']

        for ext in extensoes:
            s3_key = f"{s3_folder}{nome_sem_extensao}{ext}"
            try:
                s3_client.head_object(Bucket=S3_BUCKET_NAME, Key=s3_key)
                extensao_arquivo = os.path.splitext(s3_key)[1]
                caminho_local = os.path.join(DIRETORIO_IMAGENS, f"{nome_sem_extensao}{extensao_arquivo}")

                # SEMPRE baixa, mesmo que ja exista (para garantir dados atualizados)
                s3_client.download_file(S3_BUCKET_NAME, s3_key, caminho_local)
                print(f"    [OK] Baixado: {nome_sem_extensao}{extensao_arquivo}")
                return True
            except:
                continue

        print(f"    [ERRO] Arquivo nao encontrado no S3: {nome_sem_extensao}")
        return False

    except Exception as e:
        print(f"    [ERRO] Erro ao baixar {nome_arquivo}: {e}")
        return False

def baixar_todas_imagens(requisicoes):
    """Baixa todas as imagens via S3"""
    # Limpa diretorio de imagens antes de começar
    if os.path.exists(DIRETORIO_IMAGENS):
        print(f"\n[LIMPEZA] Removendo arquivos antigos de {DIRETORIO_IMAGENS}...")
        arquivos_removidos = 0
        for arquivo in os.listdir(DIRETORIO_IMAGENS):
            caminho_arquivo = os.path.join(DIRETORIO_IMAGENS, arquivo)
            try:
                if os.path.isfile(caminho_arquivo):
                    os.remove(caminho_arquivo)
                    arquivos_removidos += 1
            except Exception as e:
                print(f"    [AVISO] Nao foi possivel remover {arquivo}: {e}")
        print(f"[OK] {arquivos_removidos} arquivo(s) removido(s)")
    else:
        os.makedirs(DIRETORIO_IMAGENS)

    print(f"\n[DOWNLOAD] Conectando a AWS S3...")
    s3_client = criar_cliente_s3()
    print(f"[OK] Conectado ao bucket: {S3_BUCKET_NAME}")
    print(f"[INFO] Total de requisicoes para baixar: {len(requisicoes)}\n")

    total_baixados = 0
    total_ja_existem = 0
    total_erros = 0

    for idx, req in enumerate(requisicoes, 1):
        cod = req['CodRequisicao']
        nome_arquivo = req['NomArquivo']
        id_convenio = req['IdConvenio']
        tipo_img = req.get('Tipo', 'N/A')

        print(f"  [{idx}/{len(requisicoes)}] Conv {id_convenio} | Tipo {tipo_img} | {cod} ({nome_arquivo})")

        arquivos_existentes = [f for f in os.listdir(DIRETORIO_IMAGENS)
                              if f.startswith(os.path.splitext(nome_arquivo)[0])]

        if baixar_imagem_s3(s3_client, nome_arquivo, cod):
            if len(arquivos_existentes) > 0:
                total_baixados += 1
            else:
                total_ja_existem += 1
        else:
            total_erros += 1

    print(f"\n{'='*80}")
    print(f"[INFO] RESUMO DO DOWNLOAD:")
    print(f"   [OK] Baixados agora: {total_baixados}")
    print(f"   [SKIP] Ja existiam: {total_ja_existem}")
    print(f"   [ERRO] Erros: {total_erros}")
    print(f"{'='*80}\n")

    return total_baixados

def converter_pdf_para_imagem(caminho_pdf):
    """Converte PDF para imagem"""
    try:
        doc = fitz.open(caminho_pdf)
        pagina = doc[0]
        matriz = fitz.Matrix(2.0, 2.0)
        pix = pagina.get_pixmap(matrix=matriz)
        caminho_temp = caminho_pdf.replace('.PDF', '_temp.png').replace('.pdf', '_temp.png')
        pix.save(caminho_temp)
        doc.close()
        return caminho_temp
    except Exception as e:
        print(f"    [ERRO] Falha ao converter PDF: {e}")
        return None

def gerar_texto_vertex_rest(prompt, image_data, mime_type, max_output_tokens=256):
    """Chama Vertex AI Gemini via endpoint REST e retorna texto e finishReason."""
    if not VERTEX_DISPONIVEL or VERTEX_CREDENTIALS is None:
        return None, None

    try:
        # Renova token se necessário
        if not VERTEX_CREDENTIALS.valid:
            VERTEX_CREDENTIALS.refresh(GoogleAuthRequest())

        payload = {
            "contents": [{
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {
                        "inlineData": {
                            "mimeType": mime_type,
                            "data": base64.b64encode(image_data).decode('utf-8')
                        }
                    }
                ]
            }],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": max_output_tokens,
                "thinkingConfig": {"thinkingBudget": 0}
            }
        }

        headers = {
            "Authorization": f"Bearer {VERTEX_CREDENTIALS.token}",
            "Content-Type": "application/json"
        }

        modelos = [VERTEX_MODEL]
        if VERTEX_FALLBACK_MODEL and VERTEX_FALLBACK_MODEL not in modelos:
            modelos.append(VERTEX_FALLBACK_MODEL)

        for idx_modelo, modelo in enumerate(modelos):
            endpoint = (
                f"https://{VERTEX_LOCATION}-aiplatform.googleapis.com/v1/projects/"
                f"{GOOGLE_CLOUD_PROJECT}/locations/{VERTEX_LOCATION}/publishers/google/"
                f"models/{modelo}:generateContent"
            )

            for tentativa in range(1, max(1, VERTEX_MAX_RETRIES) + 1):
                try:
                    response = requests.post(
                        endpoint,
                        headers=headers,
                        json=payload,
                        timeout=max(20, VERTEX_TIMEOUT_SEC)
                    )

                    if response.status_code == 200:
                        body = response.json()
                        candidato = body.get('candidates', [{}])[0]
                        partes = candidato.get('content', {}).get('parts', [])
                        texto = ''.join(p.get('text', '') for p in partes).strip()
                        finish_reason = candidato.get('finishReason', 'SEM_FINISH_REASON')

                        if not texto:
                            print(f"    [AVISO] Vertex retornou sem texto (finishReason={finish_reason})")

                        return texto, finish_reason

                    status = response.status_code
                    erro = f"HTTP {status}: {response.text[:300]}"
                    retryable = status in (408, 429, 500, 502, 503, 504)

                    if retryable and tentativa < max(1, VERTEX_MAX_RETRIES):
                        espera = min(30, VERTEX_RETRY_BASE_SEC * (2 ** (tentativa - 1)))
                        print(f"    [AVISO] Vertex {modelo} tentativa {tentativa} falhou ({status}); retry em {espera:.1f}s")
                        time.sleep(espera)
                        continue

                    print(f"    [ERRO] Vertex {modelo} falhou: {erro}")
                    break

                except requests.exceptions.Timeout:
                    if tentativa < max(1, VERTEX_MAX_RETRIES):
                        espera = min(30, VERTEX_RETRY_BASE_SEC * (2 ** (tentativa - 1)))
                        print(f"    [AVISO] Timeout Vertex {modelo} tentativa {tentativa}; retry em {espera:.1f}s")
                        time.sleep(espera)
                        continue
                    print(f"    [ERRO] Timeout Vertex {modelo} apos {tentativa} tentativa(s)")
                except Exception as e:
                    print(f"    [ERRO] Falha chamada Vertex {modelo}: {e}")
                    break

            if idx_modelo < len(modelos) - 1:
                print(f"    [AVISO] Alternando para modelo fallback: {modelos[idx_modelo + 1]}")

        return None, None
    except Exception as e:
        print(f"    [ERRO] Falha chamada Vertex REST: {e}")
        return None, None

def analisar_assinatura_paciente_vertex(caminho_imagem):
    """Analisa imagem exclusivamente com Vertex AI."""
    arquivo_temp = None
    try:
        if not VERTEX_DISPONIVEL:
            return None

        if not os.path.exists(caminho_imagem):
            return None

        # Converte PDF para imagem se necessário
        if caminho_imagem.upper().endswith('.PDF'):
            caminho_temp = converter_pdf_para_imagem(caminho_imagem)
            if not caminho_temp:
                return None
            arquivo_temp = caminho_temp
            caminho_para_analise = caminho_temp
        else:
            caminho_para_analise = caminho_imagem

        with open(caminho_para_analise, 'rb') as f:
            image_data = f.read()

        mime_type = "image/png" if caminho_para_analise.lower().endswith('.png') else "image/jpeg"

        prompt = (
            "Verifique SOMENTE o campo de assinatura do PACIENTE nesta guia medica. "
            "Ignore assinatura de medico e carimbos. "
            "Responda EXATAMENTE com uma palavra: SIM ou NAO."
        )

        resposta, _ = gerar_texto_vertex_rest(
            prompt,
            image_data,
            mime_type,
            max_output_tokens=256
        )

        if not resposta:
            return None

        resposta = resposta.strip().upper()

        tem_assinatura = "SIM" in resposta

        # Limpa arquivo temporário
        if arquivo_temp and os.path.exists(arquivo_temp):
            try:
                os.remove(arquivo_temp)
            except:
                pass

        return tem_assinatura

    except Exception as e:
        print(f"    [ERRO] Erro ao analisar {os.path.basename(caminho_imagem)}: {e}")

        if arquivo_temp and os.path.exists(arquivo_temp):
            try:
                os.remove(arquivo_temp)
            except:
                pass

        return None

def analisar_todas_requisicoes(requisicoes, arquivos_disponiveis):
    """Analisa todas as requisições com Vertex AI (TIPO 1 E TIPO 16!)"""
    resultados = []

    print(f"\n[IA] Analisando {len(requisicoes)} guias com Inteligencia Artificial...\n")

    for idx, req in enumerate(requisicoes, 1):
        cod_req = req['CodRequisicao']
        nome_arquivo = req['NomArquivo']
        local_origem = (str(req.get('NomLocalOrigem') or '').strip()) or 'Desconhecido'
        id_convenio = req['IdConvenio']
        tipo_img = req.get('Tipo', 'N/A')

        nome_sem_extensao = os.path.splitext(nome_arquivo)[0]
        arquivo_real = arquivos_disponiveis.get(nome_sem_extensao)

        if not arquivo_real:
            for nome in arquivos_disponiveis.values():
                if nome_sem_extensao in nome:
                    arquivo_real = nome
                    break

        if not arquivo_real:
            resultados.append({
                'CodRequisicao': cod_req,
                'TipoImagem': tipo_img,
                'TemAssinatura': 'ARQUIVO_NAO_ENCONTRADO',
                'Motivo': 'DOCUMENTO_FALTANTE',
                'ArquivoAnalisado': nome_arquivo,
                'LocalOrigem': local_origem,
                'IdConvenio': id_convenio
            })
            print(f"  [{idx}/{len(requisicoes)}] Guia {cod_req}: [AVISO] Documento nao encontrado no sistema")
            continue

        caminho = os.path.join(DIRETORIO_IMAGENS, arquivo_real)
        tem_assinatura = analisar_assinatura_paciente_vertex(caminho)

        if tem_assinatura:
            status = "SIM"
            msg = "[OK] Assinatura encontrada"
        elif tem_assinatura is not None:
            status = "NAO"
            msg = "[PENDENTE] Sem assinatura — sera solicitada ao paciente"
        else:
            status = "ERRO"
            msg = "[AVISO] Nao foi possivel analisar a guia"

        print(f"  [{idx}/{len(requisicoes)}] Guia {cod_req}: {msg}")

        if status == 'SIM':
            motivo = 'COM_ASSINATURA'
        elif status == 'NAO':
            motivo = 'SEM_ASSINATURA_PACIENTE'
        else:
            motivo = 'ERRO_ANALISE_ASSINATURA'

        resultados.append({
            'CodRequisicao': cod_req,
            'TipoImagem': tipo_img,
            'TemAssinatura': status,
            'Motivo': motivo,
            'ArquivoAnalisado': arquivo_real,
            'LocalOrigem': local_origem,
            'IdConvenio': id_convenio
        })

    return resultados

def gerar_relatorio(resultados):
    """Gera relatório dos resultados"""
    print("\n" + "="*80)
    print("[INFO] RELATORIO DE ANALISE DE ASSINATURAS")
    print("="*80)

    total = len(resultados)
    com_assinatura = sum(1 for r in resultados if r['TemAssinatura'] == 'SIM')
    sem_assinatura = sum(1 for r in resultados if r['TemAssinatura'] == 'NAO')
    nao_encontrado = sum(1 for r in resultados if r['TemAssinatura'] == 'ARQUIVO_NAO_ENCONTRADO')
    erro = sum(1 for r in resultados if r['TemAssinatura'] == 'ERRO')

    print(f"\n RESUMO GERAL:")
    print(f"   Total analisado: {total}")
    print(f"   [OK] COM assinatura: {com_assinatura} ({com_assinatura/total*100:.1f}%)")
    print(f"   [ERRO] SEM assinatura: {sem_assinatura} ({sem_assinatura/total*100:.1f}%)")
    print(f"   [AVISO] Nao encontrado: {nao_encontrado}")
    if erro > 0:
        print(f"    Erros: {erro}")

    if sem_assinatura > 0:
        print(f"\n[ERRO] REQUISICOES SEM ASSINATURA ({sem_assinatura}):")
        sem_assinatura_lista = [r for r in resultados if r['TemAssinatura'] == 'NAO']
        for idx, r in enumerate(sem_assinatura_lista, 1):
            print(f"  {idx:3d}. {r['CodRequisicao']:15s} | Local: {r['LocalOrigem']:10s} | Arquivo: {r['ArquivoAnalisado']}")

        locais = [r['LocalOrigem'] for r in sem_assinatura_lista]
        contagem = Counter(locais)
        print(f"\n ESTATISTICA POR LOCAL:")
        for local, qtd in contagem.most_common():
            print(f"   {local}: {qtd} ({qtd/sem_assinatura*100:.1f}%)")

    if com_assinatura > 0:
        print(f"\n[OK] REQUISICOES COM ASSINATURA ({com_assinatura}):")
        com_assinatura_lista = [r for r in resultados if r['TemAssinatura'] == 'SIM']
        for idx, r in enumerate(com_assinatura_lista, 1):
            print(f"  {idx:3d}. {r['CodRequisicao']:15s} | Local: {r['LocalOrigem']}")

    print("\n" + "="*80)

    return sem_assinatura_lista if sem_assinatura > 0 else []

def salvar_csv(resultados, arquivo):
    """Salva resultados em CSV"""
    if not os.path.exists(DIRETORIO_RELATORIOS):
        os.makedirs(DIRETORIO_RELATORIOS)

    caminho = os.path.join(DIRETORIO_RELATORIOS, arquivo)

    with open(caminho, 'w', newline='', encoding='utf-8') as f:
        campos = ['CodRequisicao', 'IdConvenio', 'TipoImagem', 'TemAssinatura', 'Motivo', 'ArquivoAnalisado', 'LocalOrigem']
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        writer.writerows(resultados)

    print(f" CSV salvo: {caminho}")

def gerar_relatorio_locais_origem_faturamento(requisicoes, info_periodo=None):
    """Gera relatorios CSV (detalhado e resumo) com locais de origem e periodo analisado."""
    if not os.path.exists(DIRETORIO_RELATORIOS):
        os.makedirs(DIRETORIO_RELATORIOS)

    info_periodo = info_periodo or {}
    periodo_tipo = str(info_periodo.get('tipo', 'nao_informado'))
    periodo_inicio = str(info_periodo.get('data_inicial', ''))
    periodo_fim = str(info_periodo.get('data_final', ''))
    periodo_referencia = str(info_periodo.get('referencia', ''))
    data_execucao = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    arquivo_detalhado = f"relatorio_locais_origem_faturamento_{timestamp}.csv"
    arquivo_resumo = f"relatorio_locais_origem_faturamento_resumo_{timestamp}.csv"
    caminho_detalhado = os.path.join(DIRETORIO_RELATORIOS, arquivo_detalhado)
    caminho_resumo = os.path.join(DIRETORIO_RELATORIOS, arquivo_resumo)

    linhas_detalhadas = []
    for req in requisicoes or []:
        cod_req = req.get('CodRequisicao')
        id_convenio = req.get('IdConvenio')
        id_local_origem = req.get('IdLocalOrigem')
        local_origem = (str(req.get('NomLocalOrigem') or '').strip()) or 'Desconhecido'
        dta_solicitacao = req.get('DtaSolicitacao')

        if hasattr(dta_solicitacao, 'strftime'):
            dta_solicitacao = dta_solicitacao.strftime('%Y-%m-%d %H:%M:%S')
        else:
            dta_solicitacao = str(dta_solicitacao or '')

        linhas_detalhadas.append({
            'DataExecucao': data_execucao,
            'PeriodoTipo': periodo_tipo,
            'PeriodoDataReferencia': periodo_referencia,
            'PeriodoDataInicial': periodo_inicio,
            'PeriodoDataFinal': periodo_fim,
            'CodRequisicao': cod_req,
            'IdConvenio': id_convenio,
            'IdLocalOrigem': id_local_origem,
            'LocalOrigem': local_origem,
            'DtaSolicitacao': dta_solicitacao,
        })

    with open(caminho_detalhado, 'w', newline='', encoding='utf-8') as f:
        campos = [
            'DataExecucao',
            'PeriodoTipo',
            'PeriodoDataReferencia',
            'PeriodoDataInicial',
            'PeriodoDataFinal',
            'CodRequisicao',
            'IdConvenio',
            'IdLocalOrigem',
            'LocalOrigem',
            'DtaSolicitacao'
        ]
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        writer.writerows(linhas_detalhadas)

    contagem_locais = Counter(linha['LocalOrigem'] for linha in linhas_detalhadas)
    total = len(linhas_detalhadas)
    linhas_resumo = []
    for local, qtd in contagem_locais.most_common():
        percentual = (qtd / total * 100) if total else 0
        linhas_resumo.append({
            'DataExecucao': data_execucao,
            'PeriodoTipo': periodo_tipo,
            'PeriodoDataReferencia': periodo_referencia,
            'PeriodoDataInicial': periodo_inicio,
            'PeriodoDataFinal': periodo_fim,
            'LocalOrigem': local,
            'QuantidadeRequisicoes': qtd,
            'Percentual': f"{percentual:.2f}",
        })

    with open(caminho_resumo, 'w', newline='', encoding='utf-8') as f:
        campos = [
            'DataExecucao',
            'PeriodoTipo',
            'PeriodoDataReferencia',
            'PeriodoDataInicial',
            'PeriodoDataFinal',
            'LocalOrigem',
            'QuantidadeRequisicoes',
            'Percentual'
        ]
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        writer.writerows(linhas_resumo)

    print(f"[OK] Relatorio detalhado de locais salvo: {caminho_detalhado}")
    print(f"[OK] Relatorio resumo de locais salvo: {caminho_resumo}")

    return caminho_detalhado, caminho_resumo

def gerar_log_motivos(resultados, requisicoes=None):
    """Gera CSV geral de pendencias sem assinatura com todos os dados disponiveis."""
    if not os.path.exists(DIRETORIO_RELATORIOS):
        os.makedirs(DIRETORIO_RELATORIOS)

    pendencias = [
        r for r in resultados
        if r.get('TemAssinatura') in ('NAO', 'ARQUIVO_NAO_ENCONTRADO', 'ERRO')
    ]

    req_info_map = {}
    if requisicoes:
        req_info_map = {
            r.get('CodRequisicao'): {
                'CodPaciente': r.get('CodPaciente') or '',
                'NomPaciente': r.get('NomPaciente') or '',
                'DtaSolicitacao': r.get('DtaSolicitacao') or '',
                'IdLocalOrigem': r.get('IdLocalOrigem') or ''
            }
            for r in requisicoes
        }

    pendencias_enriquecidas = []
    for p in pendencias:
        item = dict(p)
        cod_req = item.get('CodRequisicao')
        req_info = req_info_map.get(cod_req, {})
        cod_paciente = req_info.get('CodPaciente')

        item['CodPaciente'] = cod_paciente
        item['NomPaciente'] = req_info.get('NomPaciente', '')
        item['DtaSolicitacao'] = req_info.get('DtaSolicitacao', '')
        item['IdLocalOrigem'] = req_info.get('IdLocalOrigem', '')

        if cod_paciente:
            telefones = buscar_telefones_paciente(cod_paciente)
            if telefones:
                item['TemTelefone'] = 'COM_TELEFONE'
                item['Telefones'] = ', '.join(telefones)
            else:
                item['TemTelefone'] = 'SEM_TELEFONE'
                item['Telefones'] = ''
        else:
            item['TemTelefone'] = 'PACIENTE_NAO_ENCONTRADO'
            item['Telefones'] = ''

        pendencias_enriquecidas.append(item)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    arquivo = f"log_motivos_sem_assinatura_{timestamp}.csv"
    caminho = os.path.join(DIRETORIO_RELATORIOS, arquivo)

    with open(caminho, 'w', newline='', encoding='utf-8') as f:
        campos = [
            'CodRequisicao',
            'CodPaciente',
            'NomPaciente',
            'DtaSolicitacao',
            'IdLocalOrigem',
            'LocalOrigem',
            'IdConvenio',
            'TipoImagem',
            'ArquivoAnalisado',
            'TemTelefone',
            'Telefones',
            'Motivo',
            'TemAssinatura'
        ]
        writer = csv.DictWriter(f, fieldnames=campos, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(pendencias_enriquecidas)

    print("\n" + "="*80)
    print("[LOG] MOTIVOS DE REQUISICOES SEM ASSINATURA")
    print("="*80)
    if not pendencias_enriquecidas:
        print("[OK] Nenhuma pendencia encontrada (sem assinatura/documento faltante).")
    else:
        for idx, item in enumerate(pendencias_enriquecidas, 1):
            print(
                f"  {idx:3d}. Req {item['CodRequisicao']} | Motivo: {item['Motivo']} "
                f"| Telefone: {item['TemTelefone']}"
            )
    print(f"\n[OK] Log de motivos salvo: {caminho}")

    return caminho

def salvar_csv_sem_telefone(sem_telefone):
    """Salva CSV dedicado com requisicoes sem telefone para exportacao."""
    if not sem_telefone:
        return None

    if not os.path.exists(DIRETORIO_RELATORIOS):
        os.makedirs(DIRETORIO_RELATORIOS)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    arquivo = f"requisicoes_sem_telefone_{timestamp}.csv"
    caminho = os.path.join(DIRETORIO_RELATORIOS, arquivo)

    linhas = []
    for item in sem_telefone:
        id_convenio = item.get('IdConvenio')
        linhas.append({
            'CodRequisicao': item.get('CodRequisicao'),
            'CodPaciente': item.get('CodPaciente'),
            'IdConvenio': id_convenio,
            'Convenio': CONVENIOS_NOMES.get(id_convenio, f"Conv {id_convenio}"),
        })

    with open(caminho, 'w', newline='', encoding='utf-8') as f:
        campos = ['CodRequisicao', 'CodPaciente', 'IdConvenio', 'Convenio']
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        writer.writerows(linhas)

    print(f"[OK] CSV de requisicoes sem telefone salvo: {caminho}")
    return caminho

def _registrar_sem_telefone_no_skip_list(sem_telefone):
    """Persiste requisicoes sem telefone no arquivo de skip para nao repetirem nas proximas execucoes."""
    if not sem_telefone:
        return

    novos = set()
    existentes = set()

    if os.path.exists(ARQUIVO_REQUISICOES_PROCESSADAS):
        try:
            with open(ARQUIVO_REQUISICOES_PROCESSADAS, 'r', encoding='utf-8') as f:
                for linha in f:
                    cod = _normalizar_cod_requisicao(linha.strip())
                    if cod:
                        existentes.add(cod)
        except Exception:
            pass

    for req in sem_telefone:
        cod = _normalizar_cod_requisicao(req.get('CodRequisicao'))
        if cod and cod not in existentes:
            novos.add(cod)

    if not novos:
        return

    try:
        if not os.path.exists(DIRETORIO_RELATORIOS):
            os.makedirs(DIRETORIO_RELATORIOS)
        with open(ARQUIVO_REQUISICOES_PROCESSADAS, 'a', encoding='utf-8') as f:
            for cod in sorted(novos):
                f.write(cod + '\n')
        print(f"[SKIP] {len(novos)} requisicao(oes) sem telefone adicionada(s) ao skip list — nao voltarao nas proximas execucoes.")
        print(f"[INFO] Para reprocessar, remova as entradas de: {ARQUIVO_REQUISICOES_PROCESSADAS}")
    except Exception as e:
        print(f"[AVISO] Nao foi possivel registrar no skip list: {e}")

def obter_periodo(args):
    """Define período da análise a partir dos argumentos ou modo interativo."""
    if args.diario:
        # Para execucao agendada diaria, processa o dia anterior para evitar dados parciais.
        data_referencia = datetime.now().date() - timedelta(days=1)
        print(f"[OK] Modo diario ativado (D-1): {data_referencia.strftime('%d/%m/%Y')}")
        return data_referencia, data_referencia, {
            'tipo': 'diario',
            'referencia': data_referencia.isoformat(),
            'data_inicial': data_referencia.isoformat(),
            'data_final': data_referencia.isoformat(),
        }

    if args.data_inicial and args.data_final:
        try:
            data_inicial = datetime.strptime(args.data_inicial, "%Y-%m-%d").date()
            data_final = datetime.strptime(args.data_final, "%Y-%m-%d").date()
        except ValueError:
            print("[ERRO] Datas invalidas! Use formato YYYY-MM-DD (ex: 2026-03-30)")
            return None, None, None

        if data_inicial > data_final:
            print("[ERRO] data_inicial nao pode ser maior que data_final")
            return None, None, None

        print(f"[OK] Modo intervalo CLI: {data_inicial.strftime('%d/%m/%Y')} ate {data_final.strftime('%d/%m/%Y')}")
        return data_inicial, data_final, {
            'tipo': 'intervalo',
            'referencia': f"{data_inicial.isoformat()}_{data_final.isoformat()}",
            'data_inicial': data_inicial.isoformat(),
            'data_final': data_final.isoformat(),
        }

    if args.semanal:
        hoje = datetime.now().date()
        data_final = hoje
        data_inicial = hoje - timedelta(days=6)
        print(f"[OK] Modo semanal ativado: {data_inicial.strftime('%d/%m/%Y')} ate {data_final.strftime('%d/%m/%Y')}")
        return data_inicial, data_final, {
            'tipo': 'semanal',
            'referencia': hoje.isoformat(),
            'data_inicial': data_inicial.isoformat(),
            'data_final': data_final.isoformat(),
        }

    if args.mes and args.ano:
        from calendar import monthrange
        data_inicial = datetime(args.ano, args.mes, 1).date()
        ultimo_dia = monthrange(args.ano, args.mes)[1]
        data_final = datetime(args.ano, args.mes, ultimo_dia).date()
        print(f"[OK] Modo CLI mensal: {args.mes:02d}/{args.ano}")
        return data_inicial, data_final, {
            'tipo': 'mensal',
            'referencia': f"{args.ano}-{args.mes:02d}",
            'data_inicial': data_inicial.isoformat(),
            'data_final': data_final.isoformat(),
        }

    data_hoje = datetime.now()
    mes_atual = data_hoje.month
    ano_atual = data_hoje.year

    mes_str = input(f"\nMês (MM/YYYY) ou ENTER para mês atual [{mes_atual:02d}/{ano_atual}]: ").strip()

    if mes_str:
        try:
            mes, ano = mes_str.split('/')
            mes = int(mes)
            ano = int(ano)

            if mes < 1 or mes > 12:
                print("[ERRO] Mês inválido! Use valores entre 01 e 12")
                return None, None, None
        except ValueError:
            print("[ERRO] Formato inválido! Use formato MM/YYYY (ex: 12/2024)")
            return None, None, None
    else:
        mes = mes_atual
        ano = ano_atual

    from calendar import monthrange
    data_inicial = datetime(ano, mes, 1).date()
    ultimo_dia = monthrange(ano, mes)[1]
    data_final = datetime(ano, mes, ultimo_dia).date()
    print(f"[OK] Buscando requisições do mês: {mes:02d}/{ano}")
    return data_inicial, data_final, {
        'tipo': 'mensal',
        'referencia': f"{ano}-{mes:02d}",
        'data_inicial': data_inicial.isoformat(),
        'data_final': data_final.isoformat(),
    }

def parse_args():
    parser = argparse.ArgumentParser(description="Analise de assinaturas com log de motivos")
    parser.add_argument("--semanal", action="store_true", help="Executa para os ultimos 7 dias")
    parser.add_argument("--data-inicial", dest="data_inicial", help="Data inicial no formato YYYY-MM-DD")
    parser.add_argument("--data-final", dest="data_final", help="Data final no formato YYYY-MM-DD")
    parser.add_argument("--diario", action="store_true", help="Executa para o dia anterior (D-1), ideal para rotina diaria")
    parser.add_argument("--mes", type=int, help="Mes da analise (1-12)")
    parser.add_argument("--ano", type=int, help="Ano da analise (YYYY)")
    parser.add_argument(
        "--apenas-log-motivos",
        action="store_true",
        help="Gera apenas o log de motivos (sem fluxo de telefone/WhatsApp/Autentique)"
    )
    parser.add_argument(
        "--somente-requisicoes-arquivo",
        dest="somente_requisicoes_arquivo",
        help="Filtra processamento para as requisicoes presentes no arquivo informado"
    )
    parser.add_argument(
        "--ignorar-periodo-quando-lista",
        action="store_true",
        help="Quando usado com --somente-requisicoes-arquivo, ignora filtro de data e usa a lista alvo como base"
    )
    parser.add_argument(
        "--enviar-lembretes",
        action="store_true",
        help="Envia lembrete de assinatura para pacientes com documento enviado ha mais de 1 dia e ainda nao assinado"
    )
    parser.add_argument(
        "--enviar-resumo-diario",
        action="store_true",
        help="Envia resumo diario do sistema para os numeros monitor configurados"
    )
    parser.add_argument(
        "--forcar-reenvio-aviso",
        action="store_true",
        dest="forcar_reenvio_aviso",
        help="Ignora a janela de 24h e reenvia mesmo para requisicoes que ja receberam aviso hoje"
    )
    parser.add_argument(
        "--gerar-relatorio-locais-origem",
        action="store_true",
        help="Gera apenas relatorio com local de origem de todas as requisicoes retornadas no faturamento"
    )
    return parser.parse_args()

def main():
    print("="*80)
    print("[BUSCA] SISTEMA DE ANALISE DE ASSINATURAS V3 - VERTEX AI")
    print(" Google Cloud (PAGO - SEM LIMITES)")
    print(" Analisa imagens TIPO 16 (Assinatura do Paciente)")
    print("="*80)

    if not VERTEX_DISPONIVEL:
        print("[ERRO] Vertex AI nao inicializou. Execucao interrompida por configuracao 100% Vertex.")
        print("[ERRO] Verifique credencial, projeto, permissao IAM e acesso HTTPS ao endpoint Vertex REST.")
        enviar_evento_umami_assinaturas('assinaturas_falha_vertex_indisponivel')
        return

    args = parse_args()
    enviar_evento_umami_assinaturas('assinaturas_execucao_iniciada', {
        'modo_teste': MODO_TESTE,
        'gerar_relatorio_locais_origem': bool(args.gerar_relatorio_locais_origem),
        'enviar_lembretes': bool(args.enviar_lembretes),
        'enviar_resumo_diario': bool(args.enviar_resumo_diario),
    })

    if args.enviar_resumo_diario:
        enviar_resumo_diario_monitoramento()
        print("\n[OK] Processo de resumo diario concluido!")
        enviar_evento_umami_assinaturas('assinaturas_resumo_diario_concluido')
        return

    # Modo lembrete: só envia lembretes para quem não assinou, sem rodar análise completa
    if args.enviar_lembretes:
        enviar_lembretes_nao_assinados(horas_minimas=24)
        print("\n[OK] Processo de lembretes concluido!")
        enviar_evento_umami_assinaturas('assinaturas_lembretes_concluido')
        return

    alvo = None
    if args.somente_requisicoes_arquivo:
        alvo = carregar_requisicoes_alvo_arquivo(args.somente_requisicoes_arquivo)
        if not alvo:
            print("[ERRO] Nenhuma requisicao alvo valida foi carregada do arquivo informado.")
            return

    usar_lista_como_base = bool(alvo) and bool(args.ignorar_periodo_quando_lista)

    data_inicial = None
    data_final = None
    info_periodo = {
        'tipo': 'nao_informado',
        'referencia': '',
        'data_inicial': '',
        'data_final': '',
    }
    if not usar_lista_como_base:
        data_inicial, data_final, info_periodo = obter_periodo(args)
        if not data_inicial or not data_final:
            return
        print(f"[INFO] Período: {data_inicial.strftime('%d/%m/%Y')} até {data_final.strftime('%d/%m/%Y')}")
    else:
        print("[FATURAMENTO] Modo lista alvo: periodo ignorado, buscando diretamente pelas requisicoes do arquivo.")
        info_periodo = {
            'tipo': 'lista_alvo_sem_periodo',
            'referencia': 'lista_alvo',
            'data_inicial': '',
            'data_final': '',
        }

    print(f"\n[INFO] Buscando requisicoes no banco de dados...")
    if usar_lista_como_base:
        requisicoes = buscar_requisicoes_sem_assinatura_por_lista(alvo)
        print(f"[FATURAMENTO] Encontradas {len(requisicoes)} requisicoes da lista alvo aptas para processamento")
        encontradas = {''.join(ch for ch in str(r.get('CodRequisicao', '')) if ch.isdigit()) for r in requisicoes}
        faltantes = len(alvo - encontradas)
        if faltantes > 0:
            print(f"[FATURAMENTO] Aviso: {faltantes} requisicoes da lista nao entraram por nao atender criterio (tipo 16 sem tipo 15 ou inexistente no banco)")
    else:
        requisicoes = buscar_requisicoes_sem_assinatura(data_inicial, data_final)
        if alvo:
            antes = len(requisicoes)
            requisicoes = [r for r in requisicoes if ''.join(ch for ch in str(r.get('CodRequisicao', '')) if ch.isdigit()) in alvo]
            print(f"[FATURAMENTO] Filtro aplicado: {len(requisicoes)} de {antes} requisicoes no periodo estao na lista alvo")

    if args.gerar_relatorio_locais_origem:
        if not requisicoes:
            print("[AVISO] Nenhuma requisicao encontrada; gerando relatorio vazio de locais de origem para o periodo informado.")
        gerar_relatorio_locais_origem_faturamento(requisicoes or [], info_periodo=info_periodo)
        print("\n[OK] Relatorio de locais de origem gerado com sucesso!")
        enviar_evento_umami_assinaturas('assinaturas_relatorio_locais_origem_gerado', {
            'total_requisicoes': len(requisicoes or []),
            'periodo_tipo': info_periodo.get('tipo', ''),
            'periodo_referencia': info_periodo.get('referencia', ''),
        })
        return

    requisicoes_documentos_enviados = _carregar_requisicoes_documentos_enviados()
    if requisicoes_documentos_enviados and not FATURAMENTO_PERMITIR_REENVIO:
        antes = len(requisicoes)
        requisicoes = [
            r for r in requisicoes
            if _normalizar_cod_requisicao(r.get('CodRequisicao')) not in requisicoes_documentos_enviados
        ]
        ja_enviadas = antes - len(requisicoes)
        if ja_enviadas > 0:
            print(
                f"[FATURAMENTO][FILA] Requisicoes com documento ja enviado removidas antes da selecao do lote: "
                f"{ja_enviadas}"
            )
    elif FATURAMENTO_PERMITIR_REENVIO:
        print("[INFO] Reenvio habilitado: fila considera tambem requisicoes com historico de documento enviado.")

    if MODO_TESTE and FATURAMENTO_TESTE_MAX_REQUISICOES > 0:
        antes = len(requisicoes)
        requisicoes = requisicoes[:FATURAMENTO_TESTE_MAX_REQUISICOES]
        if antes > len(requisicoes):
            print(f"[FATURAMENTO][TESTE] Limitando processamento a {len(requisicoes)} de {antes} requisicoes para validacao")

    if FATURAMENTO_LOTE_ENVIO_REQUISICOES > 0:
        antes = len(requisicoes)
        requisicoes = requisicoes[:FATURAMENTO_LOTE_ENVIO_REQUISICOES]
        if antes > len(requisicoes):
            print(
                f"[FATURAMENTO][LOTE] Execucao controlada ativa: "
                f"processando {len(requisicoes)} de {antes} requisicoes nesta execucao."
            )

    if not requisicoes:
        if usar_lista_como_base:
            print("\n[ERRO] Nenhuma requisicao da lista alvo foi encontrada sem assinatura (Tipo 16 sem Tipo 15)")
        else:
            print("\n[ERRO] Nenhuma requisicao encontrada no periodo especificado")
        enviar_evento_umami_assinaturas('assinaturas_sem_requisicoes', {
            'periodo_tipo': info_periodo.get('tipo', ''),
            'periodo_referencia': info_periodo.get('referencia', ''),
        })
        return EXIT_CODE_NO_DATA

    print(f"[OK] Encontradas: {len(requisicoes)} requisicoes")

    total_baixados = baixar_todas_imagens(requisicoes)

    arquivos_disponiveis = {}
    if os.path.exists(DIRETORIO_IMAGENS):
        for arquivo in os.listdir(DIRETORIO_IMAGENS):
            if os.path.isfile(os.path.join(DIRETORIO_IMAGENS, arquivo)):
                nome_base = os.path.splitext(arquivo)[0]
                arquivos_disponiveis[nome_base] = arquivo

    print(f"[OK] Arquivos disponiveis no diretorio: {len(arquivos_disponiveis)}")

    resultados = analisar_todas_requisicoes(requisicoes, arquivos_disponiveis)

    sem_assinatura = gerar_relatorio(resultados)
    sem_assinatura = _deduplicar_por_requisicao(sem_assinatura, contexto='requisicoes sem assinatura')
    gerar_log_motivos(resultados, requisicoes)
    documentos_enviados_count = 0

    if requisicoes_documentos_enviados and not FATURAMENTO_PERMITIR_REENVIO:
        antes = len(sem_assinatura)
        sem_assinatura = [
            r for r in sem_assinatura
            if _normalizar_cod_requisicao(r.get('CodRequisicao')) not in requisicoes_documentos_enviados
        ]
        ja_enviadas = antes - len(sem_assinatura)
        if ja_enviadas > 0:
            print(
                f"[INFO] Requisicoes ignoradas na verificacao final por ja terem documento enviado em execucoes anteriores: "
                f"{ja_enviadas}"
            )
    elif FATURAMENTO_PERMITIR_REENVIO:
        print("[INFO] Reenvio habilitado: ignorando bloqueio por histórico de documentos já enviados.")

    if args.apenas_log_motivos:
        print("\n[OK] Modo apenas-log-motivos finalizado!")
        return

    # BUSCA TELEFONES DAS REQUISIÇÕES SEM ASSINATURA
    if sem_assinatura:
        print(f"\n{'='*80}")
        print(f"[INFO] BUSCANDO TELEFONES DOS PACIENTES SEM ASSINATURA")
        print(f"{'='*80}\n")

        # Cria dicionários CodRequisicao -> CodPaciente e CodRequisicao -> IdConvenio
        req_paciente_map = {_normalizar_cod_requisicao(r['CodRequisicao']): r['CodPaciente'] for r in requisicoes}
        req_convenio_map = {_normalizar_cod_requisicao(r['CodRequisicao']): r['IdConvenio'] for r in requisicoes}
        req_nome_map = {_normalizar_cod_requisicao(r['CodRequisicao']): (r.get('NomPaciente') or '').strip() for r in requisicoes}
        telefones_override = _carregar_telefones_override()

        telefones_encontrados = []
        sem_telefone = []  # Lista para acumular requisições sem telefone
        req_processadas_telefone = set()

        for req_sem_ass in sem_assinatura:
            cod_req = req_sem_ass['CodRequisicao']
            cod_req_key = _normalizar_cod_requisicao(cod_req)

            # Garante 1 envio por requisicao (sem duplicar para o mesmo paciente).
            if cod_req_key in req_processadas_telefone:
                continue
            req_processadas_telefone.add(cod_req_key)

            cod_paciente = req_paciente_map.get(cod_req_key)
            id_convenio = req_convenio_map.get(cod_req_key)

            telefone_manual = telefones_override.get(cod_req_key)
            telefones = []

            if telefone_manual:
                telefones = [telefone_manual]
                print(f"[INFO] Conv {id_convenio} | Req {cod_req} | Usando telefone manual do painel: {telefone_manual}")
            elif cod_paciente:
                telefones = buscar_telefones_paciente(cod_paciente)

            if telefones:
                if telefone_manual:
                    print(f"[OK] Conv {id_convenio} | Req {cod_req} | Telefone manual aplicado")
                else:
                    print(f"[OK] Conv {id_convenio} | Req {cod_req} | Paciente {cod_paciente} | Telefones: {', '.join(telefones)}")
                telefones_encontrados.append({
                    'CodRequisicao': cod_req,
                    'IdConvenio': id_convenio,
                    'CodPaciente': cod_paciente or '',
                    'Telefones': ', '.join(telefones),
                    'LocalOrigem': req_sem_ass['LocalOrigem']
                })
            elif cod_paciente:
                print(f"[AVISO] Conv {id_convenio} | Req {cod_req} | Paciente {cod_paciente} | SEM TELEFONE cadastrado")
                # Adiciona a lista para criar tarefa depois
                sem_telefone.append({
                    'CodRequisicao': cod_req,
                    'CodPaciente': cod_paciente,
                    'IdConvenio': id_convenio
                })
            else:
                print(f"[ERRO] Conv {id_convenio} | Req {cod_req} | SEM CodPaciente")

        # Cria tarefas no Aplis para pacientes sem telefone
        if sem_telefone:
            print(f"\n{'='*80}")
            print(f"[INFO] PACIENTES SEM TELEFONE CADASTRADO")
            print(f"{'='*80}")
            print(f"Total: {len(sem_telefone)} paciente(s)\n")

            for req in sem_telefone:
                print(f"  Conv {req['IdConvenio']} | Req {req['CodRequisicao']} | Paciente {req['CodPaciente']}")

            salvar_csv_sem_telefone(sem_telefone)
            if FATURAMENTO_PERSISTIR_SEM_TELEFONE_SKIP:
                _registrar_sem_telefone_no_skip_list(sem_telefone)
            else:
                print("[INFO] Persistencia automatica no skip-list desativada (FATURAMENTO_PERSISTIR_SEM_TELEFONE_SKIP=false).")
                print("[INFO] As requisicoes sem telefone permanecerao elegiveis para novas tentativas apos correcao cadastral.")

            if CRIAR_TAREFA_APLIS:
                print("\n[INFO] Configuracao ativa: criar tarefa no Aplis automaticamente.")
                criar_tarefas_aplis_selenium(sem_telefone)
            else:
                print("[INFO] Criacao de tarefas no Aplis desativada. Seguindo com fluxo de WhatsApp.")

        # Salva CSV com telefones
        if telefones_encontrados:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            arquivo_telefones = f"telefones_sem_assinatura_{timestamp}.csv"

            if not os.path.exists(DIRETORIO_RELATORIOS):
                os.makedirs(DIRETORIO_RELATORIOS)

            caminho = os.path.join(DIRETORIO_RELATORIOS, arquivo_telefones)

            with open(caminho, 'w', newline='', encoding='utf-8') as f:
                campos = ['CodRequisicao', 'IdConvenio', 'CodPaciente', 'Telefones', 'LocalOrigem']
                writer = csv.DictWriter(f, fieldnames=campos)
                writer.writeheader()
                writer.writerows(telefones_encontrados)

            print(f"\n[OK] CSV com telefones salvo: {caminho}")
            print(f"Total de pacientes com telefone: {len(telefones_encontrados)}")

        # ENVIO DE DOCUMENTOS VIA AUTENTIQUE (PRODUÇÃO)
        if telefones_encontrados:
            print(f"\n{'='*80}")
            print(f"[AUTENTIQUE] ENVIO DE DOCUMENTOS PARA ASSINATURA VIA WHATSAPP - PRODUCAO")
            print(f"{'='*80}")
            print(f"Total de pacientes com telefone: {len(telefones_encontrados)}")
            print(f"Total de requisicoes sem assinatura: {len(sem_assinatura)}\n")

            documentos_enviados = []

            # Envia mensagem informativa e documento Autentique para CADA paciente
            print(f"\n[AUTENTIQUE] Processando envio para {len(telefones_encontrados)} paciente(s)...")

            for idx, info_tel in enumerate(telefones_encontrados, 1):
                cod_req = info_tel['CodRequisicao']
                cod_req_key = _normalizar_cod_requisicao(cod_req)
                cod_paciente = info_tel['CodPaciente']
                id_convenio = info_tel['IdConvenio']
                telefones_str = info_tel['Telefones']
                nome_convenio = CONVENIOS_NOMES.get(id_convenio, f"Conv {id_convenio}")

                # Pega o primeiro telefone da lista
                telefone = telefones_str.split(',')[0].strip()
                telefone_limpo = _normalizar_telefone_whatsapp(telefone)

                if not telefone_limpo:
                    print(f"  [AVISO] Telefone invalido para Req {cod_req}: '{telefone}'. Envio nao realizado.")
                    _registrar_log_wa(
                        telefone_original=telefone,
                        telefone_destino='',
                        status='TELEFONE_INVALIDO',
                        mensagem=f"Req {cod_req} sem envio por telefone invalido",
                        erro='telefone_invalido_ou_incompleto',
                    )
                    continue

                if TELEFONES_BLOQUEADOS_ENV:
                    tel_nacional = telefone_limpo[2:] if telefone_limpo.startswith('55') else telefone_limpo
                    if telefone_limpo in TELEFONES_BLOQUEADOS_ENV or tel_nacional in TELEFONES_BLOQUEADOS_ENV:
                        print(f"  [INFO] Req {cod_req} bloqueada por telefone na lista de excecao: {telefone_limpo}")
                        _registrar_log_wa(
                            telefone_original=telefone,
                            telefone_destino=telefone_limpo,
                            status='TELEFONE_BLOQUEADO',
                            mensagem=f"Req {cod_req} sem envio por telefone na lista de excecao",
                            erro='telefone_bloqueado_por_lista',
                        )
                        continue

                print(f"\n[{idx}/{len(telefones_encontrados)}] Req {cod_req} | Conv {id_convenio} | Tel: {telefone_limpo}")

                # Busca nome do paciente
                nome_paciente_completo = req_nome_map.get(cod_req_key) or 'Paciente'
                primeiro_nome = _primeiro_nome_paciente(nome_paciente_completo)
                local_origem = info_tel.get('LocalOrigem') or nome_convenio

                mensagem_aviso = f"""Olá, Sr.(a) *{primeiro_nome}*, tudo bem?

Aqui é a *Flávia*, do *Laboratório LAB*. Recebemos sua amostra para realização do exame encaminhada pela *{local_origem}*.

Identificamos que a guia do convênio foi enviada sem a sua assinatura, uma exigência do convênio para darmos continuidade ao processo.

Para facilitar, iremos enviar um link pelo WhatsApp, via plataforma segura *(Autentique)*, onde você poderá assinar digitalmente de forma rápida e simples.

Ficamos à disposição para qualquer dúvida.
*Laboratório LAB*"""

                if _confirmacao_enviada_recente(cod_req, telefone_limpo, janela_horas=JANELA_REENVIO_HORAS) and not args.forcar_reenvio_aviso:
                    if MODO_TESTE:
                        print(f"  [TESTE] Envio recente detectado para Req {cod_req}, reenviando para validacao.")
                    else:
                        print(f"  [SKIP] Envio recente ja realizado para Req {cod_req} (janela {JANELA_REENVIO_HORAS}h).")
                        print("  [INFO] Req pulada nesta execucao para evitar repeticao; seguiremos para as proximas.")
                        continue

                # Envia mensagem informativa
                if enviar_mensagem_waha(telefone_limpo, mensagem_aviso):
                    _registrar_log_wa(
                        telefone_original=telefone_limpo,
                        telefone_destino=telefone_limpo,
                        status='AVISO_ASSINATURA',
                        mensagem=f"REQ_AVISO:{cod_req}",
                    )

                # Busca arquivo e envia ao Autentique diretamente
                req_info_aut = next((r for r in sem_assinatura if _normalizar_cod_requisicao(r.get('CodRequisicao')) == cod_req_key), None)
                if not req_info_aut:
                    print(f"  [ERRO] Informacao do arquivo nao encontrada para Req {cod_req}")
                    continue

                arquivo_aut = req_info_aut.get('ArquivoAnalisado', '')
                caminho_arquivo_aut = os.path.join(DIRETORIO_IMAGENS, arquivo_aut) if arquivo_aut else None

                if caminho_arquivo_aut and os.path.exists(caminho_arquivo_aut):
                    doc = enviar_documento_autentique_whatsapp(
                        caminho_arquivo=caminho_arquivo_aut,
                        cod_requisicao=cod_req,
                        nome_paciente=nome_paciente_completo,
                        telefone=telefone_limpo
                    )

                    if doc:
                        documentos_enviados.append({
                            'CodRequisicao': cod_req,
                            'IdConvenio': id_convenio,
                            'DocumentoID': doc['id'],
                            'Telefone': telefone_limpo,
                            'NomPaciente': nome_paciente_completo,
                            'created_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
                        })
                        nome_convenio_s = CONVENIOS_NOMES.get(id_convenio, f"Conv {id_convenio}")
                        mensagem_sucesso = f"""✅ *Documento Enviado com Sucesso!*

Olá, Sr(a). *{primeiro_nome}*

O link de assinatura digital foi enviado pelo *Autentique*.

Você irá assinar a *guia de atendimento dos seus exames* referente à requisição abaixo.

📋 *Requisição:* {cod_req}
🏛️ *Convênio:* {nome_convenio_s}

📱 Você receberá o link em instantes via WhatsApp.

👉 *Importante:* Clique no link e assine o documento para finalizar o processo.

Agradecemos pela colaboração!

*Laboratório LAB* - Estamos à disposição. 🏥"""
                        enviar_mensagem_waha(telefone_limpo, mensagem_sucesso)
                        print(f"  [OK] Documento Autentique enviado para {telefone_limpo} (Req {cod_req})")
                        time.sleep(2)
                    else:
                        mensagem_erro = f"""❌ *Prezado(a) {primeiro_nome}*

Ocorreu um erro técnico ao tentar enviar seu documento de assinatura.

📋 *Requisição:* {cod_req}

🔧 Nossa equipe técnica já foi notificada e estamos trabalhando para resolver.

📞 Por favor, entre em contato com o *Laboratório LAB* para mais informações.

Pedimos desculpas pelo transtorno e agradecemos a compreensão."""
                        enviar_mensagem_waha(telefone_limpo, mensagem_erro)
                        print(f"  [ERRO] Falha ao enviar documento Autentique para Req {cod_req}")
                else:
                    print(f"  [ERRO] Arquivo nao encontrado para Req {cod_req}")
                    mensagem_erro = f"""❌ *Prezado(a) {primeiro_nome}*

O arquivo da sua requisição não foi localizado em nosso sistema.

📋 *Requisição:* {cod_req}

🔧 Nossa equipe técnica já foi notificada.

📞 Por favor, entre em contato com o *Laboratório LAB* para verificarmos o ocorrido.

Pedimos desculpas pelo transtorno."""
                    enviar_mensagem_waha(telefone_limpo, mensagem_erro)


            # Salva CSV com documentos enviados
            if documentos_enviados:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                arquivo_docs = f"documentos_autentique_producao_{timestamp}.csv"

                caminho = os.path.join(DIRETORIO_RELATORIOS, arquivo_docs)

                with open(caminho, 'w', newline='', encoding='utf-8') as f:
                    campos = ['CodRequisicao', 'IdConvenio', 'DocumentoID', 'Telefone', 'NomPaciente', 'created_at']
                    writer = csv.DictWriter(f, fieldnames=campos)
                    writer.writeheader()
                    writer.writerows(documentos_enviados)

                print(f"\n{'='*80}")
                print(f"[OK] CSV com documentos enviados salvo: {caminho}")
                print(f"[OK] Total de documentos enviados: {len(documentos_enviados)}")
                print(f"{'='*80}\n")
                documentos_enviados_count = len(documentos_enviados)
            else:
                print(f"\n[INFO] Nenhum documento foi enviado (nenhuma confirmacao recebida)")

    print("\n[OK] Processo concluido!")
    enviar_evento_umami_assinaturas('assinaturas_execucao_concluida', {
        'total_requisicoes': len(requisicoes),
        'total_sem_assinatura': len(sem_assinatura),
        'total_documentos_enviados': documentos_enviados_count,
        'periodo_tipo': info_periodo.get('tipo', ''),
        'periodo_referencia': info_periodo.get('referencia', ''),
    })

if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except Exception as e:
        print(f"[ERRO] Execução falhou: {e}")
        try:
            enviar_evento_umami_assinaturas('assinaturas_execucao_erro', {'erro': str(e)})
        except Exception as ee:
            print(f"[UMAMI] Falha ao enviar evento de erro: {ee}")
        raise