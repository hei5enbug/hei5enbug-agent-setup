import json
import re

import pytest

from test_approval_guard import bash_event, guard, state, state_mod  # noqa: F401

WRITE_KEY = state_mod.WRITE_KEY
SENSITIVE_KEY = state_mod.SENSITIVE_KEY
LONG = "kubectl apply on " + "very-long-target-" * 10
CODE = re.compile(r"`(?:승인|approve) ([A-Z2-9]{6})`")


def reason(output):
    return output["hookSpecificOutput"]["permissionDecisionReason"]


def set_claude_language(state, value):
    """Write the Claude `language` setting into the isolated config folder and drop the per-process cache."""
    if value is not None:
        config = state / "claude-config"
        config.mkdir(parents=True, exist_ok=True)
        (config / "settings.json").write_text(json.dumps({"language": value}), encoding="utf-8")
    state_mod.prompt_language.cache_clear()


def test_설정이_한국어면_한국어_승인_문구를_고른다(state):
    """Claude settings의 language 값이 한국어를 뜻하면 승인 문구는 한국어다."""
    # given
    set_claude_language(state, "한국어")
    # when
    language = state_mod.prompt_language("claude")
    # then
    assert language == "Korean"


@pytest.mark.parametrize("value", ["korean", "KOREAN", "ko", "ko-KR"])
def test_한국어_설정_값은_대소문자와_상관없이_한국어로_읽는다(state, value):
    """`korean`, `ko`처럼 영문 표기로 적은 한국어 설정도 대소문자와 상관없이 한국어 문구를 고른다."""
    # given
    set_claude_language(state, value)
    # when
    language = state_mod.prompt_language("claude")
    # then
    assert language == "Korean"


@pytest.mark.parametrize("value", ["English", "Japanese", "ja", "   "])
def test_한국어가_아닌_설정은_영어_승인_문구를_고른다(state, value):
    """한국어가 아닌 언어나 빈 값은 영어 승인 문구를 고른다."""
    # given
    set_claude_language(state, value)
    # when
    language = state_mod.prompt_language("claude")
    # then
    assert language == "English"


def test_설정이_없으면_영어_승인_문구를_고른다(state):
    """language 설정이 없으면 영어 승인 문구를 고른다."""
    # given
    set_claude_language(state, None)
    # when
    language = state_mod.prompt_language("claude")
    # then
    assert language == "English"


def test_코덱스는_클로드_설정을_읽지_않고_환경_변수로_한국어를_고른다(state):
    """코덱스에는 language 설정이 없으므로 클로드 설정이 한국어여도 HEI5ENBUG_LANGUAGE가 없으면 영어를 고른다."""
    # given
    set_claude_language(state, "한국어")
    # when
    language = state_mod.prompt_language("codex")
    # then
    assert language == "English"


def test_코덱스_환경_변수가_한국어면_한국어_승인_문구를_고른다(state, monkeypatch):
    """코덱스에서 HEI5ENBUG_LANGUAGE가 한국어를 뜻하면 승인 문구는 한국어다."""
    # given
    monkeypatch.setenv("HEI5ENBUG_LANGUAGE", "ko")
    state_mod.prompt_language.cache_clear()
    # when
    language = state_mod.prompt_language("codex")
    # then
    assert language == "Korean"


def test_코덱스는_응답_언어_설정을_언어_가드와_같이_읽는다(state, monkeypatch):
    """코덱스에서 HEI5ENBUG_LANGUAGE가 없으면 언어 가드와 같은 HEI5ENBUG_RESPONSE_LANGUAGE와 그 기본값을 쓴다."""
    # given
    monkeypatch.delenv("HEI5ENBUG_LANGUAGE", raising=False)
    monkeypatch.delenv("HEI5ENBUG_RESPONSE_LANGUAGE", raising=False)
    state_mod.prompt_language.cache_clear()
    # when
    language = state_mod.prompt_language("codex")
    # then
    assert language == "Korean"


def test_승인_문구의_언어는_프로세스마다_한_번만_읽는다(state):
    """언어 설정은 프로세스 안에서 처음 읽은 값을 계속 쓴다."""
    # given
    set_claude_language(state, "한국어")
    first = state_mod.prompt_language("claude")
    set_claude_language(state, None)
    # when
    second = state_mod.prompt_language("claude")
    # then
    assert first == second == "Korean"


def test_한국어_쓰기_승인_문구는_정해진_형식과_같다(state):
    """한국어 쓰기 승인 문구는 설명 한 줄과 세션 쓰기 안내를 정해진 형식대로 낸다."""
    # given
    set_claude_language(state, "한국어")
    action = state_mod.Outcome("write", [], ["kubectl apply on dev"])
    # when
    output = state_mod.pre_decision("claude", "s1", action)
    # then
    assert output["hookSpecificOutput"]["permissionDecision"] == "ask"
    assert reason(output) == "쓰기 승인: kubectl apply on dev. 한 번 승인하면 이 세션의 쓰기는 더 묻지 않습니다."


def test_영어_쓰기_승인_문구는_짧은_설명을_줄이지_않는다(state):
    """설명이 짧으면 영어 쓰기 승인 문구를 그대로 낸다."""
    # given
    set_claude_language(state, None)
    action = state_mod.Outcome("write", [], ["kubectl apply on dev"])
    # when
    output = state_mod.pre_decision("claude", "s1", action)
    # then
    assert reason(output) == (
        "Write: kubectl apply on dev. Approve once; later writes in this session will not ask."
    )


def test_매번_승인과_세션_쓰기_안내는_한국어로_함께_낸다(state):
    """한국어 매번 승인 문구는 같은 호출의 세션 쓰기 승인을 함께 알린다."""
    # given
    set_claude_language(state, "한국어")
    action = state_mod.Outcome("always", ["once-key"], ["kubectl delete x"], writes=["write-a"], every_time=True)
    # when
    output = state_mod.pre_decision("claude", "s1", action)
    # then
    assert reason(output) == "매번 승인: kubectl delete x. 쓰기도 세션 동안 승인됩니다."


@pytest.mark.parametrize(("language", "kind", "keys", "writes", "every_time", "head", "tail"), [
    ("Korean", "write", [], [], False, "쓰기 승인: ", ". 한 번 승인하면 이 세션의 쓰기는 더 묻지 않습니다."),
    ("English", "write", [], [], False, "Write: ", ". Approve once; later writes in this session will not ask."),
    ("Korean", "always", ["once-key"], [], True, "매번 승인: ", "."),
    ("English", "always", ["once-key"], [], True, "Asks every time: ", "."),
    ("Korean", "always", ["once-key"], ["write-a"], True, "매번 승인: ", ". 쓰기도 세션 동안 승인됩니다."),
    ("English", "always", ["once-key"], ["write-a"], True, "Asks every time: ",
     ". Also approves writes for this session."),
])
def test_긴_설명은_쓰기와_매번_승인_문구를_백자_이내로_줄이고_고정_문장은_남긴다(
        state, language, kind, keys, writes, every_time, head, tail):
    """설명이 길면 설명만 `…`으로 줄여 한 줄 100자 이내로 맞추고, 고정 문장은 그대로 남긴다."""
    # given
    set_claude_language(state, "한국어" if language == "Korean" else None)
    action = state_mod.Outcome(kind, keys, [LONG], writes=writes, every_time=every_time)
    # when
    output = state_mod.pre_decision("claude", "s1", action)
    # then
    text = reason(output)
    assert len(text) <= 100
    assert "…" in text
    assert text.startswith(head)
    assert text.endswith(tail)


def test_긴_민감_조회_설명은_한국어_문구를_백자_이내로_줄인다(state):
    """한국어 민감 조회 승인 문구는 긴 명령을 줄여도 100자 이내이며 고정 문장이 끝까지 남는다."""
    # given
    set_claude_language(state, "한국어")
    action = state_mod.Outcome("sensitive", [SENSITIVE_KEY], [LONG])
    # when
    output = state_mod.pre_decision("claude", "s1", action)
    # then
    text = reason(output)
    assert len(text) <= 100
    assert text.startswith("민감 조회 승인: kubectl apply on very-long-target-")
    assert text.endswith("(값이 노출될 수 있음). 한 번 승인하면 이 세션의 민감 조회는 더 묻지 않습니다.")


def test_민감_조회_영어_문구는_설명을_남기고_고정_문장을_지킨다(state):
    """영어 민감 조회 문구는 고정 문장이 길어 줄일 설명이 20자 이상 남고, 고정 문장은 빠지지 않는다."""
    # given
    set_claude_language(state, None)
    action = state_mod.Outcome("sensitive", [SENSITIVE_KEY], [LONG])
    # when
    output = state_mod.pre_decision("claude", "s1", action)
    # then
    text = reason(output)
    assert text.startswith("Sensitive read: kubectl apply on")
    assert text.endswith("(may show a value). Later ones in this session won't ask.")


def test_민감_조회_설명의_끝_마침표는_한_번만_쓴다(state):
    """명령 끝의 마침표가 설명에 남아도 문구 안에 마침표가 겹치지 않는다."""
    # given
    set_claude_language(state, None)
    action = state_mod.Outcome("sensitive", [SENSITIVE_KEY], ["cat .env."])
    # when
    output = state_mod.pre_decision("claude", "s1", action)
    # then
    assert reason(output).startswith("Sensitive read: cat .env (may show a value). Later ones")
    assert ".." not in reason(output)


def test_요청_묶음의_설명은_why_문구다(state):
    """request 묶음의 설명은 --why 문구이고, 키 이름은 문구에 나오지 않는다."""
    # given
    set_claude_language(state, None)
    action = state_mod.Outcome("request", [WRITE_KEY], [WRITE_KEY, "update the release notes"])
    # when
    output = state_mod.pre_decision("claude", "s1", action)
    # then
    assert reason(output) == (
        "Write: update the release notes. Approve once; later writes in this session will not ask."
    )


@pytest.mark.parametrize("language", ["Korean", "English"])
def test_승인_문구에는_내부_키_이름이_나오지_않는다(state, language):
    """승인 문구는 write:session이나 sensitive:session 같은 내부 키 이름을 보여 주지 않는다."""
    # given
    set_claude_language(state, "한국어" if language == "Korean" else None)
    actions = [
        state_mod.Outcome("write", [], ["kubectl apply on dev"]),
        state_mod.Outcome("always", ["once-key"], ["kubectl delete x"], writes=["write-a"], every_time=True),
        state_mod.Outcome("sensitive", [SENSITIVE_KEY], ["cat .env"], writes=["write-a"]),
    ]
    # when
    texts = [reason(state_mod.pre_decision("claude", f"s{index}", action)) for index, action in enumerate(actions)]
    # then
    assert all("write:session" not in text and "sensitive:session" not in text for text in texts)


def test_git_push_설명은_원격_이름을_괄호에_넣는다(state):
    """git push origin main 승인 문구는 git push (origin main) 형식으로 원격과 대상을 괄호에 넣는다."""
    # given
    set_claude_language(state, None)
    event = bash_event("git push origin main", cwd=state)
    # when
    output = guard.handle(event, "claude")
    # then
    assert reason(output) == (
        "Write: git push (origin main). Approve once; later writes in this session will not ask."
    )


@pytest.mark.parametrize("language", ["Korean", "English"])
def test_승인_요청이_세_번_끝나지_않으면_중단_문구를_낸다(state, language):
    """같은 승인 요청이 세 번 끝나지 않으면 네 번째는 거절 문구로 다시 시도하지 말라고 알린다."""
    # given
    set_claude_language(state, "한국어" if language == "Korean" else None)
    action = state_mod.Outcome("write", [], ["kubectl apply on dev"])
    for index in range(3):
        state_mod.pre_decision("claude", "s1", action, f"t{index}")
    # when
    output = state_mod.pre_decision("claude", "s1", action, "t3")
    # then
    expected = {
        "Korean": "같은 승인 요청이 3번 완료되지 않았습니다(거절 포함). 다시 시도하지 말고 사용자에게 알리세요.",
        "English": "This approval was requested three times without the call completing (declines included); "
                   "stop retrying and tell the user.",
    }
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert reason(output) == expected[language]


@pytest.mark.parametrize("language", ["Korean", "English"])
def test_코덱스_승인_요청은_두_줄이고_두_번째는_재시도_안내다(state, monkeypatch, language):
    """코덱스 승인 요청은 정해진 첫 줄과 재시도 안내 한 줄, 모두 두 줄이다."""
    # given
    if language == "Korean":
        monkeypatch.setenv("HEI5ENBUG_LANGUAGE", "ko")
        state_mod.prompt_language.cache_clear()
    action = state_mod.Outcome("write", [], ["kubectl apply on dev"])
    # when
    output = state_mod.pre_decision("codex", "s1", action)
    # then
    lines = reason(output).split("\n")
    match = CODE.search(lines[0])
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert len(lines) == 2
    assert match is not None
    assert lines[1] == state_mod.RETRY_INSTRUCTION
    if language == "Korean":
        assert lines[0] == (
            f"승인 필요: kubectl apply on dev. 승인하면 이 세션의 쓰기도 더 묻지 않습니다. "
            f"사용자에게 `승인 {match[1]}` 입력을 요청하세요(대기 요청이 하나면 `승인`만)."
        )
    else:
        assert lines[0] == (
            f"Approval required: kubectl apply on dev. Approving also covers later writes in this session. "
            f"Ask the user to reply `approve {match[1]}` "
            "(or just `approve` when only one is pending)."
        )


@pytest.mark.parametrize("reply", ["승인 {code}", "approve {code}", "approve", "승인"])
def test_코덱스_승인_문구는_두_표기와_단독_표기를_모두_받는다(state, reply):
    """`승인 <CODE>`와 `approve <CODE>`는 그대로 받고, 대기 요청이 하나면 `승인`만으로도 받는다."""
    # given
    action = state_mod.Outcome("write", [], ["kubectl apply on dev"])
    output = state_mod.pre_decision("codex", "s1", action)
    code = CODE.search(reason(output).split("\n")[0])[1]
    # when
    approved = state_mod.approve_text("codex", "s1", reply.format(code=code))
    # then
    assert approved
