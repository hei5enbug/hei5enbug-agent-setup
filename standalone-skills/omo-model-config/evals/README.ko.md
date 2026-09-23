# OmO 소스 fixture와 V22 사례

> 영어 원본: [README.md](README.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다.
> 에이전트 실행 시 읽거나 사용하지 않는다.

[`source-fixture.json`](source-fixture.json)에는 V22에 필요한 upstream 경로와
SHA-256 hash가 기록되어 있다.
모든 항목은 `c18ab758961b88bc07f7578ddcbcb286810a524f` commit에 속한다.
필수 파일은 20개다. 현재 평가 입력의 GPT-5.6/GPT-6 후보와 legacy reasoning 이전에 필요한
조건부 테스트 13개도 포함한다.

upstream 스키마와 구현 코드는 이 저장소에 두지 않는다.
기록된 revision의 로컬 checkout을 사용하고 목록에 있는 파일만 임시 작업 공간에 준비한다.

```bash
OMO_UPSTREAM_CHECKOUT=/path/to/verified/oh-my-openagent
OMO_EVAL_TEMP="$(mktemp -d)"
python3 standalone-skills/omo-model-config/evals/prepare_fixture.py \
  --source-checkout "$OMO_UPSTREAM_CHECKOUT" \
  --output "$OMO_EVAL_TEMP/source"
```

준비 스크립트는 checkout에서 파일을 읽는다. revision과 모든 파일 hash를 확인한 뒤
선택한 파일만 출력 경로에 복사한다.
upstream checkout을 다시 가져오거나 수정하지 않는다. 임시 결과는 저장소 밖에 둔다.
revision이나 hash가 다르면 사례 실행을 중단하고 fixture 소스를 확인한다.
V22를 실행할 때 준비한 source 디렉터리를 읽기 전용 평가 입력으로 제공한다.

평가 prompt는 전체·대상 지정 갱신, 이전 routing 필드 변환, 필수 소스 누락을 다룬다.
SHA 불일치 후 전체 재조회, allowlist에 쓸 모델이 없는 경우와 거부된 외부 동기화도 다룬다.
로컬 JSON 사례는 합성 판단 입력이며 고정된 upstream 소스를 대체하지 않는다.

## 읽기와 쓰기 경로

기준 [`SKILL.md`](../SKILL.md)는 전체 갱신과 대상 지정 갱신 모두에서 필수 파일 20개를 읽는다.
대상 지정은 쓰기 범위를 줄이지만 소스 읽기는 줄이지 않는다. 관련 조건부 테스트,
`available-models.json`과 대상 설정도 읽는다. 기준 스킬은 일괄 조회나 같은 실행 안의
재사용을 요구하지 않으므로 실제 조회 횟수는 호스트에 따라 다르다.

일괄 조회와 재사용 제안은 `SKILL.md`에 622바이트를 더하며(13,595바이트에서 14,217바이트),
필수 읽기 20개는 그대로 유지한다. 도구 호출이 줄 가능성은 있지만
전체·대상 지정 실행을 짝지어 비교한 측정은 없다.
필수 결과를 지키면서 총 도구 호출이 줄고
완료 시간이 늘지 않는다는 native trial 결과가 나올 때까지 런타임 스킬은 기준(B0)에 둔다.

native 대상 모델 trial은 아직 실행하지 않았다.
고정 소스를 사용하는 실시간 동작 trial은 오프라인에서 할 수 없다.
따라서 fixture와 사례를 준비했지만 V22 통과로 계산하지 않는다.
