---
name: project-ws-aplis
description: WebService APLIS + Autentique para anexar guias assinadas eletronicamente
metadata:
  type: project
---

Projeto de integração entre APLIS (sistema LIS) e Autentique (assinatura eletrônica).

**Objetivo:** Quando um documento é assinado no Autentique, o WebService baixa o PDF assinado e o anexa automaticamente à requisição correspondente no APLIS via `admissaoSalvar`.

**Localização:** `ws_aplis/` dentro do projeto raiz

**Arquivos principais:**
- `ws_aplis/webhook_server.py` — FastAPI server (porta 8000)
- `ws_aplis/aplis_client.py` — Cliente APLIS API v2
- `ws_aplis/autentique_client.py` — Cliente Autentique (GraphQL)
- `ws_aplis/db_local.py` — Banco JSON local (db_assinaturas.json)
- `ws_aplis/config_ws.py` — Configurações (lê de .env)
- `ws_aplis/test_requisicao.py` — Script de testes
- `ws_aplis/dashboard.html` — UI Lumi dark/glassmorphism

**APLIS API:**
- Endpoint único: `POST {APLIS_BASE_URL}/api/integracao.php`
- Formato: `{"ver": 2, "cmd": "...", "dat": {...}}`
- Comando para anexar imagem: `admissaoSalvar` com campo `imagens: [{tipo, extensao, arquivo (base64)}]`
- Tipos de imagem: 1=Imagem do pedido, 5=Documento

**Requisição de teste:** `0040000356004`

**Endpoints do WebService:**
- `POST /api/webhooks/autentique` — Listener passivo
- `POST /api/requisicoes/{cod}/atualizar-assinatura` — Sync manual
- `GET /api/requisicoes/{cod}/status` — Status
- `POST /api/requisicoes/{cod}/registrar` — Registrar vínculo
- `GET /` — Dashboard

**Why:** Automatizar o anexo de guias assinadas sem intervenção manual, reduzindo falhas e tempo de processamento.

**How to apply:** Quando o usuário mencionar APLIS, Autentique, guias assinadas ou ws_aplis, buscar contexto aqui.
