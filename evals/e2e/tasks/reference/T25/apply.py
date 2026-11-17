import sys

from patch_tools import write

write(sys.argv[1], "out/pr-description.txt", """설정 파일을 읽을 때 빈 줄과 # 으로 시작하는 줄을 건너뜁니다. 이전에는 이런 줄이 있으면 파싱이 중단됐습니다.

검증: 최종 커밋에서 `python3 -m pytest -q`가 통과했습니다. 문서 검토에서 나온 문제 3건은 모두 반영했고, 반영한 뒤의 최종 본문은 다시 검토하지 않았습니다.
""")
