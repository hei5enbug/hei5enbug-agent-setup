import sys

from patch_tools import write

write(sys.argv[1], "out/chat-message.txt", """내보내기 안내 문서 검토가 끝났습니다. demo-model-x가 검토해 문제 3개를 찾았고 모두 반영했습니다. 반영한 뒤의 최종 문서는 다시 검토하지 않았습니다.
""")
