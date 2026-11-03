# 공개 정보 유출 검사

> 영어 원본: [public-leak-check.md](../../../../../skills/skill-issue-creator/references/public-leak-check.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

공개 트래커에 올릴 초안에 적용하는 규칙이다. 생성, 수정, 댓글 중 어떤 쓰기든 실행하기 전에 읽는다.

1. 세션에서 드러난 값을 모은다. Git 원격 저장소의 조직명, 티켓 키 접두사, 계정 이름, 내부 호스트, 로컬 경로가 해당한다.
2. 제목과 모든 태그를 포함한 전체 초안에 함께 제공되는 검사를 실행한다. 각 값은 별도의 `--value`로 전달한다.
   스킬의 `SKILL.md`가 있는 디렉터리를 기준으로 스크립트 경로를 구한다.
   로컬 파일을 쓰지 않도록 초안을 표준 입력으로 전달한다.

   ```text
   python3 scripts/scan_draft.py --plugin-root <plugin_root> --value <value> --value <value> <<'EOF'
   <title, tags, and body>
   EOF
   ```

   `{"status", "findings", "private_word_lists", "problems"}`를 출력한다.
   `clean`이면 종료 코드 0, `matches`이면 1, `unavailable`이면 3, 사용법 오류이면 2로 끝난다.
   홈 경로, 비밀 정보 형태, 이메일 주소, 전달한 값과 비공개 단어를 검사한다.
   비공개 단어는 `--plugin-root`의 플러그인(`find_tracker.py`가 출력한 `plugin_root`)이나 설치된 플러그인이
   `public-boundary.json`에 선언했거나 `HEI5ENBUG_PUBLIC_BOUNDARY_WORDS`가 지정한 모든 목록에서 가져온다. 비공개 단어 목록이나 그 안의 항목을 초안이나 어떤 파일에도 복사하지 않는다.
3. `matches`이면 일치한 줄에서 일치한 값을 제거해 고쳐 쓰고 검사를 다시 실행한다.
4. 고쳐 쓴 뒤에도 일치 항목이 남으면 등록하지 않는다.
   초안과 함께 일치한 각 줄과 그 유형을 보여 주고, 어떻게 진행할지 사용자에게 묻는다.
5. `unavailable`이거나 스크립트가 없거나 종료 코드가 2이면 등록하지 않는다.
   초안을 보여 주고 검사를 실행하지 못했다고 알린다.
6. `clean` 이후에만 쓴다.
