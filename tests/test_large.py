"""Long documents must convert within a modest memory budget.

A ~800-page document is built from a real sample (tests/tools/Grow.java
repeats its body 20 times). Before the streaming fixes the engine failed on
it with 400 MB of Java heap (it needed 512-600 MB); now it needs under 300 MB."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

import hwp2x.engine as engine_mod
from hwp2x import convert_all
from hwp2x.converter import Job
from hwp2x.engine import JAR
from hwp2x.verify import check_hwpx

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = next((ROOT / "build" / "engine" / "upstream" / "hwp2hwpx" / "test").rglob("R25BD*.hwp"), None) \
    if (ROOT / "build" / "engine" / "upstream").exists() else None
pytestmark = pytest.mark.skipif(SAMPLE is None or not shutil.which("javac"),
                                reason="needs the upstream samples and a JDK")


@pytest.fixture(scope="module")
def long_doc(tmp_path_factory):
    d = tmp_path_factory.mktemp("large")
    subprocess.run(["javac", "-nowarn", "-cp", str(JAR), "-d", str(d), str(ROOT / "tests" / "tools" / "Grow.java")],
                   check=True, capture_output=True)
    out = d / "long.hwp"
    # Windows passes command-line arguments to Java in the ANSI code page, so the
    # Korean sample name would not survive: hand the helper an ASCII copy.
    src = d / "sample.hwp"
    shutil.copy(SAMPLE, src)
    env = dict(os.environ, LC_ALL="C.UTF-8")
    env.pop("JAVA_TOOL_OPTIONS", None)
    subprocess.run(["java", "-Xmx2g", "-cp", f"{JAR}{os.pathsep}{d}", "Grow", str(src), str(out), "20"],
                   check=True, capture_output=True, env=env, timeout=600)
    return out


def test_long_document_fits_a_small_heap(long_doc, monkeypatch):
    # 400 MB for every engine, including the "big retry": the old engine ran out here.
    monkeypatch.setattr(engine_mod, "heap_mb", lambda share: 400)
    for fmt in ("hwpx", "md"):
        dst = long_doc.with_suffix("." + fmt)
        [r] = convert_all([Job(long_doc, dst, fmt)], overwrite=True, workers=1)
        assert r.succeeded, (fmt, r.code, r.message)
    assert check_hwpx(long_doc.with_suffix(".hwpx")) == []
    assert long_doc.with_suffix(".md").stat().st_size > 3_000_000


def test_out_of_memory_is_reported_clearly(long_doc, monkeypatch):
    monkeypatch.setattr(engine_mod, "heap_mb", lambda share: 64)
    [r] = convert_all([Job(long_doc, long_doc.with_suffix(".oom.hwpx"), "hwpx")], overwrite=True, workers=1)
    assert r.code == "MEMORY" and "메모리" in r.message
    assert not long_doc.with_suffix(".oom.hwpx").exists()
    assert not list(long_doc.parent.glob(".hwp2x-*"))              # no temp files left behind
