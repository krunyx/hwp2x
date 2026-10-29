"""Job planning and batch conversion (shared by the CLI and the GUI)."""
from __future__ import annotations

import os
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from .engine import Engine
from .verify import check_hwpx


@dataclass
class Job:
    src: Path
    dst: Path


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


def _is_hwp(p: Path) -> bool:
    return p.suffix.lower() == ".hwp" and not p.name.startswith(("~$", "."))


def plan(inputs: Iterable[str | Path], output_dir: str | Path | None = None,
         recursive: bool = False) -> list[Job]:
    """Turn files/folders into jobs.

    * File ``a/b.hwp`` -> ``a/b.hwpx`` (or ``<output_dir>/b.hwpx``).
    * Folder input: its .hwp files (sub-folders too when ``recursive``);
      with ``output_dir`` the folder structure is mirrored underneath it so
      equal file names in different sub-folders never collide.
    * Duplicate targets get a `` (2)`` suffix rather than overwriting each other.
    """
    out = Path(output_dir).expanduser() if output_dir else None
    jobs: list[Job] = []
    seen_src: set[Path] = set()
    taken: set[str] = set()

    def add(src: Path, dst: Path) -> None:
        key_src = src.resolve()
        if key_src in seen_src:
            return
        seen_src.add(key_src)
        dst = _unique(dst, taken)
        jobs.append(Job(src, dst))

    for raw in inputs:
        p = Path(raw).expanduser()
        if p.is_dir():
            files = p.rglob("*") if recursive else p.glob("*")
            for f in sorted(x for x in files if x.is_file() and _is_hwp(x)):
                if out is None:
                    add(f, f.with_suffix(".hwpx"))
                else:
                    rel = f.relative_to(p).with_suffix(".hwpx")
                    add(f, out / p.name / rel if p.name else out / rel)
        else:
            dst = (out / p.name if out else p).with_suffix(".hwpx")
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


def convert_all(jobs: list[Job], *, overwrite: bool = False, verify: bool = True,
                workers: int | None = None, timeout: float = 300.0,
                on_result: Callable[[Result], None] | None = None,
                cancel: threading.Event | None = None) -> list[Result]:
    """Convert jobs with ``workers`` engines in parallel.

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

    def emit(i: int, r: Result) -> None:
        results[i] = r
        if on_result:
            with lock:
                on_result(r)

    def worker() -> None:
        engine: Engine | None = None
        try:
            while not (cancel and cancel.is_set()):
                try:
                    i = todo.get_nowait()
                except queue.Empty:
                    return
                job = jobs[i]
                if job.dst.exists() and not overwrite:
                    emit(i, Result(job.src, job.dst, "skipped", "EXISTS",
                                   "이미 같은 이름의 .hwpx가 있어 건너뜀 (덮어쓰기 옵션 사용)"))
                    continue
                if engine is None:
                    engine = Engine(timeout=timeout)
                    engine.start()
                t0 = time.monotonic()
                status, code, msg, ms = engine.convert(job.src, job.dst)
                if status != "error" and verify:
                    problems = check_hwpx(job.dst)
                    if problems:
                        status, code = "error", "VERIFY"
                        msg = "결과 파일 검사 실패: " + "; ".join(problems[:3])
                emit(i, Result(job.src, job.dst, status, code, msg,
                               ms or int((time.monotonic() - t0) * 1000)))
        except BaseException as e:  # engine could not start: stop everything
            fatal.append(e)
            if cancel is not None:
                cancel.set()
        finally:
            if engine is not None:
                engine.close()

    if cancel is None:
        cancel = threading.Event()
    threads = [threading.Thread(target=worker, daemon=True) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if fatal:
        raise fatal[0]
    return [r for r in results if r is not None]


def convert(src: str | Path, dst: str | Path | None = None, *, overwrite: bool = True) -> Result:
    """Convert a single file. Convenience wrapper for library use."""
    src = Path(src)
    job = Job(src, Path(dst) if dst else src.with_suffix(".hwpx"))
    return convert_all([job], overwrite=overwrite, workers=1)[0]
