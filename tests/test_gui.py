"""Drive the GUI headlessly through a full conversion."""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from hwp2x import gui  # noqa: E402

SAMPLES = Path(__file__).resolve().parent.parent / "build" / "engine" / "upstream" / "hwplib" / "sample_hwp"
pytestmark = pytest.mark.skipif(not SAMPLES.exists(), reason="run scripts/build_engine.py first")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _wait(app, w, seconds=120):
    end = time.monotonic() + seconds
    while w.busy and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.02)
    app.processEvents()
    assert not w.busy


def test_gui_converts_folder_and_lists_failures_first(app, tmp_path):
    for name in ("blank.hwp", "distribution.hwp"):
        shutil.copy(SAMPLES / name, tmp_path / name)
    shutil.copy(SAMPLES / "basic" / "표.hwp", tmp_path / "표.hwp")

    w = gui.MainWindow()
    w.add_paths([str(tmp_path)])
    assert w.table.rowCount() == 3 and w.btn_go.isEnabled()

    w.start_or_stop()
    assert w.btn_go.text() == "멈추기"
    _wait(app, w)

    assert w.table.item(0, 0).text() == "distribution.hwp"        # failure on top
    assert "실패" in w.table.item(0, 1).text()
    assert (tmp_path / "blank.hwpx").exists() and (tmp_path / "표.hwpx").exists()
    assert not (tmp_path / "distribution.hwpx").exists()
    assert "성공 2" in w.summary.text() and "실패 1" in w.summary.text()
    assert w.btn_go.text() == "변환" and w.btn_open.isVisibleTo(w)


def test_gui_other_folder_requires_a_path(app, tmp_path, monkeypatch):
    shutil.copy(SAMPLES / "blank.hwp", tmp_path / "a.hwp")
    w = gui.MainWindow()
    w.add_paths([str(tmp_path / "a.hwp")])
    w.rb_other.setChecked(True)
    shown = []
    monkeypatch.setattr(gui.QMessageBox, "information", lambda *a: shown.append(a[-1]))
    w.start_or_stop()
    assert shown and not w.busy

    out = tmp_path / "out"
    w.out_edit.setText(str(out))
    w.start_or_stop()
    _wait(app, w)
    assert (out / "a.hwpx").exists()


def test_gui_ignores_non_hwp_drops(app, tmp_path):
    (tmp_path / "note.txt").write_text("x")
    w = gui.MainWindow()
    w.add_paths([str(tmp_path / "note.txt")])
    assert w.table.rowCount() == 0 and not w.btn_go.isEnabled()
