#!/usr/bin/env python3
"""
Quick validation script for skills - minimal version
"""

import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:
    yaml = None

PYYAML_INSTALL_HINT = (
    "PyYAML is required to read SKILL.md frontmatter. Install it with: "
    "python3 -m pip install pyyaml"
)
CHECK_TIMEOUT_SECONDS = 60
# Returncode recorded when a bundled check is killed for running too long.
CHECK_TIMEOUT_RETURNCODE = None


class MissingDependencyError(RuntimeError):
    """Raised when PyYAML is not installed."""


def split_frontmatter(content):
    """Return (frontmatter_text, body) or raise ValueError when SKILL.md has no frontmatter."""
    if not content.startswith('---'):
        raise ValueError("No YAML frontmatter found")
    match = re.match(r'^---\n(.*?)\n---(?:\n|$)', content, re.DOTALL)
    if not match:
        raise ValueError("Invalid frontmatter format")
    return match.group(1), content[match.end():]


def parse_frontmatter(frontmatter_text):
    """Parse top-level skill metadata with PyYAML."""
    if yaml is None:
        raise MissingDependencyError(PYYAML_INSTALL_HINT)
    try:
        parsed = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in frontmatter: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Frontmatter must be a YAML dictionary")
    return parsed


def run_bundled_checks(skill_path, timeout_seconds=CHECK_TIMEOUT_SECONDS):
    """Run every scripts/check_*.py bundled with the skill.

    A detector exits non-zero when it finds a violation. Returns
    (ok, [(script_name, returncode, output)]) and treats a missing
    scripts/ directory as a pass. A detector that exceeds the timeout is
    killed and recorded with CHECK_TIMEOUT_RETURNCODE.
    """
    skill_path = Path(skill_path)
    detectors = sorted((skill_path / "scripts").glob("check_*.py"))
    results = []
    ok = True
    for detector in detectors:
        try:
            completed = subprocess.run(
                [sys.executable, str(detector), str(skill_path)],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            results.append((
                detector.name,
                CHECK_TIMEOUT_RETURNCODE,
                f"timed out after {timeout_seconds} seconds",
            ))
            ok = False
            continue
        output = (completed.stdout + completed.stderr).strip()
        results.append((detector.name, completed.returncode, output))
        if completed.returncode != 0:
            ok = False
    return ok, results


def check_status(returncode):
    """Human-readable status label for a bundled check result."""
    if returncode is CHECK_TIMEOUT_RETURNCODE:
        return "TIMEOUT"
    return "pass" if returncode == 0 else "FAIL"


def validate_skill(skill_path):
    """Basic validation of a skill"""
    skill_path = Path(skill_path)

    # Check SKILL.md exists
    skill_md = skill_path / 'SKILL.md'
    if not skill_md.exists():
        return False, "SKILL.md not found"

    content = skill_md.read_text()
    try:
        frontmatter_text, _ = split_frontmatter(content)
        frontmatter = parse_frontmatter(frontmatter_text)
    except ValueError as exc:
        return False, str(exc)

    # Define allowed properties
    ALLOWED_PROPERTIES = {'name', 'description', 'license', 'allowed-tools', 'metadata', 'compatibility'}

    # Check for unexpected properties (excluding nested keys under metadata)
    unexpected_keys = set(frontmatter.keys()) - ALLOWED_PROPERTIES
    if unexpected_keys:
        return False, (
            f"Unexpected key(s) in SKILL.md frontmatter: {', '.join(sorted(unexpected_keys))}. "
            f"Allowed properties are: {', '.join(sorted(ALLOWED_PROPERTIES))}"
        )

    # Check required fields
    if 'name' not in frontmatter:
        return False, "Missing 'name' in frontmatter"
    if 'description' not in frontmatter:
        return False, "Missing 'description' in frontmatter"

    # Extract name for validation
    name = frontmatter.get('name', '')
    if not isinstance(name, str):
        return False, f"Name must be a string, got {type(name).__name__}"
    name = name.strip()
    if not name:
        return False, "Name cannot be empty"
    # Check naming convention (kebab-case: lowercase with hyphens)
    if not re.match(r'^[a-z0-9-]+$', name):
        return False, f"Name '{name}' should be kebab-case (lowercase letters, digits, and hyphens only)"
    if name.startswith('-') or name.endswith('-') or '--' in name:
        return False, f"Name '{name}' cannot start/end with hyphen or contain consecutive hyphens"
    # Check name length (max 64 characters per spec)
    if len(name) > 64:
        return False, f"Name is too long ({len(name)} characters). Maximum is 64 characters."

    # Extract and validate description
    description = frontmatter.get('description', '')
    if not isinstance(description, str):
        return False, f"Description must be a string, got {type(description).__name__}"
    description = description.strip()
    if not description:
        return False, "Description cannot be empty"
    # Check for angle brackets
    if '<' in description or '>' in description:
        return False, "Description cannot contain angle brackets (< or >)"
    # Check description length (max 1024 characters per spec)
    if len(description) > 1024:
        return False, f"Description is too long ({len(description)} characters). Maximum is 1024 characters."

    # Validate compatibility field if present (optional)
    compatibility = frontmatter.get('compatibility', '')
    if compatibility:
        if not isinstance(compatibility, str):
            return False, f"Compatibility must be a string, got {type(compatibility).__name__}"
        if len(compatibility) > 500:
            return False, f"Compatibility is too long ({len(compatibility)} characters). Maximum is 500 characters."

    return True, "Skill is valid!"


def main():
    if len(sys.argv) != 2:
        print("Usage: python quick_validate.py <skill_directory>")
        sys.exit(1)

    skill_path = sys.argv[1]
    try:
        valid, message = validate_skill(skill_path)
    except MissingDependencyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)
    print(message)
    if not valid:
        sys.exit(1)

    checks_ok, results = run_bundled_checks(skill_path)
    for name, returncode, output in results:
        print(f"[{check_status(returncode)}] {name}")
        if output:
            print(output)
    sys.exit(0 if checks_ok else 1)


if __name__ == "__main__":
    main()
