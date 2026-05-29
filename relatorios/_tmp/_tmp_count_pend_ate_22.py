import os
import mysql.connector
from dotenv import load_dotenv

load_dotenv()
conn = mysql.connector.connect(
    host=os.getenv('DB_HOST', 'localhost'),
    user=os.getenv('DB_USER', 'root'),
    password=os.getenv('DB_PASSWORD'),
    database=os.getenv('DB_NAME')
)
cur = conn.cursor()
cur.execute(
    """
    SELECT COUNT(DISTINCT r.CodRequisicao)
    FROM requisicao r
    INNER JOIN requisicaoimagem ri16
            ON ri16.IdRequisicao = r.IdRequisicao
           AND ri16.Tipo = 16
           AND ri16.Inativo = 0
    LEFT JOIN requisicaoimagem ri15
           ON ri15.IdRequisicao = r.IdRequisicao
          AND ri15.Tipo = 15
          AND ri15.Inativo = 0
    WHERE ri15.IdRequisicao IS NULL
      AND r.DtaSolicitacao < %s
      AND r.IdConvenio IN (1000,1001,1091)
    """,
    ('2026-04-23',)
)
print(cur.fetchone()[0])
cur.close()
conn.close()
