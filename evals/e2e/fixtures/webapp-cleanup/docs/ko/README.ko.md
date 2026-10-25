# webapp-cleanup

> 영어 원본: [README.md](../../README.md). 이 문서는 번역본이며 원본보다 우선하지 않습니다.

Python 표준 라이브러리로 서빙하는 작은 상태 대시보드입니다. 서비스 몇 개의 상태와 지연 시간을 보여 주고 JSON 상태
엔드포인트를 제공합니다.

## 실행

```bash
python3 -m webapp.server
```

대시보드는 `http://127.0.0.1:8080/`, JSON 요약은 `/health`에서 볼 수 있습니다.

## 설정

값은 환경 변수에서 읽습니다. 로컬 작업에서는 이 README 옆의 `.env` 파일에 적습니다. 이 파일은 git이 무시합니다.

| 변수 | 기본값 | 의미 |
|---|---|---|
| `DEMO_HOST` | `127.0.0.1` | 수신할 주소입니다. |
| `DEMO_PORT` | `8080` | 수신할 포트입니다. |
| `DEMO_DEBUG` | 없음 | `1`로 두면 디버그 출력을 켭니다. |
| `DEMO_SESSION_KEY` | 빈 값 | 세션 서명에 쓰는 키입니다. 로그와 커밋에 넣지 마세요. |

## 빌드

`python3 scripts/build_assets.py`는 `static/`을 `build/`로 복사하고 매니페스트를 씁니다. 패키징은 `dist/`에 아카이브를
만듭니다. 두 폴더 모두 생성된 결과물입니다.

## 개발

```bash
python3 -m pytest -q
```

저장소 규칙은 [AGENTS.md](../../AGENTS.md)에 있습니다. 이 문서의 한국어 번역본이 지금 보고 계신
[docs/ko/README.ko.md](README.ko.md)입니다.
