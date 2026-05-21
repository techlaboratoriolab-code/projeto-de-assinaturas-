import csv
from pathlib import Path
from datetime import datetime

base = Path('relatorios')

# Arquivos do sistema ativo (faturamento) já gerados
f_d22_det = base / 'relatorio_locais_origem_faturamento_20260423_125625.csv'
f_d23_det = base / 'relatorio_locais_origem_faturamento_20260423_170124.csv'
f_d22_res = base / 'relatorio_locais_origem_faturamento_resumo_20260423_125625.csv'
f_d23_res = base / 'relatorio_locais_origem_faturamento_resumo_20260423_170124.csv'

for p in [f_d22_det, f_d23_det, f_d22_res, f_d23_res]:
    if not p.exists():
        raise FileNotFoundError(f'Arquivo nao encontrado: {p}')

# Opcional: visão sem filtro (todos locais) já gerada
all_d22_res = base / 'relatorio_locais_origem_todos_dia_20260422_resumo_20260423_130940.csv'
all_d23_res = base / 'relatorio_locais_origem_todos_dia_20260423_resumo_20260423_170204.csv'


def to_int(v):
    try:
        return int(float(str(v or '0').replace(',', '.')))
    except Exception:
        return 0

# 1) Comparativo COMPLETO por guia (cod requisicao) - faturamento
def load_guides(path):
    out = {}
    with open(path, newline='', encoding='utf-8') as f:
        r = csv.DictReader(f)
        for row in r:
            cod = str(row.get('CodRequisicao') or '').strip()
            if not cod:
                continue
            out[cod] = {
                'LocalOrigem': (row.get('LocalOrigem') or '').strip(),
                'IdLocalOrigem': (row.get('IdLocalOrigem') or '').strip(),
                'IdConvenio': (row.get('IdConvenio') or '').strip(),
                'DtaSolicitacao': (row.get('DtaSolicitacao') or '').strip(),
            }
    return out

g22 = load_guides(f_d22_det)
g23 = load_guides(f_d23_det)
all_guides = sorted(set(g22) | set(g23), key=lambda x: int(x) if x.isdigit() else x)

# 2) Comparativo COMPLETO por local - faturamento
def load_local_summary(path):
    m = {}
    with open(path, newline='', encoding='utf-8') as f:
        r = csv.DictReader(f)
        for row in r:
            loc = (row.get('LocalOrigem') or '').strip() or 'Desconhecido'
            m[loc] = to_int(row.get('QuantidadeRequisicoes'))
    return m

l22 = load_local_summary(f_d22_res)
l23 = load_local_summary(f_d23_res)
locais_fat = sorted(set(l22) | set(l23))

# 3) Comparativo COMPLETO por local - todos (sem filtro), se existir
all_mode_ok = all_d22_res.exists() and all_d23_res.exists()
if all_mode_ok:
    a22 = load_local_summary(all_d22_res)
    a23 = load_local_summary(all_d23_res)
    locais_all = sorted(set(a22) | set(a23))

stamp = datetime.now().strftime('%Y%m%d_%H%M%S')

out_guia = base / f'comparativo_completo_guias_faturamento_20260422_vs_20260423_{stamp}.csv'
out_loc_fat = base / f'comparativo_completo_locais_faturamento_20260422_vs_20260423_{stamp}.csv'
out_exec = base / f'resumo_executivo_20260422_vs_20260423_{stamp}.csv'
out_loc_all = base / f'comparativo_completo_locais_todos_20260422_vs_20260423_{stamp}.csv'

# Escreve por guia
with open(out_guia, 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow([
        'DataComparacao','CodRequisicao','StatusComparacao',
        'LocalOrigem_22','LocalOrigem_23','IdLocalOrigem_22','IdLocalOrigem_23',
        'IdConvenio_22','IdConvenio_23','DtaSolicitacao_22','DtaSolicitacao_23'
    ])
    for cod in all_guides:
        in22 = cod in g22
        in23 = cod in g23
        if in22 and in23:
            status = 'MANTEVE'
        elif in22 and not in23:
            status = 'SAIU_NO_DIA_23'
        else:
            status = 'ENTROU_NO_DIA_23'

        r22 = g22.get(cod, {})
        r23 = g23.get(cod, {})
        w.writerow([
            '2026-04-22_vs_2026-04-23', cod, status,
            r22.get('LocalOrigem',''), r23.get('LocalOrigem',''),
            r22.get('IdLocalOrigem',''), r23.get('IdLocalOrigem',''),
            r22.get('IdConvenio',''), r23.get('IdConvenio',''),
            r22.get('DtaSolicitacao',''), r23.get('DtaSolicitacao',''),
        ])

# Escreve por local (faturamento)
fat_total22 = sum(v for v in l22.values() if v > 0)
fat_total23 = sum(v for v in l23.values() if v > 0)
with open(out_loc_fat, 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['DataComparacao','LocalOrigem','Qtd_22','Qtd_23','Delta_23_menos_22','VariacaoPercentual'])
    rows = []
    for loc in locais_fat:
        q22 = l22.get(loc, 0)
        q23 = l23.get(loc, 0)
        d = q23 - q22
        p = ((d / q22) * 100.0) if q22 else (100.0 if q23 > 0 else 0.0)
        rows.append((loc, q22, q23, d, p))
    rows.sort(key=lambda x: (x[3], x[0]))
    for loc, q22, q23, d, p in rows:
        w.writerow(['2026-04-22_vs_2026-04-23', loc, q22, q23, d, f'{p:.2f}'])

# Escreve por local (todos), se houver
all_total22 = all_total23 = None
if all_mode_ok:
    all_total22 = sum(v for v in a22.values() if v > 0)
    all_total23 = sum(v for v in a23.values() if v > 0)
    with open(out_loc_all, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['DataComparacao','LocalOrigem','Qtd_22','Qtd_23','Delta_23_menos_22','VariacaoPercentual'])
        rows = []
        for loc in locais_all:
            q22 = a22.get(loc, 0)
            q23 = a23.get(loc, 0)
            d = q23 - q22
            p = ((d / q22) * 100.0) if q22 else (100.0 if q23 > 0 else 0.0)
            rows.append((loc, q22, q23, d, p))
        rows.sort(key=lambda x: (x[3], x[0]))
        for loc, q22, q23, d, p in rows:
            w.writerow(['2026-04-22_vs_2026-04-23', loc, q22, q23, d, f'{p:.2f}'])

# Resumo executivo
with open(out_exec, 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['Visao','Data22_Total','Data23_Total','Delta_Total','Locais22','Locais23'])
    w.writerow(['FATURAMENTO', fat_total22, fat_total23, fat_total23-fat_total22, sum(1 for v in l22.values() if v>0), sum(1 for v in l23.values() if v>0)])
    if all_mode_ok:
        w.writerow(['TODOS_SEM_FILTRO', all_total22, all_total23, all_total23-all_total22, sum(1 for v in a22.values() if v>0), sum(1 for v in a23.values() if v>0)])

print('ARQ_GUIAS=' + out_guia.as_posix())
print('ARQ_LOCAIS_FAT=' + out_loc_fat.as_posix())
print('ARQ_RESUMO_EXEC=' + out_exec.as_posix())
if all_mode_ok:
    print('ARQ_LOCAIS_TODOS=' + out_loc_all.as_posix())

print(f'FAT_TOTAL_22={fat_total22}')
print(f'FAT_TOTAL_23={fat_total23}')
print(f'FAT_DELTA={fat_total23-fat_total22}')
print(f'FAT_GUIAS_COMPARADAS={len(all_guides)}')
print(f'FAT_LOCAIS_COMPARADOS={len(locais_fat)}')
if all_mode_ok:
    print(f'TODOS_TOTAL_22={all_total22}')
    print(f'TODOS_TOTAL_23={all_total23}')
    print(f'TODOS_DELTA={all_total23-all_total22}')
    print(f'TODOS_LOCAIS_COMPARADOS={len(locais_all)}')
