import sys

from patch_tools import write

write(sys.argv[1], "README.md", """# demo-cli

표준 입력의 CSV에서 완료된 작업을 셉니다. JSON으로 확인하려면 demo-cli --format json을 사용하세요.
""")
