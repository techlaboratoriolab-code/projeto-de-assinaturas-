import mysql.connector
from datetime import date, datetime, timedelta
from collections import Counter
import os
import time
import csv
import argparse
import google.generativeai as genai
from PIL import Image
try:
    import fitz  # PyMuPDF para converter PDF em imagem
    PYMUPDF_OK = True
except ImportError:
    PYMUPDF_OK = False
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException

# Configurações de conexão com o banco de dados
# Substitua 'nome_do_banco' pelo nome real do seu banco de dados
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'SENHA@ROOT',
    'database': 'bancodedados'  # <--- ATENÇÃO: PREENCHER AQUI
}

# Filtros fixos solicitados: somente registros do convenio 1040 e arquivos PDF
ID_CONVENIO_FIXO = 1040
# Modo padrão: não força somente PDF; pode ser sobrescrito via CLI.
FILTRAR_APENAS_PDF = False

# Se verdadeiro, converterá PDFs (primeira página) para imagem temporária e enviará ao Gemini.
ANALISAR_PDF = False

# Configuração do Gemini usando Service Account
# Caminho para o arquivo JSON de credenciais
GOOGLE_CREDENTIALS_PATH = r"C:\Users\Windows 11\Desktop\spry-catcher-449921-h8-bbc989e73ec4.json"

# Configura as credenciais do Google Cloud
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = GOOGLE_CREDENTIALS_PATH
genai.configure()

# Diretório onde as imagens serão baixadas e salvas
DIRETORIO_IMAGENS = r"C:\Users\Windows 11\Desktop\imagemAWS"

# URLs da AWS para download
URLS_AWS = {
    "0040": "https://sa-east-1.console.aws.amazon.com/s3/buckets/aplis2?region=sa-east-1&bucketType=general&prefix=lab%2FArquivos%2FFoto%2F0040%2F&showversions=false&tab=objects",
    "0085": "https://sa-east-1.console.aws.amazon.com/s3/buckets/aplis2?region=sa-east-1&bucketType=general&prefix=lab/Arquivos/Foto/0085/&showversions=false",
    "0100": "https://sa-east-1.console.aws.amazon.com/s3/buckets/aplis2?region=sa-east-1&bucketType=general&prefix=lab%2FArquivos%2FFoto%2F0100%2F&showversions=false&tab=objects",
    "0101": "https://sa-east-1.console.aws.amazon.com/s3/buckets/aplis2?region=sa-east-1&bucketType=general&prefix=lab/Arquivos/Foto/0101/&showversions=false",
    "0200": "https://sa-east-1.console.aws.amazon.com/s3/buckets/aplis2?region=sa-east-1&bucketType=general&prefix=lab/Arquivos/Foto/0200/&showversions=false",
    "0031": "https://sa-east-1.console.aws.amazon.com/s3/buckets/aplis2?region=sa-east-1&bucketType=general&prefix=lab/Arquivos/Foto/0031/&showversions=false",
    "0102": "https://sa-east-1.console.aws.amazon.com/s3/buckets/aplis2?region=sa-east-1&bucketType=general&prefix=lab/Arquivos/Foto/0102/&showversions=false",
    "0103": "https://sa-east-1.console.aws.amazon.com/s3/buckets/aplis2?region=sa-east-1&bucketType=general&prefix=lab/Arquivos/Foto/0103/&showversions=false",
    "0300": "https://sa-east-1.console.aws.amazon.com/s3/buckets/aplis2?region=sa-east-1&bucketType=general&prefix=lab/Arquivos/Foto/0300/&showversions=false",
    "8511": "https://sa-east-1.console.aws.amazon.com/s3/buckets/aplis2?region=sa-east-1&bucketType=general&prefix=lab/Arquivos/Foto/8511/&showversions=false",
    "0032": "https://sa-east-1.console.aws.amazon.com/s3/buckets/aplis2?region=sa-east-1&bucketType=general&prefix=lab/Arquivos/Foto/0032/&showversions=false",
    "0049": "https://sa-east-1.console.aws.amazon.com/s3/buckets/aplis2?region=sa-east-1&bucketType=general&prefix=lab/Arquivos/Foto/0049/&showversions=false"
}

# Credenciais AWS
AWS_LOGIN = {
    'account': '758835577866',
    'username': 'lab',
    'password': 'NtH[&9&bdF!B@1='
} 

def setup_chrome_download_preferences(download_dir: str) -> webdriver.ChromeOptions:
    """Configura o Chrome para downloads automáticos"""
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    prefs = {
        "download.default_directory": download_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True
    }
    options.add_experimental_option("prefs", prefs)
    return options

def precisa_login(driver):
    """Verifica se está na tela de login da AWS"""
    try:
        # Verifica se existe o campo de login na página
        driver.find_element(By.ID, "signin_button")
        return True
    except NoSuchElementException:
        return False

def perform_login(driver, wait, login_details, url):
    """Realiza login na AWS"""
    try:
        driver.get(url)
        time.sleep(3)

        # Verifica se realmente precisa fazer login
        if not precisa_login(driver):
            print("  ✓ Já está logado na AWS")
            return True

        print("  → Realizando login na AWS...")
        wait.until(EC.presence_of_element_located((By.ID, "account"))).send_keys(login_details['account'])
        wait.until(EC.presence_of_element_located((By.ID, "username"))).send_keys(login_details['username'])
        wait.until(EC.presence_of_element_located((By.ID, "password"))).send_keys(login_details['password'])
        signin_button = wait.until(EC.element_to_be_clickable((By.ID, "signin_button")))
        time.sleep(1)
        signin_button.click()
        time.sleep(5)

        print("  ✓ Login realizado com sucesso")
        return True
    except Exception as e:
        print(f"  ✗ Erro no login para a URL {url}: {e}")
        return False

def baixar_imagem_aws(driver, wait, cod_requisicao):
    """Busca e baixa uma imagem específica da AWS usando o código de requisição"""
    try:
        print(f"Buscando por: {cod_requisicao} na AWS...")

        # Verifica se ainda está logado antes de buscar
        if precisa_login(driver):
            print("  ⚠ Sessão expirada durante o download. Tentando fazer login novamente...")
            url_atual = driver.current_url
            if not perform_login(driver, wait, AWS_LOGIN, url_atual):
                print("  ✗ Falha ao fazer login. Pulando este download...")
                return False

        # Conta arquivos antes do download
        arquivos_antes = set(os.listdir(DIRETORIO_IMAGENS))
        
        search_input = wait.until(EC.visibility_of_element_located((By.ID, "polaris-table-formfield-filter")))
        search_input.clear()
        search_input.send_keys(cod_requisicao)
        search_input.send_keys(Keys.ENTER)
        time.sleep(5)
        
        rows = driver.find_elements(By.XPATH, "//table//tbody/tr")

        # Prioriza linha que contenha PDF se for necessário
        linha_pdf = None
        linha_match_primeira = None
        for row in rows:
            if cod_requisicao in row.text:
                if linha_match_primeira is None:
                    linha_match_primeira = row
                if FILTRAR_APENAS_PDF and '.pdf' in row.text.lower():
                    linha_pdf = row
                    break

        alvo = linha_pdf if (FILTRAR_APENAS_PDF and linha_pdf) else linha_match_primeira

        if alvo:
            try:
                if FILTRAR_APENAS_PDF and not ('.pdf' in alvo.text.lower()):
                    print("Nenhum PDF encontrado para este código na listagem AWS.")
                    return False
                    # Execução direta cmdNova se ainda não abriu
                    if not aberto and tentar_exec_cmdNova():
                        aberto = True
                    if not aberto:
                        diagnosticar_nov()
                checkbox = alvo.find_element(By.XPATH, ".//input[@type='checkbox']")
                driver.execute_script("arguments[0].scrollIntoView(true);", checkbox)
                time.sleep(1)
                driver.execute_script("arguments[0].click();", checkbox)
                print("Checkbox correspondente clicado.")

                download_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#download-object-button")))
                download_button.click()
                print(f"Download de '{cod_requisicao}' iniciado.")

                # Aguarda até 30 segundos pelo download
                for i in range(30):
                    time.sleep(1)
                    arquivos_depois = set(os.listdir(DIRETORIO_IMAGENS))
                    novos_arquivos = arquivos_depois - arquivos_antes
                    novos_completos = [f for f in novos_arquivos if not f.endswith(('.crdownload', '.tmp'))]
                    if FILTRAR_APENAS_PDF:
                        novos_completos = [f for f in novos_completos if f.lower().endswith('.pdf')]
                    if novos_completos:
                        print(f"  ✓ Baixados: {', '.join(novos_completos)}")
                        return True
                print(f"  ⚠ Timeout: arquivo não apareceu em {DIRETORIO_IMAGENS}")
                return False
            except NoSuchElementException:
                print("Checkbox não encontrado.")
        
        print(f"Arquivo '{cod_requisicao}' não encontrado na AWS.")
        return False
    except Exception as e:
        print(f"Erro ao baixar imagem: {e}")
        return False

def baixar_imagens_do_banco(resultados_db):
    """Baixa as imagens da AWS com base nos resultados do banco
    Retorna: set com nomes dos arquivos efetivamente baixados nesta execução
    """
    if not os.path.exists(DIRETORIO_IMAGENS):
        os.makedirs(DIRETORIO_IMAGENS)

    # Conta arquivos ANTES do download para saber o que foi baixado AGORA
    arquivos_antes = set(os.listdir(DIRETORIO_IMAGENS)) if os.path.exists(DIRETORIO_IMAGENS) else set()

    # Verifica quais arquivos JÁ EXISTEM no diretório (para não baixar de novo)
    arquivos_existentes = set()
    for arquivo in arquivos_antes:
        # Remove extensão para comparar com NomArquivo do banco
        nome_sem_ext = os.path.splitext(arquivo)[0]
        arquivos_existentes.add(nome_sem_ext)
        arquivos_existentes.add(arquivo)  # Adiciona também com extensão

    print(f"\n📁 Arquivos já existentes no diretório: {len(arquivos_antes)}")

    chrome_options = setup_chrome_download_preferences(DIRETORIO_IMAGENS)

    # Agrupa códigos de requisição por prefixo para otimizar navegação
    # e FILTRA os que já foram baixados
    codigos_por_prefix = {}
    imagens_puladas = 0

    for linha in resultados_db:
        cod_requisicao = linha['CodRequisicao']
        nome_arquivo = linha['NomArquivo']

        # Remove sufixo _2, _3, _4, etc. do NomArquivo para buscar apenas o código base
        # Exemplo: "0200045822005_3" vira "0200045822005"
        nome_base_arquivo = nome_arquivo.split('_')[0] if '_' in nome_arquivo else nome_arquivo
        nome_sem_ext = os.path.splitext(nome_base_arquivo)[0]

        # Verifica se o arquivo já existe
        if nome_base_arquivo in arquivos_existentes or nome_sem_ext in arquivos_existentes:
            imagens_puladas += 1
            continue  # Pula este arquivo, já existe

        prefix = next((p for p in URLS_AWS.keys() if cod_requisicao.startswith(p)), "outros")
        # Busca pelo código base da requisição (sem sufixos)
        # Usa set para evitar duplicatas (múltiplas imagens da mesma requisição)
        if prefix not in codigos_por_prefix:
            codigos_por_prefix[prefix] = set()
        codigos_por_prefix[prefix].add(nome_base_arquivo)

    # Converte sets para listas
    for prefix in codigos_por_prefix:
        codigos_por_prefix[prefix] = list(codigos_por_prefix[prefix])

    if imagens_puladas > 0:
        print(f"⏭️  Pulando {imagens_puladas} imagens que já foram baixadas")

    if not codigos_por_prefix or all(len(codes) == 0 for codes in codigos_por_prefix.values()):
        print("✅ Todas as imagens já foram baixadas anteriormente!")
        return set()  # Retorna vazio, nada para baixar

    print(f"📥 Total de novas imagens para baixar: {sum(len(codes) for codes in codigos_por_prefix.values())}")

    try:
        driver = webdriver.Chrome(options=chrome_options)
        wait = WebDriverWait(driver, 30)

        # Login na primeira URL
        first_prefix = next(iter(codigos_por_prefix), None)
        if first_prefix and first_prefix in URLS_AWS:
            first_url = URLS_AWS[first_prefix]
            print(f"\n🔐 Realizando login na AWS: {first_url}")
            if not perform_login(driver, wait, AWS_LOGIN, first_url):
                print("Falha no login. Abortando downloads.")
                return set()  # Retorna conjunto vazio

        # Baixa os arquivos agrupados por prefixo usando código de requisição
        # Evita baixar mesma requisicao repetidamente
        requisicoes_processadas = set()
        for prefix, codigos in codigos_por_prefix.items():
            if prefix in URLS_AWS:
                target_url = URLS_AWS[prefix]
                if driver.current_url != target_url:
                    print(f"\nNavegando para: {target_url}")
                    driver.get(target_url)
                    time.sleep(3)

                    # Verifica se precisa fazer login novamente
                    if precisa_login(driver):
                        print("  ⚠ Sessão expirada. Fazendo login novamente...")
                        if not perform_login(driver, wait, AWS_LOGIN, target_url):
                            print("  ✗ Falha no login. Pulando este prefixo...")
                            continue
                    else:
                        time.sleep(2)  # Aguarda a página carregar completamente

                for codigo in codigos:
                    if codigo in requisicoes_processadas:
                        continue
                    sucesso = baixar_imagem_aws(driver, wait, codigo)
                    requisicoes_processadas.add(codigo)

        print("\n✅ Download de todas as imagens concluído.")

        # Mantém o navegador aberto até o usuário confirmar
        print("\n⏸️  Navegador permanecerá aberto para você verificar os downloads.")
        input("Pressione ENTER para fechar o navegador e continuar... ")

    except Exception as e:
        print(f"❌ Erro durante o download: {e}")
        print("\n⏸️  Navegador permanecerá aberto para debug.")
        input("Pressione ENTER para fechar o navegador... ")
    finally:
        print("🔒 Fechando navegador...")
        driver.quit()
        print("✅ Navegador fechado!")

    # Conta arquivos DEPOIS do download
    arquivos_depois = set(os.listdir(DIRETORIO_IMAGENS)) if os.path.exists(DIRETORIO_IMAGENS) else set()
    novos_arquivos = arquivos_depois - arquivos_antes

    # Remove arquivos temporários da contagem
    novos_arquivos_completos = {f for f in novos_arquivos if not f.endswith(('.crdownload', '.tmp', '.part'))}

    print(f"\n📊 RESUMO DO DOWNLOAD:")
    print(f"  • Arquivos baixados AGORA: {len(novos_arquivos_completos)}")
    print(f"  • Total de arquivos no diretório: {len(arquivos_depois)}")
    if novos_arquivos_completos:
        print(f"  • Exemplos: {', '.join(sorted(novos_arquivos_completos)[:5])}{'...' if len(novos_arquivos_completos) > 5 else ''}")

    return novos_arquivos_completos

def analisar_imagem_com_gemini(caminho_imagem):
    """
    Envia a imagem para o Gemini e pergunta se há assinatura.
    Retorna True se tiver assinatura, False caso contrário.
    """
    try:
        if not os.path.exists(caminho_imagem):
            print(f"❌ Arquivo não encontrado: {caminho_imagem}")
            return False

        print(f"📤 Enviando para análise: {os.path.basename(caminho_imagem)}")

        model = genai.GenerativeModel('models/gemini-2.5-flash')
        imagem = Image.open(caminho_imagem)

        prompt = """Analise esta imagem de documento médico/requisição e verifique se existe uma assinatura ou rubrica MANUSCRITA (escrita à mão) ESPECIFICAMENTE NO CAMPO DO PACIENTE.

🎯 FOCO EXCLUSIVO: ASSINATURA DO PACIENTE
Procure APENAS pelos campos com os textos:
- "Paciente (Assinatura)"
- "Assinatura do Paciente"
- "Ass. do Paciente"
- Campo de assinatura na PARTE INFERIOR do documento (onde o paciente assina)

⚠️ IGNORE COMPLETAMENTE:
✗ Assinatura do Médico / Profissional
✗ Carimbo médico
✗ CRM do médico
✗ Qualquer assinatura na parte SUPERIOR do documento
✗ Assinaturas em campos de "Médico Solicitante"

✅ CONSIDERE COMO ASSINADO (apenas no campo do PACIENTE):
✓ Assinatura completa manuscrita do paciente
✓ Rubrica manuscrita do paciente
✓ Iniciais ou traços à mão no campo do paciente
✓ Qualquer marca de caneta/tinta feita pelo paciente no seu campo
✓ "X" ou garatuja feita pelo paciente

❌ CONSIDERE COMO NÃO ASSINADO:
✗ Campo do paciente completamente vazio/em branco
✗ Apenas a palavra "Assinatura" ou "Ass." impressa
✗ Apenas linha tracejada sem nenhuma marca
✗ Campo do paciente sem qualquer traço manuscrito

IMPORTANTE:
1. Concentre-se APENAS na assinatura do PACIENTE
2. Ignore TOTALMENTE a assinatura do médico
3. O campo do paciente geralmente está na PARTE INFERIOR do documento
4. Seja PERMISSIVO com a assinatura do paciente - qualquer traço manuscrito no campo dele = SIM

Responda APENAS com uma palavra: SIM ou NÃO"""

        response = model.generate_content([prompt, imagem])
        resposta_texto = response.text.strip().upper()

        # Extrai resposta mais detalhada para debug
        tem_assinatura = "SIM" in resposta_texto
        emoji = "✅" if tem_assinatura else "❌"

        print(f"  {emoji} Resposta Gemini: {resposta_texto}")

        return tem_assinatura

    except Exception as e:
        print(f"❌ Erro ao analisar imagem com Gemini: {e}")
        return False

def converter_pdf_para_imagem_primeira_pagina(caminho_pdf):
    """Converte a primeira página do PDF em imagem temporária e retorna caminho da imagem.
    Usa PyMuPDF. Retorna None se falhar ou biblioteca ausente."""
    if not PYMUPDF_OK:
        print("PyMuPDF não instalado. Ignorando análise de PDF.")
        return None
    try:
        doc = fitz.open(caminho_pdf)
        if doc.page_count == 0:
            print("PDF sem páginas: ", caminho_pdf)
            return None
        page = doc.load_page(0)
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # upscale para melhor qualidade
        img_path = caminho_pdf + "__pg1.png"
        pix.save(img_path)
        doc.close()
        return img_path
    except Exception as e:
        print(f"Falha ao converter PDF '{caminho_pdf}': {e}")
        return None

def criar_tarefas_sistema_aplis(lista_codigos):
    """Automatiza criação de tarefas no sistema lab.aplis.inf.br.
    Fluxo baseado nos XPaths fornecidos.
    """
    if not lista_codigos:
        print("Lista de códigos vazia, nada a fazer.")
        return
    options = webdriver.ChromeOptions()
    options.add_argument('--start-maximized')
    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 30)
    tarefas_criadas = 0
    try:
        driver.get('https://lab.aplis.inf.br/')
        print("Aguardando carregamento completo do site...")
        time.sleep(5)
        
        # Login
        campo_login = wait.until(EC.visibility_of_element_located((By.XPATH, "//*[@id='login']")))
        driver.execute_script("arguments[0].scrollIntoView(true);", campo_login)
        time.sleep(5)
        campo_login.clear()
        campo_login.send_keys("kaua.larsson")
        time.sleep(5)
        
        campo_senha = wait.until(EC.visibility_of_element_located((By.XPATH, "//*[@id='senha']")))
        campo_senha.clear()
        campo_senha.send_keys("Kaua280626")
        time.sleep(5)
        campo_senha.send_keys(Keys.ENTER)
        
        time.sleep(5)
        print("Login realizado com sucesso.")
        
        # Header
        try:
            header = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[@id='divHeader']/div[1]")))
            driver.execute_script("arguments[0].click();", header)
            time.sleep(5)
        except Exception:
            print("Aviso: header não clicado (continuando).")
        
        # Área - Pesquisar Tarefas
        print("Clicando em 'Pesquisar Tarefas'...")
        area_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[@id='divAreas']/ul/li[2]/a")))
        driver.execute_script("arguments[0].scrollIntoView(true);", area_btn)
        time.sleep(3)
        driver.execute_script("arguments[0].click();", area_btn)
        print("✓ Área 'Pesquisar Tarefas' clicada.")

        # Aguarda nova janela/aba abrir
        time.sleep(3)

        # Muda para a nova aba se abriu
        if len(driver.window_handles) > 1:
            print(f"Detectadas {len(driver.window_handles)} abas. Mudando para a última...")
            driver.switch_to.window(driver.window_handles[-1])
            print(f"✓ Aba atual: {driver.title}")
        else:
            print("⚠ Nenhuma nova aba detectada, continuando na mesma...")

        # Aguarda página de tarefas carregar completamente
        print("Aguardando página de tarefas carregar...")
        time.sleep(5)

        # Tenta clicar no botão "Novo" que pode estar no menu dropdown
        print("Procurando botão 'Novo' na barra de ferramentas...")
        try:
            # Tenta encontrar o botão "Novo" visível na toolbar
            botao_novo = driver.execute_script("""
                // Procura por botões com texto "Novo" visíveis
                var botoes = document.querySelectorAll('a, button, div[onclick], span[onclick]');
                for (var i = 0; i < botoes.length; i++) {
                    var btn = botoes[i];
                    var texto = btn.textContent || btn.innerText || '';
                    if (texto.trim().toLowerCase() === 'novo' &&
                        btn.offsetWidth > 0 && btn.offsetHeight > 0) {
                        return btn.id || btn.className || 'BOTAO_NOVO_ENCONTRADO';
                    }
                }
                return null;
            """)

            if botao_novo:
                print(f"✓ Botão 'Novo' encontrado: {botao_novo}")
            else:
                print("⚠ Botão 'Novo' visível não encontrado na toolbar")
        except Exception as e:
            print(f"⚠ Erro ao procurar botão 'Novo': {e}")

        def diagnosticar_dom():
            """Função de diagnóstico para entender a estrutura do DOM"""
            print("\n" + "="*60)
            print("DIAGNÓSTICO DO DOM")
            print("="*60)

            try:
                diagnostico = driver.execute_script("""
                    var info = {
                        'temIdANov': !!document.getElementById('a_nov'),
                        'temClassNov': !!document.querySelector('.nov'),
                        'temOnclickCmdNova': !!document.querySelector('[onclick*="cmdNova"]'),
                        'temDivTarefas': !!document.getElementById('divTarefas'),
                        'funcaoCmdNovaExiste': typeof cmdNova !== 'undefined',
                        'todosElementosComNov': [],
                        'todosElementosComA_': []
                    };

                    // Busca todos elementos com 'nov' no id ou class
                    var todosElementos = document.querySelectorAll('*');
                    for (var i = 0; i < todosElementos.length; i++) {
                        var el = todosElementos[i];
                        var id = el.id || '';
                        var className = el.className || '';

                        if (id.toLowerCase().includes('nov') || className.toString().toLowerCase().includes('nov')) {
                            info.todosElementosComNov.push({
                                'tag': el.tagName,
                                'id': el.id,
                                'class': el.className,
                                'onclick': el.onclick ? 'SIM' : 'NAO',
                                'visivel': el.offsetWidth > 0 && el.offsetHeight > 0,
                                'display': window.getComputedStyle(el).display,
                                'visibility': window.getComputedStyle(el).visibility
                            });
                        }

                        if (id.toLowerCase().includes('a_')) {
                            info.todosElementosComA_.push({
                                'tag': el.tagName,
                                'id': el.id,
                                'class': el.className,
                                'visivel': el.offsetWidth > 0 && el.offsetHeight > 0
                            });
                        }
                    }

                    return info;
                """)

                print(f"📌 getElementById('a_nov'): {diagnostico['temIdANov']}")
                print(f"📌 querySelector('.nov'): {diagnostico['temClassNov']}")
                print(f"📌 onclick contém 'cmdNova': {diagnostico['temOnclickCmdNova']}")
                print(f"📌 getElementById('divTarefas'): {diagnostico['temDivTarefas']}")
                print(f"📌 Função cmdNova existe: {diagnostico['funcaoCmdNovaExiste']}")

                print(f"\n🔍 Elementos com 'nov' encontrados ({len(diagnostico['todosElementosComNov'])}):")
                for idx, el in enumerate(diagnostico['todosElementosComNov'][:10], 1):  # Mostra até 10
                    print(f"  {idx}. <{el['tag']}> id='{el['id']}' class='{el['class']}' "
                          f"onclick={el['onclick']} visível={el['visivel']} "
                          f"display={el['display']} visibility={el['visibility']}")

                if diagnostico['todosElementosComA_']:
                    print(f"\n🔍 Elementos com 'a_' encontrados ({len(diagnostico['todosElementosComA_'])}):")
                    for idx, el in enumerate(diagnostico['todosElementosComA_'][:5], 1):
                        print(f"  {idx}. <{el['tag']}> id='{el['id']}' class='{el['class']}' visível={el['visivel']}")

                print("="*60 + "\n")
                return diagnostico

            except Exception as e:
                print(f"❌ Erro no diagnóstico: {e}\n")
                return None

        def clicar_a_nov():
            """Função robusta para clicar no botão a_nov usando XPATH com múltiplas tentativas"""

            # Primeiro aguarda o documento estar completamente carregado
            try:
                if driver.execute_script("return document.readyState") == "complete":
                    print("  ✓ Página completamente carregada")
            except Exception:
                pass

            # Executa diagnóstico antes de tentar clicar
            diag = diagnosticar_dom()

            # Se encontrou divMenuNovaTarefa mas está invisível, tenta torná-lo visível e clicar
            if diag and diag.get('todosElementosComNov'):
                for el in diag['todosElementosComNov']:
                    if 'divMenuNovaTarefa' in el.get('id', ''):
                        print("  ⚠ Encontrado 'divMenuNovaTarefa' mas está invisível. Tentando forçar clique...")
                        try:
                            resultado = driver.execute_script("""
                                var menu = document.getElementById('divMenuNovaTarefa');
                                if (menu) {
                                    // Torna visível
                                    menu.style.display = 'block';
                                    menu.style.visibility = 'visible';

                                    // Procura botão dentro do menu
                                    var btns = menu.querySelectorAll('*');
                                    for (var i = 0; i < btns.length; i++) {
                                        var btn = btns[i];
                                        var id = btn.id || '';
                                        var className = btn.className || '';
                                        var onclick = btn.getAttribute('onclick') || '';

                                        if (id.includes('nov') || id === 'a_nov' ||
                                            className.includes('nov') ||
                                            onclick.includes('cmdNova')) {
                                            btn.click();
                                            return 'CLICADO_DENTRO_MENU: ' + id;
                                        }
                                    }

                                    // Se não achou, clica no próprio menu
                                    menu.click();
                                    return 'CLICADO_MENU';
                                }
                                return 'MENU_NAO_ENCONTRADO';
                            """)
                            print(f"    → Resultado: {resultado}")

                            if 'CLICADO' in str(resultado):
                                time.sleep(2)
                                try:
                                    WebDriverWait(driver, 3).until(
                                        EC.presence_of_element_located((By.XPATH, "//*[@id='_taReq']"))
                                    )
                                    print("  ✓✓✓ SUCESSO! Modal aberto via divMenuNovaTarefa")
                                    return True
                                except TimeoutException:
                                    print("  ⚠ Menu clicado mas modal não abriu")
                        except Exception as e:
                            print(f"  ✗ Erro ao clicar no menu: {e}")
                        break

            # Se a função cmdNova existe e não encontrou o botão, tenta executá-la direto
            if diag and diag.get('funcaoCmdNovaExiste') and not diag.get('temIdANov'):
                print("  ⚠ Botão não encontrado mas função cmdNova existe. Tentando executar direto...")
                try:
                    driver.execute_script("cmdNova();")
                    time.sleep(2)
                    try:
                        WebDriverWait(driver, 3).until(
                            EC.presence_of_element_located((By.XPATH, "//*[@id='_taReq']"))
                        )
                        print("  ✓✓✓ SUCESSO! Modal aberto via cmdNova() direto")
                        return True
                    except TimeoutException:
                        pass
                except Exception as e:
                    print(f"  ✗ Erro ao executar cmdNova(): {e}")

            # Tentativa 0: Busca por texto "Novo" visível (NOVA - mais genérica)
            def tentativa_texto_novo():
                try:
                    resultado = driver.execute_script("""
                        var botoes = document.querySelectorAll('a, button, div, span, td, li');
                        for (var i = 0; i < botoes.length; i++) {
                            var btn = botoes[i];
                            var texto = (btn.textContent || btn.innerText || '').trim().toLowerCase();

                            // Verifica se contém "novo" e está visível
                            if (texto === 'novo' && btn.offsetWidth > 0 && btn.offsetHeight > 0) {
                                btn.scrollIntoView({block: 'center'});
                                btn.click();
                                return 'CLICADO_TEXTO_NOVO: ' + btn.id + ' ' + btn.tagName;
                            }
                        }
                        return 'NAO_ENCONTRADO';
                    """)
                    return resultado
                except Exception as e:
                    return f'FALHOU: {str(e)[:10]}'

            # Tentativa 1: Busca por class="nov"
            def tentativa_class_nov():
                try:
                    btn = driver.find_element(By.CSS_SELECTOR, "div.nov")
                    driver.execute_script("""
                        arguments[0].scrollIntoView({block: 'center'});
                        arguments[0].removeAttribute('disabled');
                        arguments[0].style.pointerEvents = 'auto';
                        arguments[0].click();
                    """, btn)
                    return 'CLICADO_CLASS_NOV'
                except Exception as e:
                    return f'FALHOU: {str(e)[:50]}'

            # Tentativa 2: Busca por onclick="cmdNova()"
            def tentativa_onclick_cmdnova():
                try:
                    btn = driver.find_element(By.XPATH, "//*[@onclick='cmdNova()']")
                    driver.execute_script("""
                        arguments[0].scrollIntoView({block: 'center'});
                        arguments[0].removeAttribute('disabled');
                        arguments[0].style.pointerEvents = 'auto';
                        arguments[0].click();
                    """, btn)
                    return 'CLICADO_ONCLICK_CMDNOVA'
                except Exception as e:
                    return f'FALHOU: {str(e)[:50]}'

            # Tentativa 3: Busca combinada class + id
            def tentativa_busca_combinada():
                try:
                    resultado = driver.execute_script("""
                        // Tenta múltiplos seletores
                        var btn = document.querySelector('div.nov#a_nov') ||
                                  document.querySelector('div.nov') ||
                                  document.querySelector('#a_nov') ||
                                  document.querySelector('[onclick*="cmdNova"]');

                        if (btn) {
                            btn.scrollIntoView({block: 'center'});
                            btn.removeAttribute('disabled');
                            btn.style.pointerEvents = 'auto';
                            btn.style.display = 'block';
                            btn.click();
                            return 'CLICADO_BUSCA_COMBINADA';
                        }
                        return 'NAO_ENCONTRADO';
                    """)
                    return resultado
                except Exception as e:
                    return f'FALHOU: {str(e)[:50]}'

            # Tentativa 4: WebDriverWait + clique Selenium normal
            def tentativa_xpath_selenium():
                try:
                    btn = WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.XPATH, "//*[@id='a_nov']"))
                    )
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                    time.sleep(0.5)

                    # Aguarda ser clicável
                    WebDriverWait(driver, 3).until(
                        EC.element_to_be_clickable((By.XPATH, "//*[@id='a_nov']"))
                    )
                    btn.click()
                    return 'CLICADO_XPATH_SELENIUM'
                except Exception as e:
                    return f'FALHOU: {str(e)[:50]}'

            # Tentativa 5: XPATH + JavaScript direto
            def tentativa_xpath_js():
                try:
                    btn = driver.find_element(By.XPATH, "//*[@id='a_nov']")
                    driver.execute_script("""
                        arguments[0].scrollIntoView({block: 'center'});
                        arguments[0].removeAttribute('disabled');
                        arguments[0].style.pointerEvents = 'auto';
                        arguments[0].style.display = 'block';
                        arguments[0].click();
                    """, btn)
                    return 'CLICADO_XPATH_JS'
                except Exception as e:
                    return f'FALHOU: {str(e)[:50]}'

            # Tentativa 6: MouseEvent via XPATH
            def tentativa_xpath_mouse_event():
                try:
                    resultado = driver.execute_script("""
                        var btn = document.evaluate("//*[@id='a_nov']", document, null,
                                                     XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                        if (btn) {
                            btn.scrollIntoView({block: 'center'});
                            var evento = new MouseEvent('click', {
                                bubbles: true,
                                cancelable: true,
                                view: window
                            });
                            btn.dispatchEvent(evento);
                            return 'CLICADO_MOUSE_EVENT';
                        }
                        return 'NAO_ENCONTRADO';
                    """)
                    return resultado
                except Exception as e:
                    return f'FALHOU: {str(e)[:50]}'

            # Tentativa 7: Busca dentro de div#divTarefas
            def tentativa_dentro_div_tarefas():
                try:
                    resultado = driver.execute_script("""
                        var container = document.getElementById('divTarefas');
                        if (container) {
                            var btn = container.querySelector('.nov') ||
                                     container.querySelector('#a_nov') ||
                                     container.querySelector('[onclick*="cmdNova"]');
                            if (btn) {
                                btn.scrollIntoView({block: 'center'});
                                btn.removeAttribute('disabled');
                                btn.click();
                                return 'CLICADO_DENTRO_DIV_TAREFAS';
                            }
                        }
                        return 'NAO_ENCONTRADO';
                    """)
                    return resultado
                except Exception as e:
                    return f'FALHOU: {str(e)[:50]}'

            # Tentativa 8: Função cmdNova direta
            def tentativa_cmd_nova():
                try:
                    resultado = driver.execute_script("""
                        if (typeof cmdNova === 'function') {
                            cmdNova();
                            return 'EXECUTADO_CMD_NOVA';
                        }
                        var btn = document.getElementById('a_nov');
                        if (btn && btn.onclick) {
                            btn.onclick();
                            return 'EXECUTADO_ONCLICK';
                        }
                        return 'FUNCAO_NAO_ENCONTRADA';
                    """)
                    return resultado
                except Exception as e:
                    return f'FALHOU: {str(e)[:50]}'

            tentativas = [
                ('Busca por texto "Novo" visível', tentativa_texto_novo),
                ('Busca por class="nov"', tentativa_class_nov),
                ('Busca por onclick="cmdNova()"', tentativa_onclick_cmdnova),
                ('Busca combinada (class + id + onclick)', tentativa_busca_combinada),
                ('XPATH Selenium WebDriverWait', tentativa_xpath_selenium),
                ('XPATH JavaScript direto', tentativa_xpath_js),
                ('XPATH MouseEvent', tentativa_xpath_mouse_event),
                ('Busca dentro div#divTarefas', tentativa_dentro_div_tarefas),
                ('Função cmdNova direta', tentativa_cmd_nova)
            ]

            for i, (nome, func) in enumerate(tentativas, 1):
                try:
                    print(f"  Tentativa {i} ({nome})...")
                    resultado = func()
                    print(f"    → Resultado: {resultado}")

                    if resultado and 'CLICADO' in str(resultado) or 'EXECUTADO' in str(resultado):
                        time.sleep(2)
                        # Verifica se modal abriu
                        try:
                            WebDriverWait(driver, 3).until(
                                EC.presence_of_element_located((By.XPATH, "//*[@id='_taReq']"))
                            )
                            print(f"  ✓✓✓ SUCESSO! Modal aberto na tentativa {i}: {nome}")
                            return True
                        except TimeoutException:
                            print(f"  ⚠ Clique executado mas modal não abriu (tentativa {i})")
                            continue
                except Exception as e:
                    print(f"  ✗ Erro na tentativa {i}: {e}")
                    continue

            print("  ✗✗✗ Todas as tentativas falharam")
            return False

        # Executa função de clique
        if not clicar_a_nov():
            print("⚠ AVISO: Não foi possível abrir o modal inicial após todas as tentativas")
            print("  O script continuará e tentará abrir o modal antes de cada tarefa")
        
        # Helper interno para clique robusto
        def tentar_clique_xpath(xpath_desc, xpath, timeout=20):
            try:
                alvo = WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.XPATH, xpath)))
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", alvo)
                time.sleep(1)
                # Verifica se está oculto (ex: style display none)
                if not alvo.is_displayed():
                    print(f"[AVISO] Elemento '{xpath_desc}' presente mas não visível. Tentando clique JS mesmo assim.")
                try:
                    WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, xpath)))
                except Exception:
                    pass
                try:
                    alvo.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", alvo)
                return True
            except Exception as e:
                print(f"[ERRO] Falha ao clicar '{xpath_desc}': {e}")
                return False

        for cod in lista_codigos:
            try:
                print(f"\nCriando tarefa para requisição {cod}...")

                # Usa a função robusta para abrir o modal
                print("  Abrindo modal de nova tarefa...")
                if not clicar_a_nov():
                    print("  ✗ Não foi possível abrir modal de nova tarefa. Pulando...")
                    continue

                print("  ✓ Modal aberto com sucesso!")
                
                time.sleep(3)
                
                # Campo requisição
                campo_req = wait.until(EC.visibility_of_element_located((By.XPATH, "//*[@id='_taReq']")))
                driver.execute_script("arguments[0].scrollIntoView(true);", campo_req)
                time.sleep(5)
                campo_req.clear()
                campo_req.send_keys(cod)
                time.sleep(5)
                
                # Botão tipo
                if not tentar_clique_xpath('tipo tarefa', "//*[@id='_taTpd2']", timeout=5):
                    print("  Tipo não encontrado (seguindo).")
                
                # Dropdown setor - Seleção de "Admissão"
                print("  Selecionando setor 'Admissão'...")
                setor_selecionado = False

                # Tentativa 1: Via JavaScript direto
                try:
                    resultado = driver.execute_script("""
                        var dropdown = document.getElementById('_taSet') || document.querySelector('[id*="taSet"]');

                        if (dropdown) {
                            // Se for um SELECT normal
                            if (dropdown.tagName === 'SELECT') {
                                dropdown.scrollIntoView({block: 'center'});

                                // Procura por opção com "Admissão"
                                var options = dropdown.options;
                                for (var i = 0; i < options.length; i++) {
                                    var texto = options[i].text.toLowerCase();
                                    if (texto.includes('admiss') || texto.includes('admissao') || texto.includes('admissão')) {
                                        dropdown.selectedIndex = i;
                                        dropdown.value = options[i].value;

                                        // Dispara eventos
                                        dropdown.dispatchEvent(new Event('change', { bubbles: true }));
                                        dropdown.dispatchEvent(new Event('input', { bubbles: true }));

                                        return 'SELECT_ADMISSAO_SELECIONADO: ' + options[i].text;
                                    }
                                }
                                return 'ADMISSAO_NAO_ENCONTRADA_NO_SELECT';
                            }

                            // Se for um dropdown customizado (bootstrap, etc)
                            dropdown.click();
                            return 'DROPDOWN_ABERTO';
                        }

                        return 'DROPDOWN_NAO_ENCONTRADO';
                    """)
                    print(f"    → Resultado método 1: {resultado}")

                    if 'SELECIONADO' in str(resultado):
                        setor_selecionado = True
                        print("  ✓ Setor 'Admissão' selecionado (método 1)")
                    elif 'DROPDOWN_ABERTO' in str(resultado):
                        # Dropdown customizado abriu, agora clica na opção
                        time.sleep(1)
                        opcoes = driver.find_elements(By.XPATH, "//li[contains(translate(text(), 'ADMISSÃO', 'admissao'), 'admiss')] | //li[contains(text(), 'Admiss')] | //li[contains(text(), 'admiss')]")

                        if opcoes:
                            driver.execute_script("arguments[0].scrollIntoView(true);", opcoes[0])
                            time.sleep(0.5)
                            driver.execute_script("arguments[0].click();", opcoes[0])
                            setor_selecionado = True
                            print(f"  ✓ Setor 'Admissão' selecionado (método 1 - dropdown customizado)")
                        else:
                            print("  ⚠ Opção 'Admissão' não encontrada no dropdown")
                except Exception as e:
                    print(f"  ✗ Erro no método 1: {e}")

                # Tentativa 2: Selenium Select (se for um SELECT nativo)
                if not setor_selecionado:
                    try:
                        from selenium.webdriver.support.ui import Select
                        print("  ⚠ Método 1 falhou. Tentando método 2 (Selenium Select)...")

                        dropdown = driver.find_element(By.ID, "_taSet")
                        select = Select(dropdown)

                        # Tenta selecionar por texto
                        for option in select.options:
                            if 'admiss' in option.text.lower():
                                select.select_by_visible_text(option.text)
                                setor_selecionado = True
                                print(f"  ✓ Setor '{option.text}' selecionado (método 2)")
                                break
                    except Exception as e:
                        print(f"  ✗ Método 2 falhou: {e}")

                # Tentativa 3: Clique no dropdown e busca ampla
                if not setor_selecionado:
                    try:
                        print("  ⚠ Método 2 falhou. Tentando método 3 (clique e busca ampla)...")

                        # Clica no dropdown
                        dropdown = driver.find_element(By.XPATH, "//*[@id='_taSet']")
                        driver.execute_script("arguments[0].scrollIntoView(true);", dropdown)
                        time.sleep(0.5)
                        driver.execute_script("arguments[0].click();", dropdown)
                        time.sleep(1)

                        # Busca opções de forma mais ampla
                        opcoes = driver.find_elements(By.XPATH,
                            "//li | //option | //div[contains(@class, 'option')] | //*[@role='option']"
                        )

                        for opcao in opcoes:
                            texto = opcao.text.lower()
                            if 'admiss' in texto and opcao.is_displayed():
                                driver.execute_script("arguments[0].scrollIntoView(true);", opcao)
                                time.sleep(0.5)
                                driver.execute_script("arguments[0].click();", opcao)
                                setor_selecionado = True
                                print(f"  ✓ Setor 'Admissão' selecionado (método 3)")
                                break

                    except Exception as e:
                        print(f"  ✗ Método 3 falhou: {e}")

                if not setor_selecionado:
                    print("  ✗✗✗ AVISO: Não foi possível selecionar o setor 'Admissão'!")
                else:
                    time.sleep(1)
                
                # Mensagem - com múltiplas tentativas
                print("  Preenchendo campo de mensagem...")
                mensagem_preenchida = False

                # Tentativa 1: XPATH padrão
                try:
                    msg_box = wait.until(EC.visibility_of_element_located((By.XPATH, "//textarea | //*[@id='_taMsg']")))
                    driver.execute_script("arguments[0].scrollIntoView(true);", msg_box)
                    time.sleep(1)
                    msg_box.clear()
                    msg_box.send_keys("solicitar assinatura do paciente")
                    mensagem_preenchida = True
                    print("  ✓ Mensagem preenchida (método 1)")
                except TimeoutException:
                    print("  ⚠ Método 1 falhou. Tentando método 2...")

                # Tentativa 2: Busca por placeholder ou label
                if not mensagem_preenchida:
                    try:
                        resultado = driver.execute_script("""
                            var mensagem = 'solicitar assinatura do paciente';

                            // Procura por textarea visível
                            var textareas = document.querySelectorAll('textarea');
                            for (var i = 0; i < textareas.length; i++) {
                                var ta = textareas[i];
                                if (ta.offsetWidth > 0 && ta.offsetHeight > 0) {
                                    ta.scrollIntoView({block: 'center'});
                                    ta.value = mensagem;
                                    // Dispara eventos de input
                                    ta.dispatchEvent(new Event('input', { bubbles: true }));
                                    ta.dispatchEvent(new Event('change', { bubbles: true }));
                                    return 'TEXTAREA_PREENCHIDO: ' + ta.id;
                                }
                            }

                            // Procura por _taMsg especificamente
                            var taMsg = document.getElementById('_taMsg') || document.querySelector('[id*="taMsg"]');
                            if (taMsg) {
                                taMsg.style.display = 'block';
                                taMsg.value = mensagem;
                                taMsg.dispatchEvent(new Event('input', { bubbles: true }));
                                taMsg.dispatchEvent(new Event('change', { bubbles: true }));
                                return 'TA_MSG_PREENCHIDO';
                            }

                            return 'CAMPO_NAO_ENCONTRADO';
                        """)
                        print(f"    → Resultado método 2: {resultado}")
                        if 'PREENCHIDO' in str(resultado):
                            mensagem_preenchida = True
                            print("  ✓ Mensagem preenchida (método 2)")
                    except Exception as e:
                        print(f"  ✗ Erro no método 2: {e}")

                # Tentativa 3: Selenium direto procurando qualquer textarea
                if not mensagem_preenchida:
                    try:
                        print("  ⚠ Método 2 falhou. Tentando método 3 (Selenium textarea)...")
                        msg_box = driver.find_element(By.TAG_NAME, "textarea")
                        driver.execute_script("arguments[0].scrollIntoView(true);", msg_box)
                        time.sleep(1)
                        driver.execute_script("arguments[0].value = 'solicitar assinatura do paciente';", msg_box)
                        driver.execute_script("""
                            arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
                            arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
                        """, msg_box)
                        mensagem_preenchida = True
                        print("  ✓ Mensagem preenchida (método 3)")
                    except Exception as e:
                        print(f"  ✗ Método 3 falhou: {e}")

                if not mensagem_preenchida:
                    print("  ✗✗✗ AVISO: Não foi possível preencher o campo de mensagem!")
                else:
                    time.sleep(1)
                
                # Botão confirmar
                try:
                    confirm_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "/html/body/div[13]/div[11]/div/button[1]/span[1] | //button[contains(@class,'btn-primary') and (contains(.,'Salvar') or contains(.,'Confirmar') or contains(.,'OK'))]")))
                    driver.execute_script("arguments[0].scrollIntoView(true);", confirm_btn)
                    time.sleep(5)
                    driver.execute_script("arguments[0].click();", confirm_btn)
                    time.sleep(5)
                    tarefas_criadas += 1
                    print(f"  ✓ Tarefa criada com sucesso!")
                except Exception as e:
                    print(f"  ⚠ Não foi possível confirmar: {e}")
                    # Tenta fechar modal
                    try:
                        close_btn = driver.find_element(By.XPATH, "//button[contains(.,'Cancelar') or contains(.,'Fechar') or contains(@class,'close')]")
                        driver.execute_script("arguments[0].click();", close_btn)
                        time.sleep(0.5)
                    except Exception:
                        pass
                        
            except Exception as e:
                print(f"  ✗ Erro ao processar {cod}: {e}")
                # Tenta fechar qualquer modal aberto
                try:
                    close_btn = driver.find_element(By.XPATH, "//button[contains(.,'Cancelar') or contains(.,'Fechar') or contains(@class,'close')]")
                    driver.execute_script("arguments[0].click();", close_btn)
                    time.sleep(0.5)
                except Exception:
                    pass
                    
        print(f"\n{'='*60}")
        print(f"Total de tarefas criadas: {tarefas_criadas}/{len(lista_codigos)}")
        print(f"{'='*60}")

        # Mantém o navegador aberto até o usuário confirmar
        print("\n⏸️  Navegador permanecerá aberto para você verificar as tarefas criadas.")
        input("Pressione ENTER para fechar o navegador e finalizar... ")

    except Exception as e:
        print(f"Erro geral na criação de tarefas: {e}")
        print("\n⏸️  Navegador permanecerá aberto para debug.")
        input("Pressione ENTER para fechar o navegador... ")
    finally:
        try:
            print("🔒 Fechando navegador...")
            driver.quit()
            print("✅ Navegador fechado com sucesso!")
        except Exception:
            pass

def analisar_assinaturas(data_str=None, prefixos=None, csv_saida=None):
    """Executa o fluxo completo:
    - Obtém requisições + imagens tipo 16 (com filtros opcionais)
    - Faz fallback sem data se filtro de data não retorna nada
    - Baixa imagens da AWS por código de requisição
    - Analisa cada imagem via Gemini para detectar assinatura
    - Gera relatório e CSV opcional

    Args:
        data_str (str|None): Data única no formato YYYY-MM-DD
        prefixos (list[str]|None): Lista de prefixos (ex ['0040','0085']) filtrando CodRequisicao
        csv_saida (str|None): Caminho para salvar CSV de resultados
    """
    conn = None
    resultados = []
    consulta_sem_data = False
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        if conn.is_connected():
            print("Conectado ao banco de dados MySQL.")
        cursor = conn.cursor(dictionary=True)

        # Montagem dinâmica da query
        base_select = (
            "SELECT r.IdRequisicao, r.CodRequisicao, r.NumExterno, r.IdLocalOrigem, r.IdConvenio, "
            "COALESCE(NULLIF(TRIM(fi.NomFantasia), ''), NULLIF(TRIM(fi.RazaoSocial), '')) AS NomLocalOrigem, "
            "ri.NomArquivo, ri.Tipo, ri.DtaImg FROM requisicao r "
            "INNER JOIN requisicaoimagem ri ON r.IdRequisicao = ri.IdRequisicao "
            "LEFT JOIN fatinstituicao fi ON fi.IdInstituicao = r.IdLocalOrigem "
            "WHERE ri.Tipo = 16 AND ri.Inativo = 0 AND r.IdConvenio = %s"
        )

        params = [ID_CONVENIO_FIXO]
        if FILTRAR_APENAS_PDF:
            base_select += " AND ri.NomArquivo LIKE %s"
            params.append("%.pdf")
        if data_str:
            try:
                # Tenta primeiro formato brasileiro DD/MM/YYYY
                if '/' in data_str:
                    data_final = datetime.strptime(data_str, "%d/%m/%Y").date()
                else:
                    data_final = datetime.strptime(data_str, "%Y-%m-%d").date()

                # Busca o dia informado + 2 dias anteriores (total de 3 dias)
                data_inicial = data_final - timedelta(days=2)
                base_select += " AND DATE(ri.DtaImg) BETWEEN %s AND %s"
                params.extend([data_inicial, data_final])
                print(f"Filtro de data aplicado: buscando imagens de {data_inicial.strftime('%d/%m/%Y')} até {data_final.strftime('%d/%m/%Y')}")
            except ValueError:
                print("Formato de data inválido. Use DD/MM/YYYY ou YYYY-MM-DD. Ignorando filtro de data.")
        else:
            print("Sem filtro de data: analisando todas as imagens tipo 16.")

        if prefixos:
            prefix_condicoes = []
            for p in prefixos:
                prefix_condicoes.append("r.CodRequisicao LIKE %s")
                params.append(p + "%")
            if prefix_condicoes:
                base_select += " AND (" + " OR ".join(prefix_condicoes) + ")"
                print(f"Filtro de prefixos aplicado: {', '.join(prefixos)}")

        # Adiciona limite de 50 registros para teste
        base_select += " LIMIT 10"

        # Executa consulta inicial
        cursor.execute(base_select, tuple(params))
        resultados = cursor.fetchall()

        # Fallback sem filtro de data caso não traga registros
        if data_str and not resultados:
            print("Nenhum registro encontrado neste intervalo. Tentando novamente sem filtro de data...")
            consulta_sem_data = True
            # Reconstrói consulta sem a cláusula de data
            base_select_sem_data = base_select.replace(" AND DATE(ri.DtaImg) BETWEEN %s AND %s", "")
            # Remove as duas datas adicionadas ao final de params (data_inicial e data_final)
            params_sem_data = params[:-2]
            cursor.execute(base_select_sem_data, tuple(params_sem_data))
            resultados = cursor.fetchall()

        if not resultados:
            print("Nenhuma imagem tipo 16 encontrada conforme filtros.")
            return

        print(f"Total de registros encontrados: {len(resultados)}")
        
        # Limite e validação de lotes removidos.

        # Diagnóstico por prefixo de CodRequisicao
        cont_prefixo = Counter()
        for rrow in resultados:
            cod = rrow['CodRequisicao']
            prefix_match = next((p for p in URLS_AWS.keys() if cod.startswith(p)), 'outros')
            cont_prefixo[prefix_match] += 1
        print("\nDistribuição por prefixo:")
        for pref, qtd in cont_prefixo.most_common():
            print(f"  {pref}: {qtd}")

        # ETAPA 1: Download AWS
        print("\n--- DOWNLOAD DAS IMAGENS NA AWS ---")
        novos_arquivos_set = baixar_imagens_do_banco(resultados)

        # ETAPA 2: Análise Gemini
        print("\n--- ANÁLISE DE ASSINATURAS COM GEMINI ---")
        resultados_assinatura = []  # Para eventual CSV
        locais_sem_assinatura = []

        # Mapeia TODOS os arquivos do diretório (não apenas os recém-baixados)
        print("📂 Verificando arquivos disponíveis no diretório...")
        arquivos_disponiveis = {}
        if os.path.exists(DIRETORIO_IMAGENS):
            for arquivo in os.listdir(DIRETORIO_IMAGENS):
                caminho_completo = os.path.join(DIRETORIO_IMAGENS, arquivo)
                if os.path.isfile(caminho_completo):
                    # Remove extensão para fazer match com NomArquivo
                    nome_base = os.path.splitext(arquivo)[0]
                    arquivos_disponiveis[nome_base] = arquivo
                    arquivos_disponiveis[arquivo] = arquivo  # Adiciona também com extensão

        print(f"📁 Total de arquivos no diretório: {len(set(arquivos_disponiveis.values()))}")
        print(f"🔍 Total de registros para analisar: {len(resultados)}")
        if FILTRAR_APENAS_PDF and not ANALISAR_PDF:
            print("Modo somente PDF ativo: análise de assinatura ignorada.")
        if ANALISAR_PDF:
            if not PYMUPDF_OK:
                print("Aviso: ANALISAR_PDF ativo mas PyMuPDF não está instalado. Execute 'pip install PyMuPDF'. PDFs serão ignorados.")
            else:
                print("Conversão de PDFs para imagem habilitada (primeira página).")
        
        for linha in resultados:
            nome_arquivo = linha['NomArquivo']
            cod_req = linha['CodRequisicao']
            local_origem = str(linha.get('NomLocalOrigem') or '').strip() or 'Desconhecido'

            # Busca qualquer arquivo que comece com o código da requisição
            # Exemplo: Para requisição "0085011162008" com NomArquivo "0085011162008_2"
            # Pode encontrar "0085011162008_1.jpg" que foi baixado da AWS
            codigo_base = nome_arquivo.split('_')[0] if '_' in nome_arquivo else nome_arquivo
            arquivo_real = None

            # Procura por arquivo que comece com o código base
            for nome_disp in arquivos_disponiveis.keys():
                if nome_disp.startswith(codigo_base):
                    arquivo_real = arquivos_disponiveis[nome_disp]
                    break

            # Se não encontrou, tenta busca exata
            if not arquivo_real:
                nome_base = os.path.splitext(nome_arquivo)[0]
                arquivo_real = arquivos_disponiveis.get(nome_base, arquivos_disponiveis.get(nome_arquivo, None))

            if not arquivo_real:
                # Arquivo não encontrado
                resultados_assinatura.append({
                    'CodRequisicao': cod_req,
                    'NomArquivo': nome_arquivo,
                    'LocalOrigem': local_origem,
                    'TemAssinatura': 'ARQUIVO_NAO_ENCONTRADO'
                })
                continue

            caminho = os.path.join(DIRETORIO_IMAGENS, arquivo_real)
            
            # Caso seja PDF e análise habilitada, converter primeira página
            if nome_arquivo.lower().endswith('.pdf'):
                if ANALISAR_PDF:
                    caminho_pdf = caminho
                    img_conv = converter_pdf_para_imagem_primeira_pagina(caminho_pdf)
                    if img_conv and os.path.exists(img_conv):
                        caminho = img_conv
                    else:
                        resultados_assinatura.append({
                            'CodRequisicao': cod_req,
                            'NomArquivo': nome_arquivo,
                            'LocalOrigem': local_origem,
                            'TemAssinatura': 'IGNORADO'
                        })
                        continue
                else:
                    resultados_assinatura.append({
                        'CodRequisicao': cod_req,
                        'NomArquivo': nome_arquivo,
                        'LocalOrigem': local_origem,
                        'TemAssinatura': 'IGNORADO'
                    })
                    continue

            if not os.path.exists(caminho):
                resultados_assinatura.append({
                    'CodRequisicao': cod_req,
                    'NomArquivo': nome_arquivo,
                    'LocalOrigem': local_origem,
                    'TemAssinatura': 'ARQUIVO_NAO_ENCONTRADO'
                })
                continue

            tem_assinatura = analisar_imagem_com_gemini(caminho)
            resultados_assinatura.append({
                'CodRequisicao': cod_req,
                'NomArquivo': nome_arquivo,
                'LocalOrigem': local_origem,
                'TemAssinatura': 'SIM' if tem_assinatura else 'NAO'
            })
            if not tem_assinatura:
                locais_sem_assinatura.append(local_origem)

        print("\n" + "="*80)
        print("📊 RESULTADO DA ANÁLISE DE ASSINATURAS")
        print("="*80)

        total_analisados = len(resultados)
        total_com_assinatura = sum(1 for r in resultados_assinatura if r['TemAssinatura'] == 'SIM')
        total_sem_assinatura = sum(1 for r in resultados_assinatura if r['TemAssinatura'] == 'NAO')
        total_nao_encontrado = sum(1 for r in resultados_assinatura if r['TemAssinatura'] == 'ARQUIVO_NAO_ENCONTRADO')
        total_ignorado = sum(1 for r in resultados_assinatura if r['TemAssinatura'] == 'IGNORADO')

        print(f"\n📈 RESUMO GERAL:")
        print(f"  • Total de registros no banco: {total_analisados}")
        print(f"  • Total de arquivos analisados: {len(resultados_assinatura)}")
        print(f"  • ✅ COM assinatura: {total_com_assinatura}")
        print(f"  • ❌ SEM assinatura: {total_sem_assinatura}")
        print(f"  • ⚠️  Arquivo não encontrado: {total_nao_encontrado}")
        if total_ignorado > 0:
            print(f"  • 🔸 Ignorados (PDF não analisado): {total_ignorado}")

        # Detalhamento das imagens COM assinatura
        if total_com_assinatura > 0:
            print(f"\n✅ IMAGENS COM ASSINATURA ({total_com_assinatura}):")
            com_assinatura = [r for r in resultados_assinatura if r['TemAssinatura'] == 'SIM']
            for idx, img in enumerate(com_assinatura, 1):
                print(f"  {idx:3d}. {img['CodRequisicao']:15s} | {img['NomArquivo']:40s} | Local: {img['LocalOrigem']}")

        # Detalhamento das imagens SEM assinatura
        if total_sem_assinatura > 0:
            print(f"\n❌ IMAGENS SEM ASSINATURA ({total_sem_assinatura}):")
            sem_assinatura = [r for r in resultados_assinatura if r['TemAssinatura'] == 'NAO']
            for idx, img in enumerate(sem_assinatura, 1):
                print(f"  {idx:3d}. {img['CodRequisicao']:15s} | {img['NomArquivo']:40s} | Local: {img['LocalOrigem']}")

        # Estatísticas por local
        if locais_sem_assinatura:
            print(f"\n📍 ESTATÍSTICA POR LOCAL (sem assinatura):")
            contagem = Counter(locais_sem_assinatura)
            for local, qtd in contagem.most_common():
                percentual = (qtd / total_sem_assinatura) * 100
                print(f"  • {local}: {qtd} ({percentual:.1f}%)")
            pior_local, faltas = contagem.most_common(1)[0]
            print(f"\n  🔴 Local com mais faltas: {pior_local} ({faltas} imagens)")

        # Arquivos não encontrados
        if total_nao_encontrado > 0:
            print(f"\n⚠️  ARQUIVOS NÃO ENCONTRADOS ({total_nao_encontrado}):")
            nao_encontrados = [r for r in resultados_assinatura if r['TemAssinatura'] == 'ARQUIVO_NAO_ENCONTRADO']
            for idx, img in enumerate(nao_encontrados, 1):
                print(f"  {idx:3d}. {img['CodRequisicao']:15s} | {img['NomArquivo']:40s} | Local: {img['LocalOrigem']}")

        print("\n" + "="*80)

        if csv_saida:
            try:
                with open(csv_saida, 'w', newline='', encoding='utf-8') as fcsv:
                    campos = ['CodRequisicao','NomArquivo','LocalOrigem','TemAssinatura']
                    writer = csv.DictWriter(fcsv, fieldnames=campos)
                    writer.writeheader()
                    writer.writerows(resultados_assinatura)
                print(f"CSV salvo em: {csv_saida}")
            except Exception as e:
                print(f"Falha ao salvar CSV: {e}")

        if consulta_sem_data:
            print("(Aviso) Resultado exibido sem filtro de data devido ausência de registros na data informada.")

        # Criação automática de tarefas para requisições sem assinatura
        requisicoes_sem_assinatura = [r['CodRequisicao'] for r in resultados_assinatura if r['TemAssinatura'] == 'NAO']

        if requisicoes_sem_assinatura:
            print(f"\n{'='*70}")
            print(f"📋 REQUISIÇÕES SEM ASSINATURA DO PACIENTE")
            print(f"{'='*70}")
            print(f"Total encontrado: {len(requisicoes_sem_assinatura)} requisições\n")

            # Mostra a lista de requisições sem assinatura
            print("Lista de requisições:")
            for idx, cod_req in enumerate(requisicoes_sem_assinatura, 1):
                # Busca informações adicionais da requisição
                info = next((r for r in resultados_assinatura if r['CodRequisicao'] == cod_req), None)
                local = info['LocalOrigem'] if info else 'N/A'
                print(f"  {idx:3d}. {cod_req} - Local: {local}")

            print(f"\n{'='*70}")
            print(f"⚠️  IMPORTANTE: Estas requisições precisam de assinatura do paciente!")
            print(f"{'='*70}")

            # Confirmação do usuário
            resposta = input("\n❓ Deseja criar tarefas no APLIS para estas requisições? (S/N): ").strip().upper()

            if resposta == 'S' or resposta == 'SIM':
                print(f"\n{'='*70}")
                print(f"🚀 CRIAÇÃO DE TAREFAS NO APLIS")
                print(f"{'='*70}")
                print(f"Abrindo sistema APLIS para criar {len(requisicoes_sem_assinatura)} tarefas...\n")
                criar_tarefas_sistema_aplis(requisicoes_sem_assinatura)
            else:
                print("\n❌ Criação de tarefas cancelada pelo usuário.")
                print("   As requisições sem assinatura foram listadas acima para referência.")
        else:
            print(f"\n{'='*70}")
            print("✅ Todas as requisições analisadas possuem assinatura do paciente.")
            print("   Nenhuma tarefa precisa ser criada.")
            print(f"{'='*70}")

    except mysql.connector.Error as e:
        print(f"Erro MySQL: {e}")
    except Exception as e:
        print(f"Erro inesperado: {e}")
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()
            print("\nConexão encerrada.")

def parse_args():
    parser = argparse.ArgumentParser(
        description="Analisa assinaturas em imagens tipo 16 (convênio 1040) com intervalo de data -2 dias.",
        epilog="Exemplo: python analise_sql_assinaturas.py --data 19/11/2025 --prefixos 0085"
    )
    parser.add_argument('--data', help='Data base (DD/MM/YYYY ou YYYY-MM-DD). Usa data de hoje se não informar.', required=False)
    parser.add_argument('--prefixos', help='Lista de prefixos separados por vírgula (ex: 0040,0085)', required=False)
    parser.add_argument('--csv', help='Salvar resultado em CSV (caminho)', required=False)
    parser.add_argument('--apenas-pdf', action='store_true', help='Filtrar somente arquivos PDF do convenio 1040')
    parser.add_argument('--analisar-pdf', action='store_true', help='Converter primeira página do PDF em imagem e analisar assinatura')
    return parser.parse_args()

if __name__ == '__main__':
    args = parse_args()
    
    # Se não informou data, pergunta ao usuário
    data_para_usar = args.data
    if not data_para_usar:
        from datetime import date
        hoje = date.today()
        print(f"\n{'='*60}")
        print(f"Data de hoje: {hoje.strftime('%d/%m/%Y')}")
        print(f"{'='*60}")
        data_input = input("Digite a data (DD/MM/YYYY) ou pressione ENTER para usar hoje: ").strip()
        
        if data_input:
            data_para_usar = data_input
            print(f"✓ Usando data informada: {data_para_usar}\n")
        else:
            data_para_usar = hoje.strftime("%d/%m/%Y")
            print(f"✓ Usando data de hoje: {data_para_usar}\n")
    
    # Ajusta flags globais
    if args.apenas_pdf:
        FILTRAR_APENAS_PDF = True
    if args.analisar_pdf:
        ANALISAR_PDF = True

    prefix_list = [p.strip() for p in args.prefixos.split(',')] if args.prefixos else None
    analisar_assinaturas(
        data_str=data_para_usar,
        prefixos=prefix_list,
        csv_saida=args.csv
    )
