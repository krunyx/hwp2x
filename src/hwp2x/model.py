"""Format-neutral document model.

Every output format is written from this model, and every input format
(today HWPX, and HWP through the HWPX engine) is read into it. It keeps the
*meaning* of a document - headings, paragraphs, lists, tables, equations,
footnotes, images, links - and deliberately drops page layout.

Blocks
    Paragraph   inline content, optionally a heading or a list item
    Table       rows of cells; each cell holds blocks (tables can nest)
    Figure      an image with an optional caption
    MathBlock   an equation on its own line

Inlines
    Text        a run of characters with simple character formatting
    Math        an equation inside running text
    Note        footnote or endnote; holds blocks
    Link        hyperlink around inlines
    Image       picture inside running text
    Break       forced line break
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Union


# --------------------------------------------------------------------------- inlines
@dataclass
class Text:
    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    sup: bool = False
    sub: bool = False

    def same_style(self, other: "Text") -> bool:
        return (self.bold, self.italic, self.underline, self.strike, self.sup, self.sub) == \
            (other.bold, other.italic, other.underline, other.strike, other.sup, other.sub)


@dataclass
class Math:
    """An equation. ``source`` is the original Hangul-equation script;
    ``ast`` is the parsed tree (see :mod:`hwp2x.eqn`)."""
    source: str
    ast: object = None


@dataclass
class Note:
    kind: str                      # "footnote" | "endnote"
    blocks: list["Block"] = field(default_factory=list)


@dataclass
class Link:
    href: str
    children: list["Inline"] = field(default_factory=list)


@dataclass
class Image:
    ref: str                       # key into Document.resources
    width_mm: float = 0.0
    height_mm: float = 0.0
    alt: str = ""


@dataclass
class Break:
    pass


Inline = Union[Text, Math, Note, Link, Image, Break]


# --------------------------------------------------------------------------- blocks
@dataclass
class Paragraph:
    inlines: list[Inline] = field(default_factory=list)
    heading: int = 0               # 0 = body text, 1..6 = heading level
    list_kind: str = ""            # "" | "bullet" | "number"
    list_level: int = 0            # 0-based nesting depth
    align: str = ""                # "" | "center" | "right"

    def plain_text(self) -> str:
        return inline_text(self.inlines)


@dataclass
class Cell:
    blocks: list["Block"] = field(default_factory=list)
    row: int = 0
    col: int = 0
    rowspan: int = 1
    colspan: int = 1
    header: bool = False


@dataclass
class Table:
    rows: list[list[Cell]] = field(default_factory=list)
    n_cols: int = 0
    caption: list[Inline] = field(default_factory=list)
    col_widths: list[float] = field(default_factory=list)   # relative, sums to 1 (empty = equal)

    def widths(self) -> list[float]:
        n = max(self.n_cols, 1)
        if len(self.col_widths) == n and all(w > 0 for w in self.col_widths):
            return self.col_widths
        return [1 / n] * n

    @property
    def has_spans(self) -> bool:
        return any(c.rowspan > 1 or c.colspan > 1 for r in self.rows for c in r)

    @property
    def is_simple(self) -> bool:
        """One plain paragraph (or nothing) per cell and no merged cells:
        representable as a Markdown pipe table."""
        if self.has_spans:
            return False
        for r in self.rows:
            for c in r:
                if len(c.blocks) > 1:
                    return False
                if c.blocks and not (isinstance(c.blocks[0], Paragraph) and not c.blocks[0].heading
                                     and not c.blocks[0].list_kind
                                     and not any(isinstance(i, (Break, Note, Image)) for i in c.blocks[0].inlines)):
                    return False
        return True


@dataclass
class Figure:
    image: Image
    caption: list[Inline] = field(default_factory=list)


@dataclass
class MathBlock:
    math: Math


Block = Union[Paragraph, Table, Figure, MathBlock]


# --------------------------------------------------------------------------- document
@dataclass
class Resource:
    name: str                      # file name to use when written out, e.g. "image1.png"
    media_type: str
    data: bytes


@dataclass
class Document:
    blocks: list[Block] = field(default_factory=list)
    title: str = ""
    author: str = ""
    date: str = ""
    keywords: str = ""
    resources: dict[str, Resource] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)


# --------------------------------------------------------------------------- helpers
def inline_text(inlines: list[Inline]) -> str:
    out: list[str] = []
    for i in inlines:
        if isinstance(i, Text):
            out.append(i.text)
        elif isinstance(i, Link):
            out.append(inline_text(i.children))
        elif isinstance(i, Math):
            out.append(i.source)
        elif isinstance(i, Break):
            out.append("\n")
    return "".join(out)


def block_text(blocks: list[Block]) -> str:
    """All text in reading order, for tests and search indexing."""
    out: list[str] = []

    def inl(items: list[Inline]) -> None:
        for i in items:
            if isinstance(i, Text):
                out.append(i.text)
            elif isinstance(i, Link):
                inl(i.children)
            elif isinstance(i, Note):
                walk(i.blocks)

    def walk(bs: list[Block]) -> None:
        for b in bs:
            if isinstance(b, Paragraph):
                inl(b.inlines)
            elif isinstance(b, Table):
                inl(b.caption)
                for r in b.rows:
                    for c in r:
                        walk(c.blocks)
            elif isinstance(b, Figure):
                inl(b.caption)

    walk(blocks)
    return "".join(out)


def iter_inlines(blocks: list[Block]):
    """Yield every inline in the document, including inside tables and notes."""
    def inl(items):
        for i in items:
            yield i
            if isinstance(i, Link):
                yield from inl(i.children)
            elif isinstance(i, Note):
                yield from walk(i.blocks)

    def walk(bs):
        for b in bs:
            if isinstance(b, Paragraph):
                yield from inl(b.inlines)
            elif isinstance(b, Table):
                yield from inl(b.caption)
                for r in b.rows:
                    for c in r:
                        yield from walk(c.blocks)
            elif isinstance(b, Figure):
                yield b.image
                yield from inl(b.caption)
            elif isinstance(b, MathBlock):
                yield b.math

    yield from walk(blocks)


def optional_str(s: Optional[str]) -> str:
    return s or ""
