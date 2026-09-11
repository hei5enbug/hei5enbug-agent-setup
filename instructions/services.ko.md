# 호스팅 서비스 접근

> 영어 원본: [services.md](services.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

Google Drive, Docs, Slides, Sheets, Atlassian, Azure DevOps, Figma, Slack, Notion과 다른 호스팅
콘텐츠에는 해당 서비스의 MCP 도구로 접근한다. 익명 요청에는 사용자 세션이 없으므로 비공개 링크는
HTTP 401로 실패할 수 있다. 실제 공개 페이지이거나 해당 호스트를 다루는 MCP 서버가 없을 때만 직접 가져온다.

## Confluence 예외

Confluence 페이지, 검색, 생성, 수정, 댓글, 첨부 파일 또는 레이블 작업의 도구를 선택하기 전에
[Confluence 접근 및 작업](confluence.ko.md)을 읽고 따른다.
