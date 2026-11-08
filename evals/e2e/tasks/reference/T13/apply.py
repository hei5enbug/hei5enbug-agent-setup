import sys

from patch_tools import write

write(sys.argv[1], "out/pr-description.txt", """품목별 재고 현황을 CSV로 내보내는 기능을 추가합니다. 재고가 없는 품목도 한 행으로 나옵니다.

리뷰어가 확인할 점
- 진행 중 주문 수량에는 placed 상태 주문만 들어갑니다. shipped와 cancelled 주문은 제외됩니다.
- 재고 변동 기록이 없는 품목은 마지막 변동 시각이 빈 값입니다.

검증: 전체 테스트가 통과합니다.
""")
