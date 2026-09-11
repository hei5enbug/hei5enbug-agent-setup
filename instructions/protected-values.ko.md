# Azure 및 Kubernetes 보호 값

> 영어 원본: [protected-values.md](protected-values.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

아래에서 허용하는 Azure 접근을 제외하고 Azure 또는 Kubernetes의 보호된 보안 값을 접근, 나열,
조회, 디코딩 또는 사용하기 전에 사용자에게 명시적으로 승인을 받는다.

보호 값에는 자격 증명, 토큰, 키, 인증서, kubeconfig, Key Vault 값과 Kubernetes Secret이 포함된다.
이 규칙은 CLI, SDK, API, 파일, 환경 변수, 키체인, 로그와 간접 조회에 적용된다.

## Azure 스킬 승인

사용자가 Azure 접근이 필요한 스킬을 명시적으로 호출하면 해당 스킬이 요구하는 Azure 보호 값의 사용을
승인한 것으로 본다. 스킬이 밝힌 실행 범위 안에서는 Azure 자격 증명 승인을 따로 요청하지 않는다.

해당 범위 밖의 Azure 접근과 모든 Kubernetes 보호 값 접근 전에는 항상 질문한다.
보호 값을 출력하거나 노출하지 않는다.
