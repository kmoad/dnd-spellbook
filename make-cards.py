#!/usr/bin/env python3
"""
compile_cards.py — Markdown files → printable 3.5"×5" card PDF

4 cards per US Letter page, 2×2 grid, each card in vertical (portrait)
orientation sized for standard 3.5"×5" sleeves. Dashed scissor lines mark
the exact cut points. Each input file becomes one independent card, so new
spells can be inserted anywhere without renumbering. A spell whose content
doesn't fit on one card automatically spills onto a second card.

Usage:
    python compile_cards.py spellbook/*.md
    python compile_cards.py spellbook/*.md -o spellbook.pdf
    python compile_cards.py "spellbook/1 Magic Missile.md"
"""

import argparse
import math
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
)

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


def write_individual_card(flowables, out_path, styles):
    """Write a single 3.5" × 5" PDF for one card (extra pages if it overflows)."""
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=CARD_PAGE,
        leftMargin=CARD_PAD, rightMargin=CARD_PAD,
        topMargin=CARD_PAD, bottomMargin=CARD_PAD,
    )
    doc.build(flowables)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description='Compile markdown files into a 3.5"×5" card PDF (4 cards/page).'
    )
    ap.add_argument("files", nargs="+", help="Markdown files (order = print order)")
    ap.add_argument("-o", "--output", default="all-cards.pdf",
                    help="Output PDF filename (default: cards.pdf)")
    ap.add_argument("--cards-dir", default="cards",
                    help="Directory for individual card PDFs (default: cards/)")
    args = ap.parse_args()

    paths = [Path(f) for f in args.files]
    missing = [p for p in paths if not p.exists()]
    if missing:
        for p in missing:
            print(f"ERROR: not found: {p}", file=sys.stderr)
        sys.exit(1)

    cards_dir = Path(args.cards_dir)
    cards_dir.mkdir(exist_ok=True)

    styles = make_styles()

    # Individual card PDFs. Flowables are stateful once built (ReportLab
    # caches wrap/split results on them), so each PDF gets its own freshly
    # parsed set rather than reusing objects across builds.
    for path in paths:
        flowables = md_to_flowables(path.read_text(encoding="utf-8"), styles)
        out = cards_dir / (path.stem + ".pdf")
        write_individual_card(flowables, out, styles)
        print(f"  {out}")

    # Combined print PDF (4 per letter page, 2×2 grid, with cut lines).
    # No FrameBreak is forced when content overflows a card's frame — ReportLab
    # automatically continues into the next frame, so an oversized spell just
    # spills onto a second card. A FrameBreak is inserted between spells so
    # each one always starts on a fresh card.
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

    doc = BaseDocTemplate(args.output, pagesize=letter,
                          leftMargin=SIDE, rightMargin=SIDE,
                          topMargin=TOPBOT, bottomMargin=TOPBOT)
    doc.addPageTemplates([template])
    doc.build(story)

    n = len(paths)
    pages = math.ceil(n / 4)
    print(f"Wrote {args.output}  ({n} cards, {pages} page{'s' if pages != 1 else ''})")


if __name__ == "__main__":
    main()
