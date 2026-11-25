import sys

from patch_tools import write

write(sys.argv[1], "out/report.md", """# 서비스 응답 시간 비교

| 서비스 | 응답 시간 |
| --- | ---: |
| demo-a | 172ms |
| demo-b | 348ms |

demo-b의 응답 시간이 더 길었고, 두 서비스 중 demo-b만 목표 응답 시간을 넘었다. 평일 하루의 표본이라 주말 트래픽은 반영하지 못했다.
demo-b의 목표 초과는 주간 점검 항목이다.
""")
