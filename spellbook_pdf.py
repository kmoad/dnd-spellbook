from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
from reportlab.lib.units import inch
import re

spellbook_dir = Path('spellbook')
prep_slots = 5

def check_ritual(md_content):
    line_count = -1
    for l in md_content.split('\n'):
        if len(l.strip()) == 0: continue
        line_count += 1
        if line_count == 2:
            return 'ritual' in l
            
def check_concentration(md_content):
    for l in md_content.split('\n'):
        if re.match(r'^\s*-\s*duration:', l.lower()):
            return 'concentration' in l.lower()

spells = []
for spell_path in spellbook_dir.iterdir():
    fn = spell_path.stem
    level = int(fn.split()[0])
    spell_name = ' '.join(fn.split()[1:])
    md_content = spell_path.read_text()
    is_ritual = check_ritual(md_content)
    needs_conc = check_concentration(md_content)
    spells.append((level, is_ritual, needs_conc, spell_name))

spells.sort()

header = [''] * prep_slots + ['Lvl', 'R', 'C', 'Spell']
rows = [header]
mk_check = lambda _: '✓' if _ else ''
for level, is_ritual, needs_conc, name in spells:
    row = [''] * prep_slots + [str(level), mk_check(is_ritual), mk_check(needs_conc), name]
    rows.append(row)

doc = SimpleDocTemplate(
    'spellbook.pdf',
    pagesize=letter,
    leftMargin=0.5*inch,
    rightMargin=0.5*inch,
    topMargin=0.5*inch,
    bottomMargin=0.5*inch,
)

slot_width = 0.35*inch
lvl_width = 0.4*inch
ritual_width = 0.2*inch
conc_width = 0.2*inch
name_width = 3.0*inch
col_widths = [slot_width] * prep_slots + [lvl_width, ritual_width, conc_width, name_width]

table = Table(rows, colWidths=col_widths, repeatRows=1)
table.setStyle(TableStyle([
    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#CCCCCC')),
    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
    ('FONTSIZE', (0, 0), (-1, -1), 10),
    ('ALIGN', (0, 0), (prep_slots - 1, -1), 'CENTER'),
    ('ALIGN', (prep_slots, 0), (prep_slots + 2, -1), 'CENTER'),
    ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F0F0F0')]),
    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ('TOPPADDING', (0, 0), (-1, -1), 4),
    ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
]))

doc.build([table])
print('Wrote spellbook.pdf')
