import sys

from patch_tools import write

write(sys.argv[1], "out/report.md", """# 지역별 응답 시간

demo-cache 설정을 반영했다.

| 지역 | 응답 시간 |
| --- | ---: |
| demo-north | 241ms |
| demo-south | 382ms |
""")
