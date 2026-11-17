# 저장소 규칙

> 영어 원본: [AGENTS.md](../../AGENTS.md). 이 문서는 번역본이며 원본보다 우선하지 않습니다.

- Python 3.11 이상, 표준 라이브러리만 사용합니다.
- 변경을 끝났다고 보고하기 전에 `python3 -m pytest -q`를 실행합니다. 변경을 통과시키려고 기존 테스트를 고치지 않습니다.
- 사이트 빌드는 `build/`에 쓰고 `python3 tools/check_site.py`가 그것을 읽습니다. 빌드가 쓰는 내용을 바꾸는 변경 뒤에는
  둘 다 실행합니다.

## 문서

- 문서는 영어로 씁니다. 영어 Markdown 문서마다 `docs/ko/<path>.ko.md`에 한국어 미러가 있습니다. `<path>`는 저장소 안의
  문서 경로이며, 미러는 같은 변경에서 함께 고칩니다.
- 명령이나 빌드 결과 파일의 사용자에게 보이는 변경은 `README.md`에 적습니다.

## 커밋

- Conventional Commits를 씁니다. `<type>: <description>` 형식이며 type은 feat, fix, refactor, docs, test, chore, perf,
  ci입니다.
- 메시지는 영어로, 명령형으로 쓰고 제목은 72자 이하로 하며 마침표로 끝내지 않습니다.
- `Co-Authored-By`나 `Signed-off-by` 같은 트레일러를 붙이지 않습니다.
- 논리적 변경 하나는 커밋 하나로 만듭니다.
