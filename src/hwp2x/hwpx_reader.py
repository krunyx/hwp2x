"""Read an HWPX package into the document model (:mod:`hwp2x.model`).

HWPX layout used here
    Contents/content.hpf   metadata, manifest (binary items), spine (sections)
    Contents/header.xml    charPr (bold/italic...), paraPr (outline/list), styles
    Contents/sectionN.xml  hs:sec > hp:p > hp:run > hp:t | hp:ctrl | hp:tbl | hp:pic ...
"""
from __future__ import annotations

import posixpath
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from . import eqn
from .model import (Block, Break, Cell, Document, Figure, Image, Inline, Link, Math, MathBlock,
                    Note, Paragraph, Resource, Table, Text)

_NS = {
    "hp": "http://www.hancom.co.kr/hwpml/2011/paragraph",
    "hs": "http://www.hancom.co.kr/hwpml/2011/section",
    "hc": "http://www.hancom.co.kr/hwpml/2011/core",
    "hh": "http://www.hancom.co.kr/hwpml/2011/head",
    "opf": "http://www.idpf.org/2007/opf/",
}
_HWPUNIT_PER_MM = 7200 / 25.4
_DRAWINGS = {"rect", "ellipse", "arc", "polygon", "curve", "line", "connectLine"}
_SKIP_CTRL = {"colPr", "secPr", "pageNum", "newNum", "pageHiding", "pageNumCtrl", "bookmark",
              "indexmark", "hiddenComment", "header", "footer", "fieldEnd"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


@dataclass
class _CharStyle:
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    sup: bool = False
    sub: bool = False


@dataclass
class _ParaStyle:
    heading_type: str = "NONE"   # NONE | OUTLINE | NUMBER | BULLET
    level: int = 0
    align: str = ""


class HwpxReader:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.zf = zipfile.ZipFile(self.path)
        self.names = set(self.zf.namelist())
        self.doc = Document()
        self.chars: dict[str, _CharStyle] = {}
        self.paras: dict[str, _ParaStyle] = {}
        self.styles: dict[str, str] = {}
        self.bin_items: dict[str, tuple[str, str, bool]] = {}   # id -> (href, media type, embedded)
        self._counts: dict[str, int] = {}

    # ------------------------------------------------------------------ top level
    def read(self) -> Document:
        sections = self._read_package()
        self._read_header()
        for name in sections:
            root = ET.fromstring(self.zf.read(name))
            self.doc.blocks.extend(self._paragraphs(root, top=True))
        for what, n in sorted(self._counts.items()):
            self.doc.warn(f"{what} {n}개는 변환하지 않았습니다")
        self.zf.close()
        return self.doc

    def _read_package(self) -> list[str]:
        sections: list[str] = []
        if "Contents/content.hpf" in self.names:
            root = ET.fromstring(self.zf.read("Contents/content.hpf"))
            meta = root.find("opf:metadata", _NS)
            if meta is not None:
                t = meta.find("opf:title", _NS)
                self.doc.title = (t.text or "").strip() if t is not None else ""
                for m in meta.findall("opf:meta", _NS):
                    name, val = m.get("name", ""), (m.text or "").strip()
                    if name == "creator":
                        self.doc.author = val
                    elif name == "keyword":
                        self.doc.keywords = val
                    elif name == "date" and not self.doc.date:
                        self.doc.date = val
            ids: dict[str, str] = {}
            for item in root.iter(f"{{{_NS['opf']}}}item"):
                iid, href = item.get("id", ""), item.get("href", "")
                ids[iid] = href
                if href.startswith("BinData/") or item.get("isEmbeded") is not None:
                    self.bin_items[iid] = (href, item.get("media-type", ""), item.get("isEmbeded", "1") != "0")
            for ref in root.iter(f"{{{_NS['opf']}}}itemref"):
                href = ids.get(ref.get("idref", ""), "")
                if re.match(r"Contents/section\d+\.xml$", href):
                    sections.append(href)
        if not sections:
            sections = sorted((n for n in self.names if re.match(r"Contents/section\d+\.xml$", n)),
                              key=lambda n: int(re.findall(r"\d+", n)[0]))
        return sections

    def _read_header(self) -> None:
        if "Contents/header.xml" not in self.names:
            return
        root = ET.fromstring(self.zf.read("Contents/header.xml"))
        for cp in root.iter(f"{{{_NS['hh']}}}charPr"):
            st = _CharStyle()
            for ch in cp:
                n = _local(ch.tag)
                if n == "bold":
                    st.bold = True
                elif n == "italic":
                    st.italic = True
                elif n == "underline":
                    st.underline = ch.get("type", "NONE") not in ("NONE", "")
                elif n == "strikeout":
                    st.strike = ch.get("shape", "NONE") not in ("NONE", "")
                elif n == "supscript":
                    st.sup = True
                elif n == "subscript":
                    st.sub = True
            self.chars[cp.get("id", "")] = st
        for pp in root.iter(f"{{{_NS['hh']}}}paraPr"):
            st = _ParaStyle()
            h = pp.find("hh:heading", _NS)
            if h is not None:
                st.heading_type = h.get("type", "NONE")
                st.level = int(h.get("level", "0") or 0)
            a = pp.find("hh:align", _NS)
            if a is not None:
                st.align = {"CENTER": "center", "RIGHT": "right"}.get(a.get("horizontal", ""), "")
            self.paras[pp.get("id", "")] = st
        for s in root.iter(f"{{{_NS['hh']}}}style"):
            self.styles[s.get("id", "")] = s.get("name", "")

    # ------------------------------------------------------------------ paragraphs
    def _paragraphs(self, parent: ET.Element, top: bool = False) -> list[Block]:
        out: list[Block] = []
        for p in parent:
            if _local(p.tag) == "p":
                out.extend(self._paragraph(p))
        return out

    def _sublist(self, el: ET.Element | None) -> list[Block]:
        if el is None:
            return []
        sl = el.find("hp:subList", _NS) if _local(el.tag) != "subList" else el
        return self._paragraphs(sl) if sl is not None else []

    def _paragraph(self, p: ET.Element) -> list[Block]:
        ps = self.paras.get(p.get("paraPrIDRef", ""), _ParaStyle())
        blocks: list[Block] = []
        state = _InlineState()

        def flush() -> None:
            if state.root:
                blocks.append(self._make_para(state.root, ps))
            state.reset()

        for run in p:
            if _local(run.tag) != "run":
                continue
            cs = self.chars.get(run.get("charPrIDRef", ""), _CharStyle())
            for el in self._unswitch(run):
                self._run_child(el, cs, state, blocks, flush)
        flush()
        return blocks

    def _unswitch(self, parent: ET.Element):
        """Yield children, resolving hp:switch to its default (or first) branch."""
        for el in parent:
            if _local(el.tag) == "switch":
                branch = el.find("hp:default", _NS)
                if branch is None:
                    branch = el.find("hp:case", _NS)
                if branch is not None:
                    yield from self._unswitch(branch)
            else:
                yield el

    def _make_para(self, inlines: list[Inline], ps: _ParaStyle) -> Block:
        meaningful = [i for i in inlines if not (isinstance(i, Text) and not i.text.strip())]
        if len(meaningful) == 1 and isinstance(meaningful[0], Math):
            return MathBlock(meaningful[0])
        para = Paragraph(_merge_text(inlines), align=ps.align)
        if ps.heading_type == "OUTLINE" and para.plain_text().strip():
            para.heading = min(ps.level + 1, 6)
        elif ps.heading_type in ("NUMBER", "BULLET"):
            para.list_kind = "number" if ps.heading_type == "NUMBER" else "bullet"
            para.list_level = max(0, ps.level)
        return para

    def _run_child(self, el: ET.Element, cs: _CharStyle, st: "_InlineState",
                   blocks: list[Block], flush) -> None:
        name = _local(el.tag)
        if name == "t":
            self._text(el, cs, st)
        elif name == "ctrl":
            for c in self._unswitch(el):
                self._ctrl(c, cs, st)
        elif name == "secPr":
            pass
        elif name == "tbl":
            flush()
            blocks.append(self._table(el))
        elif name == "pic":
            img = self._image(el)
            if img is None:
                return
            caption = self._caption(el)
            if self._inline_obj(el) and not caption:
                st.add(img)
            else:
                flush()
                blocks.append(Figure(img, caption))
        elif name == "equation":
            script = el.findtext("hp:script", default="", namespaces=_NS) or ""
            math = Math(script, eqn.parse(script))
            caption = self._caption(el)
            if caption:                       # numbered/captioned equation: its own block
                flush()
                blocks.append(MathBlock(math))
                blocks.append(Paragraph(caption, align="center"))
            else:
                st.add(math)
        elif name in _DRAWINGS or name == "container":
            inner = self._drawing_blocks(el)
            if inner:
                flush()
                blocks.extend(inner)
        elif name == "textart":
            text = el.get("text", "")
            if text:
                st.add(Text(text, cs.bold, cs.italic))
        elif name == "dutmal":
            main = el.findtext("hp:mainText", default="", namespaces=_NS)
            sub = el.findtext("hp:subText", default="", namespaces=_NS)
            st.add(Text(main + (f"({sub})" if sub else ""), cs.bold, cs.italic, cs.underline, cs.strike))
        elif name == "compose":
            st.add(Text(el.get("composeText", ""), cs.bold, cs.italic))
        elif name in ("ole", "chart", "video"):
            self._count({"ole": "OLE 개체", "chart": "차트", "video": "동영상"}[name])
        elif name in ("btn", "checkBtn", "radioBtn", "comboBox", "listBox", "edit", "scrollBar"):
            self._count("양식 개체")

    def _text(self, t: ET.Element, cs: _CharStyle, st: "_InlineState") -> None:
        def add(s: str | None) -> None:
            if s:
                st.add(Text(s, cs.bold, cs.italic, cs.underline, cs.strike, cs.sup, cs.sub))

        add(t.text)
        for ch in t:
            n = _local(ch.tag)
            if n == "lineBreak":
                st.add(Break())
            elif n == "tab":
                add("\t")
            elif n == "fwSpace":
                add(" ")
            elif n == "nbSpace":
                add(" ")
            elif n == "hyphen":
                add("-")
            add(ch.tail)

    def _ctrl(self, c: ET.Element, cs: _CharStyle, st: "_InlineState") -> None:
        n = _local(c.tag)
        if n in ("footNote", "endNote"):
            blocks = self._sublist(c)
            st.add(Note("footnote" if n == "footNote" else "endnote", blocks))
        elif n == "autoNum":
            if c.get("numType") not in ("FOOTNOTE", "ENDNOTE"):
                st.add(Text(c.get("num", ""), cs.bold, cs.italic))
        elif n == "fieldBegin":
            if c.get("type") == "HYPERLINK":
                href = ""
                for sp in c.iter(f"{{{_NS['hp']}}}stringParam"):
                    if sp.get("name") == "Command":
                        href = _hyperlink_target(sp.text or "")
                st.open_link(c.get("id", ""), href)
        elif _local(c.tag) == "fieldEnd":
            st.close_link(c.get("beginIDRef", ""))
        # everything else (colPr, header/footer, page numbers, bookmarks...) carries no body text

    def _inline_obj(self, el: ET.Element) -> bool:
        pos = el.find("hp:pos", _NS)
        return pos is not None and pos.get("treatAsChar") == "1"

    def _caption(self, el: ET.Element) -> list[Inline]:
        cap = el.find("hp:caption", _NS)
        if cap is None:
            return []
        out: list[Inline] = []
        for b in self._sublist(cap):
            if isinstance(b, Paragraph):
                if out:
                    out.append(Text(" "))
                out.extend(b.inlines)
        return _strip_inlines(out)

    # ------------------------------------------------------------------ objects
    def _table(self, tbl: ET.Element) -> Table:
        t = Table(n_cols=int(tbl.get("colCnt", "0") or 0), caption=self._caption(tbl))
        widths_seen: list[tuple[int, int, int]] = []
        for tr in tbl.findall("hp:tr", _NS):
            row: list[Cell] = []
            for tc in tr.findall("hp:tc", _NS):
                addr = tc.find("hp:cellAddr", _NS)
                span = tc.find("hp:cellSpan", _NS)
                csz = tc.find("hp:cellSz", _NS)
                cell = Cell(
                    blocks=self._sublist(tc),
                    row=int(addr.get("rowAddr", "0")) if addr is not None else 0,
                    col=int(addr.get("colAddr", "0")) if addr is not None else 0,
                    rowspan=max(1, int(span.get("rowSpan", "1"))) if span is not None else 1,
                    colspan=max(1, int(span.get("colSpan", "1"))) if span is not None else 1,
                    header=tc.get("header") == "1",
                )
                if csz is not None:
                    widths_seen.append((cell.col, cell.colspan, int(csz.get("width", "0") or 0)))
                # drop trailing empty paragraphs inside cells
                while cell.blocks and isinstance(cell.blocks[-1], Paragraph) and not cell.blocks[-1].plain_text().strip() \
                        and not any(not isinstance(i, Text) for i in cell.blocks[-1].inlines):
                    cell.blocks.pop()
                row.append(cell)
            row.sort(key=lambda c: c.col)
            t.rows.append(row)
        if not t.n_cols:
            t.n_cols = max((sum(c.colspan for c in r) for r in t.rows), default=0)
        t.col_widths = _column_widths(t.n_cols, widths_seen)
        return t

    def _image(self, pic: ET.Element) -> Image | None:
        img = pic.find(".//hc:img", _NS)
        if img is None:
            return None
        ref = img.get("binaryItemIDRef", "")
        if ref not in self.doc.resources:
            item = self.bin_items.get(ref)
            if item is None:
                return None
            href, mtype, embedded = item
            path = posixpath.normpath(href)
            if not embedded or path not in self.names:
                self._count("연결된(포함되지 않은) 그림")
                return None
            data = self.zf.read(path)
            self.doc.resources[ref] = Resource(posixpath.basename(path), mtype or _guess_type(path), data)
        w = h = 0.0
        sz = pic.find("hp:sz", _NS)
        if sz is None:
            sz = pic.find(".//hp:curSz", _NS)
        if sz is not None:
            w = int(sz.get("width", "0") or 0) / _HWPUNIT_PER_MM
            h = int(sz.get("height", "0") or 0) / _HWPUNIT_PER_MM
        return Image(ref, round(w, 1), round(h, 1))

    def _drawing_blocks(self, el: ET.Element) -> list[Block]:
        """Text boxes and grouped objects: their content as ordinary blocks."""
        out: list[Block] = []
        name = _local(el.tag)
        if name == "container":
            for ch in el:
                cn = _local(ch.tag)
                if cn in _DRAWINGS or cn == "container":
                    out.extend(self._drawing_blocks(ch))
                elif cn == "pic":
                    img = self._image(ch)
                    if img:
                        out.append(Figure(img, self._caption(ch)))
            return out
        dt = el.find("hp:drawText", _NS)
        if dt is not None:
            out.extend(self._sublist(dt))
        cap = self._caption(el)
        if cap:
            out.append(Paragraph(cap))
        return out

    def _count(self, what: str) -> None:
        self._counts[what] = self._counts.get(what, 0) + 1


class _InlineState:
    """Collects inlines for one paragraph; hyperlinks open and close across runs."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.root: list[Inline] = []
        self.stack: list[tuple[str, list[Inline]]] = []

    def add(self, i: Inline) -> None:
        (self.stack[-1][1] if self.stack else self.root).append(i)

    def open_link(self, fid: str, href: str) -> None:
        link = Link(href, [])
        self.add(link)
        self.stack.append((fid, link.children))

    def close_link(self, fid: str) -> None:
        for k in range(len(self.stack) - 1, -1, -1):
            if self.stack[k][0] == fid or not fid:
                del self.stack[k:]
                return


def _column_widths(n: int, seen: list[tuple[int, int, int]]) -> list[float]:
    """Relative column widths from cell widths (a cell may span columns)."""
    if n <= 0:
        return []
    col: list[float | None] = [None] * n
    for c, span, w in seen:
        if span == 1 and 0 <= c < n and w > 0 and col[c] is None:
            col[c] = float(w)
    for _ in range(3):                       # spanning cells fill in what is left
        for c, span, w in sorted(seen, key=lambda x: x[1]):
            cols = [k for k in range(c, min(c + span, n))]
            unknown = [k for k in cols if col[k] is None]
            if not unknown or w <= 0:
                continue
            rest = w - sum(col[k] for k in cols if col[k] is not None)
            if rest > 0:
                for k in unknown:
                    col[k] = rest / len(unknown)
    known = [w for w in col if w]
    fill = sum(known) / len(known) if known else 1.0
    widths = [w if w else fill for w in col]
    total = sum(widths)
    return [w / total for w in widths]


def _hyperlink_target(command: str) -> str:
    """HWP hyperlink command: ``https\\://example.com;1;0;0;`` -> URL."""
    target = command.replace("\\:", ":").replace("\\;", "\x00").split(";", 1)[0].replace("\x00", ";")
    return target.strip()


def _merge_text(inlines: list[Inline]) -> list[Inline]:
    out: list[Inline] = []
    for i in inlines:
        if isinstance(i, Link):
            i.children = _merge_text(i.children)
        if out and isinstance(i, Text) and isinstance(out[-1], Text) and out[-1].same_style(i):
            out[-1] = Text(out[-1].text + i.text, i.bold, i.italic, i.underline, i.strike, i.sup, i.sub)
        else:
            out.append(i)
    return out


def _strip_inlines(inlines: list[Inline]) -> list[Inline]:
    inlines = _merge_text(inlines)
    if inlines and isinstance(inlines[0], Text):
        inlines[0].text = inlines[0].text.lstrip()
    if inlines and isinstance(inlines[-1], Text):
        inlines[-1].text = inlines[-1].text.rstrip()
    return [i for i in inlines if not (isinstance(i, Text) and not i.text)]


def _guess_type(path: str) -> str:
    ext = path.rsplit(".", 1)[-1].lower()
    return {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif",
            "bmp": "image/bmp", "wmf": "image/x-wmf", "emf": "image/x-emf", "svg": "image/svg+xml",
            "tif": "image/tiff", "tiff": "image/tiff"}.get(ext, "application/octet-stream")


def read_hwpx(path: str | Path) -> Document:
    return HwpxReader(path).read()
