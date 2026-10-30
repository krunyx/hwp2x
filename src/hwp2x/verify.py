"""Structural checks for a produced .hwpx file.

These catch the failures that make Hangul refuse to open a file: a broken
zip, a missing or compressed ``mimetype`` entry, malformed XML, or a
package manifest that points at parts that are not in the archive.
"""
from __future__ import annotations

import posixpath
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

MIMETYPE = b"application/hwp+zip"
REQUIRED = ("version.xml", "META-INF/container.xml", "Contents/content.hpf", "Contents/header.xml")
_SECTION = re.compile(r"^Contents/section\d+\.xml$")
_OPF_NS = "{http://www.idpf.org/2007/opf/}"


def check_hwpx(path: str | Path) -> list[str]:
    """Return a list of problems; an empty list means the package looks sound."""
    problems: list[str] = []
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        return [f"not a readable zip: {e}"]

    with zf:
        infos = zf.infolist()
        names = {i.filename for i in infos}

        if not infos or infos[0].filename != "mimetype":
            problems.append("first entry is not 'mimetype'")
        elif infos[0].compress_type != zipfile.ZIP_STORED:
            problems.append("'mimetype' entry is compressed")
        if "mimetype" in names and zf.read("mimetype").strip() != MIMETYPE:
            problems.append("unexpected mimetype content")

        for req in REQUIRED:
            if req not in names:
                problems.append(f"missing {req}")
        if not any(_SECTION.match(n) for n in names):
            problems.append("no section XML")

        bad = zf.testzip()
        if bad:
            problems.append(f"CRC error in {bad}")

        for n in sorted(names):
            if n.endswith((".xml", ".hpf")):
                try:
                    ET.fromstring(zf.read(n))
                except ET.ParseError as e:
                    problems.append(f"malformed XML in {n}: {e}")

        if "Contents/content.hpf" in names:
            try:
                root = ET.fromstring(zf.read("Contents/content.hpf"))
                for item in root.iter(f"{_OPF_NS}item"):
                    href = item.get("href")
                    if item.get("isEmbeded") == "0":
                        continue  # linked (not embedded) picture: lives outside the package
                    if href and posixpath.normpath(href) not in names:
                        problems.append(f"manifest item missing from archive: {href}")
            except ET.ParseError:
                pass  # already reported above
    return problems


def section_text(path: str | Path) -> str:
    """All text from every section in document order: runs (``hp:t``),
    dutmal main/sub text and equation scripts."""
    out: list[str] = []
    with zipfile.ZipFile(path) as zf:
        secs = sorted((n for n in zf.namelist() if _SECTION.match(n)),
                      key=lambda n: int(re.findall(r"\d+", n)[0]))
        for n in secs:
            for el in ET.fromstring(zf.read(n)).iter():
                if el.tag.endswith(("}t", "}mainText", "}subText", "}script")):
                    out.append("".join(el.itertext()))
    return "".join(out)


_DOCX_REQUIRED = ("[Content_Types].xml", "_rels/.rels", "word/document.xml")


def check_docx(path: str | Path) -> list[str]:
    """Structural checks for a produced .docx: readable zip, required parts,
    well-formed XML, and every internal relationship pointing at a real part."""
    problems: list[str] = []
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        return [f"not a readable zip: {e}"]
    with zf:
        names = set(zf.namelist())
        for req in _DOCX_REQUIRED:
            if req not in names:
                problems.append(f"missing {req}")
        for n in sorted(names):
            if n.endswith((".xml", ".rels")):
                try:
                    ET.fromstring(zf.read(n))
                except ET.ParseError as e:
                    problems.append(f"malformed XML in {n}: {e}")
        rels = "word/_rels/document.xml.rels"
        if rels in names:
            try:
                for r in ET.fromstring(zf.read(rels)):
                    if r.get("TargetMode") == "External":
                        continue
                    target = posixpath.normpath(posixpath.join("word", r.get("Target", "")))
                    if target not in names:
                        problems.append(f"relationship target missing: {target}")
            except ET.ParseError:
                pass
    return problems
