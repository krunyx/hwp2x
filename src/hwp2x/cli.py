"""hwp2x command line interface."""
from __future__ import annotations

import argparse
import sys
import threading

from . import __version__
from .converter import Result, convert_all, default_workers, plan
from .engine import EngineError

_MARK = {"ok": "✔", "warn": "△", "skipped": "–", "error": "✘"}


def _configure_stdout() -> None:
    # Windows consoles default to a legacy code page; Korean names would crash print().
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hwp2x",
        description="HWP 문서를 HWPX로 변환합니다.",
        epilog="예) hwp2x 보고서.hwp   |   hwp2x ./문서폴더 -r -o ./변환결과",
    )
    p.add_argument("inputs", nargs="+", metavar="경로", help=".hwp 파일 또는 폴더")
    p.add_argument("-o", "--output-dir", metavar="폴더",
                   help="결과를 저장할 폴더 (기본: 원본과 같은 폴더)")
    p.add_argument("-r", "--recursive", action="store_true", help="하위 폴더까지 변환")
    p.add_argument("-f", "--overwrite", action="store_true", help="이미 있는 .hwpx 덮어쓰기")
    p.add_argument("-j", "--jobs", type=int, default=default_workers(), metavar="N",
                   help=f"동시 변환 수 (기본 {default_workers()})")
    p.add_argument("--timeout", type=float, default=300, metavar="초",
                   help="파일 하나당 제한 시간 (기본 300초)")
    p.add_argument("--no-verify", action="store_true", help="결과 파일 구조 검사 생략")
    p.add_argument("-q", "--quiet", action="store_true", help="실패한 파일만 출력")
    p.add_argument("-V", "--version", action="version", version=f"hwp2x {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    _configure_stdout()
    a = build_parser().parse_args(argv)

    jobs = plan(a.inputs, a.output_dir, a.recursive)
    if not jobs:
        print("변환할 .hwp 파일이 없습니다.", file=sys.stderr)
        return 2

    total = len(jobs)
    done = 0

    def show(r: Result) -> None:
        nonlocal done
        done += 1
        if a.quiet and r.status in ("ok", "skipped"):
            return
        line = f"[{done}/{total}] {_MARK[r.status]} {r.src}"
        if r.succeeded:
            line += f" → {r.dst.name}"
        if r.message:
            line += f"  ({r.message})"
        print(line, flush=True)

    cancel = threading.Event()
    try:
        results = convert_all(jobs, overwrite=a.overwrite, verify=not a.no_verify,
                              workers=a.jobs, timeout=a.timeout, on_result=show, cancel=cancel)
    except EngineError as e:
        print(f"오류: {e}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        cancel.set()
        print("\n중단됨", file=sys.stderr)
        return 130

    n = {s: sum(r.status == s for r in results) for s in _MARK}
    print(f"\n완료: 성공 {n['ok'] + n['warn']}  건너뜀 {n['skipped']}  실패 {n['error']}  (총 {total})")
    return 1 if n["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
