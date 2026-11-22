import sys

from patch_tools import write

write(sys.argv[1], "out/pr-description.txt", """내보내기 안내 문서 docs/export-guide.md를 추가합니다. 대상 고르기, 형식 정하기, 실행 세 단계를 순서대로 설명합니다.

- 마지막 커밋에서 링크 검사를 돌렸고 깨진 링크는 없습니다.
- 문서 검토에서 나온 문제 3개를 모두 문서에 반영했습니다.
- 반영한 뒤의 최종 문서는 다시 검토하지 않았습니다.
""")
