# notes-cli

> 영어 원본: [README.md](../../README.md). 이 문서는 번역본이며 원본보다 우선하지 않습니다.

명령줄 메모 관리 도구입니다. 메모는 JSON 파일 하나에 저장하고 페이지 단위로 보여 줍니다.

## 사용법

```bash
python3 -m notes_cli memo add "Plan trip" --body "book flights" --tag travel
python3 -m notes_cli memo list
python3 -m notes_cli memo show 1
python3 -m notes_cli memo search flights
python3 -m notes_cli memo remove 1
```

- `memo add TITLE [--body TEXT] [--tag TAG ...]`는 메모를 저장하고 id를 출력합니다.
- `memo list [--tag TAG] [--page N]`은 메모를 페이지 단위로 보여 줍니다. 페이지 크기는 `config/settings.toml`에서
  가져옵니다.
- `memo show ID`는 메모 하나를 태그와 생성 시각과 함께 출력합니다.
- `memo search QUERY`는 제목이나 본문에 해당 텍스트가 들어 있는 메모를 대소문자 구분 없이 찾습니다.
- `memo remove ID`는 메모를 삭제합니다.

메모 파일은 현재 디렉터리의 `memos.json`입니다. 다른 파일을 쓰려면 명령 앞에 `--store FILE`을 붙이거나
`NOTES_CLI_STORE` 환경 변수를 설정합니다. 명령이 실패하면 이유를 stderr에 출력하고 종료 코드 1로 끝납니다.

## 개발

```bash
python3 -m pytest -q
```

커밋 메시지 형식을 포함한 기여 규칙은 [AGENTS.md](../../AGENTS.md)에 있습니다. 이 문서의 한국어 번역본이 지금 보고
계신 [docs/ko/README.ko.md](README.ko.md)입니다.
