"""End-to-end tests against the upstream sample documents.

The samples come from neolord0/hwplib and neolord0/hwp2hwpx (Apache-2.0),
which scripts/build_engine.py checks out under build/engine/upstream.
"""
from __future__ import annotations

import os
import shutil
import zipfile
from pathlib import Path

import pytest

from hwp2x import check_hwpx, convert, convert_all, plan
from hwp2x.verify import section_text

ROOT = Path(__file__).resolve().parent.parent
UP = ROOT / "build" / "engine" / "upstream"
HWPLIB = UP / "hwplib" / "sample_hwp"
H2X = UP / "hwp2hwpx" / "test"

pytestmark = pytest.mark.skipif(not HWPLIB.exists(), reason="run scripts/build_engine.py first")

ALL_SAMPLES = sorted(UP.rglob("*.hwp")) if UP.exists() else []
DISTRIBUTION = HWPLIB / "distribution.hwp"
CONTROL_CHARS = next(iter(sorted((H2X / "오류" / "20250418").glob("*.hwp"))), None) if H2X.exists() else None


def test_every_sample_converts_to_a_valid_package(tmp_path):
    jobs = plan([UP], tmp_path, recursive=True)
    assert len(jobs) == len(ALL_SAMPLES) >= 90
    results = convert_all(jobs, workers=2)
    failed = [(r.src.name, r.code) for r in results if not r.succeeded]
    # Only the copy/print-restricted distribution document is refused.
    assert failed == [("distribution.hwp", "DISTRIBUTION")]
    for r in results:
        if r.succeeded:
            assert check_hwpx(r.dst) == [], r.src


def test_mimetype_is_first_and_stored(tmp_path):
    r = convert(HWPLIB / "basic" / "표.hwp", tmp_path / "t.hwpx")
    assert r.status == "ok"
    with zipfile.ZipFile(r.dst) as z:
        first = z.infolist()[0]
        assert first.filename == "mimetype"
        assert first.compress_type == zipfile.ZIP_STORED
        assert z.read("mimetype") == b"application/hwp+zip"


def test_table_text_survives(tmp_path):
    r = convert(HWPLIB / "basic" / "표.hwp", tmp_path / "t.hwpx")
    text = section_text(r.dst)
    assert len(text.strip()) > 0


def test_control_characters_are_removed_and_reported(tmp_path):
    assert CONTROL_CHARS is not None
    r = convert(CONTROL_CHARS, tmp_path / "x.hwpx")
    assert r.status == "warn" and r.code == "SANITIZED"
    assert check_hwpx(r.dst) == []
    assert len(section_text(r.dst)) > 10000  # the long procurement document is intact


def test_distribution_document_is_refused_and_leaves_nothing(tmp_path):
    r = convert(DISTRIBUTION, tmp_path / "d.hwpx")
    assert r.status == "error" and r.code == "DISTRIBUTION"
    assert list(tmp_path.iterdir()) == []


def test_non_hwp_input_is_rejected(tmp_path):
    fake = tmp_path / "fake.hwp"
    fake.write_text("hello")
    r = convert(fake, tmp_path / "fake.hwpx")
    assert r.code == "NOT_HWP5"
    assert not (tmp_path / "fake.hwpx").exists()


def test_already_hwpx_is_rejected(tmp_path):
    good = convert(HWPLIB / "blank.hwp", tmp_path / "b.hwpx").dst
    renamed = tmp_path / "renamed.hwp"
    shutil.copy(good, renamed)
    assert convert(renamed, tmp_path / "r.hwpx").code == "ALREADY_HWPX"


def test_korean_and_space_paths(tmp_path):
    d = tmp_path / "한글 폴더" / "하위 폴더"
    d.mkdir(parents=True)
    src = d / "보고서 초안 (최종).hwp"
    shutil.copy(HWPLIB / "basic" / "글상자.hwp", src)
    r = convert(src)
    assert r.status == "ok"
    assert (d / "보고서 초안 (최종).hwpx").exists()


def test_existing_output_is_skipped_without_overwrite(tmp_path):
    src = tmp_path / "a.hwp"
    shutil.copy(HWPLIB / "blank.hwp", src)
    (tmp_path / "a.hwpx").write_bytes(b"keep me")
    [r] = convert_all(plan([src]))
    assert r.status == "skipped"
    assert (tmp_path / "a.hwpx").read_bytes() == b"keep me"
    [r] = convert_all(plan([src]), overwrite=True)
    assert r.status == "ok"


def test_plan_mirrors_folders_and_avoids_collisions(tmp_path):
    for sub in ("x", "y"):
        (tmp_path / "in" / sub).mkdir(parents=True)
        shutil.copy(HWPLIB / "blank.hwp", tmp_path / "in" / sub / "same.hwp")
    out = tmp_path / "out"
    jobs = plan([tmp_path / "in"], out, recursive=True)
    assert sorted(j.dst.relative_to(out).as_posix() for j in jobs) == ["in/x/same.hwpx", "in/y/same.hwpx"]
    # Two loose files with the same name into one folder: the second gets a suffix.
    flat = plan([tmp_path / "in" / "x" / "same.hwp", tmp_path / "in" / "y" / "same.hwp"], out)
    assert [j.dst.name for j in flat] == ["same.hwpx", "same (2).hwpx"]


def test_plan_non_recursive_and_filters(tmp_path):
    shutil.copy(HWPLIB / "blank.hwp", tmp_path / "top.HWP")
    shutil.copy(HWPLIB / "blank.hwp", tmp_path / "~$lock.hwp")
    (tmp_path / "sub").mkdir()
    shutil.copy(HWPLIB / "blank.hwp", tmp_path / "sub" / "deep.hwp")
    assert [j.src.name for j in plan([tmp_path])] == ["top.HWP"]
    assert sorted(j.src.name for j in plan([tmp_path], recursive=True)) == ["deep.hwp", "top.HWP"]


def test_cli_exit_codes(tmp_path, capsys):
    from hwp2x.cli import main
    src = tmp_path / "ok.hwp"
    shutil.copy(HWPLIB / "blank.hwp", src)
    assert main([str(src)]) == 0
    shutil.copy(DISTRIBUTION, tmp_path / "dist.hwp")
    assert main([str(tmp_path), "-f"]) == 1
    assert main([str(tmp_path / "nothing-here")]) in (1, 2)
    assert "완료" in capsys.readouterr().out


@pytest.mark.skipif(os.name == "nt", reason="locale handling only matters on POSIX")
def test_engine_under_c_locale(tmp_path, monkeypatch):
    monkeypatch.setenv("LANG", "C")
    monkeypatch.setenv("LC_ALL", "C")
    src = tmp_path / "한글.hwp"
    shutil.copy(HWPLIB / "blank.hwp", src)
    assert convert(src).status == "ok"
