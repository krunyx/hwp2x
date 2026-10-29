#!/usr/bin/env python3
"""Build the hwp2x Java engine and a minimal Java runtime for this platform.

Steps
  1. Fetch neolord0's hwplib / hwpxlib / hwp2hwpx at pinned commits.
  2. Compile them together with engine/src into one jar (no Maven needed).
  3. Use jdeps + jlink to cut a small Java runtime holding only the modules
     the jar needs, so end users never have to install Java.

Outputs (under src/hwp2x/_engine/):
  hwp2x-engine.jar
  runtime/            minimal JRE for the *current* OS/arch
  NOTICE.txt          upstream licence attribution

Requires a JDK 17+ on PATH (javac, jar, jdeps, jlink) and git.

  python scripts/build_engine.py            # jar + runtime
  python scripts/build_engine.py --no-jre   # jar only (uses system Java)
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build" / "engine"
OUT = ROOT / "src" / "hwp2x" / "_engine"

# Pinned upstream commits (all Apache-2.0, https://github.com/neolord0).
UPSTREAM = {
    "hwplib": "6746c27f17ebf5277493206284aa32044a1839c4",
    "hwpxlib": "f9fd2255ac0fc57414e0b657d115e7de51d31c65",
    "hwp2hwpx": "62d95b980a4e3a6766877dd3fb6f7f45f4afcf3d",
}

# Modules jdeps cannot see but the engine needs at run time:
#   jdk.charsets  - legacy Korean code pages (MS949/EUC-KR) found in old documents
EXTRA_MODULES = ["jdk.charsets"]


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print("+", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def tool(name: str) -> str:
    """Locate a JDK tool, preferring JAVA_HOME."""
    exe = name + (".exe" if os.name == "nt" else "")
    home = os.environ.get("JAVA_HOME")
    if home and (Path(home) / "bin" / exe).exists():
        return str(Path(home) / "bin" / exe)
    found = shutil.which(name)
    if not found:
        sys.exit(f"error: '{name}' not found. Install a JDK 17+ and set JAVA_HOME.")
    return found


def fetch_upstream() -> list[Path]:
    src_dirs = []
    up = BUILD / "upstream"
    up.mkdir(parents=True, exist_ok=True)
    for repo, commit in UPSTREAM.items():
        d = up / repo
        if not (d / ".git").exists():
            run(["git", "clone", "-q", f"https://github.com/neolord0/{repo}.git", d])
        head = subprocess.run(["git", "-C", d, "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
        if head != commit:
            run(["git", "-C", d, "fetch", "-q", "origin", commit])
            run(["git", "-C", d, "checkout", "-q", commit])
        src_dirs.append(d / "src" / "main" / "java")
    return src_dirs


def compile_jar(src_dirs: list[Path]) -> Path:
    classes = BUILD / "classes"
    shutil.rmtree(classes, ignore_errors=True)
    classes.mkdir(parents=True)

    sources = []
    for d in src_dirs + [ROOT / "engine" / "src"]:
        sources += sorted(str(p) for p in d.rglob("*.java"))
    argfile = BUILD / "sources.txt"
    # javac @argfile: quote each path so spaces survive on every OS
    argfile.write_text("\n".join('"' + s.replace("\\", "/") + '"' for s in sources), encoding="utf-8")

    run([tool("javac"), "--release", "8", "-nowarn", "-encoding", "UTF-8",
         "-d", classes, f"@{argfile}"], stdout=subprocess.DEVNULL)

    OUT.mkdir(parents=True, exist_ok=True)
    jar = OUT / "hwp2x-engine.jar"
    run([tool("jar"), "--create", "--file", jar,
         "--main-class", "kr.hwp2x.engine.Main", "-C", classes, "."])
    print(f"engine jar: {jar} ({jar.stat().st_size / 1e6:.1f} MB)")
    return jar


def build_runtime(jar: Path) -> Path:
    deps = subprocess.run(
        [tool("jdeps"), "--ignore-missing-deps", "--multi-release", "17",
         "--print-module-deps", str(jar)],
        capture_output=True, text=True, check=True).stdout.strip()
    modules = sorted(set(filter(None, deps.split(","))) | set(EXTRA_MODULES))
    print("runtime modules:", ",".join(modules))

    runtime = OUT / "runtime"
    shutil.rmtree(runtime, ignore_errors=True)
    run([tool("jlink"), "--add-modules", ",".join(modules),
         "--strip-debug", "--no-header-files", "--no-man-pages",
         "--compress", "zip-6", "--output", runtime])
    size = sum(f.stat().st_size for f in runtime.rglob("*") if f.is_file())
    print(f"runtime: {runtime} ({size / 1e6:.1f} MB)")
    return runtime


def write_notice() -> None:
    lines = [
        "hwp2x bundles the following Apache-2.0 licensed libraries",
        "by neolord0 (https://github.com/neolord0):",
        "",
    ]
    lines += [f"  {r:<9} commit {c}" for r, c in UPSTREAM.items()]
    lines += [
        "",
        "“본 제품은 한글과컴퓨터의 HWP 문서 파일(.hwp) 공개 문서를 참고하여 개발하였습니다.”",
        "",
        "When a bundled Java runtime is present it is built from OpenJDK",
        "(GPLv2 with the Classpath Exception).",
    ]
    (OUT / "NOTICE.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-jre", action="store_true", help="skip building the bundled Java runtime")
    a = ap.parse_args()

    jar = compile_jar(fetch_upstream())
    if not a.no_jre:
        build_runtime(jar)
    write_notice()


if __name__ == "__main__":
    main()
