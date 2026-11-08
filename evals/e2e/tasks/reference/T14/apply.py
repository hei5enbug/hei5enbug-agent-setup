import sys

from patch_tools import write

write(sys.argv[1], "out/review-reply.txt", """확인과 증가가 하나의 단계로 실행돼야 하기 때문입니다. 확인을 lock 밖에 두면 두 요청이 동시에 `_used < _limit`을 보고 둘 다 통과해서 하루 한도를 넘길 수 있습니다.
""")
