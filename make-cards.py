#!/usr/bin/env python3
"""
compile_cards.py — Markdown files → printable half-page card PDF

2 cards per US Letter page. A dashed scissor line marks the exact center.
Each input file becomes one independent card, so new spells can be inserted
anywhere without renumbering.

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

PAGE_W, PAGE_H = letter       # 612 × 792 pt
SIDE  = 0.5 * inch            # left / right margin
OUTER = 0.45 * inch           # top / bottom outer margin
PAD   = 0.2 * inch            # gap between cut line and card content

MID_Y  = PAGE_H / 2           # 396 pt — exact centre
CARD_W = PAGE_W - 2 * SIDE    # 7.5"
CARD_H = MID_Y - OUTER - PAD  # ≈ 4.8" usable per card

HALF_PAGE = (PAGE_W, PAGE_H / 2)  # 8.5" × 5.5" — individual card page size


# ── Cut guide ─────────────────────────────────────────────────────────────────

def draw_cut_line(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColorRGB(0.5, 0.5, 0.5)
    canvas.setLineWidth(0.5)
    canvas.setDash([6, 4])
    canvas.line(0, MID_Y, PAGE_W, MID_Y)
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
    """Write a single half-page (8.5" × 5.5") PDF for one card."""
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=HALF_PAGE,
        leftMargin=SIDE, rightMargin=SIDE,
        topMargin=OUTER, bottomMargin=OUTER,
    )
    doc.build(flowables)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Compile markdown files into a half-page card PDF (2 cards/page)."
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

    # Individual half-page PDFs
    all_flowables = []
    for path in paths:
        flowables = md_to_flowables(path.read_text(encoding="utf-8"), styles)
        all_flowables.append(flowables)
        out = cards_dir / (path.stem + ".pdf")
        write_individual_card(list(flowables), out, styles)
        print(f"  {out}")

    # Combined print PDF (2 per letter page with cut line)
    story = []
    for i, flowables in enumerate(all_flowables):
        story.extend(flowables)
        if i < len(all_flowables) - 1:
            story.append(FrameBreak())

    top_frame = Frame(SIDE, MID_Y + PAD, CARD_W, CARD_H,
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
                      id="top")
    bot_frame = Frame(SIDE, OUTER, CARD_W, CARD_H,
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
                      id="bot")
    template = PageTemplate(id="card", frames=[top_frame, bot_frame],
                            onPage=draw_cut_line)

    doc = BaseDocTemplate(args.output, pagesize=letter,
                          leftMargin=SIDE, rightMargin=SIDE,
                          topMargin=OUTER, bottomMargin=OUTER)
    doc.addPageTemplates([template])
    doc.build(story)

    n = len(paths)
    pages = math.ceil(n / 2)
    print(f"Wrote {args.output}  ({n} cards, {pages} page{'s' if pages != 1 else ''})")


if __name__ == "__main__":
    main()
