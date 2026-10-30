"""Helpers shared by the output writers."""
from __future__ import annotations

import io
from pathlib import Path

from ..model import Block, Document, Image, Paragraph, Resource

# What each target can display, and what we convert to when it cannot.
_WEB = {"image/png", "image/jpeg", "image/gif", "image/svg+xml", "image/bmp", "image/webp"}
ACCEPT = {
    "md": _WEB,
    "html": _WEB,
    "tex": {"image/png", "image/jpeg"},
    "htex": {"image/png", "image/jpeg", "image/svg+xml"},
    "docx": {"image/png", "image/jpeg", "image/gif", "image/bmp"},
}
_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/svg+xml": "svg",
        "image/bmp": "bmp", "image/webp": "webp"}


def convert_image(res: Resource, accept: set[str]) -> Resource | None:
    """Return ``res`` in a format the target accepts, or None if that is impossible.

    Raster formats (BMP, GIF, TIFF...) are converted to PNG with Pillow.
    Vector metafiles (WMF/EMF) cannot be converted without an office suite."""
    if res.media_type in accept:
        return res
    try:
        from PIL import Image as PILImage
    except ImportError:
        return None
    try:
        im = PILImage.open(io.BytesIO(res.data))
        im.load()
    except Exception:
        return None
    if im.mode not in ("RGB", "RGBA", "L", "LA"):
        im = im.convert("RGBA" if "A" in im.getbands() or im.mode == "P" else "RGB")
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    stem = res.name.rsplit(".", 1)[0]
    return Resource(stem + ".png", "image/png", buf.getvalue())


def image_size_px(data: bytes) -> tuple[int, int]:
    try:
        from PIL import Image as PILImage
        with PILImage.open(io.BytesIO(data)) as im:
            return im.size
    except Exception:
        return (0, 0)


class Assets:
    """Writes images next to the output file (``<stem>_files/``) on demand."""

    def __init__(self, doc: Document, out_path: Path, target: str):
        self.doc = doc
        self.target = target
        self.dir = out_path.with_name(out_path.stem + "_files")
        self.written: dict[str, str] = {}
        self.files: list[Path] = []

    def path_for(self, img: Image) -> str | None:
        """Relative path (posix) to the image file, writing it if needed."""
        if img.ref in self.written:
            return self.written[img.ref]
        res = self.doc.resources.get(img.ref)
        if res is None:
            return None
        conv = convert_image(res, ACCEPT[self.target])
        if conv is None:
            self.doc.warn(f"그림 형식({res.name.rsplit('.', 1)[-1].upper()})을 변환할 수 없어 일부 그림을 넣지 못했습니다")
            self.written[img.ref] = ""
            return None
        self.dir.mkdir(parents=True, exist_ok=True)
        target = self.dir / conv.name
        n = 2
        while target.exists() and target.read_bytes() != conv.data:
            target = self.dir / f"{conv.name.rsplit('.', 1)[0]}_{n}.{conv.name.rsplit('.', 1)[-1]}"
            n += 1
        target.write_bytes(conv.data)
        self.files.append(target)
        rel = f"{self.dir.name}/{target.name}"
        self.written[img.ref] = rel
        return rel


def group_lists(blocks: list[Block]):
    """Yield ("block", b) or ("list", [paragraphs]) - consecutive list items together."""
    run: list[Paragraph] = []
    for b in blocks:
        if isinstance(b, Paragraph) and b.list_kind:
            run.append(b)
            continue
        if run:
            yield "list", run
            run = []
        yield "block", b
    if run:
        yield "list", run


def nest_list(items: list[Paragraph]):
    """Turn flat list paragraphs with levels into a tree:
    [(paragraph, [children...]), ...] where children have the same shape."""
    root: list = []
    stack: list[tuple[int, list]] = [(-1, root)]
    for p in items:
        while len(stack) > 1 and stack[-1][0] >= p.list_level:
            stack.pop()
        node = (p, [])
        stack[-1][1].append(node)
        stack.append((p.list_level, node[1]))
    return root


def table_grid(table):
    """Map every grid position to (cell, is_origin). Positions not covered by
    any cell map to None. Uses the cells' own addresses."""
    n_rows = len(table.rows)
    n_cols = table.n_cols
    grid: list[list] = [[None] * n_cols for _ in range(n_rows)]
    for r_i, row in enumerate(table.rows):
        for c in row:
            r0 = c.row if c.row < n_rows else r_i
            for dr in range(c.rowspan):
                for dc in range(c.colspan):
                    rr, cc = r0 + dr, c.col + dc
                    if rr < n_rows and cc < n_cols and grid[rr][cc] is None:
                        grid[rr][cc] = (c, dr == 0 and dc == 0)
    return grid
