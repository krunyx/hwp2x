"""HTML output: one self-contained page (images embedded, equations as MathML)."""
from __future__ import annotations

import base64
from html import escape
from pathlib import Path
from typing import Callable, Optional

from .. import eqn
from ..model import (Block, Break, Document, Figure, Image, Inline, Link, Math, MathBlock, Note,
                     Paragraph, Table, Text, iter_inlines)
from .common import ACCEPT, Assets, convert_image, group_lists, nest_list, table_grid

_CSS = """
:root { color-scheme: light dark; --ink:#1b2633; --muted:#5b6878; --line:#d5dce3; --paper:#ffffff; }
@media (prefers-color-scheme: dark) { :root { --ink:#e3e8ed; --muted:#9aa6b2; --line:#3a4654; --paper:#14191f; } }
body { margin:0; background:var(--paper); color:var(--ink);
       font-family:"Noto Sans KR","Malgun Gothic","Apple SD Gothic Neo",sans-serif; line-height:1.7; }
main { max-width:52rem; margin:0 auto; padding:2rem 1rem 4rem; }
h1,h2,h3,h4,h5,h6 { line-height:1.35; margin:1.6em 0 .5em; }
p { margin:.5em 0; word-break:keep-all; overflow-wrap:anywhere; }
table { border-collapse:collapse; margin:1em 0; max-width:100%; display:block; overflow-x:auto; }
td,th { border:1px solid var(--line); padding:.35em .6em; vertical-align:top; }
td p, th p { margin:.15em 0; }
caption, figcaption { color:var(--muted); font-size:.92em; padding:.3em 0; text-align:left; }
figure { margin:1em 0; } img { max-width:100%; height:auto; }
math[display="block"] { margin:.6em 0; overflow-x:auto; }
.footnotes { border-top:1px solid var(--line); margin-top:3em; font-size:.92em; color:var(--muted); }
.center { text-align:center; } .right { text-align:right; }
"""


class HtmlRenderer:
    """Renders model blocks to HTML. ``image_src`` decides how pictures are
    referenced (embedded data URI for HTML pages, file path inside Markdown)."""

    def __init__(self, doc: Document, image_src: Callable[[Image], Optional[str]]):
        self.doc = doc
        self.image_src = image_src
        self.notes: list[Note] = []

    # -- blocks
    def blocks(self, blocks: list[Block]) -> str:
        out: list[str] = []
        for kind, item in group_lists(blocks):
            if kind == "list":
                out.append(self._list(nest_list(item)))
            else:
                out.append(self.block(item))
        return "\n".join(o for o in out if o)

    def block(self, b: Block) -> str:
        if isinstance(b, Paragraph):
            inner = self.inlines(b.inlines)
            if b.heading:
                return f"<h{b.heading}>{inner}</h{b.heading}>"
            cls = f' class="{b.align}"' if b.align else ""
            return f"<p{cls}>{inner}</p>" if inner.strip() else ""
        if isinstance(b, MathBlock):
            return self.math(b.math, display=True)
        if isinstance(b, Table):
            return self.table(b)
        if isinstance(b, Figure):
            img = self.image(b.image)
            cap = f"<figcaption>{self.inlines(b.caption)}</figcaption>" if b.caption else ""
            return f"<figure>{img}{cap}</figure>" if img or cap else ""
        return ""

    def _list(self, nodes) -> str:
        if not nodes:
            return ""
        tag = "ol" if nodes[0][0].list_kind == "number" else "ul"
        items = []
        for p, children in nodes:
            sub = self._list(children)
            items.append(f"<li>{self.inlines(p.inlines)}{sub}</li>")
        return f"<{tag}>" + "".join(items) + f"</{tag}>"

    def table(self, t: Table) -> str:
        rows = []
        grid = table_grid(t)
        for r_i, row in enumerate(t.rows):
            cells = []
            for col in range(t.n_cols):
                slot = grid[r_i][col] if r_i < len(grid) else None
                if slot is None:          # hole in a malformed table
                    cells.append("<td></td>")
                    continue
                cell, origin = slot
                if not origin:
                    continue
                tag = "th" if cell.header else "td"
                span = (f' rowspan="{cell.rowspan}"' if cell.rowspan > 1 else "") + \
                       (f' colspan="{cell.colspan}"' if cell.colspan > 1 else "")
                body = self._cell(cell.blocks)
                cells.append(f"<{tag}{span}>{body}</{tag}>")
            rows.append("<tr>" + "".join(cells) + "</tr>")
        cap = f"<caption>{self.inlines(t.caption)}</caption>" if t.caption else ""
        return f"<table>{cap}" + "".join(rows) + "</table>"

    def _cell(self, blocks: list[Block]) -> str:
        if len(blocks) == 1 and isinstance(blocks[0], Paragraph) and not blocks[0].heading \
                and not blocks[0].list_kind:
            return self.inlines(blocks[0].inlines)
        return self.blocks(blocks)

    # -- inlines
    def inlines(self, items: list[Inline]) -> str:
        return "".join(self.inline(i) for i in items)

    def inline(self, i: Inline) -> str:
        if isinstance(i, Text):
            s = escape(i.text).replace("\t", " ")
            if i.sup:
                s = f"<sup>{s}</sup>"
            if i.sub:
                s = f"<sub>{s}</sub>"
            if i.strike:
                s = f"<s>{s}</s>"
            if i.underline:
                s = f"<u>{s}</u>"
            if i.italic:
                s = f"<em>{s}</em>"
            if i.bold:
                s = f"<strong>{s}</strong>"
            return s
        if isinstance(i, Break):
            return "<br>"
        if isinstance(i, Math):
            return self.math(i)
        if isinstance(i, Link):
            href = escape(i.href, quote=True)
            return f'<a href="{href}">{self.inlines(i.children)}</a>'
        if isinstance(i, Image):
            return self.image(i)
        if isinstance(i, Note):
            self.notes.append(i)
            n = len(self.notes)
            return f'<sup id="fnref{n}"><a href="#fn{n}">{n}</a></sup>'
        return ""

    def math(self, m: Math, display: bool = False) -> str:
        tree = m.ast if m.ast is not None else eqn.parse(m.source)
        mml = eqn.to_mathml(tree, display)
        latex, _ = eqn.to_latex(tree, "md")
        # keep the TeX source as an annotation so it can be copied
        inner = mml[mml.index(">") + 1: -len("</math>")]
        head = mml[: mml.index(">") + 1]
        return (head + "<semantics><mrow>" + inner + "</mrow>"
                + f'<annotation encoding="application/x-tex">{escape(latex)}</annotation></semantics></math>')

    def image(self, img: Image) -> str:
        src = self.image_src(img)
        if not src:
            return ""
        style = f' style="width:{img.width_mm:.0f}mm"' if img.width_mm else ""
        return f'<img src="{escape(src, quote=True)}" alt="{escape(img.alt, quote=True)}"{style}>'

    def footnotes(self) -> str:
        if not self.notes:
            return ""
        items = []
        k = 0
        while k < len(self.notes):          # notes may contain notes
            note = self.notes[k]
            k += 1
            body = self.blocks(note.blocks)
            items.append(f'<li id="fn{k}">{body} <a href="#fnref{k}" aria-label="본문으로">↩</a></li>')
        return '<section class="footnotes"><ol>' + "".join(items) + "</ol></section>"


def _data_uri(doc: Document):
    cache: dict[str, Optional[str]] = {}

    def src(img: Image) -> Optional[str]:
        if img.ref not in cache:
            res = doc.resources.get(img.ref)
            conv = convert_image(res, ACCEPT["html"]) if res else None
            if res and conv is None:
                doc.warn(f"그림 형식({res.name.rsplit('.', 1)[-1].upper()})을 변환할 수 없어 일부 그림을 넣지 못했습니다")
            cache[img.ref] = (f"data:{conv.media_type};base64," + base64.b64encode(conv.data).decode()) if conv else None
        return cache[img.ref]
    return src


_EMBED_LIMIT = 20 * 1024 * 1024


def write_html(doc: Document, out: Path) -> list[Path]:
    # Embed pictures so the page is a single file, unless that would make it
    # huge (e.g. one picture repeated thousands of times): then link to files.
    uses: dict[str, int] = {}
    for i in iter_inlines(doc.blocks):
        if isinstance(i, Image):
            uses[i.ref] = uses.get(i.ref, 0) + 1
    embedded = sum(len(doc.resources[r].data) * 4 // 3 * n for r, n in uses.items() if r in doc.resources)
    assets = None
    if embedded > _EMBED_LIMIT:
        assets = Assets(doc, out, "html")
        r = HtmlRenderer(doc, assets.path_for)
    else:
        r = HtmlRenderer(doc, _data_uri(doc))
    body = r.blocks(doc.blocks)
    notes = r.footnotes()
    title = doc.title or out.stem
    meta = ""
    if doc.author:
        meta += f'<meta name="author" content="{escape(doc.author, quote=True)}">'
    if doc.keywords:
        meta += f'<meta name="keywords" content="{escape(doc.keywords, quote=True)}">'
    html = (f'<!doctype html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f'<meta name="generator" content="hwp2x">{meta}\n<title>{escape(title)}</title>\n'
            f"<style>{_CSS}</style>\n</head>\n<body>\n<main>\n{body}\n{notes}\n</main>\n</body>\n</html>\n")
    out.write_text(html, encoding="utf-8")
    return [out] + (assets.files if assets else [])
