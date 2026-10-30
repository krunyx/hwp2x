한글 문서(HWP, HWPX)를 **HWPX, Word(DOCX), Markdown, HTML, LaTeX, HyperTeX**로 바꾸는 프로그램입니다. Java가 함께 들어 있어 따로 설치할 것이 없습니다.

## 0.2.0에서 새로 생긴 것

- **출력 형식 5가지 추가**: Word(`.docx`), Markdown(`.md`), HTML(`.html`), LaTeX(`.tex`), HyperTeX(`.htex`)
- **HWPX 파일도 입력으로** 받습니다 (HWPX → 다른 형식).
- **한글 수식 변환**: 수식 편집기의 수식을 LaTeX, MathML(HTML), Word 수식으로 바꿉니다. 수식 속 한글 자모는 LaTeX에서 [hangulmath](https://ctan.org/pkg/hangulmath) 명령이 됩니다.
- 표의 병합 셀, 각주, 그림, 링크, 목록을 형식마다 옮깁니다. 표의 칸 너비는 원본 비율을 따릅니다.
- 앱에 **변환 형식** 선택이 생겼고, 명령줄에는 `-t` 옵션이 생겼습니다 (`hwp2x 문서.hwp -t docx`).

HWPX 외의 형식은 내용과 구조를 옮기며, 쪽 모양(글상자 위치, 글꼴, 쪽 크기)은 옮기지 않습니다.

## 내려받기

| 운영체제 | 파일 |
|---|---|
| Windows 10/11 (64비트) | `hwp2x-*-windows-x64.zip` |
| macOS, Apple 실리콘 (M1 이후) | `hwp2x-*-macos-arm64.dmg` |
| macOS, 인텔 | `hwp2x-*-macos-x64.dmg` |
| Linux (x64) | `hwp2x-*-linux-x64.tar.gz` |

## 설치와 첫 실행

**Windows** — 압축을 풀고 `hwp2x-gui.exe`를 실행합니다. "Windows의 PC 보호" 창이 뜨면 **추가 정보 → 실행**을 누르세요. 처음 한 번만 뜹니다.

**macOS** — dmg를 열어 `hwp2x.app`을 응용 프로그램 폴더로 옮깁니다. 처음 열 때 차단되면 **시스템 설정 → 개인정보 보호 및 보안**에서 **그래도 열기**를 누르세요. 처음 한 번만 필요합니다.

**Linux** — `tar -xzf hwp2x-*-linux-x64.tar.gz` 후 `hwp2x/hwp2x-gui`를 실행합니다.

## 사용법

변환 형식을 고르고, 파일이나 폴더를 창에 끌어다 놓은 뒤 **변환**을 누르면 원본 옆에 같은 이름의 결과 파일이 생깁니다. 실패하거나 확인이 필요한 파일은 목록 맨 위에 이유와 함께 표시됩니다.

명령줄: `hwp2x 문서폴더 -r -t md -o 결과폴더`

## 변환하지 않는 문서

- **암호가 걸린 문서**: 한글에서 암호를 해제한 뒤 변환하세요.
- **배포용 문서**: 작성자가 걸어둔 복사·인쇄 제한이 사라지므로 변환하지 않습니다.
- **HWP 3.x(한글 97 이전) 문서**: 한글에서 다시 저장한 뒤 변환하세요.

---
변환 엔진: neolord0의 hwplib · hwpxlib · hwp2hwpx (Apache-2.0).
“본 제품은 한글과컴퓨터의 HWP 문서 파일(.hwp) 공개 문서를 참고하여 개발하였습니다.”
