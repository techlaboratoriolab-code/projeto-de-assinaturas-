

import csv
import os
import json
from datetime import datetime
from collections import defaultdict
import google.generativeai as genai
from pathlib import Path
import mimetypes

# ==================== CONFIGURAÇÕES ====================
# Importa configurações do arquivo separado
try:
    from config_analise import (
        GOOGLE_CREDENTIALS_PATH,
        PASTA_HISTORICOS,
        PASTA_RELATORIOS,
        MODELO_GEMINI,
        GERAR_JSON,
        GERAR_TXT,
        validar_configuracoes
    )
    print("✓ Configurações carregadas de config_analise.py")
except ImportError:
    # Fallback para configurações padrão se arquivo não existir
    print("⚠ Arquivo config_analise.py não encontrado. Usando configurações padrão.")
    from pathlib import Path as _Path
    from dotenv import load_dotenv as _load_dotenv
    _sd = _Path(__file__).resolve().parent
    _load_dotenv(_sd.parent / '.env', override=False)
    GOOGLE_CREDENTIALS_PATH = os.getenv('GOOGLE_APPLICATION_CREDENTIALS', '')
    PASTA_HISTORICOS = os.getenv('PASTA_HISTORICOS_WHATSAPP', str(_sd.parent / 'historicos_whatsapp'))
    PASTA_RELATORIOS = os.getenv('PASTA_RELATORIOS_WHATSAPP', '')
    MODELO_GEMINI = 'models/gemini-2.5-flash'
    GERAR_JSON = True
    GERAR_TXT = True

    def validar_configuracoes():
        return []

# Configura as credenciais do Google Cloud
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = GOOGLE_CREDENTIALS_PATH
genai.configure()

# ==================== PROMPT DO SCORECARD ====================
PROMPT_SCORECARD = """""
## SCORECARD DE ENCANTAMENTO LAB - PROMPT DE AVALIAÇÃO E GERAÇÃO DE RELATÓRIO OTIMIZADO V4.0 (FINAL)

**OBJETIVO:** Atribuir pontuação (0, 1, 2) para cada atendimento, calcular a Nota Média Final e gerar um relatório que destaque sucessos e áreas de foco. A Nota Final é calculada por: (Soma dos Pontos / 8) * 10.

---

### FASE 1: APLICAÇÃO DO SCORECARD E CALIBRAÇÃO DE PONTUAÇÃO (AJUSTES DE EXPEDIENTE)

**REGRA CRÍTICA DE EXPEDIENTE:** O cálculo do Tempo de Resposta (TR) na Dimensão 1 **NÃO PODE** contabilizar a lacuna de tempo entre 18:30h e 07:30h. A contagem deve ser pausada e retomada no próximo dia útil às 07:30h.

#### 1. Agilidade (Dimensão 1 - REGRA FIXA DE TEMPO E EXPEDIENTE)

| Pontuação | Critério Base | Heurística de Calibração |
| :---: | :--- | :--- |
| **0** | Atraso severo. | Aplicar se o Tempo de Resposta (TR, excluindo o período 18:30h - 07:30h) exceder **15 minutos**, **OU** se o cliente **abandonar** a conversa devido à falta de resposta. |
| **1** | Atingimos o tempo razoável. | Aplicar se o Tempo de Resposta (TR, excluindo o período 18:30h - 07:30h) estiver entre **5 minutos e 15 minutos**. |
| **2** | Fomos super-rápidos! | Aplicar se o Tempo de Resposta (TR, excluindo o período 18:30h - 07:30h) for dado em **até 5 minutos**. |

#### 2. Clareza e Precisão (Dimensão 2 - Nível 2 Mais Atingível)

| Pontuação | Critério Base | Heurística de Calibração |
| :---: | :--- | :--- |
| **0** | Informação vaga ou incorreta. | - |
| **1** | Informações corretas, diretas e fáceis de entender. | - |
| **2** | Explicamos o "porquê" **OU** A solução foi **completa e concisa**. | **Gatilhos para 2:** Buscar por frases didáticas que contenham 'pois', 'por que', 'a explicação é que' **OU** se a atendente resolver o pedido complexo (ex: orçamento, protocolo LGPD) em uma **única mensagem completa**, sem a necessidade de perguntas de seguimento do paciente. |

#### 3. Cuidado e Empatia (Dimensão 3 - Nível 2 Mais Atingível)

| Pontuação | Critério Base | Heurística de Calibração |
| :---: | :--- | :--- |
| **0** | Tom frio ou robótico. | - |
| **1** | Fomos educados e cordiais (saudações e nome). | - |
| **2** | Mostramos empatia **OU** encerramento caloroso. | **Gatilhos para 2:** Buscar por frases de acolhimento (ex: "Entendo sua preocupação", "Peço desculpas") **OU** pela utilização de um **encerramento proativo e caloroso** (ex: "Nós que agradecemos! Tenha um ótimo dia e, se precisar de mais alguma coisa, saiba que estamos à disposição. 😊", com emoji). |

#### 4. Proatividade (Dimensão 4 - Sem Alteração Severa)

| Pontuação | Critério Base | Heurística de Calibração |
| :---: | :--- | :--- |
| **0** | Deixamos o paciente em um "beco sem saída" (ex: "não fazemos"). | Aplicar se for um 'Não' sem alternativa. |
| **1** | Resolvemos o problema ou a dúvida. | - |
| **2** | Antecipamos uma dúvida, oferecemos ajuda extra, ou transformamos um "não" em uma solução alternativa. | **Gatilhos para 2:** Oferecer solução particular/novo pedido após negação do convênio, Antecipar problemas (Ex: "Vou enviar essa aqui, mas não aceitam cópia"), Sugerir parceiro para exame não realizado. |

---

### FASE 2: GERAÇÃO DO RELATÓRIO QUALITATIVO (SAÍDA SOLICITADA)

Para cada colaborador, gere um bloco de análise qualitativa usando as notas e heurísticas.

#### 📝 Estrutura do Relatório Individual

### [Nome do Colaborador] ([Status]) - Nota Final: [Nota Média]

**Total de Atendimentos:** [Nº de Atendimentos Ativos]

**Principais Pontos de Sucesso (Por que a nota não foi baixa):**
* **Instrução:** Analisar os atendimentos onde o colaborador obteve pontuação **2** (Uau!) nas Dimensões 2, 3 e 4. Descrever o *melhor caso* de sucesso em **Proatividade** e **Cuidado/Clareza**, citando a ação específica.
* **BÔNUS DE RECUPERAÇÃO:** Se o colaborador pontuou **2 em Proatividade** após ter recebido **0 em Agilidade** na mesma conversa, adicione a menção: "Destacamos um **Bônus de Recuperação** na conversa X, onde [Nome] reverteu uma falha na Agilidade com Proatividade de Nível 2, demonstrando resiliência e foco na solução."

**Oportunidades de Crescimento (Por que não tirou 10):**
* **Instrução:** Identificar a dimensão com a pontuação média mais baixa e os **PONTOS DE ATENÇÃO (0)** mais frequentes. Citar o ofensor principal.

**Próxima Ação de Foco:**
* **Instrução:** Sugerir uma ação de treinamento específica e acionável para a dimensão mais fraca do colaborador.

#### 💰 Estrutura de Análise de Vendas

## 📈 Análise de Oportunidades e Funil de Vendas

* **Total de Oportunidades Efetiváveis:** [Soma total]
* **Fechamentos Realizados:** [Soma total]
* **Taxa de Conversão:** [Cálculo]

**Casos de Sucesso (Fechamentos):**
* **Instrução:** Para cada fechamento (Receita Confirmada), descrever o nome do paciente, o valor e citar a **ação Nível 2 de Proatividade/Clareza** do atendente que foi crucial para a conversão.

**Oportunidades Perdidas (Dinheiro na Mesa):**
* **Instrução:** Para cada Oportunidade Perdida (Motivo: Preço, Exame não realizado, etc.), descrever o motivo do não-fechamento e sugerir uma **Ação de Virada Proativa** que a atendente poderia ter tentado para reter o cliente."""""
# ==================== FUNÇÕES ====================

def listar_arquivos_csv(pasta):
    """Lista todos os arquivos CSV na pasta de históricos"""
    if not os.path.exists(pasta):
        print(f"❌ Pasta não encontrada: {pasta}")
        return []

    arquivos = [f for f in os.listdir(pasta) if f.endswith('.csv')]
    return sorted(arquivos, reverse=True)  # Mais recentes primeiro


def ler_csv_historico(caminho_csv):
    """"Lê o CSV de histórico e organiza as mensagens por chat"""
    conversas = defaultdict(list)

    try:
        with open(caminho_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                chat_id = row.get('ChatID', 'Desconhecido')
                conversas[chat_id].append({
                    'timestamp': row.get('Timestamp', ''),
                    'remetente': row.get('Remetente', ''),
                    'conteudo': row.get('Conteudo', ''),
                    'tipo_midia': row.get('TipoMidia', ''),  # audio, imagem, video, etc
                    'caminho_midia': row.get('CaminhoMidia', '')  # caminho do arquivo
                })

        print(f"✓ CSV lido com sucesso: {len(conversas)} conversas encontradas")
        return conversas

    except Exception as e:
        print(f"❌ Erro ao ler CSV: {e}")
        return {}


def processar_midia_automatico(msg):
    """
    Processa automaticamente áudios e imagens de uma mensagem

    Args:
        msg: dict com dados da mensagem incluindo tipo_midia e caminho_midia

    Returns:
        str: Conteúdo processado (transcrição ou descrição)
    """
    tipo_midia = msg.get('tipo_midia', '').lower()
    caminho = msg.get('caminho_midia', '')

    if not tipo_midia or not caminho or not os.path.exists(caminho):
        return msg.get('conteudo', '')

    # Processa áudio
    if tipo_midia in ['audio', 'ptt', 'voice']:
        print(f"  🎵 Transcrevendo áudio: {Path(caminho).name}")
        resultado = transcrever_audio_simples(caminho)
        if resultado['sucesso']:
            return f"[ÁUDIO TRANSCRITO]: {resultado['transcricao']}"
        else:
            return f"[ÁUDIO] (Erro na transcrição: {resultado['erro']})"

    # Processa imagem
    elif tipo_midia in ['image', 'imagem', 'foto', 'photo']:
        print(f"  🖼️  Analisando imagem: {Path(caminho).name}")
        resultado = analisar_imagem_simples(caminho)
        if resultado['sucesso']:
            return f"[IMAGEM]: {resultado['analise']}"
        else:
            return f"[IMAGEM] (Erro na análise: {resultado['erro']})"

    # Outros tipos de mídia
    else:
        conteudo_original = msg.get('conteudo', '')
        if conteudo_original:
            return f"[{tipo_midia.upper()}]: {conteudo_original}"
        else:
            return f"[{tipo_midia.upper()}]"


def transcrever_audio_simples(caminho_audio):
    """Versão simplificada da transcrição sem prints detalhados"""
    try:
        if not os.path.exists(caminho_audio):
            return {'sucesso': False, 'transcricao': '', 'erro': 'Arquivo não encontrado'}

        audio_file = genai.upload_file(caminho_audio)
        model = genai.GenerativeModel('models/gemini-2.5-flash')

        prompt = "Transcreva este áudio com precisão, mantendo a pontuação adequada."
        response = model.generate_content([prompt, audio_file])
        transcricao = response.text.strip()

        audio_file.delete()

        return {'sucesso': True, 'transcricao': transcricao, 'erro': ''}
    except Exception as e:
        return {'sucesso': False, 'transcricao': '', 'erro': str(e)}


def analisar_imagem_simples(caminho_imagem):
    """Versão simplificada da análise sem prints detalhados"""
    try:
        if not os.path.exists(caminho_imagem):
            return {'sucesso': False, 'analise': '', 'erro': 'Arquivo não encontrado'}

        image_file = genai.upload_file(caminho_imagem)
        model = genai.GenerativeModel('models/gemini-2.5-flash')

        prompt = "Descreva esta imagem de forma detalhada e objetiva, focando no conteúdo relevante para uma conversa de atendimento ao cliente."
        response = model.generate_content([prompt, image_file])
        analise = response.text.strip()

        image_file.delete()

        return {'sucesso': True, 'analise': analise, 'erro': ''}
    except Exception as e:
        return {'sucesso': False, 'analise': '', 'erro': str(e)}


def formatar_conversas_para_analise(conversas):
    """Formata as conversas em texto para enviar ao Gemini, processando mídias automaticamente"""
    texto_completo = []
    total_midias = 0

    print("\n📝 Formatando conversas e processando mídias...")

    for chat_id, mensagens in conversas.items():
        texto_completo.append(f"\n{'='*60}")
        texto_completo.append(f"CONVERSA: {chat_id}")
        texto_completo.append('='*60)

        for msg in mensagens:
            timestamp = msg['timestamp']
            remetente = msg['remetente']
            tipo_midia = msg.get('tipo_midia', '')

            # Se há mídia (áudio ou imagem), processa automaticamente
            if tipo_midia in ['audio', 'ptt', 'voice', 'image', 'imagem', 'foto', 'photo']:
                total_midias += 1
                conteudo_processado = processar_midia_automatico(msg)
            else:
                conteudo_processado = msg['conteudo']

            texto_completo.append(f"[{timestamp}] {remetente}: {conteudo_processado}")

    if total_midias > 0:
        print(f"✓ {total_midias} mídia(s) processada(s) automaticamente")

    return "\n".join(texto_completo)


def analisar_com_gemini(texto_conversas, data_str):
    """Envia as conversas para o Gemini e recebe a análise em formato Markdown"""
    print("\n🤖 Enviando conversas (incluindo mídias processadas) para análise do Gemini...")

    try:
        # Configuração de geração com temperatura baixa para reduzir alucinações
        generation_config = genai.types.GenerationConfig(
            temperature=0.3  # Temperatura bem baixa (0.0 a 2.0) - mais determinístico
        )

        model = genai.GenerativeModel(
            MODELO_GEMINI,
            generation_config=generation_config
        )

        instrucao_midia = """

⚠️ IMPORTANTE: Neste histórico, mensagens de áudio foram automaticamente transcritas e aparecem como [ÁUDIO TRANSCRITO]: texto...
As imagens foram analisadas e aparecem como [IMAGEM]: descrição...
Considere o conteúdo das transcrições e análises de imagens da mesma forma que as mensagens de texto normais ao aplicar o Scorecard.
"""

        prompt_completo = f"{PROMPT_SCORECARD}{instrucao_midia}\n\n## HISTÓRICO DO DIA {data_str}:\n\n{texto_conversas}"

        response = model.generate_content(prompt_completo)
        resposta_texto = response.text.strip()

        print("✓ Análise concluída!")

        # Remove markdown code blocks se presentes
        if '```markdown' in resposta_texto:
            resposta_texto = resposta_texto.split('```markdown')[1].split('```')[0].strip()
        elif '```' in resposta_texto and resposta_texto.startswith('```'):
            # Remove apenas se começar com ```
            partes = resposta_texto.split('```')
            if len(partes) >= 3:
                resposta_texto = partes[1].strip()

        # Retorna o texto markdown diretamente
        return {"resposta_markdown": resposta_texto, "data_analise": data_str}

    except Exception as e:
        print(f"❌ Erro ao analisar com Gemini: {e}")
        return None


def salvar_relatorio(resultado, data_str, pasta_saida):
    """Salva o relatório em arquivo Markdown e JSON (backup)"""
    if not resultado:
        print("❌ Nenhum resultado para salvar")
        return

    # Garante que a pasta existe
    if not os.path.exists(pasta_saida):
        os.makedirs(pasta_saida)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Extrai o markdown
    markdown_text = resultado.get('resposta_markdown', '')

    # Salva JSON (backup do resultado bruto se habilitado)
    if GERAR_JSON:
        arquivo_json = os.path.join(pasta_saida, f"analise_atendimento_{data_str}_{timestamp}.json")
        try:
            with open(arquivo_json, 'w', encoding='utf-8') as f:
                json.dump(resultado, f, ensure_ascii=False, indent=2)
            print(f"\n✓ Backup JSON salvo: {arquivo_json}")
        except Exception as e:
            print(f"❌ Erro ao salvar JSON: {e}")

    # Salva MARKDOWN (formato principal)
    if GERAR_TXT:
        arquivo_md = os.path.join(pasta_saida, f"analise_atendimento_{data_str}_{timestamp}.md")
        try:
            with open(arquivo_md, 'w', encoding='utf-8') as f:
                # Escreve o markdown gerado pelo Gemini diretamente
                f.write(markdown_text)

            print(f"✓ Relatório Markdown salvo: {arquivo_md}")
        except Exception as e:
            print(f"❌ Erro ao salvar Markdown: {e}")


def exibir_resumo(resultado):
    """Exibe um resumo da análise no terminal"""
    if not resultado:
        return

    # Extrai as primeiras linhas do markdown para exibir
    markdown_text = resultado.get('resposta_markdown', '')

    print("\n" + "="*70)
    print("PRÉVIA DO RELATÓRIO GERADO")
    print("="*70)

    # Exibe as primeiras 30 linhas do relatório
    linhas = markdown_text.split('\n')
    preview_lines = min(30, len(linhas))

    for linha in linhas[:preview_lines]:
        print(linha)

    if len(linhas) > preview_lines:
        print(f"\n... (mais {len(linhas) - preview_lines} linhas no arquivo completo)")

    print("="*70)


# ==================== FUNÇÕES DE TRANSCRIÇÃO E ANÁLISE DE MÍDIA ====================

def transcrever_audio(caminho_audio, prompt_contexto=""):
    """
    Transcreve um arquivo de áudio usando Gemini 2.5 Flash

    Args:
        caminho_audio: Caminho para o arquivo de áudio (mp3, wav, ogg, etc)
        prompt_contexto: Contexto adicional para melhorar a transcrição

    Returns:
        dict: {'sucesso': bool, 'transcricao': str, 'erro': str}
    """
    print(f"\n🎵 Iniciando transcrição de áudio: {Path(caminho_audio).name}")

    try:
        # Verifica se o arquivo existe
        if not os.path.exists(caminho_audio):
            return {
                'sucesso': False,
                'transcricao': '',
                'erro': f'Arquivo não encontrado: {caminho_audio}'
            }

        # Faz upload do arquivo de áudio
        print("📤 Fazendo upload do arquivo de áudio...")
        audio_file = genai.upload_file(caminho_audio)
        print(f"✓ Upload concluído: {audio_file.name}")

        # Configura o modelo Gemini 2.5 Flash
        model = genai.GenerativeModel('models/gemini-2.5-flash')

        # Monta o prompt
        if prompt_contexto:
            prompt = f"""Transcreva o áudio a seguir com precisão.

Contexto adicional: {prompt_contexto}

Por favor, forneça a transcrição completa do áudio, mantendo a pontuação adequada e organizando o texto de forma clara."""
        else:
            prompt = "Transcreva este áudio com precisão, mantendo a pontuação adequada e organizando o texto de forma clara."

        # Gera a transcrição
        print("🤖 Processando transcrição com Gemini 2.5 Flash...")
        response = model.generate_content([prompt, audio_file])
        transcricao = response.text.strip()

        print("✓ Transcrição concluída!")

        # Remove o arquivo temporário do Gemini
        audio_file.delete()

        return {
            'sucesso': True,
            'transcricao': transcricao,
            'erro': ''
        }

    except Exception as e:
        print(f"❌ Erro na transcrição: {e}")
        return {
            'sucesso': False,
            'transcricao': '',
            'erro': str(e)
        }


def analisar_imagem(caminho_imagem, prompt_analise="Descreva esta imagem em detalhes"):
    """
    Analisa uma imagem usando Gemini 2.5 Flash

    Args:
        caminho_imagem: Caminho para o arquivo de imagem (jpg, png, etc)
        prompt_analise: Prompt personalizado para análise da imagem

    Returns:
        dict: {'sucesso': bool, 'analise': str, 'erro': str}
    """
    print(f"\n🖼️  Iniciando análise de imagem: {Path(caminho_imagem).name}")

    try:
        # Verifica se o arquivo existe
        if not os.path.exists(caminho_imagem):
            return {
                'sucesso': False,
                'analise': '',
                'erro': f'Arquivo não encontrado: {caminho_imagem}'
            }

        # Faz upload do arquivo de imagem
        print("📤 Fazendo upload da imagem...")
        image_file = genai.upload_file(caminho_imagem)
        print(f"✓ Upload concluído: {image_file.name}")

        # Configura o modelo Gemini 2.5 Flash
        model = genai.GenerativeModel('models/gemini-2.5-flash')

        # Gera a análise
        print("🤖 Processando análise com Gemini 2.5 Flash...")
        response = model.generate_content([prompt_analise, image_file])
        analise = response.text.strip()

        print("✓ Análise concluída!")

        # Remove o arquivo temporário do Gemini
        image_file.delete()

        return {
            'sucesso': True,
            'analise': analise,
            'erro': ''
        }

    except Exception as e:
        print(f"❌ Erro na análise: {e}")
        return {
            'sucesso': False,
            'analise': '',
            'erro': str(e)
        }


def processar_midia_lote(pasta_midias, tipo='imagem', prompt_padrao=""):
    """
    Processa múltiplos arquivos de mídia (áudio ou imagem) em lote

    Args:
        pasta_midias: Caminho para a pasta com os arquivos
        tipo: 'imagem' ou 'audio'
        prompt_padrao: Prompt padrão para processamento

    Returns:
        list: Lista de resultados processados
    """
    print(f"\n📁 Processando arquivos de {tipo} em lote...")

    # Define extensões válidas
    extensoes = {
        'imagem': ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'],
        'audio': ['.mp3', '.wav', '.ogg', '.m4a', '.flac', '.aac']
    }

    if tipo not in extensoes:
        print(f"❌ Tipo inválido: {tipo}. Use 'imagem' ou 'audio'")
        return []

    # Lista arquivos
    arquivos = []
    for ext in extensoes[tipo]:
        arquivos.extend(Path(pasta_midias).glob(f"*{ext}"))

    print(f"✓ Encontrados {len(arquivos)} arquivo(s) de {tipo}")

    resultados = []

    for i, arquivo in enumerate(arquivos, 1):
        print(f"\n[{i}/{len(arquivos)}] Processando: {arquivo.name}")

        if tipo == 'imagem':
            resultado = analisar_imagem(str(arquivo), prompt_padrao or "Descreva esta imagem em detalhes")
        else:  # audio
            resultado = transcrever_audio(str(arquivo), prompt_padrao)

        resultados.append({
            'arquivo': arquivo.name,
            'caminho': str(arquivo),
            'resultado': resultado
        })

    print(f"\n✅ Processamento em lote concluído: {len(resultados)} arquivos")
    return resultados


def salvar_resultado_midia(resultado, pasta_saida):
    """
    Salva o resultado de transcrição/análise em arquivo

    Args:
        resultado: dict com os resultados
        pasta_saida: pasta onde salvar os arquivos
    """
    if not os.path.exists(pasta_saida):
        os.makedirs(pasta_saida)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Salva em JSON
    arquivo_json = os.path.join(pasta_saida, f"resultado_midia_{timestamp}.json")
    with open(arquivo_json, 'w', encoding='utf-8') as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)

    print(f"✓ Resultado salvo: {arquivo_json}")

    # Salva em TXT se for transcrição única
    if isinstance(resultado, dict) and 'transcricao' in resultado:
        arquivo_txt = os.path.join(pasta_saida, f"transcricao_{timestamp}.txt")
        with open(arquivo_txt, 'w', encoding='utf-8') as f:
            f.write(resultado['transcricao'])
        print(f"✓ Transcrição salva: {arquivo_txt}")

    elif isinstance(resultado, dict) and 'analise' in resultado:
        arquivo_txt = os.path.join(pasta_saida, f"analise_imagem_{timestamp}.txt")
        with open(arquivo_txt, 'w', encoding='utf-8') as f:
            f.write(resultado['analise'])
        print(f"✓ Análise salva: {arquivo_txt}")


# ==================== MAIN ====================

def menu_principal():
    """Exibe o menu principal com todas as opções disponíveis"""
    print("\n" + "="*70)
    print("SISTEMA DE ANÁLISE LAB - POWERED BY GEMINI 2.5 FLASH")
    print("="*70)
    print("\nEscolha uma opção:")
    print("\n1. Análise de Atendimento WhatsApp (Scorecard)")
    print("2. Transcrever Áudio")
    print("3. Analisar Imagem")
    print("4. Processar Múltiplos Áudios (Lote)")
    print("5. Processar Múltiplas Imagens (Lote)")
    print("0. Sair")
    print("="*70)

    escolha = input("\nDigite o número da opção: ").strip()
    return escolha


def opcao_transcrever_audio():
    """Menu para transcrever um único áudio"""
    print("\n" + "="*70)
    print("TRANSCRIÇÃO DE ÁUDIO")
    print("="*70)

    caminho = input("\nDigite o caminho completo do arquivo de áudio: ").strip()
    if not caminho:
        print("❌ Caminho não informado")
        return

    contexto = input("Contexto adicional (opcional, ENTER para pular): ").strip()

    resultado = transcrever_audio(caminho, contexto)

    if resultado['sucesso']:
        print("\n" + "="*70)
        print("TRANSCRIÇÃO:")
        print("="*70)
        print(resultado['transcricao'])
        print("="*70)

        salvar = input("\nDeseja salvar a transcrição? (s/n): ").strip().lower()
        if salvar == 's':
            pasta_saida = input("Digite a pasta de saída (ENTER para pasta atual): ").strip()
            if not pasta_saida:
                pasta_saida = os.getcwd()
            salvar_resultado_midia(resultado, pasta_saida)
    else:
        print(f"\n❌ Erro: {resultado['erro']}")


def opcao_analisar_imagem():
    """Menu para analisar uma única imagem"""
    print("\n" + "="*70)
    print("ANÁLISE DE IMAGEM")
    print("="*70)

    caminho = input("\nDigite o caminho completo do arquivo de imagem: ").strip()
    if not caminho:
        print("❌ Caminho não informado")
        return

    prompt = input("Prompt de análise (ENTER para usar padrão): ").strip()
    if not prompt:
        prompt = "Descreva esta imagem em detalhes"

    resultado = analisar_imagem(caminho, prompt)

    if resultado['sucesso']:
        print("\n" + "="*70)
        print("ANÁLISE DA IMAGEM:")
        print("="*70)
        print(resultado['analise'])
        print("="*70)

        salvar = input("\nDeseja salvar a análise? (s/n): ").strip().lower()
        if salvar == 's':
            pasta_saida = input("Digite a pasta de saída (ENTER para pasta atual): ").strip()
            if not pasta_saida:
                pasta_saida = os.getcwd()
            salvar_resultado_midia(resultado, pasta_saida)
    else:
        print(f"\n❌ Erro: {resultado['erro']}")


def opcao_processar_lote():
    """Menu para processar múltiplos arquivos em lote"""
    print("\n" + "="*70)
    print("PROCESSAMENTO EM LOTE")
    print("="*70)

    tipo = input("\nTipo de arquivo (audio/imagem): ").strip().lower()
    if tipo not in ['audio', 'imagem']:
        print("❌ Tipo inválido. Use 'audio' ou 'imagem'")
        return

    pasta = input("Digite o caminho da pasta com os arquivos: ").strip()
    if not pasta or not os.path.exists(pasta):
        print("❌ Pasta não encontrada")
        return

    prompt = input("Prompt padrão (ENTER para usar padrão): ").strip()

    resultados = processar_midia_lote(pasta, tipo, prompt)

    if resultados:
        print("\n" + "="*70)
        print("RESUMO DO PROCESSAMENTO")
        print("="*70)

        sucessos = sum(1 for r in resultados if r['resultado']['sucesso'])
        print(f"\n✓ Processados com sucesso: {sucessos}/{len(resultados)}")

        salvar = input("\nDeseja salvar os resultados? (s/n): ").strip().lower()
        if salvar == 's':
            pasta_saida = input("Digite a pasta de saída (ENTER para pasta atual): ").strip()
            if not pasta_saida:
                pasta_saida = os.getcwd()
            salvar_resultado_midia(resultados, pasta_saida)


def main():
    print("="*70)
    print("ANÁLISE DE ATENDIMENTO WHATSAPP - SCORECARD COM PROCESSAMENTO DE MÍDIA")
    print("="*70)
    print("🎵 Áudios transcritos automaticamente | 🖼️ Imagens analisadas automaticamente")
    print("="*70)

    # Lista arquivos disponíveis
    pasta_trabalho = PASTA_HISTORICOS
    print(f"\n📁 Buscando arquivos em: {pasta_trabalho}")
    arquivos = listar_arquivos_csv(pasta_trabalho)

    if not arquivos:
        print("❌ Nenhum arquivo CSV encontrado na pasta de históricos")
        return

    print(f"\n✓ Encontrados {len(arquivos)} arquivo(s):\n")
    for i, arquivo in enumerate(arquivos[:10], 1):  # Mostra até 10 mais recentes
        print(f"  {i}. {arquivo}")

    # Solicita escolha do arquivo
    print("\n" + "="*70)
    escolha = input("Digite o número do arquivo ou o caminho completo (ENTER para o mais recente): ").strip()

    if not escolha:
        arquivo_escolhido = arquivos[0]
        print(f"✓ Usando arquivo mais recente: {arquivo_escolhido}")
    elif escolha.isdigit() and 1 <= int(escolha) <= len(arquivos):
        arquivo_escolhido = arquivos[int(escolha) - 1]
        print(f"✓ Arquivo selecionado: {arquivo_escolhido}")
    elif os.path.exists(escolha):
        arquivo_escolhido = os.path.basename(escolha)
        pasta_trabalho = os.path.dirname(escolha)
        print(f"✓ Usando arquivo: {arquivo_escolhido}")
    else:
        print("❌ Escolha inválida")
        return

    caminho_completo = os.path.join(pasta_trabalho, arquivo_escolhido)

    # Extrai data do nome do arquivo (formato: historico_YYYY-MM-DD_*.csv)
    try:
        data_str = arquivo_escolhido.split('_')[1]
    except:
        data_str = datetime.now().strftime("%Y-%m-%d")

    print(f"\n📅 Data de análise: {data_str}")
    print("="*70)

    # Lê o CSV
    print("\n📖 Lendo histórico de conversas...")
    conversas = ler_csv_historico(caminho_completo)

    if not conversas:
        print("❌ Nenhuma conversa encontrada no arquivo")
        return

    # Formata para análise
    print(f"\n📝 Formatando {len(conversas)} conversas para análise...")
    texto_conversas = formatar_conversas_para_analise(conversas)

    # Verifica tamanho do texto (limite do Gemini)
    tamanho_mb = len(texto_conversas.encode('utf-8')) / (1024 * 1024)
    print(f"📊 Tamanho do texto: {tamanho_mb:.2f} MB")

    if tamanho_mb > 10:
        print("⚠ AVISO: Arquivo muito grande. Pode haver limitações na análise.")
        continuar = input("Deseja continuar? (s/n): ").strip().lower()
        if continuar != 's':
            print("❌ Análise cancelada")
            return

    # Analisa com Gemini
    resultado = analisar_com_gemini(texto_conversas, data_str)

    if not resultado:
        print("❌ Falha na análise")
        return

    # Salva relatório
    if PASTA_RELATORIOS:
        pasta_relatorios = PASTA_RELATORIOS
    else:
        pasta_relatorios = os.path.join(pasta_trabalho, "analises")
    salvar_relatorio(resultado, data_str, pasta_relatorios)

    # Exibe resumo
    exibir_resumo(resultado)

    print("\n✅ ANÁLISE CONCLUÍDA COM SUCESSO!")
    print("="*70)


if __name__ == "__main__":
    main()
