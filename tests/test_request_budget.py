"""요청 예산 항목 2: 요청마다의 개수, 한도, 공유 저장소."""
import json
import os
import sys
import threading
from datetime import date
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import request_budget as budget  # noqa: E402
import request_distribution as dist  # noqa: E402

ME = ("claude", "session-me")
OTHER = ("claude", "session-other")
THIRD = ("claude", "session-third")
BIG = 1000


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    for name in ("HEI5ENBUG_PARENT_SESSION", "PLUGIN_ROOT", "CLAUDE_PLUGIN_OPTION_REQUEST_RUN_CAP",
                 "CLAUDE_PLUGIN_OPTION_REQUEST_RETRY_CAP"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(budget, "DISTRIBUTION_PATH", tmp_path / "distribution.json")
    write_distribution(tmp_path, 33, 4)


def write_distribution(tmp_path, largest_runs, largest_retries):
    record = {"requests_with_delegated_run": 1, "largest_runs": largest_runs, "largest_retries": largest_retries}
    (tmp_path / "distribution.json").write_text(json.dumps(dist.default_caps(record)), encoding="utf-8")


def set_caps(monkeypatch, runs=None, retries=None):
    if runs is not None:
        monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_REQUEST_RUN_CAP", str(runs))
    if retries is not None:
        monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_REQUEST_RETRY_CAP", str(retries))


def start(who, name, kind="agent", **options):
    options.setdefault("limit", BIG)
    return budget.admit(who, kind, name, pid=os.getpid(), **options)


def test_열_번째_실행은_허용하고_열한_번째는_멈춤_메시지와_함께_거부한다(monkeypatch):
    """실행 한도 10에서 열 번째까지 허용하고 열한 번째는 한도, 개수, 마저 끝나도 됨, 중단 보고를 담아 거부한다."""
    # given
    set_caps(monkeypatch, runs=10)
    allowed = [start(ME, f"n{number}") for number in range(10)]

    # when
    denial = start(ME, "n10")

    # then
    assert allowed == [None] * 10
    assert denial.startswith(budget.CAP_MARKER)
    for part in ("10", "request_run_cap", "may finish", "stopped", "never as done"):
        assert part in denial
    assert budget.counts(ME)["runs"] == 10


def test_플러그인_에이전트_시작과_role_runner_실행은_한_개수에_더해진다(monkeypatch):
    """에이전트 유형과 role:역할 두 종류의 시작이 같은 요청의 한 개수를 올리고 한도 3에서 넷째를 거부한다."""
    # given
    set_caps(monkeypatch, runs=3)

    # when
    results = [start(ME, "a", "hei5enbug-agent-setup:scout"), start(ME, "b", "role:scout")]
    counted = budget.counts(ME)["runs"]
    results += [start(ME, "c", "role:worker"), start(ME, "d", "role:worker")]

    # then
    assert counted == 2
    assert results[:3] == [None, None, None] and results[3] is not None


def test_role_runner_자식이_시작한_실행은_프롬프트를_받은_세션의_개수에_더해진다(monkeypatch):
    """HEI5ENBUG_PARENT_SESSION 이 있으면 자식의 시작도 부모 세션의 개수로 들어가 한도 2를 함께 채운다."""
    # given
    set_caps(monkeypatch, runs=2)
    monkeypatch.setenv("HEI5ENBUG_PARENT_SESSION", "claude:session-me")

    # when
    child = budget.identity("child-own-session")
    first = start(child, "child-run")
    monkeypatch.delenv("HEI5ENBUG_PARENT_SESSION")
    after_child = budget.counts(ME)["runs"]
    second = start(budget.identity("session-me"), "own-run")
    third = start(ME, "third")

    # then
    assert child == ME and first is None and after_child == 1
    assert second is None and third is not None


def test_다음_프롬프트_뒤에는_개수가_0이다(monkeypatch):
    """프롬프트가 요청을 새로 시작하면 한도에 닿았던 세션도 다시 시작할 수 있다."""
    # given
    set_caps(monkeypatch, runs=1)
    start(ME, "a")
    denied = start(ME, "b")

    # when
    budget.reset(ME)
    again = start(ME, "c")

    # then
    assert denied is not None and again is None
    assert budget.counts(ME) == {"runs": 1, "retries": 0, "last": {"agent": "running"}}


def test_한도_바로_아래에서_동시에_온_두_시작은_정확히_하나만_통과한다(monkeypatch):
    """실행 9개 뒤 한도 10에서 두 스레드가 동시에 시작하면 하나만 허용하고 개수는 10이다."""
    # given
    set_caps(monkeypatch, runs=10)
    for number in range(9):
        start(ME, f"n{number}")
    results, gate = [], threading.Barrier(2)

    def attempt(name):
        gate.wait()
        results.append(start(ME, name))

    threads = [threading.Thread(target=attempt, args=(f"race-{index}",)) for index in range(2)]

    # when
    [thread.start() for thread in threads]
    [thread.join() for thread in threads]

    # then
    assert sorted(result is None for result in results) == [False, True]
    assert budget.counts(ME)["runs"] == 10


def test_한도_0은_아무것도_거부하지_않는다(monkeypatch):
    """두 한도가 0이면 오류로 끝난 시작을 육십 번 되풀이해도 거부하지 않는다."""
    # given
    set_caps(monkeypatch, runs=0, retries=0)

    # when
    results = []
    for number in range(60):
        results.append(start(ME, f"z{number}"))
        budget.finish(ME, "agent", f"z{number}", ok=False)

    # then
    assert results == [None] * 60
    assert start(ME, "last") is None


def test_위임_실행이_없는_기록은_두_한도를_0으로_둔다(tmp_path):
    """위임 실행이 있는 요청이 없는 기록은 기본 한도 0을 주고 cap 은 0이다."""
    # given
    record = dist.distribution([{"runs": 0, "retries": 0}], date(2026, 11, 16))
    (tmp_path / "distribution.json").write_text(json.dumps(record), encoding="utf-8")

    # when
    defaults = budget.default_caps()

    # then
    assert defaults == {budget.RUN_CAP_KEY: 0, budget.RETRY_CAP_KEY: 0}
    assert budget.cap(budget.RUN_CAP_KEY) == 0


def test_가장_큰_개수_30은_실행_한도_40을_준다(tmp_path):
    """가장 큰 실행 수 30, 재시도 수 2인 기록은 기본 한도 40과 3을 주고 옵션이 없으면 그 값을 쓴다."""
    # given
    write_distribution(tmp_path, 30, 2)

    # when
    defaults = budget.default_caps()

    # then
    assert defaults == {budget.RUN_CAP_KEY: 40, budget.RETRY_CAP_KEY: 3}
    assert budget.cap(budget.RUN_CAP_KEY) == 40


def test_끄는_값과_잘못된_값(monkeypatch):
    """off, no, 0 은 0이고 숫자는 그 값이며 잘못된 값이나 빈 값은 기본값 40이다."""
    # given
    cases = (("off", 0), ("no", 0), ("0", 0), ("7", 7), ("many", 40), ("", 40))

    # when
    results = []
    for value, _ in cases:
        monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_REQUEST_RUN_CAP", value)
        results.append(budget.cap(budget.RUN_CAP_KEY))

    # then
    assert results == [expected for _, expected in cases]


def test_오류_뒤에는_재시도_한도에서_시작이_멈춘다(monkeypatch):
    """재시도 한도 2에서 오류로 끝난 시작을 두 번 되풀이한 뒤 넷째 시작은 한도 메시지로 거부된다."""
    # given
    set_caps(monkeypatch, runs=0, retries=2)
    for number in range(3):
        assert start(ME, f"r{number}") is None
        budget.finish(ME, "agent", f"r{number}", ok=False)

    # when
    denial = start(ME, "r3")

    # then
    assert denial.startswith(budget.CAP_MARKER) and "request_retry_cap" in denial
    assert budget.counts(ME)["retries"] == 2


def test_성공_뒤의_시작은_재시도가_아니다(monkeypatch):
    """성공으로 끝난 시작 뒤의 같은 유형 시작은 재시도 수를 올리지 않는다."""
    # given
    set_caps(monkeypatch, runs=0, retries=1)

    # when
    for number in range(4):
        assert start(ME, f"s{number}") is None
        budget.finish(ME, "agent", f"s{number}", ok=True)

    # then
    assert budget.counts(ME)["retries"] == 0


def test_병렬_한도는_이_세션의_다음_시작을_자기_실행이_끝날_때까지_거부한다(monkeypatch):
    """한도 1에서 같은 세션의 둘째 시작은 기다리라는 메시지로 거부되고 개수는 오르지 않으며, 다른 세션의 첫 시작은 허용된다."""
    # given
    set_caps(monkeypatch, runs=0, retries=0)
    first = start(ME, "a", limit=1)

    # when
    denial = start(ME, "b", limit=1)
    other = start(OTHER, "c", limit=1)

    # then
    assert first is None and other is None
    assert denial.startswith(budget.LIMIT_MARKER) and "Do not poll" in denial
    assert budget.counts(ME)["runs"] == 1


def test_자기_실행이_끝나면_다시_시작할_수_있다(monkeypatch):
    """이 세션의 실행이 끝나면 한도가 차 있어도 하나를 시작할 수 있고, 둘째는 다시 거부된다."""
    # given
    set_caps(monkeypatch, runs=0, retries=0)
    start(ME, "a", limit=1)
    start(OTHER, "c", limit=1)

    # when
    budget.finish(ME, "agent", "a", ok=True)
    again = start(ME, "d", limit=1)
    second = start(ME, "e", limit=1)

    # then
    assert again is None and second is not None
    assert start(THIRD, "f", limit=1) is None


def test_한도_3에서_이곳_하나와_다른_곳_둘이_돌면_이_세션은_거부되고_셋째_세션은_허용된다(monkeypatch):
    """이슈의 예: 한도 3, 이 세션 1개와 다른 세션 2개 실행 중이면 이 세션은 거부, 끝난 뒤 허용, 실행 없는 셋째 세션은 하나 허용이다."""
    # given
    set_caps(monkeypatch, runs=0, retries=0)
    for who, name in ((ME, "a"), (OTHER, "b"), (OTHER, "c")):
        assert start(who, name, limit=3) is None

    # when
    denied = start(ME, "d", limit=3)
    third = start(THIRD, "e", limit=3)
    budget.finish(ME, "agent", "a", ok=True)
    allowed = start(ME, "d", limit=3)

    # then
    assert denied.startswith(budget.LIMIT_MARKER)
    assert third is None and allowed is None


def test_백그라운드_실행은_하위_에이전트가_멈출_때까지_자리를_차지한다(monkeypatch):
    """백그라운드로 시작해 성공으로 끝난 실행은 end_background 전까지 자리를 차지한다."""
    # given
    set_caps(monkeypatch, runs=0, retries=0)
    start(ME, "a", limit=1, background=True)
    budget.finish(ME, "agent", "a", ok=True, background=True)

    # when
    blocked = start(ME, "b", limit=1)
    budget.end_background(ME)
    freed = start(ME, "b", limit=1)

    # then
    assert blocked is not None and freed is None


def test_프로세스가_사라진_항목은_더_이상_세지_않는다(monkeypatch):
    """살아 있지 않은 프로세스의 항목은 한도에 세지 않는다."""
    # given
    set_caps(monkeypatch, runs=0, retries=0)
    start(ME, "a", limit=1, alive=lambda pid: True)

    # when
    result = start(ME, "b", limit=1, alive=lambda pid: False)

    # then
    assert result is None


def test_저장소가_쓸_수_없는_세션_ID는_개수_없이_통과한다():
    """키로 쓸 수 없는 세션 ID 는 신원이 없고, host:session 문자열은 올바른 것만 신원이 된다."""
    # given / when
    results = (budget.identity("bad id with spaces"), budget.identity_from_text("claude:bad id"),
               budget.identity_from_text("claude:abc"))

    # then
    assert results == (None, None, ("claude", "abc"))
