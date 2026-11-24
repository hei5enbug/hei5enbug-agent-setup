"""Regression for #132: a record timestamp with a trailing Z must parse on Python 3.9.

On Python 3.9 datetime.fromisoformat rejects the Z suffix that Claude Code and Codex write on every record, so decode_record
counted each record as unreadable and list_sessions.py listed no session. The current interpreter accepts Z, so the 3.9
behavior is simulated by Python39Datetime, which fails on a Z string exactly as 3.9 does.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import session_common  # noqa: E402

WHEN = datetime(2026, 10, 14, 4, 0, tzinfo=timezone.utc)


class Python39Datetime(datetime):
    @classmethod
    def fromisoformat(cls, text):
        if text.endswith("Z"):
            raise ValueError(f"Invalid isoformat string: {text!r}")
        return super().fromisoformat(text)


def record_line(stamp: str) -> bytes:
    return ('{"type": "user", "timestamp": "%s"}' % stamp).encode("utf-8")


class DecodeRecordTimestampCase(unittest.TestCase):
    def test_zulu_timestamp_parses_as_utc_on_python_39(self) -> None:
        with mock.patch.object(session_common, "datetime", Python39Datetime):
            _, when = session_common.decode_record(record_line("2026-10-14T04:00:00Z"))
        self.assertEqual(when, WHEN)

    def test_zulu_timestamp_with_fraction_parses_as_utc_on_python_39(self) -> None:
        with mock.patch.object(session_common, "datetime", Python39Datetime):
            _, when = session_common.decode_record(record_line("2026-10-14T04:00:00.250Z"))
        self.assertEqual(when, WHEN + timedelta(milliseconds=250))

    def test_offset_timestamp_still_parses(self) -> None:
        with mock.patch.object(session_common, "datetime", Python39Datetime):
            _, when = session_common.decode_record(record_line("2026-10-14T13:00:00+09:00"))
        self.assertEqual(when, WHEN)

    def test_zulu_timestamp_parses_on_the_running_interpreter(self) -> None:
        _, when = session_common.decode_record(record_line("2026-10-14T04:00:00Z"))
        self.assertEqual(when, WHEN)


if __name__ == "__main__":
    unittest.main()
