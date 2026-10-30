"""Every output format on every upstream sample document.

Each format gets the check that matters for it:
  docx   package structure (and python-docx can open it, when installed)
  html   parses, equations are MathML
  md     all body text survives
  tex    \\begin/\\end balance (XeLaTeX itself is run when HWP2X_XELATEX=1)
  htex   the HyperTeX reference parser reports no diagnostics (when installed)
"""
from __future__ import annotations

import collections
import os
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

from hwp2x import convert_all, plan
from hwp2x.converter import Job
from hwp2x.hwpx_reader import read_hwpx
from hwp2x.model import block_text
from hwp2x.verify import check_docx

ROOT = Path(__file__).resolve().parent.parent
UP = ROOT / "build" / "engine" / "upstream"
HWPLIB = UP / "hwplib" / "sample_hwp"
pytestmark = pytest.mark.skipif(not HWPLIB.exists(), reason="run scripts/build_engine.py first")


@pytest.fixture(scope="module")
def hwpx_samples(tmp_path_factory):
    """All samples converted to HWPX once (the input for the other formats)."""
    out = tmp_path_factory.mktemp("hwpx")
    jobs = [j for j in plan([UP], out, recursive=True) if "big_file" not in j.src.name]
    results = convert_all(jobs, workers=2)
    return [r.dst for r in results if r.succeeded]


def _convert(srcs, fmt, out):
    # many samples share a file name (".../from.hwpx"): number the outputs
    jobs = [Job(s, out / f"{k:03d}_{s.stem}.{fmt}", fmt) for k, s in enumerate(srcs)]
    results = convert_all(jobs, workers=2)
    failed = [(r.src.name, r.code, r.message) for r in results if not r.succeeded]
    assert not failed
    return results


def _chars(s: str) -> collections.Counter:
    return collections.Counter(c for c in s if not c.isspace() and c not in "*_\\#|`~$[]()<>-:!")


def test_docx_packages_are_valid(hwpx_samples, tmp_path):
    for r in _convert(hwpx_samples, "docx", tmp_path):
        assert check_docx(r.dst) == [], r.src
    docx = pytest.importorskip("docx")
    for r in _convert(hwpx_samples[:20], "docx", tmp_path / "again"):
        docx.Document(str(r.dst))


def test_html_parses_and_uses_mathml(hwpx_samples, tmp_path):
    results = _convert(hwpx_samples, "html", tmp_path)
    for r in results:
        HTMLParser().feed(r.dst.read_text(encoding="utf-8"))
    eq = next(r for r in results if r.src.stem.endswith("equation_from") or "수식" in r.src.stem)
    assert "<math" in eq.dst.read_text(encoding="utf-8")


def test_markdown_keeps_all_text(hwpx_samples, tmp_path):
    for r in _convert(hwpx_samples, "md", tmp_path):
        want = _chars(block_text(read_hwpx(r.src).blocks))
        got = _chars(r.dst.read_text(encoding="utf-8"))
        assert not (want - got), (r.src.name, "".join((want - got).elements())[:40])


def _balanced(tex: str) -> bool:
    stack = []
    for m in re.finditer(r"\\(begin|end)\{([^}]*)\}", tex):
        if m.group(1) == "begin":
            stack.append(m.group(2))
        elif not stack or stack.pop() != m.group(2):
            return False
    return not stack


@pytest.mark.parametrize("fmt", ["tex", "htex"])
def test_latex_environments_balance(hwpx_samples, tmp_path, fmt):
    for r in _convert(hwpx_samples, fmt, tmp_path):
        text = r.dst.read_text(encoding="utf-8")
        assert _balanced(text), r.src.name
        want = _chars(block_text(read_hwpx(r.src).blocks))
        assert not (want - _chars(text)), r.src.name


def test_htex_passes_the_hypertex_parser(hwpx_samples, tmp_path):
    htex = pytest.importorskip("htex")
    for r in _convert(hwpx_samples, "htex", tmp_path):
        tree = htex.parse_text(r.dst.read_text(encoding="utf-8"), base_dir=r.dst.parent)
        assert tree["diagnostics"] == [], (r.src.name, tree["diagnostics"][:2])


@pytest.mark.skipif(os.environ.get("HWP2X_XELATEX") != "1" or not shutil.which("xelatex"),
                    reason="set HWP2X_XELATEX=1 with a TeX installation that has kotex")
def test_tex_compiles_with_xelatex(hwpx_samples, tmp_path):
    for r in _convert(hwpx_samples, "tex", tmp_path):
        p = subprocess.run(["xelatex", "-interaction=nonstopmode", "-halt-on-error", r.dst.name],
                           cwd=r.dst.parent, capture_output=True, timeout=300)
        assert p.returncode == 0, r.src.name


def test_images_are_written_beside_the_output(tmp_path):
    src = tmp_path / "그림.hwp"
    shutil.copy(HWPLIB / "basic" / "그림.hwp", src)
    for fmt in ("md", "tex", "htex"):
        [r] = convert_all(plan([src], fmt=fmt), overwrite=True)
        assert r.succeeded
        files = list((tmp_path / "그림_files").glob("*"))
        assert files and all(f.suffix in (".png", ".jpg", ".svg") for f in files)
        assert "그림_files/" in r.dst.read_text(encoding="utf-8")


def test_hwpx_input_needs_no_java(hwpx_samples, tmp_path, monkeypatch):
    import hwp2x.converter as conv

    def no_engine(*a, **k):
        raise AssertionError("the Java engine must not start for .hwpx input")
    monkeypatch.setattr(conv, "Engine", no_engine)
    _convert(hwpx_samples[:5], "md", tmp_path)


def test_plan_prefers_hwp_over_its_converted_copy(tmp_path):
    shutil.copy(HWPLIB / "blank.hwp", tmp_path / "a.hwp")
    (tmp_path / "a.hwpx").write_bytes(b"x")
    shutil.copy(HWPLIB / "blank.hwp", tmp_path / "b.hwp")
    (tmp_path / "c.hwpx").write_bytes(b"x")
    assert sorted(j.src.name for j in plan([tmp_path], fmt="md")) == ["a.hwp", "b.hwp", "c.hwpx"]
    assert sorted(j.src.name for j in plan([tmp_path], fmt="hwpx")) == ["a.hwp", "b.hwp"]
    assert {j.dst.suffix for j in plan([tmp_path], fmt="docx")} == {".docx"}


def test_distribution_document_refused_for_every_format(tmp_path):
    src = tmp_path / "d.hwp"
    shutil.copy(HWPLIB / "distribution.hwp", src)
    for fmt in ("docx", "md", "html", "tex", "htex"):
        [r] = convert_all(plan([src], fmt=fmt))
        assert r.code == "DISTRIBUTION"
        assert not r.dst.exists()


def test_cli_format_option(tmp_path, capsys):
    from hwp2x.cli import main
    src = tmp_path / "표.hwp"
    shutil.copy(HWPLIB / "basic" / "표.hwp", src)
    assert main([str(src), "-t", "docx"]) == 0
    assert (tmp_path / "표.docx").exists()
    assert main([str(tmp_path / "표.hwpx"), "-t", "md"]) == 1      # not there yet: reported as a failure
    assert main([str(src)]) == 0
    assert main([str(tmp_path / "표.hwpx"), "-t", "md"]) == 0
    assert (tmp_path / "표.md").read_text(encoding="utf-8").strip()
