"""Shared utilities for skill-builder scripts."""

from pathlib import Path

from scripts.quick_validate import parse_frontmatter, split_frontmatter


def _string_field(frontmatter: dict, key: str) -> str:
    value = frontmatter.get(key, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"SKILL.md frontmatter '{key}' must be a string, got {type(value).__name__}")
    return value.strip()


def parse_skill_md(skill_path: Path) -> tuple[str, str, str]:
    """Parse a SKILL.md file, returning (name, description, full_content).

    Uses the same frontmatter parser as quick_validate so every consumer sees
    identical metadata.
    """
    content = (skill_path / "SKILL.md").read_text()
    frontmatter_text, _ = split_frontmatter(content)
    frontmatter = parse_frontmatter(frontmatter_text)
    return _string_field(frontmatter, "name"), _string_field(frontmatter, "description"), content
