"""Shared secret token patterns: the JSON contract and the Python redaction that uses it."""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PATTERNS_PATH = REPO_ROOT / "config" / "secret-patterns.json"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import approval_state as state_mod  # noqa: E402

ALNUM = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
UPPER_DIGITS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
URL_SAFE = ALNUM + "_-"
BASE64 = ALNUM + "+/"


def fake(length, alphabet=ALNUM, seed=1):
    return "".join(alphabet[(index * 7 + seed * 13 + index // 5) % len(alphabet)] for index in range(length))


def pem(kind="RSA PRIVATE KEY"):
    return f"-----BEGIN {kind}-----\n{fake(64, BASE64, 2)}\n{fake(64, BASE64, 3)}\n-----END {kind}-----"


def jwt():
    return f"eyJ{fake(20, URL_SAFE, 1)}.eyJ{fake(30, URL_SAFE, 2)}.{fake(43, URL_SAFE, 3)}"


# name -> (text builder, masked text builder); an unlabeled token masks its whole span.
POSITIVE = {
    "private-key": (lambda: f"key:\n{pem()}\nend", lambda: "key:\n[REDACTED:private-key]\nend"),
    "jwt": (lambda: f"t={jwt()}", lambda: "t=[REDACTED:jwt]"),
    "aws-access-key-id": (lambda: f"id AKIA{fake(16, UPPER_DIGITS)} x", lambda: "id [REDACTED:aws-access-key-id] x"),
    "aws-secret-access-key": (
        lambda: f"aws_secret_access_key = {fake(40, BASE64)}",
        lambda: "aws_secret_access_key = [REDACTED:aws-secret-access-key]",
    ),
    "github-token": (lambda: f"gh ghp_{fake(36)}", lambda: "gh [REDACTED:github-token]"),
    "github-pat": (lambda: f"github_pat_{fake(70, ALNUM + '_')}", lambda: "[REDACTED:github-pat]"),
    "gitlab-token": (lambda: f"glpat-{fake(20, URL_SAFE)}", lambda: "[REDACTED:gitlab-token]"),
    "slack-token": (lambda: f"xox{'b'}-{fake(12, '0123456789')}-{fake(24)}", lambda: "[REDACTED:slack-token]"),
    "slack-webhook": (
        lambda: f"https://hooks.slack.com/services/T{fake(8, UPPER_DIGITS)}/B{fake(8, UPPER_DIGITS)}/{fake(24)}",
        lambda: "[REDACTED:slack-webhook]",
    ),
    "anthropic-key": (lambda: f"sk-ant-api03-{fake(60, URL_SAFE)}", lambda: "[REDACTED:anthropic-key]"),
    "openai-key": (lambda: f"sk-proj-{fake(60, URL_SAFE)}", lambda: "[REDACTED:openai-key]"),
    "google-api-key": (lambda: f"AIza{fake(35, URL_SAFE)}", lambda: "[REDACTED:google-api-key]"),
    "stripe-key": (lambda: f"sk_live_{fake(30)}", lambda: "[REDACTED:stripe-key]"),
    "azure-storage-key": (
        lambda: f"DefaultEndpointsProtocol=https;AccountKey={fake(86, BASE64)}==;EndpointSuffix=core.windows.net",
        lambda: "DefaultEndpointsProtocol=https;AccountKey=[REDACTED:azure-storage-key];EndpointSuffix=core.windows.net",
    ),
    "azure-sas-signature": (
        lambda: f"https://demo.blob.example.com/c?sv=2024-01-01&sig={fake(43, BASE64)}%3D&se=2030",
        lambda: "https://demo.blob.example.com/c?sv=2024-01-01&sig=[REDACTED:azure-sas-signature]&se=2030",
    ),
    "bearer-token": (
        lambda: f"Authorization: Bearer {fake(30, URL_SAFE)}9",
        lambda: "Authorization: Bearer [REDACTED:bearer-token]",
    ),
    "url-password": (
        lambda: f"postgres://demo:{fake(14)}@db.example.com:5432/app",
        lambda: "postgres://demo:[REDACTED:url-password]@db.example.com:5432/app",
    ),
}

header = "-----BEGIN ENCRYPTED PRIVATE" + " KEY-----"
footer = "-----END ENCRYPTED PRIVATE" + " KEY-----"
EXTRA_POSITIVE = [
    (
        lambda: f"{header}\n{fake(30, BASE64, 5)}\n{fake(30, BASE64, 6)}\n{footer}",
        lambda: "[REDACTED:private-key]",
    ),
    (
        lambda: f"postgres://demo:p%40ss%23{fake(10)}%21@db.example.com/app",
        lambda: "postgres://demo:[REDACTED:url-password]@db.example.com/app",
    ),
    (
        lambda: f"{pem('OPENSSH PRIVATE KEY')}\n{pem('PRIVATE KEY')}",
        lambda: "[REDACTED:private-key]\n[REDACTED:private-key]",
    ),
    (
        lambda: f"{header}\nProc-Type: 4,ENCRYPTED\n\n{fake(64, BASE64, 4)}\n{footer}",
        lambda: "[REDACTED:private-key]",
    ),
]

NEAR_MISSES = [
    "AKIA" + "A1B2C3D4E5F6G7H",
    "id " + "AKIA" + "Q" * 16,
    "ghp_" + fake(35),
    "ghp_" + "a" * 36,
    "github_pat_" + fake(40, ALNUM + "_"),
    "glpat-" + fake(10, URL_SAFE),
    "xox" + "b-short",
    "https://hooks.slack.com/services/T0001/B0001/short",
    "sk-" + fake(20),
    "sk-ant-" + fake(10, URL_SAFE),
    "sk-learn-pipeline-with-a-long-kebab-case-name-for-testing-purposes",
    "AIza" + fake(20, URL_SAFE),
    "sk_live_" + fake(10),
    "sk_test_" + "x" * 30,
    "eyJ" + fake(5) + ".eyJ" + fake(5) + "." + fake(5),
    "AccountKey=" + fake(10, BASE64),
    "?sig=" + fake(10, BASE64),
    "Authorization: Bearer $TOKEN",
    "Authorization: Bearer YOUR_TOKEN_HERE",
    "Authorization: Bearer <token>",
    "aws_secret_access_key = config.get('secret')",
    f"aws_secret_access_key = {fake(30, BASE64)}",
    "api_key = config.get('api_key')",
    "TOKEN=",
    "TOKEN=<your-token>",
    "API_KEY=changeme",
    "password = os.environ['DB_PASSWORD']",
    "postgres://demo:${DB_PASSWORD}@db.example.com/app",
    "postgres://demo:<password>@db.example.com/app",
    "postgres://demo:password@db.example.com/app",
    "postgres://demo:****@db.example.com/app",
    "postgres://demo@db.example.com/app",
    "http://localhost:8080/path@x",
    "-----BEGIN PUBLIC KEY-----\nabc\n-----END PUBLIC KEY-----",
    "-----BEGIN RSA PRIVATE" + " KEY----- without an end line",
    "-----BEGIN PRIVATE" + " KEY-----\n<your-private-key>\n-----END PRIVATE" + " KEY-----",
    "-----BEGIN RSA PRIVATE" + " KEY-----\nMIIEpAIBAAKCAQEA...\n-----END RSA PRIVATE" + " KEY-----",
    "-----BEGIN PRIVATE" + " KEY-----\npaste your private key content here from the secrets manager\n-----END PRIVATE" + " KEY-----",
    "postgres://demo:%DB_PASSWORD%@db.example.com/app",
    "postgres://demo:%(db_password)s@db.example.com/app",
    "postgres://demo:[password]@db.example.com/app",
    "commit 3f786850e387550fdab836ed7e6dc881de23001b",
    "id 123e4567-e89b-12d3-a456-426614174000",
    "sha256:" + "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
]


@pytest.fixture
def patterns():
    return json.loads(PATTERNS_PATH.read_text(encoding="utf-8"))["patterns"]


@pytest.fixture(autouse=True)
def fresh_cache():
    state_mod.shared_patterns.cache_clear()
    yield
    state_mod.shared_patterns.cache_clear()


def test_every_pattern_compiles_and_has_a_positive_case(patterns):
    names = [entry["name"] for entry in patterns]

    assert len(names) == len(set(names))
    assert set(names) == set(POSITIVE)
    for entry in patterns:
        re.compile(entry["pattern"], re.I if "i" in entry.get("flags", "") else 0)
        if entry.get("partial"):
            assert re.compile(entry["pattern"]).groups == 3


@pytest.mark.parametrize("name", sorted(POSITIVE))
def test_pattern_masks_a_runtime_built_token_and_keeps_its_context(name):
    build, expected = POSITIVE[name]

    assert state_mod.redact_tokens(build()) == expected()


@pytest.mark.parametrize("index", range(len(EXTRA_POSITIVE)))
def test_extra_positive_cases_mask(index):
    build, expected = EXTRA_POSITIVE[index]

    assert state_mod.redact_tokens(build()) == expected()


@pytest.mark.parametrize("text", NEAR_MISSES)
def test_near_misses_stay_untouched(text):
    assert state_mod.redact_tokens(text) == text


def test_redact_applies_shared_patterns_after_its_own_rules():
    token = f"ghp_{fake(36)}"

    text = state_mod.redact(f"git push https://x-access-token:{token}@example.com/o/r.git && echo {token}")

    assert token not in text
    assert "[REDACTED:github-token]" in text
    assert "https://***@example.com" in text


def test_redact_keeps_existing_rules_unchanged():
    assert state_mod.redact("curl -u demo:pw https://example.com") == "curl -u *** https://example.com"
    assert state_mod.redact("DB_PASSWORD=hunter2 run") == "DB_PASSWORD=*** run"


def test_redact_survives_a_missing_or_invalid_patterns_file(tmp_path, monkeypatch):
    token = f"ghp_{fake(36)}"
    reference = state_mod.redact("DB_PASSWORD=hunter2 run")
    for content in (None, "not json", "{}", json.dumps({"patterns": [{"name": "x", "pattern": "("}]})):
        path = tmp_path / "patterns.json"
        path.unlink(missing_ok=True)
        if content is not None:
            path.write_text(content, encoding="utf-8")
        monkeypatch.setattr(state_mod, "SECRET_PATTERNS_PATH", path)
        state_mod.shared_patterns.cache_clear()

        assert state_mod.shared_patterns() == ()
        assert state_mod.redact("DB_PASSWORD=hunter2 run") == reference
        assert state_mod.redact(f"echo {token}") == f"echo {token}"


NODE_RUNNER = """
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
const [, , source, work] = process.argv;
writeFileSync(`${work}/language.js`, readFileSync(join(dirname(source), "language.js"), "utf8"));
writeFileSync(`${work}/redact.mjs`, readFileSync(source, "utf8"));
const { compilePatterns, maskText } = await import(`${work}/redact.mjs`);
const input = JSON.parse(readFileSync(`${work}/input.json`, "utf8"));
const patterns = compilePatterns(input.patterns);
const masked = (text) => maskText(text, patterns).text;
console.log(JSON.stringify({
  positive: Object.fromEntries(Object.entries(input.positive).map(([name, text]) => [name, masked(text)])),
  near: input.near.map(masked),
}));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_javascript_mod_masks_the_same_tokens_with_the_same_file(tmp_path):
    (tmp_path / "input.json").write_text(
        json.dumps({
            "patterns": PATTERNS_PATH.read_text(encoding="utf-8"),
            "positive": {
                **{name: build() for name, (build, _) in POSITIVE.items()},
                **{f"extra-{index}": build() for index, (build, _) in enumerate(EXTRA_POSITIVE)},
            },
            "near": NEAR_MISSES,
        }),
        encoding="utf-8",
    )
    (tmp_path / "run.mjs").write_text(NODE_RUNNER, encoding="utf-8")

    done = subprocess.run(
        ["node", str(tmp_path / "run.mjs"), str(REPO_ROOT / "hooks" / "mod" / "redact.js"), str(tmp_path)],
        capture_output=True, text=True, timeout=60, check=False,
    )

    assert done.returncode == 0, done.stderr
    output = json.loads(done.stdout)
    assert output["positive"] == {
        **{name: expected() for name, (_, expected) in POSITIVE.items()},
        **{f"extra-{index}": expected() for index, (_, expected) in enumerate(EXTRA_POSITIVE)},
    }
    assert output["near"] == NEAR_MISSES
