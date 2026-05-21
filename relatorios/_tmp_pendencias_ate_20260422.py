import csv
from pathlib import Path
from datetime import datetime

base = Path('relatorios')
detalhado = base / 'relatorio_locais_origem_faturamento_20260424_111806.csv'
resumo = base / 'relatorio_locais_origem_faturamento_resumo_20260424_111806.csv'

if not detalhado.exists() or not resumo.exists():
    raise FileNotFoundError('Arquivos base do dia 23 nao encontrados')

qtd_local = {}
with open(resumo, newline='', encoding='utf-8') as f:
    r = csv.DictReader(f)
    for row in r:
        loc = (row.get('LocalOrigem') or '').strip() or 'Desconhecido'
        try:
            qtd = int(float((row.get('QuantidadeRequisicoes') or '0').replace(',', '.')))
        except Exception:
            qtd = 0
        qtd_local[loc] = qtd

linhas = []
with open(detalhado, newline='', encoding='utf-8') as f:
    r = csv.DictReader(f)
    for row in r:
        cod = (row.get('CodRequisicao') or '').strip()
        if not cod:
            continue
        loc = (row.get('LocalOrigem') or '').strip() or 'Desconhecido'
        linhas.append((loc, cod, row.get('IdConvenio','').strip(), row.get('IdLocalOrigem','').strip(), row.get('DataExecucao','').strip()))

linhas.sort(key=lambda x: (x[0].lower(), int(x[1]) if x[1].isdigit() else x[1]))

stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
out = base / f'pendencias_documentos_dia_20260423_com_qtd_local_{stamp}.csv'

with open(out, 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow([
        'DataReferencia',
        'CodRequisicao',
        'LocalOrigem',
        'IdLocalOrigem',
        'IdConvenio',
        'QtdPendenciasNoLocal'
    ])
    for loc, cod, idconv, idloc, _ in linhas:
        w.writerow(['2026-04-23', cod, loc, idloc, idconv, qtd_local.get(loc, 0)])

print('ARQ_SAIDA=' + out.as_posix())
print('TOTAL_DOCUMENTOS=' + str(len(linhas)))
print('TOTAL_LOCAIS=' + str(sum(1 for v in qtd_local.values() if v > 0)))
print('TOP_LOCAIS:')
for loc, qtd in sorted(qtd_local.items(), key=lambda x: (-x[1], x[0]))[:10]:
    if qtd > 0:
        print(f'{loc}|{qtd}')
print('AMOSTRA_DOCUMENTOS:')
for loc, cod, idconv, idloc, _ in linhas[:20]:
    print(f'{cod}|{loc}|qtd_local={qtd_local.get(loc,0)}')
