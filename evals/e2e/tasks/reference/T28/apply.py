import sys

from patch_tools import write

write(sys.argv[1], "out/chat-message.txt", """내일 10시에 가져오기 서버를 재시작합니다. 약 5분 동안 가져오기가 멈춥니다. 설정 변경은 demo-model-x가 검토했고 문제는 없었습니다.
""")
