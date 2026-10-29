# hwp2x

한글(HWP 5.x) 문서를 HWPX로 바꾸는 프로그램입니다. Windows, macOS, Linux에서 동작하고, Java가 함께 들어 있어 따로 설치할 것이 없습니다.

## 사용법

**앱(hwp2x-gui)** — 파일이나 폴더를 창에 끌어다 놓고 **변환**을 누릅니다. 결과는 원본 옆에 같은 이름의 `.hwpx`로 저장되며, 다른 폴더를 지정할 수도 있습니다. 실패하거나 확인이 필요한 파일은 목록 맨 위에 이유와 함께 표시됩니다.

**명령줄(hwp2x)**

```
hwp2x 보고서.hwp                       # 보고서.hwpx 생성
hwp2x ./문서 -r -o ./변환결과          # 하위 폴더까지, 폴더 구조를 유지해 저장
hwp2x ./문서 -r -f -j 4                # 기존 .hwpx 덮어쓰기, 4개씩 동시 변환
```

종료 코드: `0` 전부 성공 · `1` 일부 실패 · `2` 변환할 파일 없음 · `3` 엔진 시작 실패

**파이썬 라이브러리**

```python
from hwp2x import convert, convert_all, plan

r = convert("보고서.hwp")              # Result(status='ok', dst=PosixPath('보고서.hwpx'), ...)
results = convert_all(plan(["./문서"], "./변환결과", recursive=True), overwrite=True)
```

## 변환하지 않는 문서

| 경우 | 이유 |
|---|---|
| 암호가 걸린 문서 | 한글에서 암호를 해제한 뒤 변환하세요 |
| 배포용 문서 | 작성자가 걸어둔 복사·인쇄 제한이 HWPX에서는 사라지므로 변환하지 않습니다 |
| HWP 3.x(한글 97 이전) 문서 | 이 엔진은 HWP 5.x만 읽습니다. 한글에서 다시 저장한 뒤 변환하세요 |

원본에 XML에서 허용되지 않는 제어문자(주로 깨진 글꼴 이름)가 있으면 지우고 변환하며, 결과에 **완료 (확인)** 으로 표시합니다.

## 품질 보증

모든 결과 파일은 저장 직후 구조 검사를 거칩니다 (ZIP 무결성, `mimetype` 위치·무압축, 모든 XML 파싱, 매니페스트의 내장 파일 존재). 업스트림 샘플 93개 문서로 자동 테스트하며, 본문 텍스트가 원본과 글자 단위로 일치하는지 확인합니다.

## 빌드

JDK 17 이상, Python 3.9 이상, git이 필요합니다.

```
pip install -e ".[dev]"
python scripts/build_engine.py      # 엔진 jar + 최소 Java 런타임 (현재 OS용)
pytest
pyinstaller packaging/hwp2x.spec --noconfirm
```

`dist/hwp2x/` (macOS는 `dist/hwp2x.app`)에 `hwp2x`(명령줄)와 `hwp2x-gui`(앱)가 생깁니다. 각 OS용 배포본은 GitHub Actions가 만듭니다 (`.github/workflows/build.yml`, `v*` 태그를 올리면 릴리스에 첨부).

## 라이선스

Apache-2.0. 변환 엔진은 neolord0의 [hwplib](https://github.com/neolord0/hwplib), [hwpxlib](https://github.com/neolord0/hwpxlib), [hwp2hwpx](https://github.com/neolord0/hwp2hwpx) (모두 Apache-2.0)를 고정된 커밋으로 빌드해 사용합니다. 함께 배포되는 Java 런타임은 OpenJDK(GPLv2 + Classpath Exception)입니다.

“본 제품은 한글과컴퓨터의 HWP 문서 파일(.hwp) 공개 문서를 참고하여 개발하였습니다.”
