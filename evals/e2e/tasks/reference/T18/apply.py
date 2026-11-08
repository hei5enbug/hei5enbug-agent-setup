import sys

from patch_tools import write

write(sys.argv[1], "out/chat-message.txt", """[v1.4 배포 안내]

내일 10시에 v1.4를 배포합니다. 배포 중 약 5분 동안 로그인이 되지 않습니다.

| 항목 | 변경 | 효과 |
|---|---|---|
| 알림 | 재시도 3회로 확대 | 일시 장애 때 누락 감소 |
| 보고서 | CSV 내보내기 추가 | 운영팀 수작업 감소 |
| 로그인 | 세션 만료 30분 → 60분 | 재로그인 횟수 감소 |

문의는 #demo-ops 채널로 남겨 주세요.
""")
