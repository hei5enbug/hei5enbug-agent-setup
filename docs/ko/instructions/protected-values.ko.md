# 보호 값

> 영어 원본: [protected-values.md](../../../instructions/protected-values.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

보호 값에는 자격 증명, 토큰, 키, 인증서, kubeconfig, Key Vault 값, Kubernetes Secret, 클라우드 비밀 관리자 값,
암호가 든 연결 문자열이 포함된다. 이런 값은 CLI, SDK, API, 파일, 환경 변수, 키체인, 로그 어디에서 나오든
보호 값이다.

- 보호 값을 출력, 디코딩, 기록하거나, 읽는 파일에 복사하거나, 다른 방식으로 드러내지 않는다.
- 사용자에게 보호 값을 붙여 넣으라고 요청하지 않는다.
- 보호 값은 여기서 설명하는 헬퍼를 통해서만 사용한다.
- kubeconfig를 쓰는 `kubectl`이나 로그인한 `az`처럼 CLI가 자기 자격 증명을 스스로 읽는 것은 보호 값 사용이 아니므로
  그대로 실행한다. 헬퍼는 명령에 필요한 값을 직접 읽어야 할 때만 쓴다.

## 헬퍼 사용

헬퍼를 통해 명령을 실행한다. `<Source directory>`는 세션 컨텍스트의 그 줄이다.

```text
python3 <Source directory>/scripts/secret_exec.py (--secret VAR=SOURCE | --file VAR=SOURCE)... [--timeout N] -- COMMAND [ARG...]
```

- `--secret VAR=SOURCE`는 환경 변수 `VAR`를 값으로 설정한다.
- `--file VAR=SOURCE`는 값을 임시 파일에 쓰고 `VAR`를 그 경로로 설정한다. 헬퍼는 종료할 때 이 파일을 지운다.
- 헬퍼는 명령의 stdout과 stderr에 나온 값을 가린다. 명령은 셸 없이 실행하므로, 셸이 필요하면 `sh -c '...'`를 명시한다.

| 소스 | 값 |
|---|---|
| `k8s:[<context>/]<namespace>/<secret>/<key>` | Kubernetes Secret의 키 |
| `keyvault:<vault>/<name>` | Azure Key Vault 비밀 |
| `aws:<secret id>[#<json key>]` | AWS Secrets Manager 비밀, 또는 그 JSON의 문자열 필드 하나 |
| `gcp:<project>/<name>[/<version>]` | Google Cloud Secret Manager 버전. 기본값은 `latest`다 |

예시:

```text
python3 <Source directory>/scripts/secret_exec.py --secret API_TOKEN=aws:prod/app#api_token -- sh -c 'curl -H "Authorization: Bearer $API_TOKEN" https://api.example.com/v1/me'
```

헬퍼 사용에는 별도 승인이 필요 없다. 헬퍼가 실행하는 명령은 일반 읽기와 쓰기 승인 규칙을 따른다.
보호 값을 출력하는 명령은 별도 가드가 막는다.

## Azure 스킬 접근

사용자가 Azure 접근이 필요한 스킬을 명시적으로 호출하면, 그 호출은 스킬이 밝힌 실행 범위에 필요한 Azure 접근을
승인한 것이다. 그 범위 안에서는 Azure 자격 증명 승인을 따로 요청하지 않는다.
그 접근에 필요한 보호 값은 모두 헬퍼를 통해 사용한다.
