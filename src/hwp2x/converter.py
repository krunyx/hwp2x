"""Job planning and batch conversion (shared by the CLI and the GUI).

Inputs: .hwp and .hwpx.  Outputs: hwpx, docx, md, html, tex, htex.

    .hwp  --(Java engine)--> .hwpx --(reader)--> model --(writer)--> output
    .hwpx ---------------------------^
"""
from __future__ import annotations

import os
import queue
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .engine import Engine
from .verify import check_docx, check_hwpx
from .writers import FORMATS

INPUT_SUFFIXES = (".hwp", ".hwpx")


@dataclass
class Job:
    src: Path
    dst: Path
    fmt: str = "hwpx"


@dataclass
class Result:
    src: Path
    dst: Path
    status: str            # ok | warn | skipped | error
    code: str = ""
    message: str = ""
    millis: int = 0

    @property
    def succeeded(self) -> bool:
        return self.status in ("ok", "warn")


def _is_input(p: Path, fmt: str) -> bool:
    if p.name.startswith(("~$", ".")):
        return False
    suf = p.suffix.lower()
    return suf == ".hwp" or (suf == ".hwpx" and fmt != "hwpx")


def plan(inputs: Iterable[str | Path], output_dir: str | Path | None = None,
         recursive: bool = False, fmt: str = "hwpx") -> list[Job]:
    """Turn files/folders into jobs.

    * File ``a/b.hwp`` -> ``a/b.<ext>`` (or ``<output_dir>/b.<ext>``).
    * Folder input: its .hwp files - and .hwpx files when converting to another
      format - (sub-folders too when ``recursive``). A .hwpx next to a .hwp of
      the same name is taken to be a converted copy and skipped.
      With ``output_dir`` the folder structure is mirrored underneath it.
    * Duplicate targets get a `` (2)`` suffix rather than overwriting each other.
    """
    if fmt not in FORMATS:
        raise ValueError(f"지원하지 않는 형식: {fmt}")
    ext = FORMATS[fmt][0]
    out = Path(output_dir).expanduser() if output_dir else None
    jobs: list[Job] = []
    seen_src: set[Path] = set()
    taken: set[str] = set()

    def add(src: Path, dst: Path) -> None:
        key_src = src.resolve()
        if key_src in seen_src:
            return
        seen_src.add(key_src)
        jobs.append(Job(src, _unique(dst, taken), fmt))

    for raw in inputs:
        p = Path(raw).expanduser()
        if p.is_dir():
            files = p.rglob("*") if recursive else p.glob("*")
            found = sorted(x for x in files if x.is_file() and _is_input(x, fmt))
            hwp_stems = {(f.parent, f.stem.lower()) for f in found if f.suffix.lower() == ".hwp"}
            for f in found:
                if f.suffix.lower() == ".hwpx" and (f.parent, f.stem.lower()) in hwp_stems:
                    continue
                if out is None:
                    add(f, f.with_suffix(ext))
                else:
                    rel = f.relative_to(p).with_suffix(ext)
                    add(f, out / p.name / rel if p.name else out / rel)
        else:
            dst = (out / p.name if out else p).with_suffix(ext)
            add(p, dst)
    return jobs


def _unique(dst: Path, taken: set[str]) -> Path:
    key = os.path.normcase(str(dst.resolve()))
    if key not in taken:
        taken.add(key)
        return dst
    n = 2
    while True:
        cand = dst.with_name(f"{dst.stem} ({n}){dst.suffix}")
        key = os.path.normcase(str(cand.resolve()))
        if key not in taken:
            taken.add(key)
            return cand
        n += 1


def default_workers() -> int:
    return max(1, min(4, (os.cpu_count() or 2) // 2))


class _Worker:
    """One conversion lane: a lazily started Java engine plus a scratch folder."""

    def __init__(self, timeout: float):
        self.timeout = timeout
        self.engine: Engine | None = None
        self.tmp = tempfile.TemporaryDirectory(prefix="hwp2x-")

    def close(self) -> None:
        if self.engine is not None:
            self.engine.close()
        self.tmp.cleanup()

    def _to_hwpx(self, src: Path, dst: Path) -> tuple[str, str, str, int]:
        if self.engine is None:
            self.engine = Engine(timeout=self.timeout)
            self.engine.start()
        return self.engine.convert(src, dst)

    def run(self, job: Job, verify: bool) -> Result:
        t0 = time.monotonic()
        src_is_hwpx = job.src.suffix.lower() == ".hwpx"

        if job.fmt == "hwpx":
            if src_is_hwpx:
                return Result(job.src, job.dst, "error", "ALREADY_HWPX", "이미 HWPX 형식입니다")
            status, code, msg, ms = self._to_hwpx(job.src, job.dst)
            if status != "error" and verify:
                problems = check_hwpx(job.dst)
                if problems:
                    status, code, msg = "error", "VERIFY", "결과 파일 검사 실패: " + "; ".join(problems[:3])
            return Result(job.src, job.dst, status, code, msg, ms or int((time.monotonic() - t0) * 1000))

        # Other formats go through the document model.
        warnings: list[str] = []
        hwpx = job.src
        if not src_is_hwpx:
            hwpx = Path(self.tmp.name) / "doc.hwpx"
            status, code, msg, _ms = self._to_hwpx(job.src, hwpx)
            if status == "error":
                return Result(job.src, job.dst, status, code, msg)
            if code == "SANITIZED":
                warnings.append(msg)
        elif not job.src.is_file():
            return Result(job.src, job.dst, "error", "NOTFOUND", "파일을 찾을 수 없습니다")

        from .hwpx_reader import read_hwpx
        from .writers import write
        try:
            doc = read_hwpx(hwpx)
        except Exception as e:
            return Result(job.src, job.dst, "error", "READ", f"HWPX 문서를 읽지 못했습니다 — {type(e).__name__}: {e}")
        try:
            job.dst.parent.mkdir(parents=True, exist_ok=True)
            write(doc, job.fmt, job.dst)
        except Exception as e:
            _remove_partial(job.dst)
            return Result(job.src, job.dst, "error", "WRITE", f"{job.fmt} 파일을 만들지 못했습니다 — {type(e).__name__}: {e}")
        if verify and job.fmt == "docx":
            problems = check_docx(job.dst)
            if problems:
                return Result(job.src, job.dst, "error", "VERIFY", "결과 파일 검사 실패: " + "; ".join(problems[:3]))
        warnings += doc.warnings
        ms = int((time.monotonic() - t0) * 1000)
        if warnings:
            return Result(job.src, job.dst, "warn", "PARTIAL", "변환됨. " + " / ".join(warnings), ms)
        return Result(job.src, job.dst, "ok", "", "", ms)


def _remove_partial(p: Path) -> None:
    try:
        p.unlink()
    except OSError:
        pass
    side = p.with_name(p.stem + "_files")
    if side.is_dir():
        shutil.rmtree(side, ignore_errors=True)


def convert_all(jobs: list[Job], *, overwrite: bool = False, verify: bool = True,
                workers: int | None = None, timeout: float = 300.0,
                on_result: Callable[[Result], None] | None = None,
                cancel: threading.Event | None = None) -> list[Result]:
    """Convert jobs in ``workers`` parallel lanes.

    ``on_result`` is called (from worker threads) as each file finishes.
    Results come back in job order.
    """
    workers = max(1, min(workers or default_workers(), len(jobs) or 1))
    results: list[Result | None] = [None] * len(jobs)
    todo: queue.Queue[int] = queue.Queue()
    for i in range(len(jobs)):
        todo.put(i)
    lock = threading.Lock()
    fatal: list[BaseException] = []
    stop = cancel if cancel is not None else threading.Event()

    def emit(i: int, r: Result) -> None:
        results[i] = r
        if on_result:
            with lock:
                on_result(r)

    def lane() -> None:
        w = _Worker(timeout)
        try:
            while not stop.is_set():
                try:
                    i = todo.get_nowait()
                except queue.Empty:
                    return
                job = jobs[i]
                if job.dst.exists() and not overwrite:
                    emit(i, Result(job.src, job.dst, "skipped", "EXISTS",
                                   f"이미 같은 이름의 {job.dst.suffix} 파일이 있어 건너뜀 (덮어쓰기 옵션 사용)"))
                    continue
                emit(i, w.run(job, verify))
        except BaseException as e:  # the engine could not start: stop everything
            fatal.append(e)
            stop.set()
        finally:
            w.close()

    threads = [threading.Thread(target=lane, daemon=True) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if fatal:
        raise fatal[0]
    return [r for r in results if r is not None]


def convert(src: str | Path, dst: str | Path | None = None, *, fmt: str | None = None,
            overwrite: bool = True) -> Result:
    """Convert a single file. ``fmt`` defaults to the extension of ``dst``,
    or HWPX. Convenience wrapper for library use."""
    src = Path(src)
    if fmt is None:
        suf = Path(dst).suffix.lower() if dst else ".hwpx"
        fmt = next((k for k, (e, _l) in FORMATS.items() if e == suf), "hwpx")
    job = Job(src, Path(dst) if dst else src.with_suffix(FORMATS[fmt][0]), fmt)
    return convert_all([job], overwrite=overwrite, workers=1)[0]
