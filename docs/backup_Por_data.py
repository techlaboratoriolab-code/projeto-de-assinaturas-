import argparse
import requests
import json
import csv
import os
from datetime import datetime, time
from pathlib import Path
import mimetypes
import google.generativeai as genai
from dotenv import load_dotenv

# Carrega variáveis do .env (busca na pasta do script e na pasta pai)
_script_dir = Path(__file__).resolve().parent
load_dotenv(_script_dir.parent / '.env', override=False)
load_dotenv(_script_dir / '.env', override=False)
# --- CONFIGURAÇÕES ---
WAHA_API_URL = os.getenv('WAHA_URL', 'https://waha.ngrok.dev')
WAHA_API_KEY = os.getenv('WAHA_API_KEY', 'laboratorio-lab')
SESSION_NAME = os.getenv('WAHA_SESSION', 'atendimento')
MEU_NOME = "Eu (atendimento)"
PASTA_SAIDA = os.getenv('PASTA_HISTORICOS_WHATSAPP', str(_script_dir.parent / 'historicos_whatsapp'))
PASTA_MIDIA = os.getenv('PASTA_MIDIA_WHATSAPP', str(_script_dir.parent / 'midia_whatsapp'))
# GOOGLE_APPLICATION_CREDENTIALS carregado pelo dotenv
try:
    genai.configure()
    print("✓ Google Generative AI configurado com sucesso")
except Exception as e:
    print(f"⚠️ Erro ao configurar Google Generative AI: {e}")
_umami_enabled_env = os.getenv('UMAMI_ENABLED')
if _umami_enabled_env is None:
    UMAMI_ENABLED = True
else:
    UMAMI_ENABLED = _umami_enabled_env.strip().lower() == 'true'
UMAMI_URL = os.getenv('UMAMI_URL', 'https://umamilab.ngrok.dev').rstrip('/')
UMAMI_WEBSITE_ID = os.getenv('UMAMI_WEBSITE_ID', 'd10aa39d-ed40-4a69-8810-7fe9668d7eea')
UMAMI_HOSTNAME = os.getenv('UMAMI_HOSTNAME', 'waha-backup-diario.local')
UMAMI_EVENT_URL = os.getenv('UMAMI_EVENT_URL', '/backup-whatsapp')
LIMITE_BUSCA_CHATS = 1000
LIMITE_MENSAGENS_POR_CHAT = 250
# ----------------------------------------------------
# ==============================================================================
# CLASSE DE CONEXÃO E AUTENTICAÇÃO WAHA
# ==============================================================================
class WAHAConnector:
    def __init__(self, waha_url: str, session: str = "default", api_key: str = ""):
        """
        Inicializa a conexão com WAHA
        """
        self.waha_url = waha_url.rstrip('/')
        self.session = session
        self.headers = {'Content-Type': 'application/json'}

        # Adiciona API Key nos headers se fornecida
        if api_key:
            self.headers['X-Api-Key'] = api_key

    def test_connection(self) -> bool:
        """Testa conexão com WAHA"""
        try:
            response = requests.get(
                f"{self.waha_url}/api/version",
                headers=self.headers,
                timeout=10
            )
            if response.status_code == 200:
                version_info = response.json()
                print(f"✓ Conectado ao WAHA {version_info.get('version', 'N/A')}")
                return True
            else:
                print(f"✗ Erro na conexão: status {response.status_code}")
                if response.status_code == 401:
                    print("   -> 🚨 Autenticação Falhou (401). Verifique a WAHA_API_KEY.")
                return False
        except Exception as e:
            print(f"✗ Erro de conexão: {e}")
            return False

    def test_session(self) -> bool:
        """Verifica se a sessão está ativa"""
        try:
            response = requests.get(
                f"{self.waha_url}/api/sessions",
                headers=self.headers,
                timeout=10
            )
            if response.status_code == 200:
                sessions = response.json()
                found = False
                for session in sessions:
                    if session.get('name') == self.session:
                        found = True
                        status = session.get('status', 'UNKNOWN')
                        if status == 'WORKING':
                            print(f"✓ Sessão '{self.session}' está ativa e conectada")
                            return True
                        else:
                            print(f"✗ Sessão '{self.session}' com status: {status}")
                            print("   -> Por favor, escaneie o QR Code no WAHA")
                            return False
                if not found:
                    print(f"✗ Sessão '{self.session}' não encontrada")
                    print("   -> Verifique se o nome da sessão está correto")
                return False
            else:
                print(f"✗ Erro ao verificar sessões: status {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ Erro ao verificar sessão: {e}")
            return False

    def verify_authentication(self) -> bool:
        """
        Executa verificação completa de autenticação
        Retorna True se tudo estiver OK
        """
        print("\n" + "="*60)
        print("VERIFICANDO AUTENTICAÇÃO E CONEXÃO COM WAHA")
        print("="*60)

        # Testa conexão básica
        if not self.test_connection():
            print("\n❌ Falha na conexão com WAHA")
            print("   -> Verifique se o WAHA está rodando")
            print(f"   -> URL configurada: {self.waha_url}")
            return False

        # Testa sessão do WhatsApp
        if not self.test_session():
            print("\n❌ Sessão do WhatsApp não está ativa")
            print(f"   -> Sessão configurada: {self.session}")
            print("   -> Acesse o WAHA e escaneie o QR Code")
            return False

        print("\n✅ Autenticação verificada com sucesso!")
        print("="*60)
        return True
# ==============================================================================
# FUNÇÕES DE PROCESSAMENTO DE MÍDIA COM GEMINI
# ==============================================================================

def transcrever_audio_simples(caminho_audio):
    """
    Transcreve áudio usando Gemini 2.5 Flash
    Retorna dict com: {'sucesso': bool, 'transcricao': str, 'erro': str}
    """
    try:
        if not os.path.exists(caminho_audio):
            return {
                'sucesso': False,
                'transcricao': '',
                'erro': 'Arquivo não encontrado'
            }

        # Upload do arquivo de áudio para o Gemini
        audio_file = genai.upload_file(caminho_audio)

        # Usa o modelo Gemini 2.5 Flash
        model = genai.GenerativeModel('models/gemini-2.5-flash')

        # Prompt para transcrição
        prompt = """
        Transcreva este áudio com precisão, mantendo a pontuação adequada.

        Contexto: Este é um atendimento de laboratório de análises clínicas via WhatsApp.
        Termos comuns esperados: hemograma, glicemia, colesterol, agendamento, jejum, resultado, convênio.

        Forneça apenas a transcrição do áudio sem adicionar comentários ou análises.
        """

        response = model.generate_content([prompt, audio_file])
        transcricao = response.text.strip()

        # Remove o arquivo do Gemini após processar
        audio_file.delete()

        return {
            'sucesso': True,
            'transcricao': transcricao,
            'erro': ''
        }

    except Exception as e:
        return {
            'sucesso': False,
            'transcricao': '',
            'erro': str(e)
        }

def analisar_imagem_simples(caminho_imagem):
    """
    Analisa imagem usando Gemini 2.5 Flash
    Retorna dict com: {'sucesso': bool, 'analise': str, 'erro': str}
    """
    try:
        if not os.path.exists(caminho_imagem):
            return {
                'sucesso': False,
                'analise': '',
                'erro': 'Arquivo não encontrado'
            }

        # Upload da imagem para o Gemini
        image_file = genai.upload_file(caminho_imagem)

        # Usa o modelo Gemini 2.5 Flash
        model = genai.GenerativeModel('models/gemini-2.5-flash')

        # Prompt para análise de imagem
        prompt = """
        Analise esta imagem considerando um contexto de atendimento de laboratório de análises clínicas.

        Identifique e descreva:
        - Tipo de documento (pedido médico, receita, comprovante, carteirinha, resultado de exame, etc)
        - Informações relevantes (datas, nome do médico, assinatura/carimbo, dados do paciente)
        - Qualquer detalhe importante para o contexto de atendimento

        Se for um pedido médico com checkboxes ou campos de marcação (X, ✓, bolinhas preenchidas, etc):
        - Liste APENAS os itens que estão MARCADOS/ASSINALADOS
        - NÃO liste itens que aparecem no formulário mas não estão marcados
        - Isso inclui exames, locais de coleta, indicações clínicas e informes clínicos marcados
        - Se não houver nenhuma marcação visível, informe isso explicitamente

        Seja objetivo e claro na descrição.
        """

        response = model.generate_content([prompt, image_file])
        analise = response.text.strip()

        # Remove o arquivo do Gemini após processar
        image_file.delete()

        return {
            'sucesso': True,
            'analise': analise,
            'erro': ''
        }

    except Exception as e:
        return {
            'sucesso': False,
            'analise': '',
            'erro': str(e)
        }

def baixar_midia(msg, chat_id, target_date, headers):
    """
    Baixa arquivo de mídia de uma mensagem do WhatsApp via WAHA API
    Retorna o caminho do arquivo salvo ou None se falhar
    """
    try:
        msg_id = msg.get('id', {}).get('id', '')
        if not msg_id:
            return None

        # Cria pasta de mídia se não existir
        data_formatada = target_date.strftime('%Y-%m-%d')
        pasta_dia = os.path.join(PASTA_MIDIA, data_formatada, chat_id)
        os.makedirs(pasta_dia, exist_ok=True)

        # Endpoint para baixar mídia
        endpoint = f"{WAHA_API_URL}/api/{SESSION_NAME}/chats/{chat_id}/messages/{msg_id}/media"

        response = requests.get(endpoint, headers=headers, timeout=60)
        response.raise_for_status()

        # Determina a extensão do arquivo baseado no tipo de mídia
        mime_type = msg.get('mimetype', '')
        extensoes = {
            'audio/ogg': '.ogg',
            'audio/mpeg': '.mp3',
            'audio/mp4': '.m4a',
            'audio/wav': '.wav',
            'image/jpeg': '.jpg',
            'image/png': '.png',
            'image/gif': '.gif',
            'image/webp': '.webp'
        }
        extensao = extensoes.get(mime_type, '.bin')

        # Nome do arquivo
        nome_arquivo = f"{chat_id}_{msg_id}{extensao}"
        caminho_completo = os.path.join(pasta_dia, nome_arquivo)

        # Salva o arquivo
        with open(caminho_completo, 'wb') as f:
            f.write(response.content)

        return caminho_completo

    except Exception as e:
        print(f"      ⚠️ Erro ao baixar mídia: {e}")
        return None

def get_active_chats_for_date(target_date, headers):
    """Busca todos os chats e retorna os que tiveram atividade na data especificada."""
    print(f"\nBuscando conversas ativas para o dia {target_date.strftime('%d/%m/%Y')}...")
    endpoint = f"{WAHA_API_URL}/api/{SESSION_NAME}/chats/overview"
    params = {"limit": LIMITE_BUSCA_CHATS}
    active_chats = []
    try:
        response = requests.get(endpoint, params=params, headers=headers, timeout=120)
        response.raise_for_status()
        all_chats = response.json()
        start_of_day = datetime.combine(target_date, time.min)
        end_of_day = datetime.combine(target_date, time.max)
        for chat in all_chats:
            last_message = chat.get('lastMessage')
            if last_message and last_message.get('timestamp'):
                # Converte o timestamp para datetime
                last_msg_ts = datetime.fromtimestamp(int(last_message['timestamp']))
                # Verifica se a última mensagem ocorreu no dia alvo
                if start_of_day <= last_msg_ts <= end_of_day:
                    active_chats.append(chat['id'])
        print(f"-> Encontradas {len(active_chats)} conversas ativas.")
        return active_chats
    except requests.exceptions.RequestException as e:
        print(f"❌ Erro ao buscar a lista de conversas: {e}")
        return []


def parse_args():
    parser = argparse.ArgumentParser(
        description="Executa backup do WhatsApp para uma data especifica ou automaticamente para o dia atual."
    )
    parser.add_argument(
        '--data',
        help='Data no formato DD/MM/AAAA. Se omitida, usa a data atual no modo automatico.'
    )
    parser.add_argument(
        '--modo',
        choices=['automatico', 'manual'],
        default='automatico',
        help='Modo automatico usa a data atual. Modo manual solicita a data se --data nao for informado.'
    )
    return parser.parse_args()


def resolve_target_date(args):
    if args.data:
        try:
            return datetime.strptime(args.data, '%d/%m/%Y')
        except ValueError as exc:
            raise ValueError('Data invalida. Use o formato DD/MM/AAAA.') from exc

    if args.modo == 'manual':
        while True:
            data_input = input("\nDigite a data para o backup (formato DD/MM/AAAA): ").strip()
            try:
                return datetime.strptime(data_input, '%d/%m/%Y')
            except ValueError:
                print("❌ Data inválida. Use o formato DD/MM/AAAA (ex: 16/04/2026).")

    return datetime.now()


def enviar_evento_umami(nome_evento, dados=None):
    if not UMAMI_ENABLED:
        return

    if not UMAMI_URL or not UMAMI_WEBSITE_ID or not UMAMI_HOSTNAME:
        print("⚠️ Umami habilitado, mas faltam configuracoes obrigatorias.")
        return

    payload = {
        'type': 'event',
        'payload': {
            'website': UMAMI_WEBSITE_ID,
            'hostname': UMAMI_HOSTNAME,
            'screen': '1920x1080',
            'language': 'pt-BR',
            'url': UMAMI_EVENT_URL,
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
            f"{UMAMI_URL}/api/send",
            json=payload,
            headers=headers,
            timeout=15
        )
        response.raise_for_status()
        print(f"📈 Evento Umami enviado: {nome_evento}")
    except Exception as e:
        print(f"⚠️ Falha ao enviar evento Umami: {e}")

def fetch_and_write_messages(chat_id, target_date, csv_writer, headers):
    """Baixa o histórico, processa mídias com Gemini e escreve no CSV."""
    print(f"  - Processando chat: {chat_id}")
    endpoint = f"{WAHA_API_URL}/api/{SESSION_NAME}/chats/{chat_id}/messages"
    params = {"limit": LIMITE_MENSAGENS_POR_CHAT}
    try:
        response = requests.get(endpoint, params=params, headers=headers, timeout=120)
        response.raise_for_status()
        all_messages = response.json()

        messages_for_day = []
        start_of_day = datetime.combine(target_date, time.min)
        end_of_day = datetime.combine(target_date, time.max)

        for msg in all_messages:
            msg_ts_value = msg.get('timestamp')
            if msg_ts_value:
                msg_ts = datetime.fromtimestamp(int(msg_ts_value))
                if start_of_day <= msg_ts <= end_of_day:
                    messages_for_day.append(msg)

        if not messages_for_day:
            print(f"    -> Nenhuma mensagem encontrada neste dia para {chat_id}.")
            return

        # Ordena as mensagens por timestamp
        messages_for_day.sort(key=lambda m: m.get('timestamp'))

        # Contadores de processamento
        audios_processados = 0
        imagens_processadas = 0

        for msg in messages_for_day:
            remetente = MEU_NOME if msg.get('fromMe') else msg.get('from', 'Desconhecido')

            corpo = ""
            tipo_midia = ""
            caminho_midia = ""

            if msg.get('hasMedia'):
                mime_type = msg.get('mimetype', '').lower()

                # Identifica se é áudio ou imagem
                if mime_type.startswith('audio/'):
                    tipo_midia = "audio"
                    print(f"    🎵 Baixando e transcrevendo áudio...")

                    # Baixa o arquivo de áudio
                    caminho_midia = baixar_midia(msg, chat_id, target_date, headers)

                    if caminho_midia:
                        # Transcreve o áudio usando Gemini
                        resultado = transcrever_audio_simples(caminho_midia)

                        if resultado['sucesso']:
                            corpo = f"[ÁUDIO TRANSCRITO]: {resultado['transcricao']}"
                            audios_processados += 1
                            print(f"      ✓ Áudio transcrito com sucesso")
                        else:
                            corpo = f"[ÁUDIO] (Erro: {resultado['erro']})"
                            print(f"      ⚠️ Erro na transcrição: {resultado['erro']}")
                    else:
                        corpo = "[ÁUDIO] (Erro ao baixar)"

                elif mime_type.startswith('image/'):
                    tipo_midia = "imagem"
                    print(f"    🖼️  Baixando e analisando imagem...")

                    # Baixa o arquivo de imagem
                    caminho_midia = baixar_midia(msg, chat_id, target_date, headers)

                    if caminho_midia:
                        # Analisa a imagem usando Gemini
                        resultado = analisar_imagem_simples(caminho_midia)

                        if resultado['sucesso']:
                            corpo = f"[IMAGEM]: {resultado['analise']}"
                            imagens_processadas += 1
                            print(f"      ✓ Imagem analisada com sucesso")
                        else:
                            corpo = f"[IMAGEM] (Erro: {resultado['erro']})"
                            print(f"      ⚠️ Erro na análise: {resultado['erro']}")
                    else:
                        corpo = "[IMAGEM] (Erro ao baixar)"

                else:
                    # Outros tipos de mídia (vídeo, documento, etc)
                    tipo_midia = "outro"
                    if msg.get('caption'):
                        corpo = f"[MÍDIA] | Legenda: {msg.get('caption')}"
                    else:
                        corpo = "[MÍDIA]"

                # Adiciona legenda se houver
                if msg.get('caption') and tipo_midia in ['audio', 'imagem']:
                    corpo += f" | Legenda: {msg.get('caption')}"

            else:
                # Usa o corpo da mensagem ou uma tag se não houver texto
                corpo = msg.get('body', '[Mensagem sem texto]')

            data_hora = datetime.fromtimestamp(int(msg.get('timestamp'))).strftime('%d/%m/%Y %H:%M:%S')
            # Limpa quebras de linha no conteúdo para o CSV
            corpo_limpo = corpo.replace('\n', ' ').replace('\r', '')

            # Escreve a linha no arquivo CSV com todas as colunas
            csv_writer.writerow([chat_id, data_hora, remetente, corpo_limpo, tipo_midia, caminho_midia])

        print(f"    -> {len(messages_for_day)} mensagens de '{chat_id}' adicionadas ao arquivo.")
        if audios_processados > 0 or imagens_processadas > 0:
            print(f"    -> 🎵 {audios_processados} áudio(s) transcrito(s) | 🖼️  {imagens_processadas} imagem(ns) analisada(s)")

    except requests.exceptions.RequestException as e:
        print(f"    -> ❌ Erro ao baixar o histórico para {chat_id}: {e}")

if __name__ == "__main__":
    args = parse_args()

    print("="*70)
    print("BACKUP WHATSAPP COM TRANSCRIÇÃO DE ÁUDIO E ANÁLISE DE IMAGEM")
    print(f"MODO: {args.modo.upper()}")
    print("="*70)

    try:
        target_date = resolve_target_date(args)
    except ValueError as e:
        print(f"❌ {e}")
        exit(1)

    # Inicializa o conector WAHA
    connector = WAHAConnector(WAHA_API_URL, SESSION_NAME, WAHA_API_KEY)

    # Verifica autenticação antes de prosseguir
    if not connector.verify_authentication():
        print("\n❌ Não foi possível continuar sem autenticação válida.")
        print("   Verifique as configurações e tente novamente.")
        enviar_evento_umami('backup_whatsapp_falha_autenticacao', {
            'data_referencia': target_date.strftime('%Y-%m-%d')
        })
        exit(1)

    # Garante que as pastas de destino existam
    if not os.path.exists(PASTA_SAIDA):
        print(f"AVISO: A pasta '{PASTA_SAIDA}' não foi encontrada. Criando a pasta...")
        os.makedirs(PASTA_SAIDA)

    if not os.path.exists(PASTA_MIDIA):
        print(f"AVISO: A pasta '{PASTA_MIDIA}' não foi encontrada. Criando a pasta...")
        os.makedirs(PASTA_MIDIA)

    print(f"\n📅 Processando dia: {target_date.strftime('%d/%m/%Y')}")

    active_chat_ids = get_active_chats_for_date(target_date, connector.headers)

    if active_chat_ids:
        print("\nIniciando a coleta, processamento de mídias e salvamento...")
        output_filename = os.path.join(PASTA_SAIDA, f"historico_{target_date.strftime('%Y-%m-%d')}_com_midias.csv")

        with open(output_filename, 'w', newline='', encoding='utf-8') as f_csv:
            writer = csv.writer(f_csv, delimiter=';')
            writer.writerow(['ChatID', 'Timestamp', 'Remetente', 'Conteudo', 'TipoMidia', 'CaminhoMidia'])
            for chat_id in active_chat_ids:
                fetch_and_write_messages(chat_id, target_date, writer, connector.headers)

        print(f"\n{'='*70}")
        print("✅ BACKUP DO DIA FINALIZADO COM SUCESSO!")
        print(f"{'='*70}")
        print(f"📁 Arquivo salvo em: {output_filename}")
        print(f"📁 Mídias salvas em: {PASTA_MIDIA}")
        print("☁️  O Google Drive irá sincronizar os arquivos automaticamente.")
        print(f"{'='*70}")
        enviar_evento_umami('backup_whatsapp_sucesso', {
            'data_referencia': target_date.strftime('%Y-%m-%d'),
            'total_conversas': len(active_chat_ids),
            'arquivo_saida': output_filename
        })
    else:
        print(f"\n⚠️  Nenhuma conversa encontrada em {target_date.strftime('%d/%m/%Y')}.")
        print("   Nenhum arquivo gerado.")
        enviar_evento_umami('backup_whatsapp_sem_conversas', {
            'data_referencia': target_date.strftime('%Y-%m-%d')
        })
