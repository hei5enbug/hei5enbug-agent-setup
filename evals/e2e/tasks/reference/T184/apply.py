import sys

from patch_tools import write

write(sys.argv[1], "out/pr.txt", """홈 화면에 demo-banner 안내 띠를 추가합니다. 설정에서 띠를 끌 수 있습니다.
""")
