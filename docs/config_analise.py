"""
Arquivo de Configuração - Sistema de Análise de Atendimento WhatsApp

Centralize todas as configurações aqui para facilitar ajustes futuros.
Modifique este arquivo ao invés de alterar o código principal.
"""

import os

# ==================== CREDENCIAIS ====================
# Caminho para o arquivo de credenciais do Google Cloud
GOOGLE_CREDENTIALS_PATH = r"C:\Users\Windows 11\Desktop\spry-catcher-449921-h8-bbc989e73ec4.json"

# ==================== PASTAS ====================
# Pasta onde estão os CSVs de backup do WhatsApp
PASTA_HISTORICOS = r"G:\Meu Drive\Histórico WhatsApp\historicos_diarios"

# Pasta onde os relatórios de análise serão salvos
# Se vazio, será criada subpasta "analises" dentro de PASTA_HISTORICOS
PASTA_RELATORIOS = ""  # Deixe vazio para usar subpasta automática

# ==================== MODELO GEMINI ====================
# Modelo do Gemini a ser usado
# Opções: 'models/gemini-2.5-flash' (rápido) ou 'models/gemini-2.5-pro' (mais preciso)
MODELO_GEMINI = 'models/gemini-2.5-flash'

# ==================== METAS DE ATENDIMENTO ====================
# Metas usadas na avaliação (em minutos)
TEMPO_MAX_PRIMEIRA_RESPOSTA = 10  # minutos
TEMPO_MAX_OUTRAS_RESPOSTAS = 5    # minutos

# Meta de nota mínima para considerado "bom"
NOTA_MINIMA_SATISFATORIA = 7.0

# Meta de nota para considerado "excelente"
NOTA_EXCELENCIA = 8.5

# ==================== IDENTIFICAÇÃO DE ATENDENTES ====================
# Nome/texto que identifica mensagens do próprio atendimento (não do cliente)
# Ajuste conforme aparece no CSV
MEU_NOME_ATENDIMENTO = "Eu (atendimento)"

# Lista de atendentes conhecidos (opcional, para validação)
# Se vazio, o sistema tenta identificar automaticamente
LISTA_ATENDENTES = [
    # "Maria Silva",
    # "João Santos",
    # "Ana Costa",
    # etc...
]

# ==================== PALAVRAS-CHAVE ====================
# Palavras que indicam oportunidade de particular
PALAVRAS_CHAVE_PARTICULAR = [
    "particular",
    "orçamento",
    "valor",
    "preço",
    "quanto custa",
    "pagar",
    "cartão",
    "dinheiro",
    "pix",
    "sem plano",
    "não tenho convênio",
    "não tem convênio"
]

# Palavras que indicam fechamento
PALAVRAS_CHAVE_FECHAMENTO = [
    "agendado",
    "confirmado",
    "agendar",
    "marcar",
    "ok",
    "sim",
    "pode ser",
    "aceito",
    "fechado"
]

# ==================== PONTOS DE ALERTA ====================
# Palavras que indicam problemas graves (nota zero)
PALAVRAS_ALERTA_CRITICAS = [
    "informação errada",
    "erro grave",
    "problema com parceiro",
    "sem resposta"
]

# ==================== FORMATO DOS RELATÓRIOS ====================
# Gerar relatório em JSON?
GERAR_JSON = True

# Gerar relatório em TXT?
GERAR_TXT = True

# Gerar relatório em HTML? (futuro)
GERAR_HTML = False

# ==================== ANÁLISE ====================
# Limite de conversas para processar (0 = sem limite)
LIMITE_CONVERSAS = 0

# Mostrar progresso durante análise?
MOSTRAR_PROGRESSO = True

# Incluir conteúdo completo das mensagens no relatório?
INCLUIR_MENSAGENS_COMPLETAS = False

# ==================== AVANÇADO ====================
# Timeout para requisições ao Gemini (segundos)
TIMEOUT_GEMINI = 300

# Número de tentativas em caso de erro
MAX_TENTATIVAS = 3

# Delay entre tentativas (segundos)
DELAY_ENTRE_TENTATIVAS = 5

# ==================== LOGS ====================
# Nível de log (DEBUG, INFO, WARNING, ERROR)
NIVEL_LOG = "INFO"

# Salvar logs em arquivo?
SALVAR_LOGS = True

# Pasta de logs
PASTA_LOGS = os.path.join(os.path.dirname(__file__), "logs")

# ==================== VALIDAÇÃO ====================
def validar_configuracoes():
    """Valida se as configurações estão corretas"""
    erros = []

    # Verifica credenciais
    if not os.path.exists(GOOGLE_CREDENTIALS_PATH):
        erros.append(f"❌ Arquivo de credenciais não encontrado: {GOOGLE_CREDENTIALS_PATH}")

    # Verifica pasta de históricos
    if not os.path.exists(PASTA_HISTORICOS):
        erros.append(f"⚠️ Pasta de históricos não encontrada: {PASTA_HISTORICOS}")
        erros.append(f"   A pasta será criada automaticamente.")

    # Verifica modelo
    modelos_validos = ['models/gemini-2.5-flash', 'models/gemini-2.5-pro']
    if MODELO_GEMINI not in modelos_validos:
        erros.append(f"⚠️ Modelo '{MODELO_GEMINI}' pode não ser válido. Use: {modelos_validos}")

    # Verifica metas
    if NOTA_MINIMA_SATISFATORIA > NOTA_EXCELENCIA:
        erros.append("⚠️ NOTA_MINIMA_SATISFATORIA não pode ser maior que NOTA_EXCELENCIA")

    return erros

# ==================== EXIBIR CONFIGURAÇÕES ====================
def exibir_configuracoes():
    """Exibe as configurações atuais"""
    print("="*70)
    print("CONFIGURAÇÕES DO SISTEMA DE ANÁLISE")
    print("="*70)
    print(f"\n📁 Pastas:")
    print(f"   Históricos: {PASTA_HISTORICOS}")
    print(f"   Relatórios: {PASTA_RELATORIOS or 'AUTO (subpasta de históricos)'}")
    print(f"\n🤖 IA:")
    print(f"   Modelo: {MODELO_GEMINI}")
    print(f"\n🎯 Metas:")
    print(f"   1ª Resposta: {TEMPO_MAX_PRIMEIRA_RESPOSTA} min")
    print(f"   Outras: {TEMPO_MAX_OUTRAS_RESPOSTAS} min")
    print(f"   Nota mínima: {NOTA_MINIMA_SATISFATORIA}/10")
    print(f"   Nota excelência: {NOTA_EXCELENCIA}/10")
    print(f"\n📊 Relatórios:")
    print(f"   JSON: {'✅' if GERAR_JSON else '❌'}")
    print(f"   TXT: {'✅' if GERAR_TXT else '❌'}")
    print(f"   HTML: {'✅' if GERAR_HTML else '❌'}")
    print("="*70)

# ==================== TESTE ====================
if __name__ == "__main__":
    print("🔧 TESTANDO CONFIGURAÇÕES\n")

    erros = validar_configuracoes()

    if erros:
        print("⚠️ ATENÇÃO: Problemas encontrados:\n")
        for erro in erros:
            print(erro)
        print("\n💡 Corrija as configurações em config_analise.py")
    else:
        print("✅ Todas as configurações estão OK!\n")
        exibir_configuracoes()
        print("\n🚀 Pronto para analisar atendimentos!")
