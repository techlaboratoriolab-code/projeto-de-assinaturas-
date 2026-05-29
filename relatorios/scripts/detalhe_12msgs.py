import csv, glob, os
from datetime import datetime
from collections import defaultdict

DIRETORIO = os.path.dirname(os.path.abspath(__file__))
PADRAO = os.path.join(DIRETORIO, 'documentos_autentique_producao_*.csv')

alvo = {'5561981360486', '5561991763813', '5561992335056', '5561981060105', '5561999968082', '5561983403374'}

por_tel = defaultdict(list)

for arquivo in sorted(glob.glob(PADRAO)):
    basename = os.path.basename(arquivo)
    ts_str = basename.replace('documentos_autentique_producao_', '').replace('.csv', '')
    try:
        data_arquivo = datetime.strptime(ts_str, '%Y%m%d_%H%M%S')
    except Exception:
        data_arquivo = None

    with open(arquivo, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            tel = (row.get('Telefone') or '').strip()
            if tel not in alvo:
                continue
            created_at = (row.get('created_at') or '').strip()
            try:
                dt = datetime.fromisoformat(created_at) if created_at else data_arquivo
            except Exception:
                dt = data_arquivo
            cod_req = (row.get('CodRequisicao') or '').strip()
            nome = (row.get('NomPaciente') or '').strip()
            por_tel[tel].append({'dt': dt, 'req': cod_req, 'nome': nome})

for tel in sorted(alvo):
    envios = sorted(por_tel[tel], key=lambda x: x['dt'] or datetime.min)
    nome = next((e['nome'] for e in envios if e['nome']), '(sem nome)')
    print(f'\n=== {tel} | {nome} | {len(envios)} mensagens ===')
    for e in envios:
        dt_str = e['dt'].strftime('%d/%m/%Y %H:%M') if e['dt'] else '-'
        req = e['req']
        print(f'  {dt_str}  Req: {req}')
