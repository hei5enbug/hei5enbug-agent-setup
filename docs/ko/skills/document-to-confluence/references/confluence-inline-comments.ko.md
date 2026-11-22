# Confluence 본문의 인라인 댓글 마커

> 영어 원본: [confluence-inline-comments.md](../../../../../skills/document-to-confluence/references/confluence-inline-comments.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

## 인라인 댓글 마커

**2026-10-16 storage 형식에서 관찰됨.** 인라인 댓글은 페이지 본문에서 선택한 텍스트를 감싸는
`ac:inline-comment-marker` 요소로 고정된다.

```xml
<ac:inline-comment-marker ac:ref="MARKER_REF">selected text</ac:inline-comment-marker>
```

본문에 댓글 마커가 없는 상태로 저장하면 댓글에 앵커가 남지 않고 페이지에는 삭제된 콘텐츠로 표시된다. 원본에서
다시 만든 본문에는 마커를 다시 넣기 전까지 마커가 없다.

HTML 본문은 마커를 유지하지 않는다. 마커가 있는 페이지는 storage 형식으로 쓰고, 이전에 저장된 본문을 보관한다.

다시 게시할 때마다:

1. 페이지의 인라인 댓글을 열림 또는 해결됨 상태와 관계없이 나열하고, 각 마커 참조와 원래 선택 영역을 적는다.
2. 검증한 HTML 본문을 `scripts/storage_body.py`로 변환한다. 이전에 저장된 본문과 변환한 본문으로
   `scripts/comment_markers.py restore`를 실행해 마커를 복원한다.
3. 복원기가 0이 아닌 코드로 끝나면 해결되지 않은 각 참조를 이전 문맥과 함께 나열하고 본문을 쓰지 않는다.
   같은 의미를 전달하는 새 텍스트를 골라 `--anchor`나 `--anchors`로 다시 실행하고 이동을 보고한다. 그 의미를 전달하는
   텍스트가 없으면 저장 전에 사용자에게 묻는다.
4. 나열한 모든 참조를 담은 본문만 저장한다.
5. 저장 뒤 이전 본문과 저장된 본문에 `scripts/comment_markers.py check`를 실행한다. 빠진 참조를 모두 고치고 다시
   저장한다. 각 댓글이 여전히 앵커를 보고하는지 확인하고, 브라우저를 사용할 수 있으면 렌더링된 페이지에서 삭제된
   콘텐츠 알림을 확인한다.
