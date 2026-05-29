import csv
from pathlib import Path
from datetime import datetime
from collections import Counter

base = Path('relatorios')
logs = sorted(base.glob('log_motivos_sem_assinatura_*.csv'), key=lambda p: p.stat().st_mtime, reverse=True)
if not logs:
    print('ERRO=sem_log_motivos')
    raise SystemExit(0)

ultimo = logs[0]
cont = Counter()
with open(ultimo, 'r', encoding='utf-8', newline='') as f:
    for row in csv.DictReader(f):
        loc = (row.get('LocalOrigem') or '').strip() or 'Desconhecido'
        cont[loc] += 1

out = base / f'pendencias_por_local_snapshot_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
with open(out, 'w', encoding='utf-8', newline='') as f:
    w = csv.DictWriter(f, fieldnames=['ArquivoBase', 'LocalOrigem', 'QuantidadePendencias'])
    w.writeheader()
    for loc, qtd in cont.most_common():
        w.writerow({'ArquivoBase': ultimo.name, 'LocalOrigem': loc, 'QuantidadePendencias': qtd})

print('ARQUIVO_BASE=' + ultimo.as_posix())
print('ARQUIVO_SAIDA=' + out.as_posix())
print('TOTAL_PENDENCIAS=' + str(sum(cont.values())))
print('QTD_LOCAIS=' + str(len(cont)))
for loc, qtd in list(cont.most_common())[:10]:
    print(f'TOP|{loc}|{qtd}')
