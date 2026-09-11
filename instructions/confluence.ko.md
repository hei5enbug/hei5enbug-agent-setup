# Confluence 접근 및 작업

> 영어 원본: [confluence.md](confluence.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

Confluence 읽기, 검색, 생성, 수정, 댓글, 첨부 파일 또는 레이블 작업 전에 이 규칙을 적용한다.

## 도구 선택

Atlassian Rovo Confluence 도구 대신 설치된 `confluence-cli`를 사용한다.
타입이 지정된 `confluence` 명령을 우선 사용한다. 필요한 Confluence REST API v2 작업을 수행하는
타입 지정 명령이 없을 때만 `confluence api`를 사용한다.

쓰기 전에 `confluence --help` 또는 `confluence <command> --help`로 문법을 확인한다.
`confluence-cli`를 사용할 수 없으면 다른 연결된 Confluence 도구를 사용하기 전에 제한 사항을 알린다.

문서 콘텐츠를 Confluence 페이지로 가져오거나 게시, 동기화 또는 복구할 때는
[document-to-confluence](../skills/document-to-confluence/SKILL.ko.md)를 사용한다.

## 자격 증명

Confluence 자격 증명을 출력, 기록, 파일에 저장하거나 명령행 인수로 전달하지 않는다.
CLI가 설정된 프로필, 환경 또는 보호된 자격 증명 파일에서 값을 읽게 한다.
자격 증명이 설정되지 않았으면 대화에서 값을 전달하지 않고 사용자가 설정하도록 요청한다.

## 댓글

정확한 렌더링이 중요하면 storage XHTML 또는 Atlassian Document Format(ADF)을 사용한다.
Confluence는 댓글 본문의 Markdown을 해석하지 않는다. 문단, 목록, 제목과 코드 블록을 별도 노드로 유지한다.

사용자 멘션에는 추측한 표시 이름 대신 계정 ID를 사용한다.

```xml
<ac:link><ri:user ri:account-id="ACCOUNT_ID" /></ac:link>
```

댓글을 생성하거나 수정한 뒤 `body-format=view`로 다시 읽는다.
각 멘션이 사용자 링크로 렌더링되고 블록 구조가 유지됐는지 확인한다.
Confluence가 마크업을 다시 작성하므로 전송한 요청만으로 저장된 렌더링을 확인했다고 판단하지 않는다.

## 삭제

댓글을 삭제하거나 해결 처리하기 전과 첨부 파일을 삭제하기 전에 명시적인 승인을 받는다.
각 대상을 식별하고 페이지 본문에서 첨부 파일을 더 이상 참조하지 않는지 확인한 뒤 삭제를 제안한다.
