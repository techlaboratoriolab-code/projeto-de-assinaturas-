"""
Banco de dados local em JSON para rastrear assinaturas.
Mapeia codRequisicao -> {autentique_document_id, status_assinatura, url_guia_assinada, historico}
"""

import json
import os
from datetime import datetime
from config_ws import DB_PATH

_STATUS = {
    "PENDENTE": "pendente",
    "ASSINADO": "assinado",
    "ERRO": "erro",
}


def _carregar() -> dict:
    if os.path.exists(DB_PATH):
        with open(DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _salvar(db: dict):
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


def registrar_envio(cod_requisicao: str, uuid_autentique: str):
    """Registra que um documento foi enviado ao Autentique para assinatura."""
    db = _carregar()
    db[cod_requisicao] = {
        "autentique_document_id": uuid_autentique,
        "status_assinatura": _STATUS["PENDENTE"],
        "url_guia_assinada": "",
        "historico": [
            {
                "evento": "enviado_autentique",
                "data": datetime.now().isoformat(),
                "detalhe": f"UUID Autentique: {uuid_autentique}",
            }
        ],
    }
    _salvar(db)
    print(f"✓ Requisição {cod_requisicao} registrada (pendente)")


def atualizar_assinado(cod_requisicao: str, url_guia: str):
    """Marca a requisição como assinada e salva a URL da guia."""
    db = _carregar()
    if cod_requisicao not in db:
        db[cod_requisicao] = {"autentique_document_id": "", "status_assinatura": "", "url_guia_assinada": "", "historico": []}

    db[cod_requisicao]["status_assinatura"] = _STATUS["ASSINADO"]
    db[cod_requisicao]["url_guia_assinada"] = url_guia
    db[cod_requisicao]["historico"].append(
        {
            "evento": "guia_anexada",
            "data": datetime.now().isoformat(),
            "detalhe": "Guia anexada automaticamente via Webhook Autentique",
        }
    )
    _salvar(db)
    print(f"✓ Requisição {cod_requisicao} marcada como assinada")


def atualizar_erro(cod_requisicao: str, detalhe: str):
    """Registra um erro no fluxo de assinatura."""
    db = _carregar()
    if cod_requisicao not in db:
        db[cod_requisicao] = {"autentique_document_id": "", "status_assinatura": "", "url_guia_assinada": "", "historico": []}

    db[cod_requisicao]["status_assinatura"] = _STATUS["ERRO"]
    db[cod_requisicao]["historico"].append(
        {
            "evento": "erro",
            "data": datetime.now().isoformat(),
            "detalhe": detalhe,
        }
    )
    _salvar(db)
    print(f"✗ Erro registrado para requisição {cod_requisicao}: {detalhe}")


def buscar(cod_requisicao: str) -> dict | None:
    """Retorna os dados de uma requisição ou None se não existir."""
    db = _carregar()
    return db.get(cod_requisicao)


def buscar_por_uuid(uuid_autentique: str) -> tuple[str, dict] | tuple[None, None]:
    """Busca requisição pelo UUID do documento Autentique."""
    db = _carregar()
    for cod, dados in db.items():
        if dados.get("autentique_document_id") == uuid_autentique:
            return cod, dados
    return None, None


def listar_todas() -> dict:
    """Retorna todas as requisições registradas."""
    return _carregar()
