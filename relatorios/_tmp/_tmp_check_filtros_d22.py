import os
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

d='2026-04-22'

# 1) Todas as requisicoes do dia (sem filtro)
cur.execute("""
SELECT COALESCE(fi.NomFantasia, CAST(r.IdLocalOrigem AS CHAR), 'Desconhecido') AS local,
       COUNT(DISTINCT r.CodRequisicao) AS qtd
FROM requisicao r
LEFT JOIN fatinstituicao fi ON fi.IdInstituicao = r.IdLocalOrigem
WHERE DATE(r.DtaSolicitacao)=%s
GROUP BY COALESCE(fi.NomFantasia, CAST(r.IdLocalOrigem AS CHAR), 'Desconhecido')
ORDER BY qtd DESC
""", (d,))
all_rows = cur.fetchall()

# 2) Com tipo16 e sem tipo15 (todos convenios)
cur.execute("""
SELECT COALESCE(fi.NomFantasia, CAST(r.IdLocalOrigem AS CHAR), 'Desconhecido') AS local,
       COUNT(DISTINCT r.CodRequisicao) AS qtd
FROM requisicao r
INNER JOIN requisicaoimagem ri ON ri.IdRequisicao=r.IdRequisicao
LEFT JOIN fatinstituicao fi ON fi.IdInstituicao = r.IdLocalOrigem
WHERE DATE(r.DtaSolicitacao)=%s
  AND ri.Tipo=16
  AND ri.Inativo=0
  AND NOT EXISTS (
      SELECT 1 FROM requisicaoimagem ri2
      WHERE ri2.IdRequisicao=r.IdRequisicao
        AND ri2.Tipo=15
        AND ri2.Inativo=0
  )
GROUP BY COALESCE(fi.NomFantasia, CAST(r.IdLocalOrigem AS CHAR), 'Desconhecido')
ORDER BY qtd DESC
""", (d,))
pend_all_conv = cur.fetchall()

# 3) Mesmo filtro + convenios do script
cur.execute("""
SELECT COALESCE(fi.NomFantasia, CAST(r.IdLocalOrigem AS CHAR), 'Desconhecido') AS local,
       COUNT(DISTINCT r.CodRequisicao) AS qtd
FROM requisicao r
INNER JOIN requisicaoimagem ri ON ri.IdRequisicao=r.IdRequisicao
LEFT JOIN fatinstituicao fi ON fi.IdInstituicao = r.IdLocalOrigem
WHERE DATE(r.DtaSolicitacao)=%s
  AND ri.Tipo=16
  AND ri.Inativo=0
  AND NOT EXISTS (
      SELECT 1 FROM requisicaoimagem ri2
      WHERE ri2.IdRequisicao=r.IdRequisicao
        AND ri2.Tipo=15
        AND ri2.Inativo=0
  )
  AND r.IdConvenio IN (1000,1001,1091)
GROUP BY COALESCE(fi.NomFantasia, CAST(r.IdLocalOrigem AS CHAR), 'Desconhecido')
ORDER BY qtd DESC
""", (d,))
pend_3_conv = cur.fetchall()

print('ALL_DIA_TOTAL=', sum(r['qtd'] for r in all_rows), 'LOCAIS=', len(all_rows))
print('TIPO16_SEM15_TODOS_CONV_TOTAL=', sum(r['qtd'] for r in pend_all_conv), 'LOCAIS=', len(pend_all_conv))
print('TIPO16_SEM15_3_CONV_TOTAL=', sum(r['qtd'] for r in pend_3_conv), 'LOCAIS=', len(pend_3_conv))
print('TOP_ALL_DIA=', all_rows[:10])

cur.close(); conn.close()
