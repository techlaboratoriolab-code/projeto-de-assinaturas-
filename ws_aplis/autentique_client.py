"""
Cliente da API Autentique (GraphQL)
Documentação: https://autentique.com.br/docs
"""

import json
import requests
from config_ws import AUTENTIQUE_API_URL, AUTENTIQUE_TOKEN

HEADERS = {
    "Authorization": f"Bearer {AUTENTIQUE_TOKEN}",
    "Content-Type": "application/json",
}

# Query GraphQL para buscar documento por UUID
_QUERY_DOCUMENTO = """
query GetDocumento($id: UUID!) {
  document(id: $id) {
    id
    name
    created_at
    files {
      signed
    }
    signatures {
      public_id
      name
      email
      signed {
        created_at
      }
      viewed {
        created_at
      }
    }
  }
}
"""


# Query para listar documentos por nome
_QUERY_BUSCAR_POR_NOME = """
query($page: Int!, $limit: Int!) {
  documents(page: $page, limit: $limit) {
    data {
      id
      name
      created_at
    }
  }
}
"""


def _graphql(query: str, variables: dict) -> dict:
    try:
        resp = requests.post(
            f"{AUTENTIQUE_API_URL}/graphql",
            json={"query": query, "variables": variables},
            headers=HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        if "errors" in data:
            erros = "; ".join(e.get("message", "") for e in data["errors"])
            return {"sucesso": False, "erro": erros, "data": None}

        return {"sucesso": True, "erro": "", "data": data.get("data")}

    except requests.exceptions.RequestException as e:
        return {"sucesso": False, "erro": str(e), "data": None}


def buscar_documentos_por_nome(termo: str, limit: int = 10) -> list:
    """
    Busca documentos na conta que contenham o termo no nome.
    """
    resultado = _graphql(_QUERY_BUSCAR_POR_NOME, {"page": 1, "limit": 60})
    if not resultado["sucesso"] or not resultado["data"]:
        return []
    
    docs = resultado["data"].get("documents", {}).get("data", [])
    if not docs:
        return []
    
    # Filtra localmente pelo termo (geralmente o número da requisição)
    encontrados = [d for d in docs if termo in str(d.get("name", ""))]
    # Ordena pelo mais recente
    encontrados.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return encontrados


def buscar_documento(doc_id: str) -> dict:
    """
    Busca os dados do documento no Autentique pelo ID.

    Returns:
        {sucesso, erro, uuid, nome, status, url_assinado, assinantes}
    """
    resultado = _graphql(_QUERY_DOCUMENTO, {"id": doc_id})

    if not resultado["sucesso"]:
        return {"sucesso": False, "erro": resultado["erro"]}

    doc = resultado["data"].get("document")
    if not doc:
        return {"sucesso": False, "erro": "Documento não encontrado"}

    assinantes = doc.get("signatures", [])
    todos_assinaram = all(s.get("signed") for s in assinantes) if assinantes else False

    return {
        "sucesso": True,
        "erro": "",
        "uuid": doc["id"],
        "nome": doc["name"],
        "status": "CONCLUIDO" if todos_assinaram else "PENDENTE",
        "url_assinado": doc.get("files", {}).get("signed", ""),
        "assinantes": assinantes,
        "todos_assinaram": todos_assinaram,
    }


def baixar_pdf_assinado(url: str) -> bytes | None:
    """
    Faz download do PDF assinado pelo link fornecido pelo Autentique.

    Returns:
        bytes do PDF ou None em caso de erro
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=60)
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "")
        if "pdf" not in content_type.lower() and len(resp.content) < 100:
            print(f"⚠ Resposta suspeita (Content-Type: {content_type})")
            return None

        print(f"✓ PDF baixado: {len(resp.content) / 1024:.1f} KB")
        return resp.content

    except requests.exceptions.RequestException as e:
        print(f"✗ Erro ao baixar PDF: {e}")
        return None


def validar_webhook_secret(header_secret: str, esperado: str) -> bool:
    """Valida o token secreto do webhook para evitar requisições falsas."""
    if not esperado:
        return True  # sem secret configurado, aceita tudo
    return header_secret == esperado


def parse_webhook_payload(payload: dict) -> dict:
    """
    Normaliza o payload do webhook do Autentique para um formato padrão.

    O Autentique pode enviar diferentes formatos dependendo da versão.
    Retorna: {uuid, nome, status, url_assinado, event_type}
    """
    # Formato v2 (GraphQL webhook)
    if "id" in payload or "uuid" in payload:
        return {
            "uuid": payload.get("id") or payload.get("uuid", ""),
            "nome": payload.get("name", ""),
            "status": payload.get("status", ""),
            "url_assinado": payload.get("files", {}).get("signed", ""),
            "event_type": payload.get("event", "document_signed"),
        }

    # Formato alternativo com wrapper "document"
    doc = payload.get("document", {})
    return {
        "uuid": doc.get("id") or doc.get("uuid", ""),
        "nome": doc.get("name", ""),
        "status": doc.get("status", ""),
        "url_assinado": doc.get("files", {}).get("signed", ""),
        "event_type": payload.get("event", "document_signed"),
    }
