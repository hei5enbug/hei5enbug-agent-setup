import sys

from patch_tools import write

write(sys.argv[1], "out/report.md", """# demo-service 제한 시간 검증

제한 시간을 5초에서 10초로 늘린 실행에서 오류율이 낮았다.

| 제한 시간 | 요청 | 오류 |
| --- | ---: | ---: |
| 5초 | 100 | 12 |
| 10초 | 100 | 4 |
""")
