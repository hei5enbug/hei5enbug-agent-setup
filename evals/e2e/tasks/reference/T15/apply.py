import sys

from patch_tools import write

write(sys.argv[1], "out/issue-body.txt", """설정 화면의 도움말 아이콘이 404 페이지로 연결됩니다.

재현: 설정 화면에서 오른쪽 위 도움말 아이콘을 누릅니다.
현재: https://example.com/old-guide 로 연결되어 404가 뜹니다.
기대: 새 가이드(https://example.com/guide)가 열립니다.
영향: 신규 사용자가 설정 방법을 찾지 못해 문의가 늘고 있습니다.
""")
