import csv
from collections import Counter
from pathlib import Path

path = Path('log_motivos_sem_assinatura_20260515_095557.csv')
rows = []
with path.open('r', encoding='utf-8', newline='') as f:
    reader = csv.DictReader(f)
    for row in reader:
        rows.append(row)

count = Counter()
for r in rows:
    clinic = r.get('LocalOrigem', '').strip()
    if clinic:
        count[clinic] += 1

for clinic, qty in count.most_common(15):
    print(f'{qty:>3} - {clinic}')
