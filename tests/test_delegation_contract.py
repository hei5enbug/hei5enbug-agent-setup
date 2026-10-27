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
        "tightly dependent work, implementation that changes at most two files, and integration fixes in the main session",
        "Delegate implementation that changes more than two files to the implementation worker",
        "except the kinds the host session file assigns to the main session",
        "Delegate investigation of more than three files or a long log as independent questions run together",
        "Parallelize only work with independent resources",
        "continue authorized work in the main session",
        "Independent review is the exception to main-session review",
    ]

    # When
    rendered = context.render_context(REPO, host)

    # Then
    normalized = " ".join(rendered.split())
    assert all(phrase in normalized for phrase in expected)
    assert len(rendered.encode()) <= context.MAX_CONTEXT_BYTES
    assert "## Scheduling" not in rendered
    assert "## Reviewer selection" not in rendered
    assert "($I/independent-model-validation.md)" in rendered


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
    assert "Read [shared model routing](model-routing.md) before dispatching a skill review role" in host_text
    assert "Other dispatches need only this file." in host_text
    assert "in the last case, apply its effective-settings checks first" in host_text
    assert "The execution host remains the same" in route_text
    assert "actual model family that authored the deliverable" in route_text
    assert "## Keep role settings fixed" not in rendered


def released_role(tag: str, name: str) -> str:
    return subprocess.run(
        ["git", "show", f"{tag}:standalone-agents/codex-{name}.toml"],
        cwd=REPO, check=True, capture_output=True, text=True,
    ).stdout


@pytest.mark.parametrize("user_edited", [False, True])
@pytest.mark.parametrize("name", ["scout", "reviewer"])
def test_v2_10_1_scout와_reviewer는_원본과_같을_때만_현재_역할로_교체한다(tmp_path, monkeypatch, name, user_edited):
    """v2.10.1에 들어 있던 scout와 reviewer의 미수정 복사본은 현재 역할로 바꾸고 사용자 수정본은 그대로 둔다."""
    # Given
    released = released_role("v2.10.1", name)
    target = tmp_path / f"agents/{name}.toml"
    target.parent.mkdir()
    original = released + ("\n# user setting\n" if user_edited else "")
    target.write_text(original)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))

    # When
    context.provision_codex_agents(REPO)

    # Then
    current = (REPO / f"standalone-agents/codex-{name}.toml").read_text()
    assert released != current
    assert target.read_text() == (original if user_edited else current)


@pytest.mark.parametrize("user_edited", [False, True])
def test_구형_scout는_원본과_같을_때만_현재_역할로_교체한다(tmp_path, monkeypatch, user_edited):
    """이전 scout의 미수정 복사본은 실행 중 조사를 허용하도록 교체하고 사용자 수정본은 그대로 둔다."""
    # Given
    current = (REPO / "standalone-agents/codex-scout.toml").read_text()
    previous = released_role("v2.10.1", "scout").replace("sandbox_mode", 'model_reasoning_effort = "xhigh"\nsandbox_mode', 1)
    previous = previous.replace(
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


HEAD_ROLE_DIGESTS = {
    "scout": "49e5f7dab3d3b9384b49250e8622fd57cf65b600d7eb1b3b5b1732554ef1b5c7",
    "designer": "be8b8dc3f856bd8fdab5e15f17b464deab2e50819d3a7d060cccbc2847b7610a",
    "reviewer": "5d2bd7dd2786e5824cfed218fb2a3ff0ae966d193a0495782cbe70defafc9cca",
}


@pytest.mark.parametrize("user_edited", [False, True])
@pytest.mark.parametrize("name", sorted(HEAD_ROLE_DIGESTS))
def test_effort를_고정하던_역할_파일은_원본과_같을_때만_effort_없는_현재_파일로_교체한다(tmp_path, monkeypatch, name, user_edited):
    """effort 줄이 있던 scout, designer, reviewer의 미수정 복사본은 effort 없는 현재 파일로 바꾸고 사용자 수정본은 그대로 둔다."""
    # Given
    current = (REPO / f"standalone-agents/codex-{name}.toml").read_text()
    previous = released_role("v2.10.1", name).replace("sandbox_mode", 'model_reasoning_effort = "xhigh"\nsandbox_mode', 1)
    target = tmp_path / f"agents/{name}.toml"
    target.parent.mkdir()
    original = previous + ("\n# user setting\n" if user_edited else "")
    target.write_text(original)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))

    # When
    context.provision_codex_agents(REPO)

    # Then
    assert hashlib.sha256(previous.encode()).hexdigest() == HEAD_ROLE_DIGESTS[name]
    assert HEAD_ROLE_DIGESTS[name] in context.RETIRED_CODEX_AGENTS[name]
    assert "model_reasoning_effort" not in current
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
    paths = (REPO / "instructions/implementation-execution.md", REPO / "instructions/implementation-delegation.md")

    # When
    text = " ".join(" ".join(path.read_text().split()) for path in paths)

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
    """구현 검토는 최종 단계에서 자동으로 한 번 수행하고 더 이른 검토만 승인을 요구하며, 실제 모델·사고 강도와 미추적 변경까지 확인한다."""
    # Given
    path = REPO / "instructions/independent-model-validation.md"

    # When
    text = " ".join(path.read_text().split())

    # Then
    assert "completed implementation changes" in text
    assert "runs only when the user approves it for that deliverable" in text
    assert "exactly one reviewer that the mapping below selects" in text
    assert "| Claude | `gpt-6.1-sol` or `gpt-6-astra` | `high` or `xhigh` |" in text
    assert "| GPT | `claude-opus-5-5` or `claude-fable-5-1` | `high` or `xhigh` |" in text
    assert "the `review_model` setting" not in text
    assert "Code that a delegated worker wrote belongs to that worker's model family." in text
    assert "A role runner exit code 3 or 4 means the same." in text
    assert "do not substitute" in text
    assert ".ko.md" not in text
    assert text.index("| Authoring model family | Reviewer | Reasoning effort |") > 0
    assert "verify the actual model and effort from host records" in text
    assert "Include necessary untracked files" in text
    assert "Do not enable extra billing or change authentication" in text
    assert "Routine author inspection and required tests still run" in text
