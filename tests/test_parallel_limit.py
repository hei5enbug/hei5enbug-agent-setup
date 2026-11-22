"""요청 예산 항목 3: 시드한 계수기로 구한 병렬 한도와 기계 전체의 실행 목록."""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import parallel_limit as pl  # noqa: E402

GIB = 1024


def limit(cpus=12, memory_mb=20 * GIB, load=1.0, fraction=0.5, host=16, maximum=None):
    return pl.compute_limit(cpus, memory_mb, load, fraction, host, maximum)


def entry(run_id, session, started=1000.0, pid=1):
    return {"id": run_id, "session": session, "pid": pid, "started": started}


def test_CPU와_메모리와_호스트_한도_중_가장_낮은_값이_한도다():
    """CPU 12개, 메모리 20GiB, 호스트 한도 16은 11이고 메모리 3GiB는 3, 호스트 한도 4는 4다."""
    # given / when
    results = [limit(), limit(memory_mb=3 * GIB), limit(host=4)]

    # then
    assert results == [11, 3, 4]


def test_1GiB_미만이어도_한_실행은_허용한다():
    """가용 메모리가 0.8GiB여도 한도는 1이다."""
    # given / when
    result = limit(memory_mb=int(0.8 * GIB))

    # then
    assert result == 1


def test_부하_평균이_CPU_수의_두_배_이상이면_한도는_1이다():
    """12 CPU에서 부하 24는 1이고 23.9는 11이다."""
    # given / when
    results = [limit(load=24.0), limit(load=23.9)]

    # then
    assert results == [1, 11]


def test_읽을_수_없는_CPU_수는_그_항을_빼고_6으로_자른다():
    """CPU 수를 읽지 못하면 3GiB는 3이고, 20GiB와 호스트 한도 16은 6이다."""
    # given / when
    results = [limit(cpus=None, memory_mb=3 * GIB), limit(cpus=None, memory_mb=20 * GIB, host=16)]

    # then
    assert results == [3, 6]


def test_둘_다_읽을_수_없으면_호스트_한도와_6을_쓴다():
    """CPU와 메모리를 모두 못 읽으면 호스트 한도 4는 4, 없으면 6, 16은 6이다."""
    # given / when
    results = [limit(cpus=None, memory_mb=None, host=host) for host in (4, None, 16)]

    # then
    assert results == [4, 6, 6]


def test_CPU_수를_못_읽어도_메모리_부족을_알면_한도는_1이다():
    """CPU 수를 못 읽고 가용 메모리가 10퍼센트 미만이면 한도는 1이다."""
    # given / when
    result = limit(cpus=None, memory_mb=20 * GIB, load=None, fraction=0.05)

    # then
    assert result == 1


def test_설정한_상한은_마지막에_적용된다():
    """상한 6은 11을 6으로 자르고, 이미 낮은 3은 그대로 둔다."""
    # given / when
    results = [limit(maximum=6), limit(maximum=6, memory_mb=3 * GIB)]

    # then
    assert results == [6, 3]


def test_한도를_넘는_시작은_이_세션의_실행이_끝날_때까지_거부한다():
    """한도 3에서 이 세션 하나와 다른 세션 둘이 돌면 이 세션은 거부되고, 자기 실행이 끝난 뒤나 실행이 없는 세션은 허용된다."""
    # given
    entries = [entry("a", "claude:me"), entry("b", "claude:other"), entry("c", "claude:other")]

    # when
    results = (
        pl.over_limit(entries, "claude:me", 3),
        pl.over_limit(pl.remove_entries(entries, run_id="a"), "claude:me", 3),
        pl.over_limit(entries, "claude:third", 3),
    )

    # then
    assert results == (True, False, False)


def test_자기_실행이_없는_세션은_언제나_하나를_시작할_수_있다():
    """다른 세션의 실행이 한도를 채워도 실행이 없는 세션은 하나를 시작한다."""
    # given
    entries = [entry(str(index), "claude:other") for index in range(10)]

    # when
    result = pl.over_limit(entries, "claude:me", 1)

    # then
    assert result is False


def test_프로세스가_사라졌거나_너무_오래_돈_항목은_더_이상_세지_않는다():
    """살아 있지 않은 pid 와 실행 시간 제한을 넘긴 항목은 목록에서 빠진다."""
    # given
    entries = [entry("a", "s", 2500.0, pid=11), entry("b", "s", 2500.0, pid=22), entry("c", "s", started=0.0, pid=11)]

    # when
    kept = pl.live_entries(entries, 3000.0, alive=lambda pid: pid == 11)
    expired = pl.live_entries(entries, 2500.0 + pl.MAX_RUN_SECONDS + 1, alive=lambda pid: True)

    # then
    assert [item["id"] for item in kept] == ["a"]
    assert expired == []


def test_백그라운드_실행의_종료는_그_세션과_유형에서_가장_오래된_항목을_뺀다():
    """같은 세션과 유형의 가장 오래된 백그라운드 항목만 빠지고 다른 세션의 것은 남는다."""
    # given
    entries = [
        {**entry("a", "s", 1.0), "background": True, "kind": "x"},
        {**entry("b", "s", 2.0), "background": True, "kind": "x"},
        {**entry("c", "t", 0.5), "background": True, "kind": "x"},
    ]

    # when
    remaining = pl.remove_entries(entries, session="s", kind="x")

    # then
    assert [item["id"] for item in remaining] == ["b", "c"]


def test_출하_상한은_6이고_환경_변수가_덮어쓴다(monkeypatch):
    """환경 변수가 없으면 설정 파일의 6이고, 0은 상한 없음, 9는 9다."""
    # given
    monkeypatch.delenv(pl.MAX_ENV, raising=False)

    # when
    shipped = pl.configured_maximum()
    monkeypatch.setenv(pl.MAX_ENV, "0")
    off = pl.configured_maximum()
    monkeypatch.setenv(pl.MAX_ENV, "9")
    nine = pl.configured_maximum()

    # then
    assert (shipped, off, nine) == (6, None, 9)


def test_호스트_한도(monkeypatch, tmp_path):
    """Claude Code 는 기본 20과 변수 값을, Codex 는 설정 파일에 값이 있을 때만 값을 쓴다."""
    # given
    monkeypatch.delenv(pl.CLAUDE_SUBAGENT_LIMIT_ENV, raising=False)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))

    # when
    default = pl.host_limit("claude")
    monkeypatch.setenv(pl.CLAUDE_SUBAGENT_LIMIT_ENV, "8")
    configured = pl.host_limit("claude")
    unset = pl.host_limit("codex")
    (tmp_path / "config.toml").write_text("[agents]\nmax_concurrent_threads_per_session = 5\n", encoding="utf-8")
    codex = pl.host_limit("codex")

    # then
    assert (default, configured, unset, codex) == (20, 8, None, 5)


def test_가용_메모리는_프로세스를_띄우지_않고_테스트_값이나_읽은_값을_쓴다(monkeypatch):
    """테스트 값이 있으면 그 MB 를, 숫자가 아니면 None 을 주고, 값이 없으면 이 플랫폼에서 읽은 양수 값이나 None 을 준다."""
    # given
    monkeypatch.setenv(pl.session_memory.TEST_OVERRIDE, "2048")

    # when
    fixed = pl.read_available_mb(0.5)
    monkeypatch.setenv(pl.session_memory.TEST_OVERRIDE, "many")
    invalid = pl.read_available_mb(0.5)
    monkeypatch.delenv(pl.session_memory.TEST_OVERRIDE)
    live = pl.read_available_mb(0.5)

    # then
    assert (fixed, invalid) == (2048, None)
    assert live is None or live > 0
