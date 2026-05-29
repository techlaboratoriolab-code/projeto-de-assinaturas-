"""
Métrica: quantas vezes cada paciente recebeu mensagem WhatsApp do sistema de assinaturas.
Lê todos os arquivos documentos_autentique_producao_*.csv da pasta relatorios/.
"""

import csv
import glob
import os
from collections import defaultdict
from datetime import datetime

DIRETORIO = os.path.dirname(os.path.abspath(__file__))
PADRAO = os.path.join(DIRETORIO, 'documentos_autentique_producao_*.csv')

# Estrutura: chave = Telefone, valor = dict com dados agregados
pacientes = defaultdict(lambda: {
    'nome': '',
    'telefone': '',
    'total_mensagens': 0,
    'requisicoes': set(),
    'primeira_mensagem': None,
    'ultima_mensagem': None,
})

arquivos = sorted(glob.glob(PADRAO))
print(f"[INFO] Arquivos encontrados: {len(arquivos)}")

for arquivo in arquivos:
    # Extrai timestamp do nome do arquivo como fallback de data
    basename = os.path.basename(arquivo)
    try:
        ts_str = basename.replace('documentos_autentique_producao_', '').replace('.csv', '')
        data_arquivo = datetime.strptime(ts_str, '%Y%m%d_%H%M%S')
    except Exception:
        data_arquivo = None

    with open(arquivo, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            telefone = (row.get('Telefone') or '').strip()
            if not telefone:
                continue

            cod_req = (row.get('CodRequisicao') or '').strip()
            nome = (row.get('NomPaciente') or '').strip()

            # Data do envio: coluna created_at se disponível, senão timestamp do arquivo
            data_envio = None
            created_at_raw = (row.get('created_at') or '').strip()
            if created_at_raw:
                try:
                    data_envio = datetime.fromisoformat(created_at_raw)
                except Exception:
                    pass
            if data_envio is None:
                data_envio = data_arquivo

            p = pacientes[telefone]
            p['telefone'] = telefone
            if nome and not p['nome']:
                p['nome'] = nome
            p['total_mensagens'] += 1
            if cod_req:
                p['requisicoes'].add(cod_req)
            if data_envio:
                if p['primeira_mensagem'] is None or data_envio < p['primeira_mensagem']:
                    p['primeira_mensagem'] = data_envio
                if p['ultima_mensagem'] is None or data_envio > p['ultima_mensagem']:
                    p['ultima_mensagem'] = data_envio


# Ordena por total de mensagens decrescente
resultado = sorted(pacientes.values(), key=lambda x: x['total_mensagens'], reverse=True)

# Exibe no terminal
print(f"\n{'='*90}")
print(f"{'TELEFONE':<20} {'NOME':<35} {'MSGS':>5} {'REQS':>5}  {'PRIMEIRA':>19}  {'ULTIMA':>19}")
print(f"{'-'*90}")
for p in resultado:
    primeira = p['primeira_mensagem'].strftime('%d/%m/%Y %H:%M') if p['primeira_mensagem'] else '-'
    ultima   = p['ultima_mensagem'].strftime('%d/%m/%Y %H:%M')   if p['ultima_mensagem']   else '-'
    print(f"{p['telefone']:<20} {p['nome']:<35} {p['total_mensagens']:>5} {len(p['requisicoes']):>5}  {primeira:>19}  {ultima:>19}")

print(f"{'='*90}")
print(f"\nTotal de pacientes/telefones únicos: {len(resultado)}")
print(f"Total de mensagens enviadas (geral): {sum(p['total_mensagens'] for p in resultado)}")
print(f"Total de requisições únicas:         {len(set(r for p in resultado for r in p['requisicoes']))}")

# Salva CSV de saída
output_csv = os.path.join(DIRETORIO, f"metrica_mensagens_paciente_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
with open(output_csv, 'w', newline='', encoding='utf-8-sig') as f:
    campos = ['Telefone', 'NomPaciente', 'TotalMensagens', 'TotalRequisicoes', 'PrimeiraMensagem', 'UltimaMensagem']
    writer = csv.DictWriter(f, fieldnames=campos)
    writer.writeheader()
    for p in resultado:
        writer.writerow({
            'Telefone': p['telefone'],
            'NomPaciente': p['nome'],
            'TotalMensagens': p['total_mensagens'],
            'TotalRequisicoes': len(p['requisicoes']),
            'PrimeiraMensagem': p['primeira_mensagem'].strftime('%d/%m/%Y %H:%M') if p['primeira_mensagem'] else '',
            'UltimaMensagem':   p['ultima_mensagem'].strftime('%d/%m/%Y %H:%M')   if p['ultima_mensagem']   else '',
        })

print(f"\n[OK] CSV salvo em: {output_csv}")
