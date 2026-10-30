"""Markdown output (GitHub-flavoured: pipe tables, footnotes, $math$).

Tables with merged cells or several paragraphs per cell cannot be written
as pipe tables; they are written as HTML tables, which Markdown allows."""
from __future__ import annotations

import re
from pathlib import Path

from .. import eqn
from ..model import (Block, Break, Document, Figure, Image, Inline, Link, Math, MathBlock, Note,
                     Paragraph, Table, Text, inline_text)
from .common import Assets, group_lists, nest_list
from .html import HtmlRenderer

_ESC = re.compile(r"([\\`*_\[\]<>|~$])")
_LINE_START = re.compile(r"^(\s*)([#>+\-=]|\d+[.)])(?=\s|$)")


def _esc(s: str) -> str:
    return _ESC.sub(r"\\\1", s)


class _Md:
    def __init__(self, doc: Document, assets: Assets):
        self.doc = doc
        self.assets = assets
        self.notes: list[Note] = []

    # -- blocks
    def blocks(self, blocks: list[Block]) -> str:
        parts: list[str] = []
        for kind, item in group_lists(blocks):
            if kind == "list":
                parts.append(self._list(nest_list(item), 0))
            else:
                s = self.block(item)
                if s.strip():
                    parts.append(s)
        return "\n\n".join(parts)

    def block(self, b: Block) -> str:
        if isinstance(b, Paragraph):
            text = self.para_text(b.inlines)
            if b.heading:
                return "#" * b.heading + " " + text.replace("\n", " ")
            return text
        if isinstance(b, MathBlock):
            return "$$\n" + self._latex(b.math) + "\n$$"
        if isinstance(b, Table):
            return self.table(b)
        if isinstance(b, Figure):
            img = self.image(b.image)
            cap = self.inlines(b.caption)
            return img + (f"\n\n*{cap}*" if cap.strip() else "")
        return ""

    def para_text(self, items: list[Inline]) -> str:
        text = self.inlines(items).strip()
        # A leading "1." "-" "#" would turn the paragraph into a list/heading.
        text = "\n".join(_LINE_START.sub(lambda m: m.group(1) + "\\" + m.group(2), ln.lstrip())
                         for ln in text.split("\n"))
        return text

    def _list(self, nodes, depth: int) -> str:
        lines = []
        for k, (p, children) in enumerate(nodes, 1):
            marker = f"{k}." if p.list_kind == "number" else "-"
            pad = "    " * depth
            body = self.inlines(p.inlines).strip().replace("\n", "\n" + pad + "    ")
            lines.append(f"{pad}{marker} {body}")
            if children:
                lines.append(self._list(children, depth + 1))
        return "\n".join(lines)

    def table(self, t: Table) -> str:
        cap = f"*{self.inlines(t.caption)}*\n\n" if t.caption else ""
        if not t.is_simple or not t.rows:
            html = HtmlRenderer(self.doc, self.assets.path_for)
            html.notes = self.notes          # keep one footnote sequence
            return cap + html.table(Table(t.rows, t.n_cols, []))
        width = t.n_cols or max(len(r) for r in t.rows)

        def cell_text(c) -> str:
            if not c.blocks:
                return ""
            return self.inlines(c.blocks[0].inlines).replace("\n", "<br>").replace("|", r"\|").strip()

        rows = [[cell_text(c) for c in r] + [""] * (width - len(r)) for r in t.rows]
        head, body = rows[0], rows[1:]
        out = ["| " + " | ".join(head) + " |", "|" + "---|" * width]
        out += ["| " + " | ".join(r) + " |" for r in body]
        return cap + "\n".join(out)

    # -- inlines
    def inlines(self, items: list[Inline]) -> str:
        out: list[str] = []
        for i in items:
            out.append(self.inline(i))
        return "".join(out)

    def inline(self, i: Inline) -> str:
        if isinstance(i, Text):
            s = _esc(i.text.replace("\t", " "))
            if not s.strip():
                return s
            lead = s[: len(s) - len(s.lstrip())]
            trail = s[len(s.rstrip()):]
            core = s.strip()
            if i.sup:
                core = f"<sup>{core}</sup>"
            if i.sub:
                core = f"<sub>{core}</sub>"
            if i.underline:
                core = f"<u>{core}</u>"
            if i.strike:
                core = f"~~{core}~~"
            if i.italic:
                core = f"*{core}*"
            if i.bold:
                core = f"**{core}**"
            return lead + core + trail
        if isinstance(i, Break):
            return "\\\n"
        if isinstance(i, Math):
            return "$" + self._latex(i) + "$"
        if isinstance(i, Link):
            text = self.inlines(i.children) or _esc(i.href)
            return f"[{text}](<{i.href}>)"
        if isinstance(i, Image):
            return self.image(i)
        if isinstance(i, Note):
            self.notes.append(i)
            return f"[^{len(self.notes)}]"
        return ""

    def _latex(self, m: Math) -> str:
        tree = m.ast if m.ast is not None else eqn.parse(m.source)
        return eqn.to_latex(tree, "md")[0]

    def image(self, img: Image) -> str:
        path = self.assets.path_for(img)
        if not path:
            return ""
        return f"![{_esc(img.alt)}](<{path}>)"

    def footnotes(self) -> str:
        out = []
        k = 0
        while k < len(self.notes):
            note = self.notes[k]
            k += 1
            body = self.blocks(note.blocks).strip() or " "
            body = body.replace("\n", "\n    ")
            out.append(f"[^{k}]: {body}")
        return "\n\n".join(out)


def write_markdown(doc: Document, out: Path) -> list[Path]:
    assets = Assets(doc, out, "md")
    md = _Md(doc, assets)
    body = md.blocks(doc.blocks)
    notes = md.footnotes()
    text = body + ("\n\n" + notes if notes else "") + "\n"
    out.write_text(text, encoding="utf-8")
    return [out] + assets.files
