# docs-kit

> 영어 원본: [README.md](../../README.md). 이 문서는 번역본이며 원본보다 우선하지 않습니다.

정적 문서 사이트 빌더입니다. `content/`의 Markdown 페이지를 HTML, 사이트맵, 검색 색인으로 바꾸고 방문 횟수를 로컬
데이터베이스에 보관합니다.

## 사용법

```bash
python3 -m dockit build
python3 tools/check_site.py
python3 -m dockit visit guide
```

- `build [--out DIR]`은 페이지마다 HTML 파일 하나, `sitemap.xml`, `search-index.json`을 `build/`(또는 `DIR`)에 씁니다.
  폴더를 먼저 비우고, 다른 빌드가 그 폴더를 쓰는 동안에는 실행을 거부합니다. 세 단계는 각각 몇 초가 걸립니다.
- `python3 tools/check_site.py`는 `build/`를 읽어 빌드가 써야 하는데 쓰지 않은 파일을 모두 알려 줍니다.
- 나머지 명령은 기능에서 오며 아래를 봅니다.

페이지는 선택 사항인 front matter를 가진 Markdown 파일입니다. front matter는 `---` 두 줄 사이의 `key: value` 줄이며, 키는
`title`, `updated`(`YYYY-MM-DD` 날짜), `draft`(`true`는 아직 준비되지 않은 페이지)입니다.

빌드 결과 파일은 `docs/sitemap.md`와 `docs/search-index.md`에 설명합니다.

## 기능

기능은 `dockit/features/`의 모듈 하나입니다. 프로그램이 그곳의 모듈을 스스로 찾습니다. 모듈은 `MIGRATIONS`(이름과 SQL 문장의
쌍), 하위 명령을 더하는 `register(commands)`, 명령을 실행하고 실행했는지 돌려주는 `handle(args, store)`를 정의할 수
있습니다. 기능마다 `docs/features/`에 쪽 하나가 있습니다.

로컬 데이터베이스는 `data/dockit.db`입니다. 명령 앞에 `--db FILE`을 붙이거나 환경 변수 `DOCKIT_DB`로 다른 파일을 고릅니다.
파일은 한 번에 프로세스 하나만 씁니다. 두 번째 프로세스는 파일을 잡고 있는 프로세스를 알리는 오류로 멈춥니다. 테스트도 같은
파일을 쓰며 테스트 실행 내내 잡고 있습니다.

## 개발

```bash
python3 -m pytest -q
```
