#!/usr/bin/env python3
"""
make-spellbook.py — Markdown spells in spells/ → cards.pdf and table.pdf

Cards: 3.5"×5" cards, 4 per US Letter page, 2×2 grid, with dashed scissor
lines. Each spell file becomes one independent card, and oversized spells
automatically spill onto a second card.

Table: one-line-per-spell prep sheet with prep-slot checkboxes, level,
ritual/concentration flags, and name.

Usage:
    python make-spellbook.py
"""

import math
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

import markdown
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate, Frame, FrameBreak, HRFlowable,
    ListFlowable, ListItem, PageTemplate, Paragraph, SimpleDocTemplate,
    Table, TableStyle,
)

SPELLS_DIR = Path("spells")
CARDS_PDF = "cards.pdf"
TABLE_PDF = "table.pdf"
PREP_SLOTS = 5

# ── Page geometry ─────────────────────────────────────────────────────────────

PAGE_W, PAGE_H = letter        # 612 × 792 pt (8.5" × 11")

CARD_W = 3.5 * inch            # physical card width (sleeve size)
CARD_H = 5.0 * inch            # physical card height (sleeve size)

SIDE   = 0.5 * inch            # left / right page margin
TOPBOT = 0.25 * inch           # top / bottom page margin
GAP_H  = 0.5 * inch            # horizontal gap between the two columns
GAP_V  = 0.5 * inch            # vertical gap between the two rows

CARD_PAD = 0.15 * inch         # inset between card edge and card content

CARD_PAGE = (CARD_W, CARD_H)   # individual card page size

# Column / row origins (bottom-left corner of each card, in points)
COL_X = [SIDE, SIDE + CARD_W + GAP_H]
ROW_Y = [TOPBOT + CARD_H + GAP_V, TOPBOT]   # [top row, bottom row]

# Exact card edges along each axis — cutting on every one of these yields
# pieces that are precisely 3.5" × 5".
CUT_X = [COL_X[0], COL_X[0] + CARD_W, COL_X[1], COL_X[1] + CARD_W]
CUT_Y = [ROW_Y[1], ROW_Y[1] + CARD_H, ROW_Y[0], ROW_Y[0] + CARD_H]


# ── Cut guide ─────────────────────────────────────────────────────────────────

def draw_cut_lines(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColorRGB(0.5, 0.5, 0.5)
    canvas.setLineWidth(0.5)
    canvas.setDash([6, 4])
    for x in CUT_X:
        canvas.line(x, 0, x, PAGE_H)
    for y in CUT_Y:
        canvas.line(0, y, PAGE_W, y)
    canvas.restoreState()


# ── Styles ────────────────────────────────────────────────────────────────────

def make_styles():
    c = dict(alignment=TA_LEFT, textColor=colors.black)
    return {
        "h1":   ParagraphStyle("h1",   fontName="Helvetica-Bold",        fontSize=15, leading=18, spaceAfter=2, **c),
        "h2":   ParagraphStyle("h2",   fontName="Helvetica-Bold",        fontSize=12, leading=14, spaceAfter=2, **c),
        "h3":   ParagraphStyle("h3",   fontName="Helvetica-BoldOblique", fontSize=10, leading=12, spaceAfter=2, **c),
        "h4":   ParagraphStyle("h4",   fontName="Helvetica-Bold",        fontSize=9,  leading=11, spaceAfter=2, **c),
        "body": ParagraphStyle("body", fontName="Helvetica",             fontSize=9,  leading=12, spaceAfter=3, **c),
        "code": ParagraphStyle("code", fontName="Courier",              fontSize=8,  leading=10, spaceAfter=3, **c),
    }


# ── HTML → ReportLab flowables ────────────────────────────────────────────────

def _esc(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class HTMLFlowableParser(HTMLParser):
    """Walk HTML (output of markdown library) and produce ReportLab flowables."""

    BLOCK_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "pre", "blockquote"}

    def __init__(self, styles):
        super().__init__()
        self.styles    = styles
        self.flowables = []
        self._block    = None   # current block-level tag
        self._buf      = []     # inline markup buffer for current block
        self._li_buf   = []     # inline markup buffer for current <li>
        self._li_items = []     # collected Paragraphs for the current list
        self._list_type = []    # stack: 'ul' | 'ol'
        self._depth    = 0      # list nesting depth
        self._bold     = False
        self._italic   = False
        self._code     = False
        self._pre      = False

    # helpers

    def _fmt(self, text):
        text = _esc(text)
        if self._pre or self._code:
            text = f'<font name="Courier">{text}</font>'
        if self._bold and self._italic:
            return f"<b><i>{text}</i></b>"
        if self._bold:
            return f"<b>{text}</b>"
        if self._italic:
            return f"<i>{text}</i>"
        return text

    def _flush_block(self):
        text = "".join(self._buf).strip()
        self._buf = []
        if not text:
            return
        tag = self._block or "p"
        smap = {"h1":"h1","h2":"h2","h3":"h3","h4":"h4","h5":"h4","h6":"h4",
                "p":"body","blockquote":"body","pre":"code"}
        self.flowables.append(Paragraph(text, self.styles[smap.get(tag, "body")]))

    def _flush_li(self):
        text = "".join(self._li_buf).strip()
        self._li_buf = []
        if text:
            self._li_items.append(Paragraph(text, self.styles["body"]))

    # HTMLParser callbacks

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCK_TAGS:
            if self._depth == 0:       # ignore block tags nested inside lists
                self._flush_block()
                self._block = tag
                self._pre = (tag == "pre")
        elif tag in ("ul", "ol"):
            if self._depth == 0:
                self._flush_block()
                self._li_items = []
            self._list_type.append(tag)
            self._depth += 1
        elif tag == "li":
            self._flush_li()
        elif tag in ("strong", "b"):
            self._bold = True
        elif tag in ("em", "i"):
            self._italic = True
        elif tag == "code":
            self._code = True
        elif tag == "hr":
            self._flush_block()
            self.flowables.append(
                HRFlowable(width="100%", thickness=0.5, color=colors.grey, spaceAfter=4)
            )
        elif tag == "br":
            (self._li_buf if self._depth else self._buf).append("<br/>")

    def handle_endtag(self, tag):
        if tag in self.BLOCK_TAGS:
            if self._depth == 0:
                self._flush_block()
                self._block = None
                self._pre = False
        elif tag == "li":
            self._flush_li()
        elif tag in ("ul", "ol"):
            self._depth -= 1
            if self._depth == 0:
                ltype = self._list_type[-1] if self._list_type else "ul"
                btype = "bullet" if ltype == "ul" else "1"
                if self._li_items:
                    self.flowables.append(
                        ListFlowable(
                            [ListItem(p, leftIndent=12) for p in self._li_items],
                            bulletType=btype, leftIndent=12, spaceAfter=4,
                        )
                    )
                self._li_items = []
            if self._list_type:
                self._list_type.pop()
        elif tag in ("strong", "b"):
            self._bold = False
        elif tag in ("em", "i"):
            self._italic = False
        elif tag == "code":
            self._code = False

    def handle_data(self, data):
        if self._depth > 0:
            self._li_buf.append(self._fmt(data))
        elif self._block:
            self._buf.append(self._fmt(data))

    def get_flowables(self):
        self._flush_block()
        self._flush_li()
        return self.flowables


def md_to_flowables(md_text, styles):
    html = markdown.markdown(md_text)
    parser = HTMLFlowableParser(styles)
    parser.feed(html)
    return parser.get_flowables()


# ── Cards PDF ─────────────────────────────────────────────────────────────────

def build_cards_pdf(paths, styles):
    # Flowables are stateful once built (ReportLab caches wrap/split results
    # on them), so each spell gets its own freshly parsed set.
    story = []
    for i, path in enumerate(paths):
        flowables = md_to_flowables(path.read_text(encoding="utf-8"), styles)
        story.extend(flowables)
        if i < len(paths) - 1:
            story.append(FrameBreak())

    frames = [
        Frame(COL_X[0], ROW_Y[0], CARD_W, CARD_H,
              leftPadding=CARD_PAD, rightPadding=CARD_PAD,
              topPadding=CARD_PAD, bottomPadding=CARD_PAD, id="tl"),
        Frame(COL_X[1], ROW_Y[0], CARD_W, CARD_H,
              leftPadding=CARD_PAD, rightPadding=CARD_PAD,
              topPadding=CARD_PAD, bottomPadding=CARD_PAD, id="tr"),
        Frame(COL_X[0], ROW_Y[1], CARD_W, CARD_H,
              leftPadding=CARD_PAD, rightPadding=CARD_PAD,
              topPadding=CARD_PAD, bottomPadding=CARD_PAD, id="bl"),
        Frame(COL_X[1], ROW_Y[1], CARD_W, CARD_H,
              leftPadding=CARD_PAD, rightPadding=CARD_PAD,
              topPadding=CARD_PAD, bottomPadding=CARD_PAD, id="br"),
    ]
    template = PageTemplate(id="card", frames=frames, onPage=draw_cut_lines)

    doc = BaseDocTemplate(CARDS_PDF, pagesize=letter,
                          leftMargin=SIDE, rightMargin=SIDE,
                          topMargin=TOPBOT, bottomMargin=TOPBOT)
    doc.addPageTemplates([template])
    doc.build(story)

    n = len(paths)
    pages = math.ceil(n / 4)
    print(f"Wrote {CARDS_PDF}  ({n} cards, {pages} page{'s' if pages != 1 else ''})")


# ── Table PDF ─────────────────────────────────────────────────────────────────

def check_ritual(md_content):
    line_count = -1
    for l in md_content.split('\n'):
        if len(l.strip()) == 0: continue
        line_count += 1
        if line_count == 1:
            return 'ritual' in l.lower()


def check_concentration(md_content):
    for l in md_content.split('\n'):
        if re.match(r'^\s*-\s*duration:', l.lower()):
            return 'concentration' in l.lower()


def build_table_pdf(paths):
    spells = []
    for spell_path in paths:
        fn = spell_path.stem
        level = int(fn.split()[0])
        spell_name = ' '.join(fn.split()[1:])
        md_content = spell_path.read_text()
        is_ritual = check_ritual(md_content)
        needs_conc = check_concentration(md_content)
        spells.append((level, is_ritual, needs_conc, spell_name))

    spells.sort()

    header = ['Lvl', 'R', 'C', 'Spell'] + [''] * PREP_SLOTS
    rows = [header]
    mk_check = lambda _: '✓' if _ else ''
    for level, is_ritual, needs_conc, name in spells:
        row = [str(level), mk_check(is_ritual), mk_check(needs_conc), name] + [''] * PREP_SLOTS
        rows.append(row)

    doc = SimpleDocTemplate(
        TABLE_PDF,
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
    name_width = 2.0*inch
    col_widths = [lvl_width, ritual_width, conc_width, name_width] + [slot_width] * PREP_SLOTS

    table = Table(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#CCCCCC')),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (0, 0), (2, -1), 'CENTER'),
        ('ALIGN', (4, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F0F0F0')]),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))

    doc.build([table])
    print(f'Wrote {TABLE_PDF}')


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not SPELLS_DIR.is_dir():
        print(f"ERROR: not found: {SPELLS_DIR}", file=sys.stderr)
        sys.exit(1)

    paths = sorted(SPELLS_DIR.glob("*.md"))
    if not paths:
        print(f"ERROR: no spell files found in {SPELLS_DIR}", file=sys.stderr)
        sys.exit(1)

    styles = make_styles()
    build_cards_pdf(paths, styles)
    build_table_pdf(paths)


if __name__ == "__main__":
    main()
