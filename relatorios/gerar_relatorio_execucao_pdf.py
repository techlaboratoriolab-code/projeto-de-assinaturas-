from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
import csv
from pathlib import Path

INPUT = Path('log_motivos_sem_assinatura_20260515_095557.csv')
OUTPUT = Path('relatorio_execucao_20260515_095557.pdf')

rows = []
with INPUT.open('r', encoding='utf-8', newline='') as f:
    reader = csv.DictReader(f)
    for row in reader:
        rows.append(row)

summary = {
    'total': len(rows),
    'com_telefone': sum(1 for r in rows if r.get('TemTelefone','').upper() == 'COM_TELEFONE'),
    'sem_telefone': sum(1 for r in rows if r.get('TemTelefone','').upper() == 'SEM_TELEFONE'),
    'motivo_sem_assinatura': sum(1 for r in rows if r.get('Motivo','') == 'SEM_ASSINATURA_PACIENTE'),
    'com_assinatura': sum(1 for r in rows if (r.get('TemAssinatura','').upper() == 'SIM')),
}

styles = getSampleStyleSheet()
styleN = styles['BodyText']
styleH = styles['Heading1']
styleH2 = styles['Heading2']
styleB = styles['BodyText']
styleB.spaceAfter = 6

story = []
story.append(Paragraph('Relatório de Execução - Assinaturas', styleH))
story.append(Spacer(1, 12))
story.append(Paragraph('Período analisado: 13/05/2026 a 15/05/2026', styleB))
story.append(Paragraph('Data do relatório: 15/05/2026', styleB))
story.append(Spacer(1, 12))

story.append(Paragraph('Resumo da Execução', styleH2))
story.append(Spacer(1, 6))
summary_data = [
    ['Total de requisições analisadas', summary['total']],
    ['Motivo principal', 'SEM_ASSINATURA_PACIENTE'],
    ['Pacientes com telefone', summary['com_telefone']],
    ['Pacientes sem telefone', summary['sem_telefone']],
    ['Total com assinatura', summary['com_assinatura']],
    ['Total sem assinatura', summary['motivo_sem_assinatura']],
    ['Enviados para WhatsApp', 21],
    ['Envios com telefone inválido', 2],
]
summary_table = Table(summary_data, colWidths=[240, 120])
summary_table.setStyle(TableStyle([
    ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
    ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
    ('FONTSIZE', (0, 0), (-1, -1), 10),
]))
story.append(summary_table)
story.append(Spacer(1, 12))

story.append(Paragraph('Arquivos gerados', styleH2))
story.append(Spacer(1, 6))
for name in [
    'log_motivos_sem_assinatura_20260515_095557.csv',
    'requisicoes_sem_telefone_20260515_095704.csv',
    'telefones_sem_assinatura_20260515_095704.csv',
    'documentos_autentique_producao_20260515_095923.csv',
]:
    story.append(Paragraph(f'- {name}', styleB))
story.append(Spacer(1, 12))

story.append(Paragraph('Principais observações', styleH2))
story.append(Spacer(1, 6))
notes = [
    'Foram identificadas 32 requisições sem assinatura de paciente.',
    '23 pacientes tinham telefone cadastrado e 9 estavam sem telefone.',
    '21 documentos foram enviados para assinatura via WhatsApp com sucesso.',
    '2 envios falharam devido a telefone inválido.',
    'A persistência de skip-list para sem telefone está desativada, mantendo esses casos para nova tentativa quando o telefone for corrigido.',
]
for note in notes:
    story.append(Paragraph(f'- {note}', styleB))
story.append(Spacer(1, 12))

story.append(Paragraph('Requisições sem telefone', styleH2))
story.append(Spacer(1, 6))
sem_tel = [r for r in rows if r.get('TemTelefone','').upper() == 'SEM_TELEFONE']
if sem_tel:
    for r in sem_tel:
        story.append(Paragraph(f"- {r['CodRequisicao']} | {r['NomPaciente']} | {r['LocalOrigem']} | Conv {r['IdConvenio']}", styleB))
else:
    story.append(Paragraph('Nenhuma requisição sem telefone encontrada.', styleB))
story.append(Spacer(1, 12))

story.append(Paragraph('Telefones inválidos identificados', styleH2))
story.append(Spacer(1, 6))
invalid = [r for r in rows if r.get('Telefones') and len(''.join(c for c in r['Telefones'] if c.isdigit())) < 11]
if invalid:
    for r in invalid:
        story.append(Paragraph(f"- {r['CodRequisicao']} | {r['NomPaciente']} | {r['Telefones']}", styleB))
else:
    story.append(Paragraph('Nenhum telefone inválido detectado.', styleB))

pdf = SimpleDocTemplate(str(OUTPUT), pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
pdf.build(story)
print(f'PDF gerado: {OUTPUT.resolve()}')
