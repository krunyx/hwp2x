"""Output writers. Each takes a Document and an output path and returns the
list of files written (the main file first, then any images)."""
from __future__ import annotations

from pathlib import Path

from ..model import Document

FORMATS = {
    # key: (extension, label)
    "hwpx": (".hwpx", "HWPX (한글 문서)"),
    "docx": (".docx", "Word 문서 (DOCX)"),
    "md": (".md", "Markdown"),
    "html": (".html", "웹 페이지 (HTML)"),
    "tex": (".tex", "LaTeX (TEX)"),
    "htex": (".htex", "HyperTeX (HTEX)"),
}


def write(doc: Document, fmt: str, out: Path) -> list[Path]:
    if fmt == "md":
        from .markdown import write_markdown
        return write_markdown(doc, out)
    if fmt == "html":
        from .html import write_html
        return write_html(doc, out)
    if fmt in ("tex", "htex"):
        from .latex import write_latex
        return write_latex(doc, out, profile=fmt)
    if fmt == "docx":
        from .docx import write_docx
        return write_docx(doc, out)
    raise ValueError(f"unknown format: {fmt}")
