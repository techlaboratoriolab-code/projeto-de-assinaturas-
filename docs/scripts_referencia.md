# Referência dos Scripts

Visão geral de cada script disponível nesta pasta, agrupados por tipo e finalidade.

---

## Scripts Python

### `analise_sql_assinaturas.py`

Script principal de análise de assinaturas de pacientes.

**Fluxo:**
1. Conecta ao banco MySQL e busca requisições do convênio 1040 com imagens tipo 16
2. Baixa as imagens correspondentes do S3 da AWS via Selenium (Chrome automatizado)
3. Envia cada imagem para o Gemini analisar se há assinatura **do paciente** no documento
4. Exibe relatório com totais (com assinatura / sem assinatura / arquivo não encontrado)
5. Oferece ao usuário a opção de criar tarefas automaticamente no sistema APLIS para as requisições sem assinatura

**Como usar:**
```bash
python analise_sql_assinaturas.py
python analise_sql_assinaturas.py --data 19/11/2025
python analise_sql_assinaturas.py --data 19/11/2025 --prefixos 0085,0040
python analise_sql_assinaturas.py --apenas-pdf
python analise_sql_assinaturas.py --analisar-pdf --csv resultado.csv
```

**Dependências:** `mysql-connector-python`, `selenium`, `Pillow`, `PyMuPDF` (opcional), `google-generativeai`

---

### `backup_Por_data.py`

Realiza backup diário do histórico de atendimentos do WhatsApp via WAHA API.

**Fluxo:**
1. Verifica autenticação e sessão ativa no WAHA
2. Busca todos os chats com atividade na data alvo
3. Para cada chat, baixa as mensagens do dia
4. Áudios são transcritos automaticamente com Gemini 2.5 Flash
5. Imagens são analisadas e descritas pelo Gemini 2.5 Flash
6. Salva tudo em um arquivo CSV no Google Drive (`historico_YYYY-MM-DD_com_midias.csv`)
7. Registra evento de telemetria no Umami

**Como usar:**
```bash
python backup_Por_data.py                      # modo automático, data de hoje
python backup_Por_data.py --modo manual        # solicita a data interativamente
python backup_Por_data.py --data 16/04/2026    # data específica
```

**Dependências:** `requests`, `google-generativeai`, `python-dotenv`

---

### `analisar_atendimento_whatsapp.py`

Analisa a qualidade dos atendimentos do WhatsApp usando o **Scorecard de Encantamento LAB**.

**Fluxo:**
1. Lista os arquivos CSV de histórico disponíveis na pasta configurada
2. Lê o CSV escolhido e organiza as conversas por chat
3. Processa áudios (transcrição) e imagens (análise) automaticamente via Gemini
4. Envia todo o histórico formatado para o Gemini avaliar as 4 dimensões do scorecard: Agilidade, Clareza, Cuidado/Empatia e Proatividade
5. Salva relatório em Markdown e JSON com nota de cada atendente e análise de oportunidades de vendas

**Scorecard:** Cada dimensão recebe 0, 1 ou 2 pontos. Nota final = (soma / 8) × 10.

**Como usar:**
```bash
python analisar_atendimento_whatsapp.py
```
O script apresenta um menu interativo para escolher o arquivo CSV e as opções de processamento.

**Dependências:** `google-generativeai`, `python-dotenv`

---

### `config_analise.py`

Arquivo de configuração centralizado para o sistema de análise de atendimento.

Não é executado diretamente — é importado por `analisar_atendimento_whatsapp.py`. Contém:

- Caminho para credenciais do Google Cloud
- Pastas de históricos e relatórios
- Modelo Gemini a usar (`gemini-2.5-flash` ou `gemini-2.5-pro`)
- Metas de tempo de resposta e notas mínimas
- Palavras-chave para identificar oportunidades de venda e fechamentos
- Flags para formatos de saída (JSON, TXT, HTML)

Para validar as configurações:
```bash
python config_analise.py
```

---

## Scripts BAT (Windows)

### `executar_backup.bat`

Ativa o ambiente virtual e executa `backup_Por_data.py` no **modo automático** (usa a data atual). Também define as variáveis de ambiente do Umami antes de chamar o Python.

Usado como alvo pelos agendadores `agendar_backup.ps1` e `rodar_backup.bat`.

---

### `rodar_backup.bat`

Versão do executor de backup que **registra log** em `log_backup.txt`. Cada execução appenda uma linha de início e uma de fim com data/hora.

Útil para verificar se o backup está rodando corretamente quando agendado pelo Windows.

---

### `executar_assinaturas_semanal.bat`

Executa `analisar_assinaturas_v3_vertexai.py` com as flags `--semanal --apenas-log-motivos` para a análise semanal completa com registro de motivos.

Usado como alvo pelo agendador `agendar_assinaturas_semanal.ps1`.

---

### `executar_resumo_diario.bat`

Executa `analisar_assinaturas_v3_vertexai.py` com a flag `--enviar-resumo-diario` para disparar o resumo diário do sistema via WhatsApp para os números monitor.

Usado como alvo pelo agendador `agendar_resumo_diario.ps1`.

---

### `executar_relatorio_locais_diario.bat`

Executa `analisar_assinaturas_v3_vertexai.py` com as flags `--diario --gerar-relatorio-locais-origem` para gerar o relatório diário de faturamento por local de origem (D-1).

Usado como alvo pelo agendador `agendar_relatorio_locais_diario.ps1`.

---

### `instalar_dependencias.bat`

Instala todas as dependências Python do projeto via `pip`. Execute uma vez ao configurar o ambiente em uma nova máquina.

Pacotes instalados: `boto3`, `PyMuPDF`, `requests`, `Pillow`, `python-dotenv`, `mysql-connector-python`, `google-cloud-aiplatform`, `selenium`.

---

## Scripts PowerShell (Agendadores)

Todos os scripts `.ps1` devem ser executados **como Administrador**. Eles registram uma tarefa no **Agendador de Tarefas do Windows** e removem a tarefa anterior de mesmo nome se já existir.

| Script | Tarefa criada | Horário |
|---|---|---|
| `agendar_backup.ps1` | Backup WhatsApp Diário | Diariamente às 19:00 |
| `agendar_resumo_diario.ps1` | Resumo Diário Assinaturas | Diariamente às 17:00 |
| `agendar_relatorio_locais_diario.ps1` | Relatório Diário Locais Faturamento | Diariamente às 07:00 |
| `agendar_assinaturas_semanal.ps1` | Análise Assinaturas Semanal | Toda segunda-feira às 08:00 |

---

## Arquivos de Dados e Logs

| Arquivo | Descrição |
|---|---|
| `log_backup.txt` | Log gerado pelo `rodar_backup.bat` com registro de cada execução do backup |
| `requisicao_teste_4027.txt` | Arquivo de requisição para testes |
| `requisicoes_faturamento.txt` | Dados de requisições de faturamento |

---

## Resumo do Fluxo Automatizado

```
Agendadores .ps1
    └── Registram tarefas no Windows Task Scheduler
            ├── 07:00 → executar_relatorio_locais_diario.bat → relatório de locais de faturamento
            ├── 17:00 → executar_resumo_diario.bat → resumo diário via WhatsApp
            ├── 19:00 → executar_backup.bat → backup do histórico WhatsApp
            └── Segunda 08:00 → executar_assinaturas_semanal.bat → análise semanal de assinaturas
```
