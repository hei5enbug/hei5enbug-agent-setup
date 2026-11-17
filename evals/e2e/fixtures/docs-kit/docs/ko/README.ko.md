# docs-kit

> 영어 원본: [README.md](../../README.md). 이 문서는 번역본이며 원본보다 우선하지 않습니다.

정적 문서 사이트 빌더입니다. `content/`의 Markdown 페이지를 HTML, 사이트맵, 검색 색인으로 바꾸고 방문 횟수를 로컬
데이터베이스에 보관합니다.

## 사용법

```bash
python3 -m dockit build
python3 tools/check_site.py
python3 -m dockit visit guide
python3 -m dockit visits
```

- `build [--out DIR]`은 페이지마다 HTML 파일 하나, `sitemap.xml`, `search-index.json`을 `build/`(또는 `DIR`)에 씁니다.
  폴더를 먼저 비우고, 다른 빌드가 그 폴더를 쓰는 동안에는 실행을 거부합니다. 세 단계는 각각 몇 초가 걸립니다.
- `python3 tools/check_site.py`는 `build/`를 읽어 빌드가 써야 하는데 쓰지 않은 파일을 모두 알려 줍니다.
- `visit SLUG`는 페이지에 방문을 한 번 더합니다. `visits`는 방문 횟수를 한 줄에 `SLUG COUNT`로 출력합니다.

페이지는 선택 사항인 front matter를 가진 Markdown 파일입니다. front matter는 `---` 두 줄 사이의 `key: value` 줄이며, 키는
`title`, `updated`(`YYYY-MM-DD` 날짜), `draft`(`true`는 아직 준비되지 않은 페이지)입니다.

사이트맵에는 모든 페이지가 들어갑니다.
검색 색인에는 모든 페이지의 URL과 제목이 들어갑니다.

로컬 데이터베이스는 `data/dockit.db`입니다. 명령 앞에 `--db FILE`을 붙이거나 환경 변수 `DOCKIT_DB`로 다른 파일을 고릅니다.
파일은 한 번에 프로세스 하나만 씁니다. 두 번째 프로세스는 파일을 잡고 있는 프로세스를 알리는 오류로 멈춥니다. 테스트도 같은
파일을 쓰며 테스트 실행 내내 잡고 있습니다.

## 개발

```bash
python3 -m pytest -q
```
