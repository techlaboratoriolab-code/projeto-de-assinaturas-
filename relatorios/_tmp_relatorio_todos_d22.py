import os
import csv
from datetime import datetime
from pathlib import Path
import mysql.connector
from dotenv import load_dotenv

load_dotenv()
conn = mysql.connector.connect(
    host=os.getenv('DB_HOST','localhost'),
    user=os.getenv('DB_USER','root'),
    password=os.getenv('DB_PASSWORD'),
    database=os.getenv('DB_NAME')
)
cur = conn.cursor(dictionary=True)

data_ref = '2026-04-22'

cur.execute("""
SELECT
    r.CodRequisicao,
    r.IdConvenio,
    r.IdLocalOrigem,
    COALESCE(fi.NomFantasia, CAST(r.IdLocalOrigem AS CHAR), 'Desconhecido') AS LocalOrigem,
    r.DtaSolicitacao
FROM requisicao r
LEFT JOIN fatinstituicao fi ON fi.IdInstituicao = r.IdLocalOrigem
WHERE DATE(r.DtaSolicitacao) = %s
ORDER BY r.DtaSolicitacao DESC, r.CodRequisicao
""", (data_ref,))
rows = cur.fetchall()

base = Path('relatorios')
base.mkdir(parents=True, exist_ok=True)
ts = datetime.now().strftime('%Y%m%d_%H%M%S')

detalhado = base / f'relatorio_locais_origem_todos_dia_20260422_{ts}.csv'
resumo = base / f'relatorio_locais_origem_todos_dia_20260422_resumo_{ts}.csv'

with open(detalhado, 'w', newline='', encoding='utf-8') as f:
    cols = ['DataReferencia','CodRequisicao','IdConvenio','IdLocalOrigem','LocalOrigem','DtaSolicitacao']
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    for r in rows:
        dta = r.get('DtaSolicitacao')
        if hasattr(dta, 'strftime'):
            dta = dta.strftime('%Y-%m-%d %H:%M:%S')
        else:
            dta = str(dta or '')
        w.writerow({
            'DataReferencia': data_ref,
            'CodRequisicao': r.get('CodRequisicao'),
            'IdConvenio': r.get('IdConvenio'),
            'IdLocalOrigem': r.get('IdLocalOrigem'),
            'LocalOrigem': r.get('LocalOrigem'),
            'DtaSolicitacao': dta,
        })

cont = {}
for r in rows:
    loc = r.get('LocalOrigem') or 'Desconhecido'
    cont[loc] = cont.get(loc, 0) + 1

total = len(rows)
ordenado = sorted(cont.items(), key=lambda x: (-x[1], x[0]))

with open(resumo, 'w', newline='', encoding='utf-8') as f:
    cols = ['DataReferencia','LocalOrigem','QuantidadeRequisicoes','Percentual']
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    for loc, qtd in ordenado:
        pct = (qtd / total * 100.0) if total else 0.0
        w.writerow({
            'DataReferencia': data_ref,
            'LocalOrigem': loc,
            'QuantidadeRequisicoes': qtd,
            'Percentual': f'{pct:.2f}',
        })

print('ARQ_DETALHADO=' + detalhado.as_posix())
print('ARQ_RESUMO=' + resumo.as_posix())
print('TOTAL=' + str(total))
print('LOCAIS=' + str(len(ordenado)))
for loc, qtd in ordenado[:10]:
    print(f'TOP|{loc}|{qtd}')

cur.close(); conn.close()
