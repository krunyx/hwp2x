"""Word (DOCX) output, written directly as Office Open XML.

Supports headings, lists (bullet and numbered, nested), tables with merged
cells, footnotes, hyperlinks, images and equations (as native Word
equations, OMML)."""
from __future__ import annotations

import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from .. import eqn
from ..model import (Block, Break, Document, Figure, Image, Inline, Link, Math, MathBlock, Note,
                     Paragraph, Table, Text)
from .common import ACCEPT, convert_image, group_lists, image_size_px, table_grid

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_DECL = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math" '
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"'
)
_TEXT_WIDTH_MM = 160.0      # A4 with 25 mm margins
_EMU_PER_MM = 36000
_TWIPS_PER_MM = 56.6929


def _t(text: str) -> str:
    return f'<w:t xml:space="preserve">{escape(text)}</w:t>'


class _Docx:
    def __init__(self, doc: Document):
        self.doc = doc
        self.rels: list[tuple[str, str, str, bool]] = []   # id, type, target, external
        self.media: dict[str, tuple[str, bytes, str]] = {} # ref -> (name, data, media type)
        self.media_rid: dict[str, str] = {}
        self.footnotes: list[str] = []
        self.numbering: list[tuple[int, int]] = []        # (numId, abstractNumId)
        self._next_pic = 1

    def rid(self, rtype: str, target: str, external: bool = False) -> str:
        rid = f"rId{len(self.rels) + 10}"
        self.rels.append((rid, rtype, target, external))
        return rid

    # -- blocks
    def blocks(self, blocks: list[Block]) -> str:
        out: list[str] = []
        for kind, item in group_lists(blocks):
            if kind == "list":
                out.append(self._list(item))
            else:
                out.append(self.block(item))
        return "".join(out)

    def block(self, b: Block) -> str:
        if isinstance(b, Paragraph):
            ppr = ""
            if b.heading:
                ppr += f'<w:pStyle w:val="Heading{b.heading}"/>'
            if b.align:
                ppr += f'<w:jc w:val="{"center" if b.align == "center" else "right"}"/>'
            return self._p(ppr, self.inlines(b.inlines))
        if isinstance(b, MathBlock):
            tree = b.math.ast if b.math.ast is not None else eqn.parse(b.math.source)
            return "<w:p>" + eqn.to_omml(tree, display=True) + "</w:p>"
        if isinstance(b, Table):
            return self.table(b)
        if isinstance(b, Figure):
            out = self._p('<w:jc w:val="center"/>', self.image(b.image))
            if b.caption:
                out += self._p('<w:pStyle w:val="Caption"/>', self.inlines(b.caption))
            return out
        return ""

    def _p(self, ppr: str, content: str) -> str:
        return "<w:p>" + (f"<w:pPr>{ppr}</w:pPr>" if ppr else "") + content + "</w:p>"

    def _list(self, items: list[Paragraph]) -> str:
        abstract = 1 if items[0].list_kind == "number" else 0
        num_id = len(self.numbering) + 1
        self.numbering.append((num_id, abstract))
        out = []
        for p in items:
            ppr = (f'<w:pStyle w:val="ListParagraph"/><w:numPr><w:ilvl w:val="{min(p.list_level, 8)}"/>'
                   f'<w:numId w:val="{num_id}"/></w:numPr>')
            out.append(self._p(ppr, self.inlines(p.inlines)))
        return "".join(out)

    def table(self, t: Table) -> str:
        n = max(t.n_cols, 1)
        col_w = int(_TEXT_WIDTH_MM * _TWIPS_PER_MM / n)
        grid = table_grid(t)
        out = []
        if t.caption:
            out.append(self._p('<w:pStyle w:val="Caption"/><w:keepNext/>', self.inlines(t.caption)))
        out.append('<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:w="5000" w:type="pct"/>'
                   '<w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid>'
                   + f'<w:gridCol w:w="{col_w}"/>' * n + "</w:tblGrid>")
        for r_i in range(len(t.rows)):
            out.append("<w:tr>")
            col = 0
            while col < n:
                slot = grid[r_i][col]
                if slot is None:
                    out.append(f'<w:tc><w:tcPr><w:tcW w:w="{col_w}" w:type="dxa"/></w:tcPr><w:p/></w:tc>')
                    col += 1
                    continue
                cell, origin = slot
                span = cell.colspan
                tcpr = f'<w:tcW w:w="{col_w * span}" w:type="dxa"/>'
                if span > 1:
                    tcpr += f'<w:gridSpan w:val="{span}"/>'
                if cell.rowspan > 1:
                    tcpr += '<w:vMerge w:val="restart"/>' if origin else "<w:vMerge/>"
                body = self.blocks(cell.blocks) if origin else ""
                if not body.endswith("</w:p>"):
                    body += "<w:p/>"          # a cell must end with a paragraph
                out.append(f"<w:tc><w:tcPr>{tcpr}</w:tcPr>{body}</w:tc>")
                col += span
            out.append("</w:tr>")
        out.append("</w:tbl>")
        out.append("<w:p/>")                  # Word needs a paragraph between tables
        return "".join(out)

    # -- inlines
    def inlines(self, items: list[Inline]) -> str:
        return "".join(self.inline(i) for i in items)

    def _rpr(self, i: Text, rstyle: str = "") -> str:
        r = f'<w:rStyle w:val="{rstyle}"/>' if rstyle else ""     # rStyle must come first
        if i.bold:
            r += "<w:b/>"
        if i.italic:
            r += "<w:i/>"
        if i.strike:
            r += "<w:strike/>"
        if i.underline:
            r += '<w:u w:val="single"/>'
        if i.sup:
            r += '<w:vertAlign w:val="superscript"/>'
        elif i.sub:
            r += '<w:vertAlign w:val="subscript"/>'
        return f"<w:rPr>{r}</w:rPr>" if r else ""

    def inline(self, i: Inline, rstyle: str = "") -> str:
        if isinstance(i, Text):
            content = "<w:tab/>".join(_t(p) for p in i.text.split("\t"))
            return f"<w:r>{self._rpr(i, rstyle)}{content}</w:r>"
        if isinstance(i, Break):
            return "<w:r><w:br/></w:r>"
        if isinstance(i, Math):
            tree = i.ast if i.ast is not None else eqn.parse(i.source)
            return eqn.to_omml(tree)
        if isinstance(i, Link):
            if not i.href:
                return self.inlines(i.children)
            if i.href.startswith("#"):
                return f'<w:hyperlink w:anchor={quoteattr(i.href[1:])}>' + \
                    "".join(self.inline(c, "Hyperlink") for c in i.children) + "</w:hyperlink>"
            rid = self.rid(f"{_R}/hyperlink", i.href, external=True)
            kids = i.children or [Text(i.href)]
            return f'<w:hyperlink r:id="{rid}">' + "".join(self.inline(c, "Hyperlink") for c in kids) + "</w:hyperlink>"
        if isinstance(i, Image):
            return self.image(i)
        if isinstance(i, Note):
            fid = len(self.footnotes) + 1
            self.footnotes.append("")          # reserve the id (notes can nest)
            body = self.blocks(i.blocks) or "<w:p/>"
            ref = '<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr><w:footnoteRef/></w:r><w:r><w:t xml:space="preserve"> </w:t></w:r>'
            # put the footnote mark at the start of the first paragraph
            if body.startswith("<w:p><w:pPr>"):
                k = body.index("</w:pPr>") + len("</w:pPr>")
                body = body[:k] + ref + body[k:]
            elif body.startswith("<w:p>"):
                body = '<w:p><w:pPr><w:pStyle w:val="FootnoteText"/></w:pPr>' + ref + body[len("<w:p>"):]
            else:
                body = '<w:p><w:pPr><w:pStyle w:val="FootnoteText"/></w:pPr>' + ref + "</w:p>" + body
            self.footnotes[fid - 1] = f'<w:footnote w:id="{fid}">{body}</w:footnote>'
            return f'<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr><w:footnoteReference w:id="{fid}"/></w:r>'
        return ""

    def image(self, img: Image) -> str:
        res = self.doc.resources.get(img.ref)
        if res is None:
            return ""
        if img.ref not in self.media_rid:
            conv = convert_image(res, ACCEPT["docx"])
            if conv is None:
                self.doc.warn(f"그림 형식({res.name.rsplit('.', 1)[-1].upper()})을 변환할 수 없어 일부 그림을 넣지 못했습니다")
                self.media_rid[img.ref] = ""
                return ""
            ext = conv.name.rsplit(".", 1)[-1].lower()
            name = f"image{len(self.media) + 1}.{ext}"
            self.media[img.ref] = (name, conv.data, conv.media_type)
            self.media_rid[img.ref] = self.rid(f"{_R}/image", f"media/{name}")
        rid = self.media_rid[img.ref]
        if not rid:
            return ""
        w, h = img.width_mm, img.height_mm
        if not (w and h):
            px = image_size_px(self.media[img.ref][1])
            w, h = (px[0] * 25.4 / 96, px[1] * 25.4 / 96) if px[0] else (80.0, 60.0)
        if w > _TEXT_WIDTH_MM:
            h, w = h * _TEXT_WIDTH_MM / w, _TEXT_WIDTH_MM
        cx, cy = int(w * _EMU_PER_MM), int(h * _EMU_PER_MM)
        pid = self._next_pic
        self._next_pic += 1
        return (f'<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">'
                f'<wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="{pid}" name="그림 {pid}"/>'
                f'<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
                f'<pic:pic><pic:nvPicPr><pic:cNvPr id="{pid}" name="{self.media[img.ref][0]}"/><pic:cNvPicPr/></pic:nvPicPr>'
                f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
                f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
                f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
                f"</a:graphicData></a:graphic></wp:inline></w:drawing></w:r>")


# --------------------------------------------------------------------------- package parts
def _styles() -> str:
    heads = ""
    sizes = {1: 32, 2: 28, 3: 26, 4: 24, 5: 22, 6: 22}
    for lvl in range(1, 7):
        heads += (f'<w:style w:type="paragraph" w:styleId="Heading{lvl}"><w:name w:val="heading {lvl}"/>'
                  f'<w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:uiPriority w:val="9"/><w:qFormat/>'
                  f'<w:pPr><w:keepNext/><w:spacing w:before="{360 - lvl * 30}" w:after="120"/>'
                  f'<w:outlineLvl w:val="{lvl - 1}"/></w:pPr>'
                  f'<w:rPr><w:b/><w:sz w:val="{sizes[lvl]}"/><w:szCs w:val="{sizes[lvl]}"/></w:rPr></w:style>')
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:styles {_NS_DECL}>'
            '<w:docDefaults><w:rPrDefault><w:rPr>'
            '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="맑은 고딕" w:cs="Calibri"/>'
            '<w:sz w:val="21"/><w:szCs w:val="21"/><w:lang w:val="en-US" w:eastAsia="ko-KR"/>'
            '</w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="300" w:lineRule="auto"/>'
            '<w:wordWrap w:val="0"/></w:pPr></w:pPrDefault></w:docDefaults>'
            '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>'
            + heads +
            '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/>'
            '<w:pPr><w:jc w:val="center"/><w:spacing w:after="240"/></w:pPr><w:rPr><w:b/><w:sz w:val="36"/></w:rPr></w:style>'
            '<w:style w:type="paragraph" w:styleId="Caption"><w:name w:val="caption"/><w:basedOn w:val="Normal"/>'
            '<w:rPr><w:color w:val="5B6878"/><w:sz w:val="18"/></w:rPr></w:style>'
            '<w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/>'
            '<w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="40"/><w:ind w:left="720"/></w:pPr></w:style>'
            '<w:style w:type="paragraph" w:styleId="FootnoteText"><w:name w:val="footnote text"/>'
            '<w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="0"/></w:pPr><w:rPr><w:sz w:val="18"/></w:rPr></w:style>'
            '<w:style w:type="character" w:styleId="FootnoteReference"><w:name w:val="footnote reference"/>'
            '<w:rPr><w:vertAlign w:val="superscript"/></w:rPr></w:style>'
            '<w:style w:type="character" w:styleId="Hyperlink"><w:name w:val="Hyperlink"/>'
            '<w:rPr><w:color w:val="24508A"/><w:u w:val="single"/></w:rPr></w:style>'
            '<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/>'
            '<w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr>'
            '<w:tblPr><w:tblBorders>'
            + "".join(f'<w:{s} w:val="single" w:sz="4" w:space="0" w:color="808080"/>'
                      for s in ("top", "left", "bottom", "right", "insideH", "insideV")) +
            '</w:tblBorders><w:tblCellMar><w:left w:w="100" w:type="dxa"/><w:right w:w="100" w:type="dxa"/>'
            '</w:tblCellMar></w:tblPr></w:style>'
            "</w:styles>")


def _numbering(nums: list[tuple[int, int]]) -> str:
    bullets = "•◦▪•◦▪•◦▪"
    abs0 = "".join(
        f'<w:lvl w:ilvl="{l}"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="{bullets[l]}"/>'
        f'<w:lvlJc w:val="left"/><w:pPr><w:ind w:left="{720 + 360 * l}" w:hanging="360"/></w:pPr></w:lvl>'
        for l in range(9))
    fmts = ["decimal", "lowerLetter", "lowerRoman"] * 3
    abs1 = "".join(
        f'<w:lvl w:ilvl="{l}"><w:start w:val="1"/><w:numFmt w:val="{fmts[l]}"/><w:lvlText w:val="%{l + 1}."/>'
        f'<w:lvlJc w:val="left"/><w:pPr><w:ind w:left="{720 + 360 * l}" w:hanging="360"/></w:pPr></w:lvl>'
        for l in range(9))
    nums_xml = "".join(
        f'<w:num w:numId="{n}"><w:abstractNumId w:val="{a}"/>'
        + "".join(f'<w:lvlOverride w:ilvl="{l}"><w:startOverride w:val="1"/></w:lvlOverride>' for l in range(9))
        + "</w:num>" for n, a in nums)
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:numbering {_NS_DECL}>'
            f'<w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="hybridMultilevel"/>{abs0}</w:abstractNum>'
            f'<w:abstractNum w:abstractNumId="1"><w:multiLevelType w:val="hybridMultilevel"/>{abs1}</w:abstractNum>'
            f"{nums_xml}</w:numbering>")


def _footnotes(notes: list[str]) -> str:
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:footnotes {_NS_DECL}>'
            '<w:footnote w:type="separator" w:id="-1"><w:p><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr><w:r><w:separator/></w:r></w:p></w:footnote>'
            '<w:footnote w:type="continuationSeparator" w:id="0"><w:p><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr><w:r><w:continuationSeparator/></w:r></w:p></w:footnote>'
            + "".join(notes) + "</w:footnotes>")


def _settings() -> str:
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:settings {_NS_DECL}>'
            '<w:footnotePr><w:footnote w:id="-1"/><w:footnote w:id="0"/></w:footnotePr>'
            '<w:compat><w:compatSetting w:name="compatibilityMode" w:uri="http://schemas.microsoft.com/office/word" w:val="15"/></w:compat>'
            '<m:mathPr><m:mathFont m:val="Cambria Math"/></m:mathPr>'
            "</w:settings>")


def _core(doc: Document) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f"<dc:title>{escape(doc.title)}</dc:title><dc:creator>{escape(doc.author)}</dc:creator>"
            f"<cp:keywords>{escape(doc.keywords)}</cp:keywords><cp:lastModifiedBy>hwp2x</cp:lastModifiedBy>"
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
            f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>'
            "</cp:coreProperties>")


def write_docx(doc: Document, out: Path) -> list[Path]:
    d = _Docx(doc)
    body = d.blocks(doc.blocks)
    if doc.title:
        body = f'<w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr><w:r>{_t(doc.title)}</w:r></w:p>' + body
    margin = int(25 * _TWIPS_PER_MM)
    sect = (f'<w:sectPr><w:footnotePr><w:numFmt w:val="decimal"/></w:footnotePr>'
            f'<w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="{margin}" w:right="{margin}" w:bottom="{margin}" '
            f'w:left="{margin}" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>')
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:document {_NS_DECL}>'
                f"<w:body>{body}{sect}</w:body></w:document>")

    ct_defaults = {"rels": "application/vnd.openxmlformats-package.relationships+xml", "xml": "application/xml"}
    for name, _data, mtype in d.media.values():
        ct_defaults[name.rsplit(".", 1)[-1].lower()] = mtype
    content_types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     + "".join(f'<Default Extension="{e}" ContentType="{t}"/>' for e, t in ct_defaults.items())
                     + '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                     '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
                     '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>'
                     '<Override PartName="/word/footnotes.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"/>'
                     '<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>'
                     '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
                     "</Types>")
    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                 '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
                 "</Relationships>")
    fixed = [("rId1", f"{_R}/styles", "styles.xml", False), ("rId2", f"{_R}/numbering", "numbering.xml", False),
             ("rId3", f"{_R}/footnotes", "footnotes.xml", False), ("rId4", f"{_R}/settings", "settings.xml", False)]
    doc_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                + "".join(f'<Relationship Id="{i}" Type="{t}" Target={quoteattr(tg)}'
                          + (' TargetMode="External"' if ext else "") + "/>"
                          for i, t, tg, ext in fixed + d.rels)
                + "</Relationships>")

    tmp = out.with_name(out.name + ".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("docProps/core.xml", _core(doc))
        z.writestr("word/document.xml", document)
        z.writestr("word/_rels/document.xml.rels", doc_rels)
        z.writestr("word/styles.xml", _styles())
        z.writestr("word/numbering.xml", _numbering(d.numbering))
        z.writestr("word/footnotes.xml", _footnotes(d.footnotes))
        z.writestr("word/settings.xml", _settings())
        for name, data, _m in d.media.values():
            z.writestr(f"word/media/{name}", data)
    tmp.replace(out)
    return [out]
