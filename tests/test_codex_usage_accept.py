"""Acceptance checks for scripts/codex_usage.py, which reads the Codex weekly usage from local rollout records."""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "codex_usage.py"
WEEK = 10080


def iso(seconds_ago=0):
    moment = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def event(used, window=WEEK, seconds_ago=0, resets_in=3 * 86400, slot="primary"):
    limits = {"limit_id": "codex", "primary": None, "secondary": None}
    limits[slot] = {"used_percent": used, "window_minutes": window, "resets_at": int(time.time()) + resets_in}
    return json.dumps({
        "timestamp": iso(seconds_ago), "ordinal": 1, "type": "event_msg",
        "payload": {"type": "token_count", "info": None, "rate_limits": limits},
    })


def rollout(home, name, lines, age=0):
    path = home / "sessions" / "2026" / "10" / "17" / f"rollout-{name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    stamp = time.time() - age
    os.utime(path, (stamp, stamp))
    return path


def run(home=None, *args, env=None):
    command = [sys.executable, str(SCRIPT), *args]
    if home is not None:
        command += ["--home", str(home)]
    environment = {key: value for key, value in os.environ.items() if key != "CODEX_HOME"}
    environment.update(env or {})
    done = subprocess.run(command, capture_output=True, text=True, env=environment)
    assert done.returncode == 0, done.stderr
    lines = done.stdout.strip().splitlines()
    assert len(lines) == 1
    return json.loads(lines[0])


def test_마지막_사용량_이벤트의_주간_사용률을_읽는다(tmp_path):
    rollout(tmp_path, "a", ["not json", event(30.0), '{"type": "other"}', event(55.5)])
    result = run(tmp_path)
    assert result["weekly_used_percent"] == 55.5
    assert set(result) == {"weekly_used_percent", "limit_reset_at", "observed_at"}
    assert isinstance(result["limit_reset_at"], int)
    assert result["observed_at"].endswith("Z")


def test_사용량_이벤트가_가장_최근인_파일이_우선이다(tmp_path):
    rollout(tmp_path, "old", [event(90.0, seconds_ago=3600)], age=0)
    rollout(tmp_path, "new", [event(12.0, seconds_ago=10)], age=500)
    assert run(tmp_path)["weekly_used_percent"] == 12.0


def test_수정_시각이_최신이어도_이벤트가_오래된_파일은_밀린다(tmp_path):
    rollout(tmp_path, "busy", [event(25.0, seconds_ago=7200)], age=0)
    rollout(tmp_path, "other", [event(80.0, seconds_ago=30)], age=900)
    assert run(tmp_path)["weekly_used_percent"] == 80.0


def test_가장_최근_이벤트에_주간_창이_없으면_이전_파일의_값을_쓰지_않는다(tmp_path):
    rollout(tmp_path, "old", [event(44.0, seconds_ago=3600)], age=600)
    rollout(tmp_path, "new", [event(70.0, window=300, seconds_ago=10)], age=0)
    assert run(tmp_path)["weekly_used_percent"] is None


def test_미래_시각의_이벤트는_알_수_없다(tmp_path):
    rollout(tmp_path, "a", [event(20.0, seconds_ago=-3600)])
    assert run(tmp_path)["weekly_used_percent"] is None


def test_시계_오차_안의_미래_시각은_허용한다(tmp_path):
    rollout(tmp_path, "a", [event(20.0, seconds_ago=-5)])
    assert run(tmp_path)["weekly_used_percent"] == 20.0


def test_사용량_이벤트가_없는_최신_파일은_건너뛰고_다음_파일을_본다(tmp_path):
    rollout(tmp_path, "old", [event(44.0)], age=3600)
    rollout(tmp_path, "new", ['{"type": "other"}', "garbage"], age=10)
    assert run(tmp_path)["weekly_used_percent"] == 44.0


def test_주간_창은_secondary_자리에_있어도_읽는다(tmp_path):
    lines = [json.dumps({
        "timestamp": iso(), "type": "event_msg",
        "payload": {"type": "token_count", "rate_limits": {
            "primary": {"used_percent": 99.0, "window_minutes": 300, "resets_at": int(time.time()) + 600},
            "secondary": {"used_percent": 37.0, "window_minutes": WEEK, "resets_at": int(time.time()) + 86400},
        }},
    })]
    rollout(tmp_path, "a", lines)
    assert run(tmp_path)["weekly_used_percent"] == 37.0


def test_주간_창이_없으면_알_수_없다(tmp_path):
    rollout(tmp_path, "a", [event(70.0, window=300)])
    assert run(tmp_path)["weekly_used_percent"] is None


def test_세션_폴더가_없으면_알_수_없다(tmp_path):
    result = run(tmp_path / "missing")
    assert result["weekly_used_percent"] is None
    assert result["limit_reset_at"] is None and result["observed_at"] is None


def test_빈_파일만_있으면_알_수_없다(tmp_path):
    rollout(tmp_path, "a", [""])
    assert run(tmp_path)["weekly_used_percent"] is None


def test_하루보다_오래된_이벤트는_알_수_없다(tmp_path):
    rollout(tmp_path, "a", [event(20.0, seconds_ago=2 * 86400)])
    assert run(tmp_path)["weekly_used_percent"] is None


def test_최대_경과_시간_옵션이_오래된_이벤트를_허용한다(tmp_path):
    rollout(tmp_path, "a", [event(20.0, seconds_ago=2 * 86400)])
    assert run(tmp_path, "--max-age-seconds", str(10 * 86400))["weekly_used_percent"] == 20.0


def test_창이_이미_초기화됐으면_알_수_없다(tmp_path):
    rollout(tmp_path, "a", [event(80.0, resets_in=-60)])
    assert run(tmp_path)["weekly_used_percent"] is None


def test_home_옵션이_없으면_CODEX_HOME을_쓴다(tmp_path):
    rollout(tmp_path, "a", [event(61.0)])
    assert run(None, env={"CODEX_HOME": str(tmp_path)})["weekly_used_percent"] == 61.0


def test_큰_파일의_끝에_있는_이벤트를_찾는다(tmp_path):
    filler = ['{"type": "event_msg", "payload": {"type": "agent_message", "text": "' + "x" * 900 + '"}}'] * 3500
    rollout(tmp_path, "big", [*filler, event(73.0)])
    assert (tmp_path / "sessions/2026/10/17/rollout-big.jsonl").stat().st_size > 3 * 1024 * 1024
    assert run(tmp_path)["weekly_used_percent"] == 73.0


def test_열_번째보다_오래된_파일은_보지_않는다(tmp_path):
    rollout(tmp_path, "ancient", [event(88.0)], age=100000)
    for index in range(10):
        rollout(tmp_path, f"empty{index}", ['{"type": "other"}'], age=10 + index)
    assert run(tmp_path)["weekly_used_percent"] is None


@pytest.mark.parametrize("bad", ["abc", "-5", ""])
def test_잘못된_최대_경과_시간은_종료_코드_0으로_알_수_없다고_답한다(tmp_path, bad):
    rollout(tmp_path, "a", [event(20.0)])
    command = [sys.executable, str(SCRIPT), "--home", str(tmp_path), "--max-age-seconds", bad]
    done = subprocess.run(command, capture_output=True, text=True)
    assert done.returncode in (0, 2)
    if done.returncode == 0:
        assert json.loads(done.stdout.strip())["weekly_used_percent"] is None
