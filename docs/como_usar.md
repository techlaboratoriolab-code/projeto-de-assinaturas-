# Sistema de Análise de Assinaturas — Como Usar

## O que o sistema faz

Automação ponta a ponta para um laboratório: identifica guias **sem assinatura do paciente**, contata o paciente via **WhatsApp**, aguarda confirmação, e envia o documento para **assinatura digital** via Autentique.

**Pipeline completo:**
1. Busca requisições no MySQL (convênios 1000, 1001, 1091) sem assinatura
2. Baixa imagens/PDFs do AWS S3
3. Envia para **Vertex AI (Gemini 2.5 Flash)** que classifica: `SIM / NÃO / ERRO`
4. Gera relatórios CSV
5. Envia mensagem de confirmação via **WAHA (WhatsApp API)**
6. Aguarda resposta do paciente (timeout configurável)
7. Se confirmado → envia documento para **Autentique** assinar
8. Notifica sucesso/falha ao paciente

---

## Como iniciar

```bash
./iniciar.sh
```

Isso vai:
- Matar qualquer processo na porta `8001`
- Fazer build do frontend React (`npm run build`)
- Subir o backend FastAPI em `http://localhost:8001`

---

## Configuração (.env)

As variáveis principais que você precisa ter corretas:

| Variável | O que é |
|---|---|
| `DB_HOST / DB_USER / DB_PASSWORD / DB_NAME` | Conexão MySQL |
| `AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / S3_BUCKET_NAME` | Acesso ao S3 |
| `GOOGLE_APPLICATION_CREDENTIALS / GOOGLE_CLOUD_PROJECT` | Credenciais Vertex AI |
| `WAHA_URL / WAHA_SESSION / WAHA_API_KEY` | API WhatsApp |
| `AUTENTIQUE_TOKEN` | API de assinatura digital |
| `MODO_TESTE` | `true` = manda WhatsApp só pro número de teste, não pacientes reais |
| `LIMITE_REGISTROS` | Quantas requisições processar por execução (padrão: 300) |

O `config.json` na raiz controla `modo_teste` e `criar_tarefa_aplis` em runtime (sem reiniciar).

---

## Modos de execução

**Modo Diário** — análise de um período de datas:
- Endpoint: `POST /api/run` com `{ "data_inicial": "2025-01-01", "data_final": "2025-01-31" }`
- Disparado pela tela principal do frontend

**Modo Faturamento** — fluxo contínuo com controle individual por requisição:
- Endpoint: `POST /api/faturamento/run`
- Suporta `POST /api/faturamento/run-individual` para processar uma requisição específica

**Modo Teste (`MODO_TESTE=true`):**
- Todos os WhatsApps são redirecionados para `TELEFONE_WAHA` em vez dos pacientes reais
- Útil para validar o pipeline sem afetar pacientes

---

## Interface Web (http://localhost:8001)

O frontend React oferece:
- **Status do backend** em tempo real
- **Toggle modo teste**
- **Disparo por período de datas**
- **Stream de logs ao vivo** (via SSE em `/api/dashboard/stream`)
- **Cards de estatísticas**: downloads, análises IA, mensagens WAHA enviadas

---

## Endpoints principais da API

| Endpoint | Função |
|---|---|
| `GET /api/status` | Status atual do processo |
| `POST /api/run` | Inicia análise diária |
| `POST /api/stop` | Para o processo |
| `POST /api/faturamento/run` | Inicia modo faturamento |
| `GET /api/logs` | Histórico de logs |
| `GET /api/autentique/documentos` | Documentos no Autentique |
| `GET /api/whatsapp/enviadas` | Mensagens WhatsApp enviadas |
| `GET /api/requisicoes/{id}/imagens` | Imagens de uma requisição |

---

## Ponto de atenção

O `MODO_TESTE` atualmente está `false` no `.env` — ou seja, **em produção**. Qualquer execução vai mandar mensagens reais para pacientes. Certifique-se de setar `MODO_TESTE=true` antes de testar.
