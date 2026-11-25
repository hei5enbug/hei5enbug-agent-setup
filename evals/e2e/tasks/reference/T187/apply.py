import sys

from patch_tools import write

write(sys.argv[1], "out/rewrite.md", """# demo-a와 demo-b의 응답 시간 비교

두 서비스는 같은 서버에서 실행됐다.

1차 측정은 617ms였고 재측정은 817ms였다.

재측정 결과는 817ms로 기록했다. 재측정 로그에도 같은 값이 남았다.

회의 안건에는 1차 측정과 재측정을 올렸다.
해당 결과를 다음 회의에서 다시 논의한다.

TTL을 두 배로 늘리면 demo-ttl-v2로 해결할 수 있다는 제안은 아직 검증하지 않았다.
""")
