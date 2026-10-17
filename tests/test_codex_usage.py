from __future__ import annotations

import importlib.util
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "codex_usage.py"
SPEC = importlib.util.spec_from_file_location("codex_usage", SCRIPT)
USAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(USAGE)


def usage_event(used=42, seconds_ago=0):
    return {
        "timestamp": datetime.fromtimestamp(time.time() - seconds_ago, timezone.utc).isoformat(),
        "payload": {"rate_limits": {"primary": {
            "window_minutes": 10080, "used_percent": used, "resets_at": int(time.time()) + 86400,
        }}},
    }


def write_rollout(home, content):
    path = home / "sessions" / "rollout-test.jsonl"
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    return path


def test_event_crossing_chunk_boundary(tmp_path):
    """청크 경계에 걸친 마지막 이벤트를 읽는다."""
    # given
    event = usage_event()
    encoded = json.dumps(event).encode()
    suffix = b"\n" + b"x" * (USAGE.CHUNK_SIZE - len(encoded) // 2)
    write_rollout(tmp_path, b"invalid\n" + encoded + suffix)

    # when
    result = USAGE.weekly_usage(tmp_path, 86400)

    # then
    assert result["weekly_used_percent"] == 42
    assert result["observed_at"] == event["timestamp"]


def test_event_outside_read_limit(tmp_path):
    """끝에서 8 MiB보다 앞에 있는 이벤트는 읽지 않는다."""
    # given
    encoded = json.dumps(usage_event()).encode()
    write_rollout(tmp_path, encoded + b"\n" + b"x" * USAGE.MAX_READ)

    # when
    result = USAGE.weekly_usage(tmp_path, 86400)

    # then
    assert result == USAGE.UNKNOWN


def test_latest_rate_limits_event_has_no_weekly_window(tmp_path):
    """마지막 사용량 이벤트에 주간 창이 없으면 이전 이벤트를 사용하지 않는다."""
    # given
    latest = usage_event(90)
    latest["payload"]["rate_limits"]["primary"]["window_minutes"] = 300
    write_rollout(tmp_path, (json.dumps(usage_event()) + "\n" + json.dumps(latest)).encode())

    # when
    result = USAGE.weekly_usage(tmp_path, 86400)

    # then
    assert result == USAGE.UNKNOWN


@pytest.mark.parametrize("bad_value", [None, "42", True, float("nan"), float("inf"), 10 ** 400])
def test_invalid_usage_value(tmp_path, bad_value):
    """유효한 숫자가 아닌 사용률은 알 수 없는 값으로 반환한다."""
    # given
    write_rollout(tmp_path, json.dumps(usage_event(bad_value)).encode())

    # when
    result = USAGE.weekly_usage(tmp_path, 86400)

    # then
    assert result == USAGE.UNKNOWN


def test_malformed_lines_after_event(tmp_path):
    """마지막 이벤트 뒤의 잘못된 JSON과 다른 자료형을 건너뛴다."""
    # given
    encoded = json.dumps(usage_event()).encode()
    write_rollout(tmp_path, encoded + b'\n\xff\n[]\nnull\n{"payload": []}\n')

    # when
    result = USAGE.weekly_usage(tmp_path, 86400)

    # then
    assert result["weekly_used_percent"] == 42


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_nonstandard_json_constants_make_the_line_invalid(tmp_path, constant):
    """JSON 명세 밖의 상수가 든 줄은 잘못된 줄로 건너뛰고 이전 정상 이벤트를 쓴다."""
    # given
    valid = json.dumps(usage_event(42))
    broken = json.dumps(usage_event(77))[:-1] + f', "extra": {constant}}}'
    write_rollout(tmp_path, (valid + "\n" + broken).encode())

    # when
    result = USAGE.weekly_usage(tmp_path, 86400)

    # then
    assert result["weekly_used_percent"] == 42


def test_equal_event_timestamps_use_latest_file_modification(tmp_path):
    """이벤트 시각이 같으면 더 최근에 수정한 파일의 사용률을 읽는다."""
    # given
    older = usage_event(42)
    newer = usage_event(77)
    newer["timestamp"] = older["timestamp"]
    older_path = write_rollout(tmp_path, json.dumps(older).encode())
    newer_path = older_path.with_name("rollout-newer.jsonl")
    newer_path.write_text(json.dumps(newer))
    modified = time.time_ns()
    os.utime(older_path, ns=(modified - 1000000000, modified - 1000000000))
    os.utime(newer_path, ns=(modified, modified))

    # when
    result = USAGE.weekly_usage(tmp_path, 86400)

    # then
    assert result["weekly_used_percent"] == 77


def test_weekly_window_in_secondary(tmp_path):
    """주간 창이 secondary에 있으면 해당 사용률을 읽는다."""
    # given
    event = usage_event(37)
    limits = event["payload"]["rate_limits"]
    limits["secondary"] = limits["primary"]
    limits["primary"] = {"window_minutes": 300, "used_percent": 99}
    write_rollout(tmp_path, json.dumps(event).encode())

    # when
    result = USAGE.weekly_usage(tmp_path, 86400)

    # then
    assert result["weekly_used_percent"] == 37


@pytest.mark.parametrize("field, value", [("used_percent", None), ("resets_at", "invalid")])
def test_invalid_latest_event_does_not_use_older_file(tmp_path, field, value):
    """최신 이벤트의 주간 필드가 잘못됐으면 이전 파일의 사용률을 사용하지 않는다."""
    # given
    older_path = write_rollout(tmp_path, json.dumps(usage_event(42, seconds_ago=60)).encode())
    latest = usage_event(77)
    latest["payload"]["rate_limits"]["primary"][field] = value
    older_path.with_name("rollout-latest.jsonl").write_text(json.dumps(latest))

    # when
    result = USAGE.weekly_usage(tmp_path, 86400)

    # then
    assert result == USAGE.UNKNOWN
