#!/usr/bin/env python3
"""
make-slot-tracker.py — one-page wizard spell slot tracker PDF.

Given a wizard's class level and Intelligence score, computes cantrips
known, spells prepared, arcane recovery capacity, and spell slots per
spell level, then lays out a checkbox grid (one row per day) for
tracking slot usage across multiple sessions on a single printed page.

Usage:
    python make-slot-tracker.py --level 5 --int 18
    python make-slot-tracker.py --level 5 --int 18 --name Elminster --days 8 -o elminster-slots.pdf
"""

import argparse
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    Flowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

# ── Wizard progression tables (PHB) ─────────────────────────────────────────

# Index 0 unused; index = character level, value = list of slot counts for
# spell levels 1..9 (trailing zeros trimmed away when used).
SLOTS_BY_LEVEL = {
    1:  [2],
    2:  [3],
    3:  [4, 2],
    4:  [4, 3],
    5:  [4, 3, 2],
    6:  [4, 3, 3],
    7:  [4, 3, 3, 1],
    8:  [4, 3, 3, 2],
    9:  [4, 3, 3, 3, 1],
    10: [4, 3, 3, 3, 2],
    11: [4, 3, 3, 3, 2, 1],
    12: [4, 3, 3, 3, 2, 1],
    13: [4, 3, 3, 3, 2, 1, 1],
    14: [4, 3, 3, 3, 2, 1, 1],
    15: [4, 3, 3, 3, 2, 1, 1, 1],
    16: [4, 3, 3, 3, 2, 1, 1, 1],
    17: [4, 3, 3, 3, 2, 1, 1, 1, 1],
    18: [4, 3, 3, 3, 3, 1, 1, 1, 1],
    19: [4, 3, 3, 3, 3, 2, 1, 1, 1],
    20: [4, 3, 3, 3, 3, 2, 2, 1, 1],
}


def cantrips_known(level):
    if level >= 10:
        return 5
    if level >= 4:
        return 4
    return 3


def int_modifier(score):
    return (score - 10) // 2


def spells_prepared(level, int_score):
    return max(1, level + int_modifier(int_score))


def arcane_recovery_max(level):
    # Combined slot levels recoverable; never a slot of 6th level or higher.
    return -(-level // 2)  # ceil(level / 2)


def proficiency_bonus(level):
    return 2 + (level - 1) // 4


def spell_attack_bonus(level, int_score):
    return proficiency_bonus(level) + int_modifier(int_score)


def spell_save_dc(level, int_score):
    return 8 + proficiency_bonus(level) + int_modifier(int_score)


# ── Checkbox flowable ────────────────────────────────────────────────────────

class Checkboxes(Flowable):
    """A row of small square checkboxes, drawn left to right."""

    def __init__(self, n, box=10, gap=4, per_row=None):
        super().__init__()
        self.n = n
        self.box = box
        self.gap = gap
        self.per_row = per_row or n or 1
        rows = max(1, -(-n // self.per_row)) if n else 1
        self.width = self.per_row * box + (self.per_row - 1) * gap
        self.height = rows * box + (rows - 1) * gap

    def wrap(self, availWidth, availHeight):
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.saveState()
        c.setStrokeColor(colors.black)
        c.setLineWidth(0.75)
        for i in range(self.n):
            row = i // self.per_row
            col = i % self.per_row
            x = col * (self.box + self.gap)
            y = self.height - self.box - row * (self.box + self.gap)
            c.rect(x, y, self.box, self.box)
        c.restoreState()


# ── PDF build ─────────────────────────────────────────────────────────────────

def make_styles():
    c = dict(alignment=TA_LEFT, textColor=colors.black)
    return {
        "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=18, leading=22, **c),
        "sub":   ParagraphStyle("sub",   fontName="Helvetica",      fontSize=11, leading=14, **c),
        "stat":  ParagraphStyle("stat",  fontName="Helvetica",      fontSize=10, leading=13, **c),
        "statb": ParagraphStyle("statb", fontName="Helvetica-Bold", fontSize=10, leading=13, **c),
        "hdr":   ParagraphStyle("hdr",   fontName="Helvetica-Bold", fontSize=9,  leading=11, textColor=colors.white, alignment=1),
        "cell":  ParagraphStyle("cell",  fontName="Helvetica",      fontSize=9,  leading=11, **c),
        "note":  ParagraphStyle("note",  fontName="Helvetica-Oblique", fontSize=8, leading=10, **c),
    }


def build_pdf(level, int_score, name, days, out_path, bonus_cantrips=0):
    if not (1 <= level <= 20):
        print("ERROR: level must be between 1 and 20", file=sys.stderr)
        sys.exit(1)

    slots = SLOTS_BY_LEVEL[level]
    max_spell_level = len(slots)
    mod = int_modifier(int_score)
    n_cantrips = cantrips_known(level) + bonus_cantrips
    n_prepared = spells_prepared(level, int_score)
    recovery = arcane_recovery_max(level)
    atk_bonus = spell_attack_bonus(level, int_score)
    save_dc = spell_save_dc(level, int_score)

    styles = make_styles()
    story = []

    who = f"{name} — " if name else ""
    story.append(Paragraph(f"{who}Wizard Tracker", styles["title"]))
    story.append(Paragraph(
        f"Level {level} Wizard &nbsp;&bull;&nbsp; INT {int_score} ({mod:+d})",
        styles["sub"],
    ))
    story.append(Spacer(1, 8))

    cantrips_display = str(n_cantrips)
    if bonus_cantrips:
        base = cantrips_known(level)
        cantrips_display = f"{n_cantrips} ({base} base + {bonus_cantrips} bonus)"

    stat_row = [
        [Paragraph("Cantrips Known", styles["stat"]),
         Paragraph("Spells Prepared", styles["stat"]),
         Paragraph("Spell Attack", styles["stat"]),
         Paragraph("Spell Save DC", styles["stat"]),
         Paragraph("Arcane Recovery", styles["stat"])],
        [Paragraph(cantrips_display, styles["statb"]),
         Paragraph(str(n_prepared), styles["statb"]),
         Paragraph(f"{atk_bonus:+d}", styles["statb"]),
         Paragraph(str(save_dc), styles["statb"]),
         Paragraph(f"up to {recovery} slot level{'s' if recovery != 1 else ''}", styles["statb"])],
    ]
    stat_table = Table(stat_row, colWidths=[1.7 * inch, 1.4 * inch, 1.1 * inch, 1.2 * inch, 1.6 * inch])
    stat_table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.75, colors.black),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#CCCCCC')),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(stat_table)
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"Arcane Recovery: once per day (usually after a short rest), recover expended "
        f"spell slots with a combined level up to {recovery} (no slot of 6th level or higher).",
        styles["note"],
    ))
    story.append(Spacer(1, 10))

    # ── Slot-tracking grid: one row per day ──
    header = [Paragraph("Day / Date", styles["hdr"])]
    for lvl, count in enumerate(slots, start=1):
        header.append(Paragraph(f"Lvl {lvl}<br/>({count})", styles["hdr"]))
    header.append(Paragraph("Arcane<br/>Recovery", styles["hdr"]))

    rows = [header]
    for d in range(1, days + 1):
        row = [Paragraph(f"Day {d}<br/>____________", styles["cell"])]
        for count in slots:
            row.append(Checkboxes(count, box=9, gap=4, per_row=2))
        row.append(Checkboxes(1, box=9, gap=4, per_row=1))
        rows.append(row)

    day_col = 1.1 * inch
    slot_col = (7.5 * inch - day_col - 0.7 * inch) / max_spell_level
    col_widths = [day_col] + [slot_col] * max_spell_level + [0.7 * inch]

    grid = Table(rows, colWidths=col_widths, repeatRows=1)
    grid.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4A4A4A')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F0F0F0')]),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(grid)

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=letter,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.4 * inch,
        bottomMargin=0.4 * inch,
    )
    doc.build(story)
    print(f"Wrote {out_path}")


def main():
    p = argparse.ArgumentParser(description="Generate a one-page wizard spell slot tracker PDF.")
    p.add_argument("--level", type=int, required=True, help="wizard class level (1-20)")
    p.add_argument("--int", type=int, required=True, dest="int_score", help="Intelligence score")
    p.add_argument("--name", default="", help="character name (optional)")
    p.add_argument("--days", type=int, default=10, help="number of day rows to print (default: 10)")
    p.add_argument("--bonus-cantrips", type=int, default=0,
                    help="extra cantrips known from race/feats/subclass, e.g. High Elf's Cantrip Trainer trait")
    p.add_argument("-o", "--output", default="slot-tracker.pdf", help="output PDF path")
    args = p.parse_args()

    build_pdf(args.level, args.int_score, args.name, args.days, Path(args.output),
              bonus_cantrips=args.bonus_cantrips)


if __name__ == "__main__":
    main()
