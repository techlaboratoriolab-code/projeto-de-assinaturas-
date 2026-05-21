# Projeto de Assinaturas - Documento Tecnico Detalhado

## 1. Visao geral
O projeto realiza analise automatica de guias para identificar ausencia de assinatura do paciente, aciona contato via WhatsApp, coleta confirmacao e envia documentos para assinatura digital.

Fluxo principal:
1. Buscar requisicoes no banco
2. Baixar documentos no S3
3. Analisar assinatura com Vertex AI
4. Gerar relatorios
5. Buscar telefones dos pacientes
6. Enviar confirmacao via WAHA
7. Aguardar resposta
8. Enviar documento no Autentique para confirmados

## 2. Arquitetura atual

### 2.1 Camadas
- Camada de API: FastAPI
- Camada de processo: script Python de orquestracao
- Camada de interface: React + Vite
- Camada de dados: MySQL + S3 + CSV
- Camada de terceiros: Vertex AI, WAHA, Autentique

### 2.2 Componente backend
A API expoe endpoints para iniciar/parar processamento e stream de logs via SSE.
O processamento real e executado por subprocesso Python com parametros de periodo.

### 2.3 Componente frontend
A tela principal opera como console:
- status backend
- modo teste
- disparo por dia
- stream de log
- cards de estatistica

## 3. Modulos e responsabilidades

### 3.1 API de controle
Responsavel por:
- status de execucao
- atualizacao de configuracao
- disparo de processamento
- parada de processo
- historico e stream de logs

### 3.2 Orquestrador principal
Responsavel por:
- composicao do pipeline de analise
- controle de periodo
- persistencia de relatorios CSV
- notificacao e confirmacao com pacientes

### 3.3 IA de assinatura
Responsavel por:
- carregar documento (PDF/imagem)
- converter quando necessario
- chamar Vertex AI com prompt objetivo
- classificar em SIM/NAO/ERRO

### 3.4 Integracao WhatsApp (WAHA)
Responsavel por:
- envio de mensagem de confirmacao
- leitura de mensagens para confirmacao
- controle de timeout e negativa

### 3.5 Integracao Autentique
Responsavel por:
- criar documento de assinatura
- enviar para WhatsApp do paciente
- capturar sucesso/erro

## 4. Dependencias tecnicas

### 4.1 Backend
- fastapi
- pydantic
- mysql-connector-python
- boto3
- google-cloud-aiplatform
- Pillow
- PyMuPDF
- requests
- selenium

### 4.2 Frontend
- react
- react-dom
- vite

## 5. Variaveis e configuracao

### 5.1 Ambiente backend
- DB_HOST
- DB_USER
- DB_PASSWORD
- DB_NAME
- AWS_ACCESS_KEY_ID
- AWS_SECRET_ACCESS_KEY
- AWS_REGION
- S3_BUCKET_NAME
- GOOGLE_APPLICATION_CREDENTIALS
- GOOGLE_CLOUD_PROJECT
- VERTEX_LOCATION
- VERTEX_MODEL
- AUTENTIQUE_TOKEN
- MODO_TESTE

### 5.2 Ambiente frontend
- VITE_API_URL

## 6. Fluxo operacional detalhado

### Etapa A - coleta
- Consulta no banco para requisicoes do periodo com tipo esperado
- Limite de volume por execucao

### Etapa B - aquisicao de documento
- Resolve caminho S3 por prefixo de requisicao
- Baixa documentos para diretorio local de trabalho

### Etapa C - inferencia
- Converte PDF para imagem quando necessario
- Envia imagem para Vertex AI com prompt focado em assinatura do paciente
- Classifica resultado para decisao

### Etapa D - relatorio
- Gera resumo geral
- Gera CSV tecnico de motivos
- Gera CSV de telefones e de envios

### Etapa E - contato e confirmacao
- Envia mensagem inicial via WAHA
- Aguarda resposta SIM/NAO/timeout
- Em modo teste, aplica confirmacao global

### Etapa F - assinatura digital
- Envia documento para Autentique dos confirmados
- Notifica sucesso/erro ao paciente

## 7. Pontos fortes
- Pipeline completo ponta a ponta
- Integracao com IA e assinatura digital
- Interface unica para operacao e monitoramento
- Logs em tempo real com controle de execucao

## 8. Riscos e gargalos
- Processo longo acoplado ao servidor web
- Uso de armazenamento local como dependencia operacional
- Dependencia de integracoes externas sem isolamento por fila
- Possivel variacao de encoding em ambientes Windows
- Credenciais sensiveis devem ficar fora do codigo

## 9. Melhorias recomendadas

### 9.1 Arquitetura
- Introduzir fila de jobs e worker dedicado
- Persistir estado de job em banco
- Desacoplar processamento da API HTTP

### 9.2 Confiabilidade
- Retry com backoff para APIs externas
- Circuit breaker para indisponibilidade transitiva
- Idempotencia por requisicao/documento

### 9.3 Seguranca
- Secret manager para tokens e chaves
- Rotacao de credenciais
- mascaramento de dados sensiveis em logs

### 9.4 Observabilidade
- Correlacao por job_id
- metricas por etapa
- alertas por taxa de falha

## 10. Operacao recomendada
- Executar por janela diaria definida
- Monitorar taxa de confirmacao e envio
- Reprocessar apenas pendencias com falha tecnica
- Revisar periodicamente limites e timeout por volume

## 11. Prontidao para nuvem
Frontend: pronto para deploy estatico (ex.: Vercel).
Backend: recomendado em ambiente com processo persistente (ex.: Render/Railway/Fly/VM), nao serverless puro para o fluxo atual.

## 12. Checklist de producao
- [ ] remover credenciais hardcoded
- [ ] centralizar env vars
- [ ] configurar backup e retencao de relatorios
- [ ] definir SLA operacional
- [ ] implementar fila de processamento
- [ ] documentar runbook de incidente

## 13. Conclusao
O projeto ja entrega valor real com automacao ponta a ponta.
A evolucao natural para escalar com seguranca e separar API de controle, processamento assincro e armazenamento persistente de estado/artefatos.
