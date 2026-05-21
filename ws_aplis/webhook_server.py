"""
WebService - Integração APLIS + Autentique
Gerencia o ciclo de vida das guias assinadas:
  POST /api/webhooks/autentique   → Listener passivo (Autentique chama quando assina)
  POST /api/requisicoes/{cod}/atualizar-assinatura → Sync manual por UUID
  GET  /api/requisicoes/{cod}/status              → Status da assinatura local
  GET  /api/requisicoes             → Lista todas as requisições rastreadas
  GET  /                            → Dashboard HTML
"""

import os
import sys
import json
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

sys.path.insert(0, str(Path(__file__).parent))

from config_ws import AUTENTIQUE_WEBHOOK_SECRET, WS_HOST, WS_PORT, PASTA_GUIAS_ASSINADAS
from aplis_client import get_client
from autentique_client import (
    buscar_documento, baixar_pdf_assinado,
    validar_webhook_secret, parse_webhook_payload,
)
import db_local

app = FastAPI(
    title="WS Guias Assinadas - APLIS + Autentique",
    version="1.0.0",
    docs_url="/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs(PASTA_GUIAS_ASSINADAS, exist_ok=True)


# ==================== CORE: processar guia assinada ====================

async def _processar_guia(cod_requisicao: str, url_pdf: str, uuid_doc: str) -> dict:
    """
    Fluxo principal:
    1. Baixa PDF assinado do Autentique
    2. Salva localmente
    3. Envia para APLIS via admissaoSalvar
    4. Atualiza status no DB local
    """
    # 1. Download do PDF
    pdf_bytes = baixar_pdf_assinado(url_pdf)
    if not pdf_bytes:
        db_local.atualizar_erro(cod_requisicao, f"Falha ao baixar PDF do Autentique: {url_pdf}")
        return {"sucesso": False, "erro": "Falha ao baixar PDF assinado"}

    # 2. Salvar localmente
    nome_arquivo = f"{cod_requisicao}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_assinado.pdf"
    caminho_local = os.path.join(PASTA_GUIAS_ASSINADAS, nome_arquivo)
    with open(caminho_local, "wb") as f:
        f.write(pdf_bytes)
    print(f"💾 PDF salvo em: {caminho_local}")

    # 3. Anexar no APLIS
    client = get_client()
    resultado = client.anexar_guia_assinada(cod_requisicao, pdf_bytes)

    if resultado.get("sucesso") == 1:
        db_local.atualizar_assinado(cod_requisicao, caminho_local)
        return {
            "sucesso": True,
            "codRequisicao": cod_requisicao,
            "caminho_guia": caminho_local,
            "aplis_resposta": resultado,
        }
    else:
        erro = f"[{resultado.get('codErro')}] {resultado.get('msgErro')}"
        db_local.atualizar_erro(cod_requisicao, f"APLIS admissaoSalvar falhou: {erro}")
        return {"sucesso": False, "erro": f"Falha ao anexar no APLIS: {erro}"}


# ==================== ENDPOINTS ====================

@app.post("/api/webhooks/autentique")
async def webhook_autentique(
    request: Request,
    x_autentique_secret: str = Header(default=""),
):
    """
    Endpoint passivo — o Autentique chama aqui quando o documento é assinado.
    Configure no painel Autentique: Webhooks → apontar para esta URL.
    """
    # Valida token secreto
    if not validar_webhook_secret(x_autentique_secret, AUTENTIQUE_WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Token de webhook inválido")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Payload JSON inválido")

    print(f"\n📬 Webhook Autentique recebido: {json.dumps(payload, indent=2)[:300]}...")

    dados = parse_webhook_payload(payload)
    uuid_doc = dados.get("uuid", "")
    status = dados.get("status", "").upper()
    url_assinado = dados.get("url_assinado", "")

    # Só processa se o status for SIGNED
    if status not in ("SIGNED", "CONCLUIDO", "FINALIZADO"):
        return JSONResponse({"aceito": True, "acao": "ignorado", "status": status})

    # Busca qual requisição corresponde a esse UUID
    cod_req, _ = db_local.buscar_por_uuid(uuid_doc)
    if not cod_req:
        print(f"⚠ UUID {uuid_doc} não encontrado no DB local. Ignorando.")
        return JSONResponse({"aceito": True, "acao": "uuid_nao_mapeado"})

    if not url_assinado:
        # Busca URL no Autentique diretamente
        doc = buscar_documento(uuid_doc)
        url_assinado = doc.get("url_assinado", "")

    if not url_assinado:
        db_local.atualizar_erro(cod_req, "Webhook recebido mas sem URL do PDF assinado")
        return JSONResponse({"sucesso": False, "erro": "Sem URL do PDF assinado"})

    resultado = await _processar_guia(cod_req, url_assinado, uuid_doc)
    return JSONResponse(resultado)


@app.post("/api/requisicoes/{cod_requisicao}/atualizar-assinatura")
async def atualizar_assinatura_manual(cod_requisicao: str, request: Request):
    """
    Sync manual — o usuário clica em 'Atualizar Status' ou passa o UUID Autentique.
    Body JSON (opcional): {"uuid_autentique": "..."}
    """
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    uuid_doc = body.get("uuid_autentique", "")

    # Tenta buscar UUID do DB local se não foi passado
    if not uuid_doc:
        registro = db_local.buscar(cod_requisicao)
        if registro:
            uuid_doc = registro.get("autentique_document_id", "")

    # Fallback: Se não achou no DB local (comum no Vercel), tenta buscar na API do Autentique pelo nome (que contém a requisição)
    if not uuid_doc:
        print(f"🔍 UUID não encontrado no DB local para {cod_requisicao}. Buscando na API do Autentique...")
        from autentique_client import buscar_documentos_por_nome
        docs_encontrados = buscar_documentos_por_nome(cod_requisicao)
        if docs_encontrados:
            # Pega o mais recente que combine com a requisição
            uuid_doc = docs_encontrados[0].get("id")
            print(f"✅ Encontrado no Autentique: {uuid_doc}")
            # Registra localmente para a próxima vez
            db_local.registrar_envio(cod_requisicao, uuid_doc)

    if not uuid_doc:
        raise HTTPException(
            status_code=400,
            detail="Informe uuid_autentique no body ou registre a requisição primeiro",
        )

    print(f"\n🔄 Sync manual: requisição {cod_requisicao} | UUID {uuid_doc}")

    doc = buscar_documento(uuid_doc)
    if not doc.get("sucesso"):
        raise HTTPException(status_code=502, detail=f"Erro ao consultar Autentique: {doc.get('erro')}")

    if not doc.get("todos_assinaram"):
        return JSONResponse({
            "sucesso": False,
            "status": "pendente",
            "mensagem": "Documento ainda não foi assinado por todos",
            "assinantes": doc.get("assinantes", []),
        })

    url_assinado = doc.get("url_assinado", "")
    resultado = await _processar_guia(cod_requisicao, url_assinado, uuid_doc)
    return JSONResponse(resultado)


@app.get("/api/requisicoes/{cod_requisicao}/status")
async def status_requisicao(cod_requisicao: str):
    """Retorna o status de assinatura local da requisição."""
    registro = db_local.buscar(cod_requisicao)
    if not registro:
        raise HTTPException(status_code=404, detail="Requisição não encontrada no sistema local")
    return JSONResponse({"codRequisicao": cod_requisicao, **registro})


@app.post("/api/requisicoes/{cod_requisicao}/registrar")
async def registrar_requisicao(cod_requisicao: str, request: Request):
    """
    Registra o vínculo entre uma requisição e seu documento no Autentique.
    Body: {"uuid_autentique": "..."}
    """
    body = await request.json()
    uuid_doc = body.get("uuid_autentique", "")
    if not uuid_doc:
        raise HTTPException(status_code=400, detail="uuid_autentique é obrigatório")

    db_local.registrar_envio(cod_requisicao, uuid_doc)
    return JSONResponse({"sucesso": True, "codRequisicao": cod_requisicao, "uuid_autentique": uuid_doc})


@app.get("/api/requisicoes")
async def listar_requisicoes():
    """Lista todas as requisições rastreadas no sistema."""
    return JSONResponse(db_local.listar_todas())


@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


# ==================== DASHBOARD ====================

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    dashboard_path = Path(__file__).parent / "dashboard.html"
    if dashboard_path.exists():
        return HTMLResponse(dashboard_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Dashboard não encontrado</h1>")


# ==================== MAIN ====================

if __name__ == "__main__":
    print("=" * 60)
    print("WS GUIAS ASSINADAS - APLIS + AUTENTIQUE")
    print("=" * 60)
    print(f"Dashboard:  http://{WS_HOST}:{WS_PORT}/")
    print(f"API Docs:   http://{WS_HOST}:{WS_PORT}/docs")
    print(f"Webhook:    POST http://{WS_HOST}:{WS_PORT}/api/webhooks/autentique")
    print("=" * 60)
    uvicorn.run("webhook_server:app", host=WS_HOST, port=WS_PORT, reload=True)
