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

# Licence, warranty disclaimer and limitation of liability (Apache-2.0 sections 7-8),
# shown in the About dialog and by `hwp2x --license`. The full text is on the web page.
TERMS_URL = "https://krunyx.com/hwp2x/#license"
TERMS = [
    ("라이선스", "이 프로그램은 Apache License 2.0에 따라 개인·공공·상업 목적 모두 무료로 사용·복제·수정·배포할 수 "
                "있는 오픈소스 소프트웨어입니다."),
    ("보증 없음", "이 프로그램은 \u201c있는 그대로\u201d 제공되며, 명시적이든 묵시적이든 특정 목적에의 적합성을 포함한 "
                 "어떠한 보증도 하지 않습니다."),
    ("책임 제한", "krunyx와 기여자는 이 프로그램의 사용 또는 사용 불능으로 생긴 어떠한 손해(문서·자료의 손실이나 손상 포함)에도 "
                 "책임을 지지 않습니다."),
    ("결과 확인", "변환 결과가 원본과 완전히 같다고 보장하지 않습니다. 변환하는 원본 문서는 바꾸거나 지우지 않으며, "
                 "같은 이름의 결과 파일은 덮어쓰기를 켰을 때만 바뀝니다. 공문서 등 중요한 문서는 사용하기 전에 "
                 "원본과 대조해 확인하세요."),
    ("상표", "\u201c한글\u201d, \u201cHWP\u201d, \u201cHWPX\u201d는 (주)한글과컴퓨터의 상표이며, hwp2x는 한글과컴퓨터와 "
            "관련이 없는 독립 프로젝트입니다."),
]


def terms_text() -> str:
    """Plain-text terms for the command line."""
    lines = [f"{APP_NAME} {VERSION}  {COPYRIGHT}", ""]
    for head, body in TERMS:
        lines += [f"[{head}] {body}", ""]
    lines += [f"함께 쓰는 오픈소스: " + "; ".join(f"{c} ({lic})" for c, _w, lic, _u in THIRD_PARTY), "",
              f"\u201c{HANCOM_NOTICE}\u201d", "", f"전문: {TERMS_URL}"]
    return "\n".join(lines)


def version_line() -> str:
    return f"{APP_NAME} {VERSION}  {COPYRIGHT}  ({LICENSE})"
