"""Product metadata in one place: the app window, the About dialog, the CLI,
the Windows exe version resource and the macOS Info.plist all read it."""
from __future__ import annotations

from . import __version__

APP_NAME = "hwp2x"
VERSION = __version__
DESCRIPTION = "한글 문서(HWP·HWPX)를 HWPX, Word, Markdown, HTML, LaTeX, HyperTeX로 변환합니다."
DESCRIPTION_EN = "Convert Hangul documents (HWP, HWPX) to HWPX, DOCX, Markdown, HTML, LaTeX and HyperTeX"
COMPANY = "krunyx"
YEAR = "2026"
COPYRIGHT = f"© {YEAR} {COMPANY}"
COPYRIGHT_ASCII = f"Copyright (C) {YEAR} {COMPANY}"
LICENSE = "Apache License 2.0"
BUNDLE_ID = "com.krunyx.hwp2x"

HOMEPAGE = "https://krunyx.com"
SOURCE_URL = "https://github.com/krunyx/hwp2x"
LATEST_URL = "https://github.com/krunyx/hwp2x/releases/latest"

# (component, author, licence, link) - shown in the About dialog.
THIRD_PARTY = [
    ("hwplib, hwpxlib, hwp2hwpx", "neolord0", "Apache-2.0", "https://github.com/neolord0"),
    ("OpenJDK", "Java 런타임", "GPLv2 + Classpath Exception", "https://openjdk.org"),
    ("Qt for Python", "앱 화면", "LGPLv3", "https://www.qt.io/qt-for-python"),
    ("Pillow", "그림 변환", "HPND", "https://python-pillow.org"),
]
HANCOM_NOTICE = "본 제품은 한글과컴퓨터의 HWP 문서 파일(.hwp) 공개 문서를 참고하여 개발하였습니다."


def version_line() -> str:
    return f"{APP_NAME} {VERSION}  {COPYRIGHT}  ({LICENSE})"
