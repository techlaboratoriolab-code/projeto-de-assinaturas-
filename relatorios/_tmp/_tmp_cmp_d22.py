import csv
from pathlib import Path

filtro = Path('relatorios/relatorio_locais_origem_faturamento_resumo_20260423_125625.csv')
todos = Path('relatorios/relatorio_locais_origem_todos_dia_20260422_resumo_20260423_130940.csv')

ff = {}
ftotal = 0
with open(filtro, newline='', encoding='utf-8') as f:
    r = csv.DictReader(f)
    for row in r:
        loc = row['LocalOrigem']
        qtd = int(float(row['QuantidadeRequisicoes']))
        ff[loc] = qtd
        ftotal += qtd

tt = {}
ttotal = 0
with open(todos, newline='', encoding='utf-8') as f:
    r = csv.DictReader(f)
    for row in r:
        loc = row['LocalOrigem']
        qtd = int(float(row['QuantidadeRequisicoes']))
        tt[loc] = qtd
        ttotal += qtd

locais = sorted(set(ff) | set(tt))
linhas = []
for loc in locais:
    a = ff.get(loc, 0)
    b = tt.get(loc, 0)
    if a or b:
        linhas.append((loc, a, b, b-a))

linhas.sort(key=lambda x: (-x[2], x[0]))

print(f'FILTRO_TOTAL={ftotal}')
print(f'TODOS_TOTAL={ttotal}')
print(f'FALTANTES_NO_FILTRO={ttotal-ftotal}')
print(f'FILTRO_LOCAIS={sum(1 for v in ff.values() if v>0)}')
print(f'TODOS_LOCAIS={sum(1 for v in tt.values() if v>0)}')
print('---TOP COMPARATIVO---')
for loc,a,b,d in linhas[:15]:
    print(f'{loc}|filtro={a}|todos={b}|delta={d}')
