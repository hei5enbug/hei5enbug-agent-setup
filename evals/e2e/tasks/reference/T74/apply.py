import sys

from patch_tools import append, write

repo = sys.argv[1]

write(repo, 'README.md', '# plugin-host\n\nBuilds the session context of a fictional plugin host and reads its options from `plugin.json`.\n\n## Documentation map\n\n| Document | Purpose |\n|---|---|\n| [docs/configuration.md](docs/configuration.md) | The options and their values. |\n| [instructions/routing.md](instructions/routing.md) | How the delivery mode changes what a session does. |\n| [instructions/asking.md](instructions/asking.md) | How a session asks the user a question. |\n\nRun the tests with `python3 -m pytest -q`.\n')
write(repo, 'docs/ko/README.ko.md', '# plugin-host\n\n> 영어 원본: [README.md](../../README.md)\n> 이 문서는 비권위 한국어 번역본이다.\n\n가상의 플러그인 호스트의 세션 컨텍스트를 만들고 `plugin.json`에서 옵션을 읽는다.\n\n## 문서 지도\n\n| 문서 | 목적 |\n|---|---|\n| [docs/configuration.md](docs/ko/docs/configuration.ko.md) | 옵션과 값. |\n| [instructions/routing.md](docs/ko/instructions/routing.ko.md) | 배포 방식이 세션의 동작을 바꾸는 방법. |\n| [instructions/asking.md](docs/ko/instructions/asking.ko.md) | 세션이 사용자에게 묻는 방법. |\n\n테스트는 `python3 -m pytest -q`로 실행한다.\n')
write(repo, 'docs/ko/instructions/asking.ko.md', '# 사용자에게 묻기\n\n> 영어 원본: [asking.md](../../../instructions/asking.md)\n> 이 문서는 비권위 한국어 번역본이며 실행 중에는 읽지 않는다.\n\n- 질문은 한 번에 하나만 하고, 첫 문장에 그 질문이 막고 있는 결정을 쓴다.\n- 선택지는 두세 개를 주고 추천안을 맨 앞에 두며, 추천 이유를 한 절로 쓴다.\n- 이 대화에서 사용자가 보지 못한 용어, 약어, 이름표는 풀어 쓴다.\n- 코드, 스키마, 기존 합의가 이미 정한 것은 묻지 말고 그 근거를 밝힌다.\n- 답을 받으면 결정을 한 줄로 다시 적고, 같은 질문을 다시 하지 않고 이어 간다.\n- 계속하는 데 답이 필요 없으면 가정을 기록하고 진행한다.\n- 범위 안의 되돌릴 수 있는 로컬 단계는 묻지 않는다.\n- 사용자가 답하지 않으면 그 답에 기대지 않는 일만 계속한다.\n- 결정에 대한 질문에 관련 없는 승인을 함께 묶지 않는다.\n')
write(repo, 'instructions/asking.md', '# Asking the user\n\n- Ask one question at a time, with the decision it blocks in the first sentence.\n- Give two or three options, put the recommended one first, and say why it is recommended in one clause.\n- Spell out any term, abbreviation, or label the user has not seen in this conversation.\n- Never ask what the code, the schema, or an existing agreement already settles; state the basis instead.\n- After the answer, repeat the decision in one line and continue without asking it again.\n- When no answer is needed to continue, record the assumption and go on.\n- Ask nothing about a reversible local step that is in scope.\n- If the user does not answer, continue only with work that does not depend on the answer.\n- Never bundle an unrelated approval into a question about a decision.\n')
write(repo, 'instructions/session/common.md', '# Common\n\n- Report what the reader must act on first.\n- Keep answers short and in the language the user writes.\n- Before asking the user a question, read asking.md.\n')

append(repo, "tests/test_context.py", '''

def test_the_asking_rules_are_read_from_a_reference():
    text = render_context(ROOT, {})
    assert "read asking.md" in text
    assert "Ask one question at a time" not in text
''')
