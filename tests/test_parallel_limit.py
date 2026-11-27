"""요청 예산 항목 3: 시드한 계수기로 구한 병렬 한도와 기계 전체의 실행 목록."""
import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import parallel_limit as pl  # noqa: E402

GIB = 1024


def limit(cpus=12, memory_mb=20 * GIB, load=1.0, fraction=0.5, host=16, maximum=None, run_mib=512, pressure=None):
    return pl.compute_limit(cpus, memory_mb, load, fraction, host, maximum, run_mib, pressure)


def entry(run_id, session, started=1000.0, pid=1):
    return {"id": run_id, "session": session, "pid": pid, "started": started}


def test_CPU와_메모리와_호스트_한도_중_가장_낮은_값이_한도다():
    """CPU 12개, 메모리 20GiB, 호스트 한도 16은 11이고 메모리 1536MiB는 3, 호스트 한도 4는 4다."""
    # given / when
    results = [limit(), limit(memory_mb=3 * GIB // 2), limit(host=4)]

    # then
    assert results == [11, 3, 4]


def test_실행_하나의_추정_메모리_미만이어도_한_실행은_허용한다():
    """가용 메모리가 400MiB여도 한도는 1이다."""
    # given / when
    result = limit(memory_mb=400)

    # then
    assert result == 1


def test_부하_평균이_CPU_수의_두_배_이상이면_한도는_1이다():
    """12 CPU에서 부하 24는 1이고 23.9는 11이다."""
    # given / when
    results = [limit(load=24.0), limit(load=23.9)]

    # then
    assert results == [1, 11]


def test_읽을_수_없는_CPU_수는_그_항을_빼고_6으로_자른다():
    """CPU 수를 읽지 못하면 1536MiB는 3이고, 20GiB와 호스트 한도 16은 6이다."""
    # given / when
    results = [limit(cpus=None, memory_mb=3 * GIB // 2), limit(cpus=None, memory_mb=20 * GIB, host=16)]

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
    results = [limit(maximum=6), limit(maximum=6, memory_mb=3 * GIB // 2)]

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


def make_workspace(tmp_path, build_file=None, in_folder=False):
    """`.git` 이 있는 저장소 최상위에 빌드 파일을 두거나, 그 아래 하위 폴더에 둔다."""
    top = tmp_path / "repo"
    folder = top / "service" / "api"
    folder.mkdir(parents=True)
    (top / ".git").write_text("gitdir: /tmp/work/example\n", encoding="utf-8")
    if build_file:
        ((folder if in_folder else top) / build_file).write_text("", encoding="utf-8")
    return folder


@pytest.mark.parametrize("build_file", pl.JVM_BUILD_FILES)
def test_Git_최상위에_JVM_빌드_파일이_있으면_실행_하나는_1536MiB로_센다(tmp_path, build_file):
    """4096MiB 가용 메모리에서 하위 폴더의 Git 최상위에 빌드 파일이 있으면 메모리 항은 2다."""
    # given
    folder = make_workspace(tmp_path, build_file)

    # when
    estimate = pl.run_memory_mib(str(folder))

    # then
    assert (estimate, limit(memory_mb=4096, run_mib=estimate)) == (1536, 2)


def test_폴더_자체에_pom이_있으면_Git_최상위가_아니어도_JVM_작업_공간이다(tmp_path):
    """Git 저장소 밖 폴더든 저장소 안 하위 폴더든 pom.xml 이 폴더에 있으면 1536MiB, 메모리 항은 2다."""
    # given
    inside = make_workspace(tmp_path, "pom.xml", in_folder=True)
    outside = tmp_path / "plain"
    outside.mkdir()
    (outside / "pom.xml").write_text("", encoding="utf-8")

    # when
    estimates = [pl.run_memory_mib(str(inside)), pl.run_memory_mib(str(outside))]

    # then
    assert estimates == [1536, 1536]
    assert limit(memory_mb=4096, run_mib=estimates[0]) == 2


def test_읽을_수_없는_빌드_파일_항목은_없는_것으로_보고_다른_빌드_파일을_계속_찾는다(tmp_path):
    """접근할 수 없는 build.gradle 링크가 있어도 예외 없이 다음 항목을 확인해 pom.xml 이 있으면 1536MiB로 센다."""
    # given
    if os.geteuid() == 0:
        pytest.skip("root ignores file modes")
    folder = make_workspace(tmp_path, "pom.xml", in_folder=True)
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "target").write_text("", encoding="utf-8")
    (folder / "build.gradle").symlink_to(locked / "target")
    locked.chmod(0)

    # when
    try:
        estimate = pl.run_memory_mib(str(folder))
    finally:
        locked.chmod(0o755)

    # then
    assert estimate == 1536


def test_JVM_빌드_파일이_없으면_실행_하나는_512MiB로_세어_메모리_항이_8이다(tmp_path):
    """4096MiB 가용 메모리에서 빌드 파일이 없는 폴더와 존재하지 않는 폴더는 모두 512MiB, 메모리 항은 8이다."""
    # given
    folder = make_workspace(tmp_path)

    # when
    estimates = [pl.run_memory_mib(str(folder)), pl.run_memory_mib(str(tmp_path / "missing"))]

    # then
    assert estimates == [512, 512]
    assert limit(memory_mb=4096, run_mib=estimates[0]) == 8


def write_config(tmp_path, monkeypatch, content):
    path = tmp_path / "parallel-limit.json"
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
    monkeypatch.setattr(pl, "CONFIG_PATH", path)


def test_설정_파일의_추정값이_출하_값을_대신한다(tmp_path, monkeypatch):
    """설정 파일의 run_memory_mib 700 과 jvm_run_memory_mib 2000 이 각각 일반 폴더와 JVM 폴더에 쓰인다."""
    # given
    write_config(tmp_path, monkeypatch, {"run_memory_mib": 700, "jvm_run_memory_mib": 2000})
    plain = tmp_path / "plain"
    plain.mkdir()
    jvm = make_workspace(tmp_path, "build.gradle")

    # when
    estimates = [pl.run_memory_mib(str(plain)), pl.run_memory_mib(str(jvm))]

    # then
    assert estimates == [700, 2000]


@pytest.mark.parametrize("content", [
    {}, {"run_memory_mib": 0, "jvm_run_memory_mib": 0}, {"run_memory_mib": -5, "jvm_run_memory_mib": -5},
    {"run_memory_mib": "700", "jvm_run_memory_mib": 2000.5}, {"run_memory_mib": True, "jvm_run_memory_mib": None},
    "not json", [],
])
def test_없거나_0이거나_음수이거나_정수가_아닌_추정값은_출하_값을_쓴다(tmp_path, monkeypatch, content):
    """누락, 0, 음수, 문자열, 실수, 불리언, 깨진 파일은 각각 512 와 1536 이다."""
    # given
    write_config(tmp_path, monkeypatch, content)
    plain = tmp_path / "plain"
    plain.mkdir()
    jvm = make_workspace(tmp_path, "build.gradle")

    # when
    estimates = [pl.run_memory_mib(str(plain)), pl.run_memory_mib(str(jvm))]

    # then
    assert estimates == [512, 1536]


def test_설정_파일이_없으면_출하_추정값을_쓴다(tmp_path, monkeypatch):
    """설정 파일을 읽을 수 없으면 일반 폴더는 512, JVM 폴더는 1536 이다."""
    # given
    monkeypatch.setattr(pl, "CONFIG_PATH", tmp_path / "absent.json")
    jvm = make_workspace(tmp_path, "settings.gradle.kts")

    # when
    estimates = [pl.run_memory_mib(str(tmp_path)), pl.run_memory_mib(str(jvm))]

    # then
    assert estimates == [512, 1536]


def test_출하_설정_파일은_두_추정값과_상한을_함께_담는다():
    """출하 config/parallel-limit.json 은 max 6 과 두 추정값 512, 1536 을 담는다."""
    # given / when
    shipped = json.loads(pl.CONFIG_PATH.read_text(encoding="utf-8"))

    # then
    assert (shipped["max"], shipped["run_memory_mib"], shipped["jvm_run_memory_mib"]) == (6, 512, 1536)


def test_메모리_압력_경고는_한도를_절반으로_줄이되_1_밑으로_내리지_않는다():
    """압력 2 에서 한도 5 는 2, 1 은 1 이다."""
    # given / when
    results = [limit(maximum=5, pressure=2), limit(maximum=1, pressure=2)]

    # then
    assert results == [2, 1]


def test_메모리_압력_위험은_한도를_1로_만든다():
    """압력 4 에서 한도 11 은 1 이다."""
    # given / when
    result = limit(pressure=4)

    # then
    assert result == 1


@pytest.mark.parametrize("pressure", [None, 1, 0, 3, 8])
def test_메모리_압력이_정상이거나_읽을_수_없으면_한도는_그대로다(pressure):
    """압력 1, 읽지 못함, 정의되지 않은 값은 한도 11 을 바꾸지 않는다."""
    # given / when
    result = limit(pressure=pressure)

    # then
    assert result == 11


def test_메모리_압력은_macOS_에서만_읽는다(monkeypatch):
    """macOS 가 아니면 sysctl 을 부르지 않고 None 을 주며, macOS 에서는 읽은 값이나 None 이다."""
    # given
    monkeypatch.setattr(pl.sys, "platform", "linux")
    monkeypatch.setattr(pl, "darwin_sysctl", lambda name, kind: pytest.fail("sysctl must not be called"))

    # when
    other = pl.memory_pressure_level()
    monkeypatch.setattr(pl.sys, "platform", "darwin")
    monkeypatch.setattr(pl, "darwin_sysctl", lambda name, kind: 2 if name == b"kern.memorystatus_vm_pressure_level" else None)
    read = pl.memory_pressure_level()
    monkeypatch.setattr(pl, "darwin_sysctl", lambda name, kind: None)
    unreadable = pl.memory_pressure_level()

    # then
    assert (other, read, unreadable) == (None, 2, None)


def test_현재_한도는_작업_폴더의_추정값과_메모리_압력을_함께_쓴다(tmp_path, monkeypatch):
    """4096MiB 에서 일반 폴더는 8, JVM 폴더는 2 이고, 압력 2 에서는 각각 4 와 1 이다."""
    # given
    counters = pl.machine_load.Counters(1.0, 32, 0.5, 0.5)
    monkeypatch.setattr(pl.machine_load, "system_counters", lambda cwd: counters)
    monkeypatch.setattr(pl, "read_available_mb", lambda fraction: 4096)
    monkeypatch.setattr(pl, "host_limit", lambda host: 20)
    monkeypatch.setattr(pl, "configured_maximum", lambda: None)
    monkeypatch.setattr(pl, "CONFIG_PATH", tmp_path / "absent.json")
    plain = tmp_path / "plain"
    plain.mkdir()
    jvm = make_workspace(tmp_path, "build.gradle.kts")
    levels = iter([1, 1, 2, 2])
    monkeypatch.setattr(pl, "memory_pressure_level", lambda: next(levels))

    # when
    results = [pl.current_limit("claude", str(folder)) for folder in (plain, jvm, plain, jvm)]

    # then
    assert results == [8, 2, 4, 1]
