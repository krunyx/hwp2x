# hwp2x

한글 문서(HWP, HWPX)를 **HWPX, Word(DOCX), Markdown, HTML, LaTeX, HyperTeX**로 바꾸는 프로그램입니다. Windows, macOS, Linux에서 동작하고, Java가 함께 들어 있어 따로 설치할 것이 없습니다.

| 형식 | 확장자 | 무엇이 남나 |
|---|---|---|
| HWPX | `.hwpx` | 원본 그대로 (HWP 입력만) |
| Word | `.docx` | 제목·목록·표(병합 셀)·각주·그림·링크, 수식은 Word 수식으로 |
| Markdown | `.md` | 내용과 구조. 복잡한 표는 HTML 표로, 수식은 `$…$` |
| HTML | `.html` | 그림이 들어간 웹 페이지 한 장, 수식은 MathML |
| LaTeX | `.tex` | XeLaTeX/LuaLaTeX 문서. 수식 속 한글 자모는 [hangulmath](https://ctan.org/pkg/hangulmath) |
| HyperTeX | `.htex` | [HyperTeX 2.0](https://github.com/krunyx/hypertex) 문서 |

HWPX 외의 형식은 **내용과 구조**를 옮깁니다. 쪽 크기, 글상자 위치, 글꼴 같은 지면 모양은 옮기지 않습니다. Markdown·LaTeX·HyperTeX의 그림은 결과 파일 옆 `이름_files/` 폴더에 저장됩니다.

## 사용법

**앱(hwp2x-gui)** — 변환 형식을 고르고, 파일이나 폴더를 창에 끌어다 놓은 뒤 **변환**을 누릅니다. 실패하거나 확인이 필요한 파일은 목록 맨 위에 이유와 함께 표시됩니다.

**명령줄(hwp2x)**

```
hwp2x 보고서.hwp                       # 보고서.hwpx
hwp2x 보고서.hwp -t docx               # 보고서.docx
hwp2x 보고서.hwpx -t md                # HWPX도 입력으로 받습니다
hwp2x ./문서 -r -t tex -o ./변환결과    # 하위 폴더까지, 폴더 구조를 유지해 저장
```

`-t` 형식: `hwpx`(기본) `docx` `md` `html` `tex` `htex`. 폴더 안에 같은 이름의 `.hwp`와 `.hwpx`가 함께 있으면 `.hwp`만 변환합니다.

종료 코드: `0` 전부 성공 · `1` 일부 실패 · `2` 변환할 파일 없음 · `3` 엔진 시작 실패

**파이썬 라이브러리**

```python
from hwp2x import convert, convert_all, plan

convert("보고서.hwp", "보고서.docx")
results = convert_all(plan(["./문서"], "./변환결과", recursive=True, fmt="md"), overwrite=True)
```

## 수식

한글 수식 편집기의 수식(`{a+b} over c`, `sqrt`, `sum from … to …`, `matrix`, `cases`, `left ( … right )` 등)을 해석해 각 형식의 수식으로 바꿉니다.

| 형식 | 수식 | 수식 속 한글 |
|---|---|---|
| LaTeX | `\frac{a+b}{c}` | 자모는 hangulmath 명령(`\giug`), 음절은 `\text{}` |
| HyperTeX | 위와 같음 | 자모와 한 음절은 그대로, 여러 음절은 `\text{}` (HyperTeX 명세) |
| HTML | MathML (TeX 원문을 annotation으로 함께) | |
| Word | Word 수식(OMML) | |
| Markdown | `$…$` (GitHub, Obsidian 등) | `\text{}` |

## 변환하지 않는 문서와 내용

- **암호가 걸린 문서**: 한글에서 암호를 해제한 뒤 변환하세요.
- **배포용 문서**: 작성자가 걸어둔 복사·인쇄 제한이 사라지므로 어떤 형식으로도 변환하지 않습니다.
- **HWP 3.x(한글 97 이전) 문서**: 한글에서 다시 저장한 뒤 변환하세요.
- 머리말·꼬리말, 쪽 번호, 숨은 설명, 메모, 양식 개체(단추·입력란), OLE 개체(차트 등)는 HWPX 외의 형식으로 옮기지 않습니다. 빠진 것이 있으면 결과에 **완료 (확인)** 과 함께 무엇이 빠졌는지 표시합니다.
- HyperTeX에는 세로 셀 병합과 취소선이 없어, 병합 셀 내용은 첫 칸에만 넣고 취소선 서식은 뺍니다.

## 품질 보증

업스트림 샘플 93개 문서로 다음을 자동 검사합니다.

- HWPX: ZIP 무결성, `mimetype` 위치·무압축, 모든 XML 파싱, 매니페스트의 내장 파일 존재
- DOCX: 패키지 구조와 관계(rels) 검사, python-docx로 열기
- Markdown·LaTeX·HyperTeX: 원본 본문 글자가 하나도 빠지지 않았는지 대조
- HyperTeX: HyperTeX 기준 파서가 오류·경고를 하나도 내지 않는지
- LaTeX: XeLaTeX 컴파일 (`HWP2X_XELATEX=1`로 켬)

## 빌드

JDK 17 이상, Python 3.9 이상, git이 필요합니다.

```
pip install -e ".[dev]"
python scripts/build_engine.py      # 엔진 jar + 최소 Java 런타임 (현재 OS용)
pytest
pyinstaller packaging/hwp2x.spec --noconfirm
```

`dist/hwp2x/` (macOS는 `dist/hwp2x.app`)에 `hwp2x`(명령줄)와 `hwp2x-gui`(앱)가 생깁니다. 각 OS용 배포본은 GitHub Actions가 만들고, GitHub에서 릴리스를 게시하면 그 릴리스에 자동으로 첨부합니다.

## 구조

```
.hwp  ─(Java 엔진)─→ .hwpx ─(hwpx_reader)─→ 문서 모델 ─(writers)─→ docx · md · html · tex · htex
.hwpx ───────────────────────┘
```

- `src/hwp2x/model.py` 형식 중립 문서 모델 (문단·제목·목록·표·그림·수식·각주·링크)
- `src/hwp2x/eqn.py` 한글 수식 → 트리 → LaTeX / MathML / OMML
- `src/hwp2x/writers/` 형식별 출력

## 라이선스

Apache-2.0. 변환 엔진은 neolord0의 [hwplib](https://github.com/neolord0/hwplib), [hwpxlib](https://github.com/neolord0/hwpxlib), [hwp2hwpx](https://github.com/neolord0/hwp2hwpx) (모두 Apache-2.0)를 고정된 커밋으로 빌드해 사용합니다. 함께 배포되는 Java 런타임은 OpenJDK(GPLv2 + Classpath Exception), 그림 변환에 쓰는 Pillow는 HPND 라이선스입니다.

“본 제품은 한글과컴퓨터의 HWP 문서 파일(.hwp) 공개 문서를 참고하여 개발하였습니다.”
