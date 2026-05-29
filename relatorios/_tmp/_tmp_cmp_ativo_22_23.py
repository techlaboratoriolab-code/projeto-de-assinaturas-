import csv
from pathlib import Path
from datetime import datetime

base = Path('relatorios')

# Usa os relatórios do sistema ativo já gerados nesta sessão
arq_d22 = base / 'relatorio_locais_origem_faturamento_resumo_20260423_125625.csv'
arq_d23 = base / 'relatorio_locais_origem_faturamento_resumo_20260423_170124.csv'

if not arq_d22.exists():
    raise FileNotFoundError(f'Arquivo não encontrado: {arq_d22}')
if not arq_d23.exists():
    raise FileNotFoundError(f'Arquivo não encontrado: {arq_d23}')

def carregar(path):
    dados = {}
    total = 0
    with open(path, newline='', encoding='utf-8') as f:
        r = csv.DictReader(f)
        for row in r:
            loc = (row.get('LocalOrigem') or '').strip() or 'Desconhecido'
            qtd_txt = row.get('QuantidadeRequisicoes') or '0'
            qtd = int(float(qtd_txt))
            if qtd > 0:
                dados[loc] = qtd
                total += qtd
    return dados, total

map22, total22 = carregar(arq_d22)
map23, total23 = carregar(arq_d23)

locais = sorted(set(map22) | set(map23))
linhas = []
for loc in locais:
    q22 = map22.get(loc, 0)
    q23 = map23.get(loc, 0)
    delta = q23 - q22
    pct = ((delta / q22) * 100.0) if q22 else (100.0 if q23 > 0 else 0.0)
    linhas.append((loc, q22, q23, delta, pct))

# Ordena por maior queda primeiro
linhas.sort(key=lambda x: (x[3], x[0]))

ts = datetime.now().strftime('%Y%m%d_%H%M%S')
out = base / f'comparativo_avanco_assinaturas_20260422_vs_20260423_{ts}.csv'

with open(out, 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow([
        'DataComparacao',
        'LocalOrigem',
        'Qtd_2026_04_22',
        'Qtd_2026_04_23',
        'Delta_23_menos_22',
        'VariacaoPercentual'
    ])
    for loc, q22, q23, delta, pct in linhas:
        w.writerow([
            '2026-04-22_vs_2026-04-23',
            loc,
            q22,
            q23,
            delta,
            f'{pct:.2f}'
        ])

print(f'ARQ_COMPARATIVO={out.as_posix()}')
print(f'TOTAL_22={total22}')
print(f'TOTAL_23={total23}')
print(f'DELTA_TOTAL={total23-total22}')
print(f'LOCAIS_22={len(map22)}')
print(f'LOCAIS_23={len(map23)}')
print('TOP_QUEDAS:')
for loc, q22, q23, delta, pct in linhas[:10]:
    print(f'{loc}|22={q22}|23={q23}|delta={delta}|var%={pct:.2f}')
