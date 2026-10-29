"""hwp2x desktop app (PySide6)."""
from __future__ import annotations

import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QFileDialog, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton,
    QRadioButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import __version__
from .converter import Result, convert_all, plan
from .engine import EngineError

PAPER, INK, MUTED, LINE = "#F4F6F8", "#1B2633", "#5B6878", "#D5DCE3"
ACCENT, ACCENT_DARK = "#24508A", "#1A3C69"
STATUS = {  # symbol, label, colour
    "pending": ("", "대기", MUTED),
    "running": ("…", "변환 중", ACCENT),
    "ok": ("✔", "완료", "#2F7A4F"),
    "warn": ("△", "완료 (확인)", "#A86A12"),
    "skipped": ("–", "건너뜀", MUTED),
    "error": ("✘", "실패", "#B42318"),
}

QSS = f"""
QWidget {{ background: {PAPER}; color: {INK}; font-size: 13px; }}
QLabel#muted {{ color: {MUTED}; }}
QFrame#drop {{ background: #FFFFFF; border: 2px dashed {LINE}; border-radius: 10px; }}
QFrame#drop[hover="true"] {{ border-color: {ACCENT}; background: #EEF3FA; }}
QLabel#arrow {{ color: {ACCENT}; background: transparent; font-size: 40px; font-weight: 600; letter-spacing: 1px; }}
QLabel#hint {{ color: {MUTED}; background: transparent; font-size: 14px; }}
QTableWidget::item:focus {{ border: none; }}
QTableWidget:focus {{ border: 1px solid {ACCENT}; }}
QTableWidget {{ background: #FFFFFF; border: 1px solid {LINE}; border-radius: 6px;
               gridline-color: transparent; selection-background-color: #E3EBF5;
               selection-color: {INK}; }}
QHeaderView::section {{ background: #FFFFFF; color: {MUTED}; border: none;
                        border-bottom: 1px solid {LINE}; padding: 6px 8px; }}
QPushButton {{ background: #FFFFFF; border: 1px solid {LINE}; border-radius: 6px; padding: 7px 14px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:focus {{ border: 2px solid {ACCENT}; }}
QPushButton:disabled {{ color: #A6B0BB; }}
QPushButton#primary {{ background: {ACCENT}; color: #FFFFFF; border: none; padding: 8px 22px; font-weight: 600; }}
QPushButton#primary:hover {{ background: {ACCENT_DARK}; }}
QPushButton#primary:focus {{ border: 2px solid #9DB8DC; }}
QPushButton#primary:disabled {{ background: #9DB0C8; }}
QLineEdit {{ background: #FFFFFF; border: 1px solid {LINE}; border-radius: 6px; padding: 6px 8px; }}
QLineEdit:disabled {{ color: #A6B0BB; }}
QProgressBar {{ background: #E3E8ED; border: none; border-radius: 3px; max-height: 6px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
"""


class DropZone(QFrame):
    dropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("drop")
        self.setAcceptDrops(True)
        self.setMinimumHeight(150)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        arrow = QLabel(".hwp  →  .hwpx")
        arrow.setObjectName("arrow")
        arrow.setAlignment(Qt.AlignCenter)
        hint = QLabel("HWP 파일이나 폴더를 여기에 끌어다 놓으세요")
        hint.setObjectName("hint")
        hint.setAlignment(Qt.AlignCenter)
        lay.addWidget(arrow)
        lay.addWidget(hint)

    def _hover(self, on: bool) -> None:
        self.setProperty("hover", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, e) -> None:  # noqa: N802
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._hover(True)

    def dragLeaveEvent(self, e) -> None:  # noqa: N802
        self._hover(False)

    def dropEvent(self, e) -> None:  # noqa: N802
        self._hover(False)
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.dropped.emit(paths)


class Worker(QObject):
    progressed = Signal(object)  # Result
    finished = Signal(str)       # error message, empty on success

    def __init__(self, jobs, overwrite: bool) -> None:
        super().__init__()
        self.jobs, self.overwrite = jobs, overwrite
        self.cancel = threading.Event()

    def run(self) -> None:
        try:
            convert_all(self.jobs, overwrite=self.overwrite,
                        on_result=self.progressed.emit, cancel=self.cancel)
            self.finished.emit("")
        except EngineError as e:
            self.finished.emit(str(e))
        except Exception as e:  # pragma: no cover - defensive
            self.finished.emit(f"예상치 못한 오류: {e}")


class MainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("hwp2x")
        self.resize(820, 620)
        self.setMinimumSize(560, 460)
        self.inputs: list[Path] = []
        self.rows: dict[Path, int] = {}
        self.results: dict[Path, Result] = {}
        self.last_out_dir: Path | None = None
        self.thread: QThread | None = None
        self.worker: Worker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        self.drop = DropZone()
        self.drop.dropped.connect(self.add_paths)
        root.addWidget(self.drop)

        adders = QHBoxLayout()
        self.btn_files = QPushButton("파일 추가")
        self.btn_dir = QPushButton("폴더 추가")
        self.btn_clear = QPushButton("목록 비우기")
        self.btn_files.clicked.connect(self.pick_files)
        self.btn_dir.clicked.connect(self.pick_dir)
        self.btn_clear.clicked.connect(self.clear)
        self.count = QLabel("")
        self.count.setObjectName("muted")
        for w in (self.btn_files, self.btn_dir):
            adders.addWidget(w)
        adders.addStretch(1)
        adders.addWidget(self.count)
        adders.addWidget(self.btn_clear)
        root.addLayout(adders)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["파일", "상태", "내용"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(False)
        h = self.table.horizontalHeader()
        h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.cellDoubleClicked.connect(self.open_row)
        root.addWidget(self.table, 1)

        # Output options
        opts = QVBoxLayout()
        opts.setSpacing(6)
        dest = QHBoxLayout()
        dest.addWidget(QLabel("저장 위치"))
        self.rb_same = QRadioButton("원본과 같은 폴더")
        self.rb_other = QRadioButton("다른 폴더")
        self.rb_same.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.rb_same)
        grp.addButton(self.rb_other)
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("결과를 저장할 폴더")
        self.btn_out = QPushButton("찾아보기")
        self.btn_out.clicked.connect(self.pick_out)
        self.rb_other.toggled.connect(self._sync_dest)
        for w in (self.rb_same, self.rb_other):
            dest.addWidget(w)
        dest.addWidget(self.out_edit, 1)
        dest.addWidget(self.btn_out)
        opts.addLayout(dest)

        flags = QHBoxLayout()
        self.cb_recursive = QCheckBox("폴더 안의 하위 폴더까지 포함")
        self.cb_recursive.setChecked(True)
        self.cb_recursive.toggled.connect(self.refresh_rows)
        self.cb_overwrite = QCheckBox("같은 이름의 .hwpx가 있으면 덮어쓰기")
        flags.addWidget(self.cb_recursive)
        flags.addSpacing(18)
        flags.addWidget(self.cb_overwrite)
        flags.addStretch(1)
        opts.addLayout(flags)
        root.addLayout(opts)

        bottom = QHBoxLayout()
        left = QVBoxLayout()
        left.setSpacing(4)
        self.summary = QLabel("변환할 파일을 추가하세요.")
        self.summary.setObjectName("muted")
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setValue(0)
        left.addWidget(self.summary)
        left.addWidget(self.bar)
        bottom.addLayout(left, 1)
        self.btn_open = QPushButton("결과 폴더 열기")
        self.btn_open.clicked.connect(self.open_out)
        self.btn_open.setVisible(False)
        self.btn_go = QPushButton("변환")
        self.btn_go.setObjectName("primary")
        self.btn_go.setDefault(True)
        self.btn_go.clicked.connect(self.start_or_stop)
        bottom.addWidget(self.btn_open)
        bottom.addWidget(self.btn_go)
        root.addLayout(bottom)

        self._sync_dest()
        self._sync_buttons()

    # -- list management -----------------------------------------------------
    def pick_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "HWP 파일 선택", "", "한글 문서 (*.hwp *.HWP)")
        self.add_paths(files)

    def pick_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "폴더 선택")
        if d:
            self.add_paths([d])

    def pick_out(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "저장할 폴더 선택")
        if d:
            self.out_edit.setText(d)
            self.rb_other.setChecked(True)

    def add_paths(self, paths: list[str]) -> None:
        if self.busy:
            return
        known = {p.resolve() for p in self.inputs}
        for raw in paths:
            p = Path(raw)
            if p.resolve() not in known and (p.is_dir() or p.suffix.lower() == ".hwp"):
                self.inputs.append(p)
                known.add(p.resolve())
        self.refresh_rows()

    def clear(self) -> None:
        self.inputs.clear()
        self.refresh_rows()

    def refresh_rows(self) -> None:
        self.results.clear()
        jobs = plan(self.inputs, None, self.cb_recursive.isChecked())
        self._fill([job.src for job in jobs])
        n = len(jobs)
        self.count.setText(f"{n}개 파일" if n else "")
        self.summary.setText("변환 준비가 됐습니다." if n else "변환할 파일을 추가하세요.")
        self.bar.setValue(0)
        self.btn_open.setVisible(False)
        self._sync_buttons()

    def _fill(self, sources: list[Path]) -> None:
        self.table.setRowCount(0)
        self.rows.clear()
        for src in sources:
            r = self.table.rowCount()
            self.table.insertRow(r)
            name = QTableWidgetItem(src.name)
            name.setToolTip(str(src))
            self.table.setItem(r, 0, name)
            self.rows[src.resolve()] = r
            res = self.results.get(src.resolve())
            if res is None:
                self._set_status(r, "pending", "")
            else:
                self._show_result(r, res)

    def _show_result(self, row: int, r: Result) -> None:
        msg = r.message or (r.dst.name if r.succeeded else "")
        self._set_status(row, r.status, msg, str(r.dst) if r.succeeded else r.message)
        if r.succeeded:
            self.table.item(row, 0).setData(Qt.UserRole, str(r.dst))

    def _set_status(self, row: int, status: str, message: str, tip: str = "") -> None:
        sym, label, color = STATUS[status]
        st = QTableWidgetItem(f"{sym} {label}".strip())
        st.setForeground(QColor(color))
        self.table.setItem(row, 1, st)
        msg = QTableWidgetItem(message)
        msg.setToolTip(tip or message)
        msg.setForeground(QColor(MUTED if status in ("ok", "pending", "skipped") else color))
        self.table.setItem(row, 2, msg)

    # -- conversion -------------------------------------------------------------
    @property
    def busy(self) -> bool:
        return self.thread is not None

    def start_or_stop(self) -> None:
        if self.busy:
            if self.worker:
                self.worker.cancel.set()
            self.btn_go.setEnabled(False)
            self.summary.setText("지금 변환 중인 파일까지 마치고 멈춥니다…")
            return
        out_dir = None
        if self.rb_other.isChecked():
            text = self.out_edit.text().strip()
            if not text:
                QMessageBox.information(self, "hwp2x", "결과를 저장할 폴더를 선택하세요.")
                return
            out_dir = Path(text)
        jobs = plan(self.inputs, out_dir, self.cb_recursive.isChecked())
        if not jobs:
            return
        self.last_out_dir = out_dir
        self.total, self.done = len(jobs), 0
        self.counts = {k: 0 for k in STATUS}
        self.bar.setMaximum(self.total)
        self.bar.setValue(0)
        for job in jobs:
            r = self.rows.get(job.src.resolve())
            if r is not None:
                self._set_status(r, "running", "")
        self.btn_open.setVisible(False)
        self.summary.setText(f"{self.total}개 파일 변환 중…")

        self.thread = QThread(self)
        self.worker = Worker(jobs, self.cb_overwrite.isChecked())
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progressed.connect(self.on_result)
        self.worker.finished.connect(self.on_finished)
        self.thread.start()
        self._sync_buttons()

    def on_result(self, r: Result) -> None:
        self.done += 1
        self.counts[r.status] += 1
        self.results[r.src.resolve()] = r
        row = self.rows.get(r.src.resolve())
        if row is not None:
            self._show_result(row, r)
        self.bar.setValue(self.done)
        self.summary.setText(f"{self.done} / {self.total}")

    def on_finished(self, error: str) -> None:
        cancelled = self.worker is not None and self.worker.cancel.is_set() and not error
        if self.thread:
            self.thread.quit()
            self.thread.wait()
        self.thread = self.worker = None
        # Problems first so they are never buried in a long list; rows a stop
        # never reached go back to "waiting".
        order = {"error": 0, "warn": 1, "skipped": 2, "ok": 3}
        srcs = [Path(self.table.item(i, 0).toolTip()) for i in range(self.table.rowCount())]
        srcs.sort(key=lambda p: order.get(getattr(self.results.get(p.resolve()), "status", ""), 4))
        self._fill(srcs)
        self.table.scrollToTop()
        if error:
            self.summary.setText("변환 엔진을 시작하지 못했습니다.")
            QMessageBox.critical(self, "hwp2x", error)
        else:
            c = self.counts
            parts = [f"성공 {c['ok'] + c['warn']}"]
            if c["skipped"]:
                parts.append(f"건너뜀 {c['skipped']}")
            if c["error"]:
                parts.append(f"실패 {c['error']} (실패한 줄에 이유가 있습니다)")
            head = "멈췄습니다" if cancelled else "끝났습니다"
            self.summary.setText(f"{head}. " + ", ".join(parts))
            self.btn_open.setVisible(c["ok"] + c["warn"] > 0)
        self._sync_buttons()

    # -- helpers ------------------------------------------------------------------
    def _result_dir(self) -> Path | None:
        if self.last_out_dir:
            return self.last_out_dir
        for r in range(self.table.rowCount()):
            dst = self.table.item(r, 0).data(Qt.UserRole)
            if dst:
                return Path(dst).parent
        return None

    def open_out(self) -> None:
        d = self._result_dir()
        if d:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    def open_row(self, row: int, _col: int) -> None:
        dst = self.table.item(row, 0).data(Qt.UserRole)
        if dst:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(dst).parent)))

    def _sync_dest(self) -> None:
        on = self.rb_other.isChecked()
        self.out_edit.setEnabled(on)
        self.btn_out.setEnabled(True)

    def _sync_buttons(self) -> None:
        busy = self.busy
        has = self.table.rowCount() > 0
        self.btn_go.setText("멈추기" if busy else "변환")
        self.btn_go.setEnabled(has)
        for w in (self.btn_files, self.btn_dir, self.btn_clear, self.cb_recursive,
                  self.cb_overwrite, self.rb_same, self.rb_other, self.out_edit, self.btn_out):
            w.setEnabled(not busy)
        if not busy:
            self._sync_dest()
        self.btn_clear.setEnabled(not busy and has)
        self.drop.setAcceptDrops(not busy)

    def closeEvent(self, e) -> None:  # noqa: N802
        if self.busy and self.worker:
            self.worker.cancel.set()
            self.thread.quit()
            self.thread.wait(5000)
        e.accept()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("hwp2x")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")  # identical look on Windows, macOS and Linux
    app.setStyleSheet(QSS)
    w = MainWindow()
    w.show()
    w.add_paths([a for a in sys.argv[1:] if Path(a).exists()])  # "Open with…" / drop on icon
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
