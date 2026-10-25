# 테스트 실행

> 영어 원본: [docs/testing.md](../../../docs/testing.md). 이 문서는 번역본이며 원본보다 우선하지 않습니다.

테스트는 `SAMPLE_DATA_DIR` 환경 변수가 가리키는 디렉터리에서 샘플 CSV 파일을 읽습니다. 이 변수가 없으면 모든 테스트가
준비 단계에서 이 문서를 가리키는 오류와 함께 멈춥니다.

```bash
export SAMPLE_DATA_DIR=testdata
python3 -m pytest -q
```

저장소의 `testdata/`에는 3월 샘플 분개와 거래 내역이 들어 있습니다. 테스트를 통과시키려고 이 파일들을 고치지 마세요.
기대하는 입력을 설명하는 파일입니다.
