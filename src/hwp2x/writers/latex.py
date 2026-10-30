"""LaTeX output in two profiles.

tex   a standalone XeLaTeX/LuaLaTeX document (kotex for Korean text,
      hangulmath when equations contain Hangul jamo).
htex  a HyperTeX 2.0 document: only the declarative command set of the
      HyperTeX spec (no page commands, no \\multirow, no \\sout, https links).
"""
from __future__ import annotations

import re
from pathlib import Path

from .. import eqn
from ..eqn import tex_text
from ..model import (Block, Break, Document, Figure, Image, Inline, Link, Math, MathBlock, Note,
                     Paragraph, Table, Text, iter_inlines)
from .common import Assets, group_lists, nest_list, table_grid

_SECTION = {"tex": ["section", "subsection", "subsubsection", "paragraph", "subparagraph", "subparagraph"],
            "htex": ["section", "subsection", "subsubsection", "paragraph", "paragraph", "paragraph"]}

_TEX_PREAMBLE = r"""%% hwp2x 가 만든 문서입니다. XeLaTeX 또는 LuaLaTeX 로 컴파일하세요.
\documentclass[11pt]{article}
\usepackage{kotex}
\usepackage{amsmath,amssymb}
\usepackage{graphicx}
\usepackage[a4paper,margin=25mm]{geometry}
\usepackage{array,longtable,multirow}
\IfFileExists{ulem.sty}{\usepackage[normalem]{ulem}}{}
\providecommand\sout[1]{#1}
%% 한글 글꼴: 설치된 글꼴 가운데 처음 찾은 것을 씁니다. 원하는 글꼴로 바꿔도 됩니다.
\ExplSyntaxOn
\clist_map_inline:nn { Noto~Serif~CJK~KR, NanumMyeongjo, Batang, AppleMyungjo, Malgun~Gothic, UnBatang }
  { \IfFontExistsTF {#1} { \setmainhangulfont {#1} \clist_map_break: } { } }
\ExplSyntaxOff
"""
_TEX_POST = r"""\usepackage[hidelinks]{hyperref}
"""


class _Latex:
    def __init__(self, doc: Document, assets: Assets, profile: str):
        self.doc = doc
        self.assets = assets
        self.p = profile
        self.uses_hangulmath = False
        self.uses_hangul_math = False
        self.dropped_rowspan = False
        self.dropped_strike = False

    # -- blocks
    def blocks(self, blocks: list[Block]) -> str:
        parts: list[str] = []
        for kind, item in group_lists(blocks):
            if kind == "list":
                parts.append(self._list(nest_list(item)))
            else:
                s = self.block(item)
                if s.strip():
                    parts.append(s)
        return "\n\n".join(parts)

    def block(self, b: Block) -> str:
        if isinstance(b, Paragraph):
            text = self.para_text(b.inlines)
            if b.heading:
                cmd = _SECTION[self.p][min(b.heading, 6) - 1]
                plain = text.replace(r"\\", " ").replace("\n", " ")
                return f"\\{cmd}{{{plain}}}"
            if not text.strip():
                return ""
            if b.align == "center":
                return "\\begin{center}\n" + text + "\n\\end{center}"
            return text
        if isinstance(b, MathBlock):
            return "\\[\n" + self._math(b.math) + "\n\\]"
        if isinstance(b, Table):
            return self.table(b)
        if isinstance(b, Figure):
            inc = self._include(b.image)
            if not inc and not b.caption:
                return ""
            cap = f"\n\\caption{{{self.inlines(b.caption)}}}" if b.caption else ""
            if self.p == "tex":
                return "\\begin{figure}[htbp]\n\\centering\n" + inc + cap + "\n\\end{figure}"
            return "\\begin{figure}\n" + inc + cap + "\n\\end{figure}"
        return ""

    def para_text(self, items: list[Inline]) -> str:
        s = self.inlines(items)
        s = re.sub(r"[ \t]+", " ", s).strip()
        s = re.sub(r"(\\\\\s*)+$", "", s)         # no trailing line breaks
        return s

    def _list(self, nodes) -> str:
        if not nodes:
            return ""
        env = "enumerate" if nodes[0][0].list_kind == "number" else "itemize"
        lines = [f"\\begin{{{env}}}"]
        for p, children in nodes:
            lines.append("  \\item " + self.para_text(p.inlines))
            if children:
                lines.append(self._list(children))
        lines.append(f"\\end{{{env}}}")
        return "\n".join(lines)

    def table(self, t: Table, nested: bool = False) -> str:
        n = max(t.n_cols, 1)
        grid = table_grid(t)
        self._widths = t.widths()
        self._n = n
        rows: list[str] = []
        for r_i in range(len(t.rows)):
            cells: list[str] = []
            col = 0
            while col < n:
                slot = grid[r_i][col]
                if slot is None:
                    cells.append("")
                    col += 1
                    continue
                cell, origin = slot
                if not origin:
                    # covered by a cell above (rowspan): an empty slot of the same width
                    if cell.colspan > 1:
                        cells.append(f"\\multicolumn{{{cell.colspan}}}{{|{self._colspec(col, cell.colspan)}|}}{{}}")
                    else:
                        cells.append("")
                    col += cell.colspan
                    continue
                body = self._cell(cell.blocks)
                if cell.rowspan > 1:
                    if self.p == "tex":
                        body = f"\\multirow{{{cell.rowspan}}}{{=}}{{{body}}}"
                    else:
                        self.dropped_rowspan = True
                if cell.colspan > 1:
                    body = f"\\multicolumn{{{cell.colspan}}}{{|{self._colspec(col, cell.colspan)}|}}{{{body}}}"
                cells.append(body)
                col += cell.colspan
            rows.append(" & ".join(cells) + r" \\" + self._rule(grid, r_i, n))
        cap = self.inlines(t.caption) if t.caption else ""
        if self.p == "tex":
            spec = "|" + "".join(self._colspec(c, 1) + "|" for c in range(n))
            sep = self._tabcolsep(n)
            env = "tabular" if nested else "longtable"
            head = f"{cap} \\newline " if nested and cap else ""   # no \caption inside a cell
            head += "" if nested else f"{{\\setlength\\tabcolsep{{{sep}pt}}\n"
            head += f"\\begin{{{env}}}{{{spec}}}\n"
            if cap and not nested:
                head += f"\\caption{{{cap}}} \\\\\n"
            tail = f"\n\\end{{{env}}}" + ("" if nested else "}")
            return head + "\\hline\n" + "\n".join(rows) + tail
        spec = "|" + "l|" * n
        tab = f"\\begin{{tabular}}{{{spec}}}\n\\hline\n" + "\n".join(rows) + "\n\\end{tabular}"
        if cap and nested:
            return cap + " \\newline " + tab
        if cap:
            return "\\begin{table}\n\\caption{" + cap + "}\n" + tab + "\n\\end{table}"
        return tab

    @staticmethod
    def _tabcolsep(n: int) -> float:
        """Cell padding shrinks for many-column tables so the text never runs out of width."""
        return round(max(1.0, min(6.0, 6.0 * 8 / n)), 2)

    def _colspec(self, col: int, span: int) -> str:
        if self.p != "tex":
            return "l"
        # Width = share of the space left after padding and rules, plus the
        # padding and rules swallowed when the cell spans several columns.
        frac = sum(self._widths[col:col + span])
        n = self._n
        w = (f"{frac:.4f}\\dimexpr\\linewidth-{2 * n}\\tabcolsep-{n + 1}\\arrayrulewidth\\relax"
             + (f"+{2 * (span - 1)}\\tabcolsep+{span - 1}\\arrayrulewidth" if span > 1 else ""))
        return f"p{{\\dimexpr{w}\\relax}}"

    def _rule(self, grid, r_i: int, n: int) -> str:
        """\\hline, or \\cline segments where a cell continues downwards."""
        if r_i + 1 >= len(grid):
            return " \\hline"
        open_cols = [c for c in range(n)
                     if grid[r_i][c] is not None and grid[r_i + 1][c] is not None
                     and grid[r_i][c][0] is grid[r_i + 1][c][0]]
        if not open_cols:
            return " \\hline"
        segs, start = [], None
        for c in range(n + 1):
            closed = c < n and c not in open_cols
            if closed and start is None:
                start = c
            if not closed and start is not None:
                segs.append(f"\\cline{{{start + 1}-{c}}}")
                start = None
        return " " + " ".join(segs)

    def _cell(self, blocks: list[Block]) -> str:
        parts = []
        for b in blocks:
            if isinstance(b, Paragraph):
                s = self.para_text(b.inlines)
                if s:
                    parts.append(s.replace(r"\\", r"\newline "))
            elif isinstance(b, Table):
                saved = (self._widths, self._n)
                parts.append(self.table(b, nested=True))
                self._widths, self._n = saved
            elif isinstance(b, MathBlock):
                parts.append("$" + self._math(b.math) + "$")
            elif isinstance(b, Figure):
                parts.append(self._include(b.image, cell=True))
        return r" \newline ".join(p for p in parts if p)

    # -- inlines
    def inlines(self, items: list[Inline]) -> str:
        return "".join(self.inline(i) for i in items)

    def inline(self, i: Inline) -> str:
        if isinstance(i, Text):
            s = tex_text(i.text.replace("\t", " ")).replace("\u00a0", "~")
            if not s.strip():
                return s
            lead = s[: len(s) - len(s.lstrip())]
            trail = s[len(s.rstrip()):]
            core = s.strip()
            if i.sup:
                core = f"\\textsuperscript{{{core}}}" if self.p == "tex" else f"$^{{\\text{{{core}}}}}$"
            if i.sub:
                core = f"\\textsubscript{{{core}}}" if self.p == "tex" else f"$_{{\\text{{{core}}}}}$"
            if i.strike:
                if self.p == "tex":
                    core = f"\\sout{{{core}}}"
                else:
                    self.dropped_strike = True
            if i.underline:
                core = f"\\underline{{{core}}}"
            if i.italic:
                core = f"\\textit{{{core}}}"
            if i.bold:
                core = f"\\textbf{{{core}}}"
            return lead + core + trail
        if isinstance(i, Break):
            return r"\\" + "\n"
        if isinstance(i, Math):
            return "$" + self._math(i) + "$"
        if isinstance(i, Link):
            text = self.inlines(i.children)
            href = i.href
            if self.p == "htex" and not href.lower().startswith(("https://", "htex://", "#")):
                # HyperTeX only links to https: show the address instead of a broken link
                return text + (f" ({tex_text(href)})" if href and tex_text(href) not in text else "")
            url = href.replace("\\", "/").replace("%", r"\%").replace("#", r"\#")
            return f"\\href{{{url}}}{{{text or tex_text(href)}}}"
        if isinstance(i, Image):
            return self._include(i, inline=True)
        if isinstance(i, Note):
            body = self.blocks(i.blocks).replace("\n\n", r"\par ").strip()
            return f"\\footnote{{{body}}}"
        return ""

    def _math(self, m: Math) -> str:
        tree = m.ast if m.ast is not None else eqn.parse(m.source)
        latex, hm = eqn.to_latex(tree, self.p)
        self.uses_hangulmath |= hm
        if re.search(r"[\u3131-\u318e\uac00-\ud7a3]", m.source):
            self.uses_hangul_math = True
        return latex

    def _include(self, img: Image, inline: bool = False, cell: bool = False) -> str:
        path = self.assets.path_for(img)
        if not path:
            return ""
        if self.p == "htex":
            return f"\\includegraphics{{{path}}}"
        if cell:
            opt = "width=\\linewidth"
        elif img.width_mm:
            opt = f"width={min(img.width_mm, 160):.1f}mm"
        else:
            opt = "width=0.8\\linewidth"
        if inline:
            opt = f"height={min(img.height_mm, 60):.1f}mm" if img.height_mm and img.width_mm < 40 else opt
        return f"\\includegraphics[{opt},keepaspectratio]{{{path}}}"


def write_latex(doc: Document, out: Path, profile: str = "tex") -> list[Path]:
    assets = Assets(doc, out, profile)
    w = _Latex(doc, assets, profile)
    body = w.blocks(doc.blocks)

    meta = []
    if doc.title:
        meta.append(f"\\title{{{tex_text(doc.title)}}}")
    if doc.author:
        meta.append(f"\\author{{{tex_text(doc.author)}}}")
    if profile == "htex" and doc.keywords:
        meta.append(f"\\keywords{{{tex_text(doc.keywords)}}}")
    if doc.title:
        meta.append("\\date{}" if profile == "tex" else "")

    if profile == "tex":
        head = _TEX_PREAMBLE
        if w.uses_hangulmath:
            head += "\\usepackage{hangulmath}  %% 수식 속 한글 자모 (CTAN: hangulmath)\n"
        head += _TEX_POST
    else:
        head = "%% hwp2x 가 만든 HyperTeX 문서입니다.\n\\documentclass{hypertex}\n"
        if w.uses_hangul_math:
            head += "\\usemath{hangulmath}\n"
    head += "\n".join(m for m in meta if m) + ("\n" if meta else "")
    title = "\\maketitle\n\n" if doc.title else ""
    text = f"{head}\n\\begin{{document}}\n{title}{body}\n\n\\end{{document}}\n"
    out.write_text(text, encoding="utf-8")

    if w.dropped_rowspan:
        doc.warn("HyperTeX 표는 세로 병합을 지원하지 않아, 병합된 셀 내용을 첫 칸에만 넣었습니다")
    if w.dropped_strike:
        doc.warn("HyperTeX는 취소선을 지원하지 않아 취소선 서식을 뺐습니다")
    return [out] + assets.files
