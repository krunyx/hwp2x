"""Bridge to the Java conversion engine.

One :class:`Engine` owns one JVM running ``kr.hwp2x.engine.Main --serve`` and
feeds it jobs over stdin, so a batch pays JVM start-up once. If the JVM dies
or a file takes longer than the timeout, the job is reported as failed and the
JVM is restarted for the next job.
"""
from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent / "_engine"
JAR = ENGINE_DIR / "hwp2x-engine.jar"
_EXE = ".exe" if os.name == "nt" else ""

# Environment variables that inject options into any JVM. A user's global
# Java settings must not change how the bundled engine behaves.
_JVM_ENV = ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS", "CLASSPATH")


class EngineError(RuntimeError):
    """The engine could not be started at all (no Java, missing jar...)."""


def find_java() -> tuple[str, bool]:
    """Return (java executable, is_bundled). Bundled runtime wins."""
    bundled = ENGINE_DIR / "runtime" / "bin" / f"java{_EXE}"
    if bundled.exists():
        return str(bundled), True
    home = os.environ.get("JAVA_HOME")
    if home and (Path(home) / "bin" / f"java{_EXE}").exists():
        return str(Path(home) / "bin" / f"java{_EXE}"), False
    found = shutil.which("java")
    if found:
        return found, False
    raise EngineError(
        "Java 실행 환경을 찾지 못했습니다. 배포판(설치본)을 쓰거나 Java 8 이상을 설치하세요.")


def _child_env(bundled: bool) -> dict[str, str]:
    env = dict(os.environ)
    if bundled:
        for k in _JVM_ENV:
            env.pop(k, None)
    # The JVM encodes file names using the locale. Under a non-UTF-8 locale
    # (e.g. LANG=C on a server) it cannot open Korean file names at all.
    # macOS always uses UTF-8 for file names; Windows uses the UTF-16 file API.
    if sys.platform.startswith("linux"):
        cur = env.get("LC_ALL") or env.get("LC_CTYPE") or env.get("LANG") or ""
        if "utf-8" not in cur.lower() and "utf8" not in cur.lower():
            env["LC_ALL"] = "C.UTF-8"
    return env


class Engine:
    """A running conversion JVM. Use as a context manager."""

    def __init__(self, timeout: float = 300.0):
        if not JAR.exists():
            raise EngineError(f"엔진 파일이 없습니다: {JAR}  (scripts/build_engine.py 로 빌드하세요)")
        self.java, self.bundled = find_java()
        self.timeout = timeout
        self._proc: subprocess.Popen | None = None
        self._lines: queue.Queue[str | None] = queue.Queue()

    # -- process management ------------------------------------------------
    def start(self) -> None:
        cmd = [self.java, "-Xss8m", "-Djava.awt.headless=true",
               "-Dfile.encoding=UTF-8", "-jar", str(JAR), "--serve"]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console flash on Windows
        try:
            self._proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                env=_child_env(self.bundled), creationflags=flags)
        except OSError as e:
            raise EngineError(f"엔진을 시작하지 못했습니다: {e}") from e
        self._lines = queue.Queue()
        threading.Thread(target=self._pump, args=(self._proc, self._lines), daemon=True).start()
        first = self._next_line(60.0)
        if first is None or not first.startswith("READY"):
            self.close()
            raise EngineError("엔진이 응답하지 않습니다 (Java 버전을 확인하세요).")

    @staticmethod
    def _pump(proc: subprocess.Popen, q: queue.Queue) -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            q.put(raw.decode("utf-8", "replace").rstrip("\r\n"))
        q.put(None)  # EOF: process ended

    def _next_line(self, timeout: float) -> str | None:
        try:
            return self._lines.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError from None

    def close(self) -> None:
        p, self._proc = self._proc, None
        if p is None:
            return
        try:
            if p.stdin:
                p.stdin.close()
            p.wait(timeout=5)
        except Exception:
            p.kill()
            p.wait()

    def __enter__(self) -> "Engine":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- conversion ---------------------------------------------------------
    def convert(self, src: str | Path, dst: str | Path) -> tuple[str, str, str, int]:
        """Convert one file. Returns (status, code, message, millis) where
        status is 'ok', 'warn' or 'error'. Never raises for a bad document."""
        src, dst = os.path.abspath(src), os.path.abspath(dst)
        if "\t" in src or "\n" in src or "\t" in dst or "\n" in dst:
            return "error", "BADNAME", "파일 이름에 탭/줄바꿈 문자가 있습니다", 0
        if self._proc is None or self._proc.poll() is not None:
            self.start()
        assert self._proc is not None and self._proc.stdin is not None
        try:
            self._proc.stdin.write(f"{src}\t{dst}\n".encode("utf-8"))
            self._proc.stdin.flush()
            line = self._next_line(self.timeout)
        except TimeoutError:
            self._kill()
            return "error", "TIMEOUT", f"{int(self.timeout)}초 안에 끝나지 않았습니다", 0
        except OSError:
            line = None
        if line is None:  # JVM died on this file (e.g. out of memory)
            self._kill()
            return "error", "CRASH", "변환 엔진이 비정상 종료했습니다 (파일이 너무 크거나 손상됨)", 0
        return _parse(line)

    def _kill(self) -> None:
        if self._proc is not None:
            self._proc.kill()
            self._proc.wait()
            self._proc = None


def _parse(line: str) -> tuple[str, str, str, int]:
    parts = line.split("\t")
    if parts[0] == "OK":
        ms = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        warn = next((p[5:] for p in parts[2:] if p.startswith("WARN:")), "")
        if warn:
            return "warn", "SANITIZED", _WARN_KO.get("SANITIZED", warn), ms
        return "ok", "", "", ms
    code = parts[1] if len(parts) > 1 else "UNKNOWN"
    detail = parts[2] if len(parts) > 2 else ""
    msg = MESSAGES_KO.get(code, "변환 실패")
    if code in ("READ", "CONVERT") and detail:
        msg = f"{msg} — {detail}"
    return "error", code, msg, 0


MESSAGES_KO = {
    "NOTFOUND": "파일을 찾을 수 없습니다",
    "ALREADY_HWPX": "이미 HWPX 형식입니다",
    "NOT_HWP5": "HWP 5.0 형식이 아닙니다 (한글 97 이전 문서이거나 다른 형식)",
    "PASSWORD": "암호가 걸린 문서. 한글에서 암호를 해제한 뒤 다시 변환하세요",
    "DISTRIBUTION": "배포용 문서라 변환하지 않음 (작성자가 복사·인쇄를 제한한 문서)",
    "READ": "문서를 읽지 못했습니다 (손상되었거나 지원하지 않는 기능)",
    "CONVERT": "변환 중 오류가 발생했습니다",
    "BADJOB": "내부 오류",
}
_WARN_KO = {
    "SANITIZED": "변환됨. 원본 글꼴 이름 등의 깨진 문자를 지움 — 결과를 열어 확인하세요",
}
