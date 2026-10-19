---
name: Markdown 가명화 및 필터링
description: LLM이 markdown 문서의 이름을 그대로 읽지 못하도록 하는 스킬
---
## 필요사항
- Python 3.10 이상.
- 외부 패키지 불필요.
## 실행
`python scripts/pseudonymize.py "입력.md" "manifest.md" -o "결과.md"`

**예시**
`python scripts/pseudonymize.py input.example.md manifest.example.md -o result.new.md`

## 버전 확인
`python scripts/pseudonymize.py --version`

## 필요사항
- manifest.md 표: `Key | Value | note | action`
- `action` 열 또는 셀이 없으면 replace. note는 설명으로만 사용.
- `action` 종류
	- replace: Key를 Value로 치환 (Value 필수)
	- remove_text: Key 문자열만 삭제 (Value는 빈칸)
	- remove_line: Key를 포함한 줄 전체 삭제 (Value는 빈칸)
- 행은 `|`로 시작하며 `Key`와 `Value`는 첫 두 열, `note/action`은 선택 열이다.
- Key 칸에 쉼표 또는 `<br>`로 별칭을 여러 개 쓸 수 있고 모두 같은 Value로 처리된다.
- 쉼표 문자는 `,`로 쓴다.
- 구분자가 연속되거나 끝에 붙어서 생긴 빈 별칭은 무시한다.
- 별칭 안의 띄어쓰기는 유지한다.
- 모든 칸이 빈 행은 건너뛴다.
## 트러블슈팅
- `Key`가 중복되면 경고만 표시하고 가장 나중에 읽은 행의 규칙을 쓴다.
- 서로 다른 행이 같은 `Value`를 쓰면 작업을 중단한다.
- 같은 가명으로 묶을 원문은 한 행의 별칭으로 모은다.
- 별칭이 하나도 없는 `Key`, 잘못된 `action` 및 열 수는 오류다.
- 오류·경고 메시지에는 행 번호만 표시된다.
## 우선순위
- 줄 삭제를 먼저 수행하고 남은 텍스트를 한 번에 치환·삭제한다.
- 같은 위치에서는 긴 문자열 우선이며 치환 결과를 다시 치환하지 않는다.
- 대소문자를 구분하는 정확한 문자열 매칭이고 단어 경계·조사 보정은 없다.
## 기타
- UTF-8 입력, UTF-8(BOM 없음) 출력.
- LF/CRLF 유지.
- 원문, 정답지, 기존 출력은 덮어쓰지 않는다.
- 출력 상위 폴더가 있어야 한다.
- -o 생략 시 원문명.pseudonymized.md 생성.
- Windows에서는 py, WSL에서는 python3도 사용할 수 있다.
- 정답지에 없는 개인정보 및 이미지·외부 링크 대상은 자동 탐지하지 않는다.
- 표·코드·링크를 포함한 전체 텍스트에 적용하므로 변환 후 문서 구조를 확인한다.
- 정답지와 공유할 결과는 별도로 보관한다.
- 기존 JSON 규칙도 호환용으로 읽지만 표와 한 파일에 혼합할 수 없다.
