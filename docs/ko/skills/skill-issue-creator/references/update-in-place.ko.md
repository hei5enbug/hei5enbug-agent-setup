# 기존 이슈 갱신

> 영어 원본: [update-in-place.md](../../../../../skills/skill-issue-creator/references/update-in-place.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

새 이슈를 만드는 대신 기존 이슈를 변경하는 규칙이다.
5단계에서 이슈를 갱신하기 전, 8단계에서 다시 읽기 실패를 수정하기 전, 9단계의 미리 보기 후 이슈를 변경하기 전에 읽는다.

`target.public`이 true이면 아래의 모든 쓰기 전에 새 본문이나 댓글에
[공개 정보 유출 검사](public-leak-check.ko.md)를 실행한다.

## 같은 빈틈을 다루는 열린 이슈

작성자에 따라 결정한다.
GitHub에서는 `gh issue view <number> --repo <location> --json author`의 `author.login`을
`gh api user --jq .login`과 비교한다. 다른 트래커에서는 연결된 도구의 현재 사용자와 비교한다.

- 현재 계정이 작성했다면 본문을 편집한다.
  본문 전체를 읽고 각 문장을 현재 규칙과 대조한다.
  여전히 맞는 내용은 유지하고, 새 관찰 내용, Proposal 규칙, Acceptance criteria를 6단계의 절 순서에 맞춰 합친다.
  GitHub에서는 본문을 표준 입력으로 전달한다.

  ```text
  gh issue edit <number> --repo <location> --body-file - <<'EOF'
  <body>
  EOF
  ```

- 다른 사람이 작성했다면 새 관찰 내용, 규칙, 기준을 댓글로 추가하고 그 사람의 본문은 그대로 둔다.
  GitHub에서는 `gh issue comment <number> --repo <location> --body-file -`를 사용하고 같은 방식으로 텍스트를 표준 입력으로 전달한다.

먼저 질문하지 않는다. `preview_required`가 true일 때 아래의 승인만 사용자를 기다린다. 이후 쓴 내용을 다시 읽고 링크와 무엇을 변경했는지 보고한다. 편집한 본문은 8단계처럼 읽는다.
댓글은 이슈의 댓글에서 읽으며, GitHub에서는
`gh issue view <number> --repo <location> --comments --json comments --jq '.comments[-1]'`로 현재 계정이 썼는지와
텍스트에 원시 마크업이 보이지 않는지 확인한다.

## 다시 읽기 실패 또는 미리 보기 후 변경

이 스킬이 쓴 것만 바꾸고 다시 읽는다. 이 스킬이 만들었거나 현재 계정이 쓴 이슈는 같은 명령으로 본문을 편집한다.
댓글은 그 댓글을 고치며, GitHub에서는 `gh issue comment <number> --repo <location> --edit-last --body-file -`에
텍스트를 표준 입력으로 전달한다. 다른 사람이 쓴 이슈의 본문은 편집하지 않는다.

## 승인

`preview_required`가 true이면 새 본문이나 댓글 문구를 보여 주고, 사용자가 이후 메시지에서 그 내용을 승인한 뒤에만 쓴다.
승인 뒤 내용이 바뀌면 다시 보여 주고 새 승인을 기다린다.
`preview_required`가 false이면 바로 쓴다.

## 다른 트래커

같은 작업에 대해 선언 옵션이 고르는 경로를 사용하며, 선언된 위치에만 쓴다.
