# Confluence 본문의 이미지

> 영어 원본: [confluence-images.md](../../../../../skills/document-to-confluence/references/confluence-images.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

## 이미지

### 일반 img 요소 사용

**Verified.** 인라인 이미지를 배치하는 신뢰할 수 있는 방식이다.

```html
<p><img src="/wiki/download/attachments/PAGE_ID/FILENAME" alt="..." width="900" height="225"></p>
```

변환기는 이를 같은 너비 메타데이터를 가진 자체 figure 노드로 다시 작성한다. 그 노드를 직접 작성하지 않는다.

### 캡션이 있는 이미지

**Observed on 2026-11-03.** 연결된 Confluence 페이지 도구로 외부 이미지 URL을 쓴 이 figure를 보내자
`<ac:caption><p>CAPTION</p></ac:caption>`을 담은 `ac:image`로 저장됐다. `data-type="media-single"`이 없는 같은
figure는 거부됐다. 이 형식에 첨부 파일 다운로드 URL을 쓰는 경우는 시험하지 않았다.

```html
<figure data-type="media-single" data-layout="center"><img src="/wiki/download/attachments/PAGE_ID/FILENAME" alt="..." width="900" height="225"><figcaption>CAPTION</figcaption></figure>
```

storage 형식으로 쓸 때는 `scripts/storage_body.py`가 이 figure를 변환한다.

### 직접 작성한 media-single 거부

**Verified.** `data-type="media-single"`을 가진 `div`를 보내면 지원되지 않는 data-type 오류로 요청이 실패한다.
저장된 콘텐츠에서는 유효한 노드지만 HTML 변환기 입력으로는 허용되지 않는다.

### media-group은 카드로 렌더링

**Verified.** `data-type="media-group"`은 인라인 이미지가 아니라 첨부 파일 카드를 만든다.
요청은 성공하지만 문단이나 표 안 그림에는 잘못된 노드이며 오류가 표시되지 않고 페이지 모양만 잘못된다.

### 표 셀 안 이미지

**Verified.** 표 셀 안의 `img`는 정상적으로 변환되고 셀 안에 남는다.

```html
<td><p><img src="/wiki/download/attachments/PAGE_ID/before.jpg" alt="before" width="200" height="139"></p></td>
```

그림을 넣기 위해 표를 열 레이아웃으로 바꾸지 않는다. 필요하지 않은 이유로 문서 구조가 달라진다.

### 너비와 높이 지정

**Convention.** 파일에서 두 수치를 읽고 함께 비례 조정한다. 실제 비율과 다른 `img`는 늘어나 보인다.

크기를 줄일 수는 있지만 키우지 않는다. 파일 픽셀 너비보다 큰 표시 너비는 이미지를 흐리게 하므로
더 높은 해상도로 렌더링한다.

페이지 너비가 바뀌면 모든 표시 너비를 다시 검토한다. 좁은 페이지용 다이어그램은 넓은 페이지의 공간을
낭비하고 작은 이미지를 늘리면 읽기 어려워진다.

`scripts/image_size.py`가 계산한다. 반환된 `display_width`, `display_height`를 요소에 쓰고, 실제 파일 크기인
`width`, `height`는 비율 확인에만 사용한다. `clamped: true`면 요청 너비가 파일보다 커서 파일 너비로 줄었다.

### 식별자로 참조

**Verified.** 다운로드 URL 대신 식별자로 미디어 노드를 참조하려면 UUID인 미디어 파일 ID를 사용한다.
숫자 앞에 `att`가 붙은 첨부 파일 ID는 다른 값이다.

미디어 파일 ID 자리에 첨부 파일 ID를 전달해도 실패하지 않는다. Confluence가 식별자 문자열을 이름으로 한
빈 첨부 파일을 만들고 독자는 깨진 미리 보기를 본다. 삭제하려면 사용자 승인이 필요하다.

다운로드 URL은 이 문제를 피하므로 위 `img` 형식을 기본으로 사용한다.

### storage 형식 이미지

**Observed.** storage 형식에서 이미지의 다운로드 URL을 외부 미디어 노드로 참조한 본문은 오류 없이 저장됐다.
다음 버전은 이를 `<ac:image ac:width="WIDTH"><ri:attachment ri:filename="FILENAME" /></ac:image>`로 바꿨고,
그 버전 메시지는 렌더링이 정상화됐다고 보고했다. 이전 화면은 직접 확인하지 않았다.
