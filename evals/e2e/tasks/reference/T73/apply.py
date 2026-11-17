import sys

from patch_tools import append, write

repo = sys.argv[1]

write(repo, 'docs/configuration.md', "# Configuration\n\nSet options in `plugin.json` or with the host's settings screen.\n\n| Option | Values | Default |\n|---|---|---|\n| `delivery` | `auto`, `strict`, or `manual` | `auto` |\n\nThe delivery mode is reported in the session context as `Delivery: <label>.` An unset or unknown value uses `auto`.\n")
write(repo, 'docs/ko/docs/configuration.ko.md', '# 설정\n\n> 영어 원본: [configuration.md](../../../docs/configuration.md)\n> 이 문서는 비권위 한국어 번역본이다.\n\n옵션은 `plugin.json`이나 호스트의 설정 화면에서 정한다.\n\n| 옵션 | 값 | 기본값 |\n|---|---|---|\n| `delivery` | `auto`, `strict` 또는 `manual` | `auto` |\n\n배포 방식은 세션 컨텍스트에 `Delivery: <label>.` 줄로 나타난다. 값이 없거나 알 수 없으면 `auto`를 쓴다.\n')
write(repo, 'docs/ko/instructions/routing.ko.md', '# 라우팅\n\n> 영어 원본: [routing.md](../../../instructions/routing.md)\n> 이 문서는 비권위 한국어 번역본이다.\n\n배포 방식은 세션이 변경을 배포하는 방법을 정한다.\n\n- `auto`: 세션이 변경마다 배포 방법을 고르고 묻지 않고 진행한다.\n- `strict`: 배포가 실패하면 세션이 멈추고 원인을 보고하며, 다른 방법으로 바꾸지 않는다.\n- `manual`: 세션이 변경을 배포하기 전에 묻고 답을 기다린다.\n\n알 수 없는 값은 `auto`로 처리한다.\n')
write(repo, 'instructions/routing.md', '# Routing\n\nThe delivery mode decides how a session delivers a change.\n\n- `auto`: the session picks the delivery per change and goes on without asking.\n- `strict`: when a delivery fails, the session stops and reports the cause, and never switches to another way.\n- `manual`: the session asks before it delivers a change and waits for the answer.\n\nAn unknown value uses `auto`.\n')

append(repo, "tests/test_context.py", '''

def test_strict_is_named_in_the_context():
    assert "Delivery: Strict (`strict`)." in render_context(ROOT, {"HOST_OPTION_DELIVERY": "strict"})
''')
