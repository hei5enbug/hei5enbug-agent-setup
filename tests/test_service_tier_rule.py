"""Acceptance checks: the agent instructions pass the fast service tier only on the user's request, for the session, with the pins unchanged."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FILES = ("instructions/claude-agents.md", "instructions/codex-agents.md")


def normalized(name: str) -> str:
    return " ".join((REPO_ROOT / name).read_text(encoding="utf-8").split())


def test_두_지침은_빠른_등급을_사용자_요청이_있을_때만_세션_끝까지_넘기고_고정값은_바꾸지_않는다():
    """claude-agents와 codex-agents 모두 요청 조건, 세션 지속, 철회, 요청 없으면 금지, 고정값 불변을 적는다."""
    # given
    expected = [
        "--service-tier fast",
        "this session",
        "every `role_runner.py` run and every `text_review.py review`",
        "until the user withdraws",
        "never",
        "pinned model or effort",
    ]
    # when
    texts = {name: normalized(name) for name in FILES}
    # then
    for name, text in texts.items():
        missing = [phrase for phrase in expected if phrase not in text]
        assert missing == [], f"{name} must state: {missing}"
