"""
Script de Teste - Requisição 0040000356004
==========================================
Executa testes graduais na integração APLIS + Autentique.

Uso:
    python test_requisicao.py

Preencha o arquivo .env (ou configure as variáveis abaixo) antes de rodar.
"""

import sys
import os
import json
import base64
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

# ==================== CONFIGURAÇÃO DE TESTE ====================
COD_REQUISICAO = "0040000356004"

# UUID do documento no Autentique (preencha após enviar o documento)
AUTENTIQUE_UUID_TESTE = os.getenv("AUTENTIQUE_UUID_TESTE", "")

# PDF de teste (cria um PDF mínimo em memória se não informar caminho)
PDF_TESTE_PATH = os.getenv("PDF_TESTE_PATH", "")


# ==================== HELPERS ====================

def separador(titulo: str):
    print("\n" + "=" * 60)
    print(f"  {titulo}")
    print("=" * 60)


def resultado(ok: bool, msg: str):
    icone = "[OK]" if ok else "[ERR]"
    print(f"  {icone} {msg}")
    return ok


def criar_pdf_minimo() -> bytes:
    """Cria um PDF mínimo válido em memória para testes."""
    conteudo = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<<>>>>endobj\n"
        b"xref\n0 4\n0000000000 65535 f\n"
        b"0000000009 00000 n\n"
        b"0000000058 00000 n\n"
        b"0000000115 00000 n\n"
        b"trailer<</Size 4/Root 1 0 R>>\n"
        b"startxref\n199\n%%EOF"
    )
    return conteudo


# ==================== TESTES ====================

def teste_1_conexao_aplis():
    """TESTE 1: Verificar se a API APLIS responde."""
    separador("TESTE 1: Conexão com APLIS")

    from config_ws import APLIS_API_URL, APLIS_USER
    print(f"  URL:   {APLIS_API_URL}")
    print(f"  User:  {APLIS_USER or '(não configurado)'}")

    if not APLIS_USER:
        print("  ⚠ Configure APLIS_USER e APLIS_PASS no arquivo .env")
        return False

    from aplis_client import AplisClient
    client = AplisClient()
    ok = client.login()

    if ok:
        resultado(True, "Login na API APLIS bem-sucedido")
        client.logout()
    else:
        resultado(False, "Falha no login — verifique APLIS_USER, APLIS_PASS e APLIS_BASE_URL")

    return ok


def teste_2_status_requisicao():
    """TESTE 2: Consultar status da requisição de teste."""
    separador(f"TESTE 2: Status da Requisição {COD_REQUISICAO}")

    from aplis_client import AplisClient
    client = AplisClient()

    if not client.login():
        resultado(False, "Sem login — pulando teste")
        return False

    status = client.requisicao_status(COD_REQUISICAO)
    client.logout()

    if status.get("sucesso") == 1:
        historico = status.get("historico", [])
        ultimo = historico[-1] if historico else {}
        resultado(True, f"Requisição encontrada")
        print(f"  Admissão:  {status.get('dtaAdmissao', '—')}")
        print(f"  Prevista:  {status.get('dtaPrevista', '—')}")
        print(f"  Status:    {ultimo.get('descricao', '—')} ({ultimo.get('data', '—')})")
        return True
    else:
        resultado(False, f"[{status.get('codErro')}] {status.get('msgErro')}")
        return False


def teste_3_anexar_pdf_teste():
    """TESTE 3: Anexar um PDF de teste à requisição."""
    separador(f"TESTE 3: Anexar PDF à Requisição {COD_REQUISICAO}")

    if PDF_TESTE_PATH and os.path.exists(PDF_TESTE_PATH):
        print(f"  Usando PDF: {PDF_TESTE_PATH}")
        with open(PDF_TESTE_PATH, "rb") as f:
            pdf_bytes = f.read()
    else:
        print("  Usando PDF mínimo gerado em memória (para validar a chamada API)")
        pdf_bytes = criar_pdf_minimo()

    print(f"  Tamanho PDF: {len(pdf_bytes) / 1024:.1f} KB")

    from aplis_client import AplisClient
    client = AplisClient()

    if not client.login():
        resultado(False, "Sem login — pulando teste")
        return False

    resp = client.anexar_guia_assinada(COD_REQUISICAO, pdf_bytes)
    client.logout()

    if resp.get("sucesso") == 1:
        resultado(True, f"PDF anexado com sucesso")
        print(f"  codRequisicao: {resp.get('codRequisicao')}")
        print(f"  dtaPrevista:   {resp.get('dtaPrevista', '—')}")
        print(f"  idEvento:      {resp.get('idEvento', '—')}")
        return True
    else:
        resultado(False, f"[{resp.get('codErro')}] {resp.get('msgErro')}")
        print("  ⚠ Se o erro for de campos obrigatórios, configure os campos extras em aplis_client.py")
        print("    (idUnidade, idConvenio, idFontePagadora, idMedico, idExame, examesConvenio)")
        return False


def teste_4_autentique():
    """TESTE 4: Consultar documento no Autentique pelo UUID."""
    separador("TESTE 4: Consulta Autentique")

    from config_ws import AUTENTIQUE_TOKEN
    if not AUTENTIQUE_TOKEN:
        resultado(False, "AUTENTIQUE_TOKEN não configurado no .env")
        return False

    if not AUTENTIQUE_UUID_TESTE:
        print("  ⚠ AUTENTIQUE_UUID_TESTE não configurado. Pulando.")
        print("    Configure a variável de ambiente ou edite o script.")
        return None

    from autentique_client import buscar_documento
    doc = buscar_documento(AUTENTIQUE_UUID_TESTE)

    if doc.get("sucesso"):
        resultado(True, f"Documento encontrado: {doc.get('nome')}")
        print(f"  Status:         {doc.get('status')}")
        print(f"  Todos assinaram: {doc.get('todos_assinaram')}")
        print(f"  URL PDF:        {doc.get('url_assinado', '—')[:60]}...")
        return True
    else:
        resultado(False, f"Erro: {doc.get('erro')}")
        return False


def teste_5_fluxo_completo():
    """TESTE 5: Fluxo completo — busca PDF assinado no Autentique e anexa ao APLIS."""
    separador("TESTE 5: Fluxo Completo")

    if not AUTENTIQUE_UUID_TESTE:
        print("  ⚠ AUTENTIQUE_UUID_TESTE não configurado. Pulando.")
        return None

    from autentique_client import buscar_documento, baixar_pdf_assinado
    from aplis_client import AplisClient

    # Busca documento no Autentique
    doc = buscar_documento(AUTENTIQUE_UUID_TESTE)
    if not doc.get("sucesso"):
        resultado(False, f"Autentique: {doc.get('erro')}")
        return False

    if not doc.get("todos_assinaram"):
        resultado(False, "Documento ainda não foi assinado por todos")
        print(f"  Status atual: {doc.get('status')}")
        return False

    # Download do PDF
    url = doc.get("url_assinado", "")
    pdf_bytes = baixar_pdf_assinado(url)
    if not pdf_bytes:
        resultado(False, "Falha ao baixar o PDF assinado")
        return False

    resultado(True, f"PDF baixado ({len(pdf_bytes)/1024:.1f} KB)")

    # Salva localmente
    from config_ws import PASTA_GUIAS_ASSINADAS
    os.makedirs(PASTA_GUIAS_ASSINADAS, exist_ok=True)
    nome = f"TESTE_{COD_REQUISICAO}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_assinado.pdf"
    caminho = os.path.join(PASTA_GUIAS_ASSINADAS, nome)
    with open(caminho, "wb") as f:
        f.write(pdf_bytes)
    print(f"  Salvo em: {caminho}")

    # Anexa no APLIS
    client = AplisClient()
    if not client.login():
        resultado(False, "Sem login APLIS — fluxo interrompido")
        return False

    resp = client.anexar_guia_assinada(COD_REQUISICAO, pdf_bytes)
    client.logout()

    if resp.get("sucesso") == 1:
        resultado(True, "Guia assinada anexada no APLIS com sucesso!")
        return True
    else:
        resultado(False, f"Falha APLIS: [{resp.get('codErro')}] {resp.get('msgErro')}")
        return False


# ==================== MAIN ====================

def main():
    print("\n" + "=" * 60)
    print("  TESTES - INTEGRAÇÃO APLIS + AUTENTIQUE")
    print(f"  Requisição de teste: {COD_REQUISICAO}")
    print(f"  Data: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print("=" * 60)

    resultados = {}

    # Roda os testes sequencialmente
    for num, fn in enumerate([teste_1_conexao_aplis, teste_2_status_requisicao,
                               teste_3_anexar_pdf_teste, teste_4_autentique,
                               teste_5_fluxo_completo], 1):
        try:
            resultados[num] = fn()
        except Exception as e:
            resultados[num] = False
            print(f"\n  ✗ EXCEÇÃO no teste {num}: {e}")

    # Resumo
    separador("RESUMO DOS TESTES")
    nomes = {
        1: "Conexão APLIS",
        2: f"Status req. {COD_REQUISICAO}",
        3: "Anexar PDF (teste)",
        4: "Consulta Autentique",
        5: "Fluxo Completo",
    }
    for num, ok in resultados.items():
        if ok is None:
            icon = ">>"
            status = "PULADO"
        elif ok:
            icon = "[OK]"
            status = "OK"
        else:
            icon = "[ERR]"
            status = "FALHOU"
        print(f"  {icon} Teste {num}: {nomes[num]:<35} {status}")

    total_ok = sum(1 for v in resultados.values() if v is True)
    total_falha = sum(1 for v in resultados.values() if v is False)
    print(f"\n  Resultado: {total_ok} OK | {total_falha} FALHA")
    print("=" * 60)

    # Configuração necessária
    print("\n  LISTA DE TAREFAS:")
    print("  1. Crie o arquivo .env em ws_aplis/ com:")
    print("     APLIS_BASE_URL=https://seu-laboratorio.aplis.inf.br")
    print("     APLIS_USER=seu_usuario")
    print("     APLIS_PASS=sua_senha")
    print("     APLIS_ID_LABORATORIO=1")
    print("     AUTENTIQUE_TOKEN=seu_token_aqui")
    print("     AUTENTIQUE_WEBHOOK_SECRET=seu_secret_aqui")
    print("     PASTA_GUIAS_ASSINADAS=C:\\guias_assinadas")
    print("  2. Configure o webhook no painel Autentique:")
    print(f"     URL: http://seu-servidor:8000/api/webhooks/autentique")
    print("  3. Rode o servidor: python webhook_server.py")
    print()


if __name__ == "__main__":
    main()
