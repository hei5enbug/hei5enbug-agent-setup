"""호스트에 전달되는 위임 계약과 이전 역할의 안전한 교체를 검사하며 실제 모델 준수를 주장하지 않는다."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import session_context as context


@pytest.mark.parametrize("host", ["codex", "claude"])
def test_두_호스트는_가벼운_위임_기준과_검토_연결만_항상_받는다(host):
    """두 호스트의 시작 문맥은 상황별 위임·대체 처리·검토 연결을 포함하고 상세 절차는 지연 로딩한다."""
    # Given
    expected = [
        "small cohesive edits",
        "tightly dependent work in the main session",
        "Delegate bounded investigation",
        "Parallelize only work with independent resources",
        "continue authorized work in the main session",
        "do not invoke a reviewer without the user's approval",
    ]

    # When
    rendered = context.render_context(REPO, host)

    # Then
    normalized = " ".join(rendered.split())
    assert all(phrase in normalized for phrase in expected)
    assert len(rendered.encode()) <= context.MAX_CONTEXT_BYTES
    assert "## Scheduling" not in rendered
    assert "## Reviewer selection" not in rendered
    assert "independent-model-validation.md" in rendered


@pytest.mark.parametrize("host", ["codex", "claude"])
def test_공유_모델_라우팅은_위임_때_읽고_시작_문맥에는_본문을_싣지_않는다(host):
    """호스트 규칙은 위임할 때 공유 라우팅을 읽게 하고 시작 문맥은 그 본문을 미리 싣지 않는다."""
    # Given
    rendered = context.render_context(REPO, host)
    host_rules = REPO / "instructions" / f"{host}-agents.md"
    routing = REPO / "instructions/model-routing.md"

    # When
    host_text = " ".join(host_rules.read_text(encoding="utf-8").split())
    route_text = " ".join(routing.read_text(encoding="utf-8").split())

    # Then
    assert "read [shared model routing](model-routing.md)" in host_text
    assert "instruction-reuse rules in [work efficiency](work-efficiency.md)" in host_text
    assert "apply its effective-settings checks before dispatch" in host_text
    assert "The execution host remains the same" in route_text
    assert "actual model family that authored the deliverable" in route_text
    assert "## Keep role settings fixed" not in rendered


@pytest.mark.parametrize("user_edited", [False, True])
def test_구형_scout는_원본과_같을_때만_현재_역할로_교체한다(tmp_path, monkeypatch, user_edited):
    """이전 scout의 미수정 복사본은 실행 중 조사를 허용하도록 교체하고 사용자 수정본은 그대로 둔다."""
    # Given
    current = (REPO / "standalone-agents/codex-scout.toml").read_text()
    previous = current.replace(
        "Read-only worker for one bounded local investigation, including a local-evidence research ticket "
        "that a skill assigns.",
        "Read-only worker for one bounded assignment, either a bounded investigation or a review persona, "
        "research ticket, or grading role that a skill assigns.",
    )
    previous = previous.replace(
        "either a bounded investigation or a",
        "either an investigation during planning or a",
    )
    previous = previous.replace(
        "conclusion the quoted evidence does not support.\nReturn the result",
        "conclusion the quoted evidence does not support.\n"
        "For a review persona, research ticket, or grading role that a skill assigns, follow that role's instructions "
        "and output contract. Base every finding, answer, or grade on quoted evidence.\nReturn the result",
    )
    prior_digest = hashlib.sha256(previous.encode()).hexdigest()
    target = tmp_path / "agents/scout.toml"
    target.parent.mkdir()
    original = previous + ("\n# user setting\n" if user_edited else "")
    target.write_text(original)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))

    # When
    context.provision_codex_agents(REPO)

    # Then
    assert prior_digest in context.RETIRED_CODEX_AGENTS["scout"]
    assert target.read_text() == (original if user_edited else current)


@pytest.mark.parametrize("user_edited", [False, True])
def test_v2_1_0_scout는_원본과_같을_때만_로컬_조사_전용_역할로_교체한다(tmp_path, monkeypatch, user_edited):
    """v2.1.0에 들어 있던 scout의 미수정 복사본은 현재 역할로 바꾸고 사용자 수정본은 그대로 둔다."""
    # Given
    released = subprocess.run(
        ["git", "show", "v2.1.0:standalone-agents/codex-scout.toml"],
        cwd=REPO, check=True, capture_output=True, text=True,
    ).stdout
    target = tmp_path / "agents/scout.toml"
    target.parent.mkdir()
    original = released + ("\n# user setting\n" if user_edited else "")
    target.write_text(original)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))

    # When
    context.provision_codex_agents(REPO)

    # Then
    current = (REPO / "standalone-agents/codex-scout.toml").read_text()
    assert target.read_text() == (original if user_edited else current)


def test_메인_대체_처리는_부분_작업과_권한_검증을_보존한다():
    """메인 대체 처리는 작업자 종료와 부분 변경 확인을 요구하며 권한이나 실패 검사를 우회하지 않는다."""
    # Given
    path = REPO / "instructions/implementation-execution.md"

    # When
    text = " ".join(path.read_text().split())

    # Then
    assert "main-owned implementation is allowed" in text
    assert "do not perform them for direct work" in text
    assert "Stop the affected worker before taking ownership, inspect its partial diff" in text
    assert "including its own" in text
    assert "Do not repeatedly retry a known quota or capability failure" in text
    assert "Fallback never bypasses a missing user decision, permission restriction, or failed acceptance check." in text
    assert "Workers make every implementation edit" not in text
    assert "but it never edits" not in text


def test_중요_변경의_독립_검토는_개별_승인과_실제_설정_확인을_요구한다():
    """구현 검토는 개별 승인 뒤 한 번 수행하고 실제 모델·사고 강도와 미추적 변경까지 확인한다."""
    # Given
    path = REPO / "instructions/independent-model-validation.md"

    # When
    text = " ".join(path.read_text().split())

    # Then
    assert "completed implementation changes" in text
    assert "general workflow is not approval to invoke a reviewer" in text
    assert "exactly one reviewer from the other model family" in text
    assert "verify the actual model and effort from host records" in text
    assert "Include necessary untracked files" in text
    assert "Do not enable extra billing or change authentication" in text
    assert "Routine author inspection and required tests still run" in text
