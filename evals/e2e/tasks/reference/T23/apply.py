import sys

from patch_tools import write

write(sys.argv[1], "out/comment-draft.txt", """demo-c 완료 보고드립니다. 스테이징(2026-11-06)에서 아래처럼 확인했습니다.

- 기준 1 (단계별 제한 시간): 캐시가 있는 실행 5회에서 가져오기 최대 41초, 변환 최대 63초, 내보내기 최대 30초로 제한 안에 끝났습니다. 캐시 없는 첫 실행은 가져오기가 95초로 제한을 넘었고, 이 경우는 테스트 test_cold_start_exceeds_limit이 확인합니다.
- 기준 2 (실패한 단계 이름을 로그에 남김): 변환 단계를 일부러 실패시켰더니 로그에 단계 이름 transform이 남았습니다.
""")
