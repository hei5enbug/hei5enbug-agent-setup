import sys
from pathlib import Path

repo = Path(sys.argv[1])
text = (repo / "notes" / "wiki-draft.txt").read_text(encoding="utf-8").strip()
CUTS = (
    (" 이 페이지는 그 계획을 운영 관점에서 다시 정리한 것이며, 롤아웃은 5퍼센트에서 100퍼센트까지 네 단계로 진행되고 단계 사이에 30분 이상 간격을 둡니다.", ""),
    ("\n참고로 demo-api는 demo-flag 값을 직접 읽지 않고, 시작할 때 받은 설정 파일만 봅니다.\n", ""),
    ("대상 비율을 0퍼센트로 되돌립니다. 이때도 demo-api 재시작이 필요하다는 점은 같습니다. 문제가 생겼을 때 가장 빠른 방법은 대상 비율을 0퍼센트로 되돌리는 것이며, 그러면 모든 사용자가 이전 결제 화면을 봅니다.",
     "대상 비율을 0퍼센트로 되돌리면 모든 사용자가 이전 결제 화면을 봅니다. 이때도 demo-api 재시작이 필요합니다."),
    ("- 지표는 모두 대시보드 한 화면에서 볼 수 있습니다.\n", ""),
    (" 오류율이 1퍼센트를 넘으면 바로 끕니다.", ""),
    (" 롤아웃 계획(https://example.com/wiki/demo-flag-rollout)과 위키 목차(https://example.com/wiki)도 참고할 수 있습니다. 롤아웃 계획 페이지는 위키 목차에서도 찾을 수 있습니다.", ""),
    ("- 지난 롤아웃에서 재시작을 빠뜨려 한 시간 동안 일부 사용자가 이전 화면을 본 적이 있습니다.\n", ""),
)
for old, new in CUTS:
    if text.count(old) != 1:
        raise SystemExit(f"expected exactly one match for {old[:40]!r}")
    text = text.replace(old, new)
out = repo / "out" / "wiki-page.txt"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(text + "\n", encoding="utf-8")
