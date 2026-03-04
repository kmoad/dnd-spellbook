from pathlib import Path
import pandas as pd

spellbook_dir = Path('spellbook')
prep_slots = 5
spells = []
for spell_path in spellbook_dir.iterdir():
    fn = spell_path.stem
    level = int(fn.split()[0])
    spell_name = ' '.join(fn.split()[1:])
    entry = ['_'] * prep_slots + [level, spell_name]
    spells.append(entry)

spells.sort(key=lambda entry: (entry[prep_slots], entry[prep_slots+1]))

for entry in spells:
    print('\t'.join([str(_) for _ in entry]))
