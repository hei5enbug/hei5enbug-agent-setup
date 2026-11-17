import subprocess

from guardkit.boundary import scan_range, scan_text

TOKEN = "demo_tok_" + "A1b2C3d4E5f6G7h8"


def git(repo, *args):
    env = {"GIT_AUTHOR_NAME": "Demo", "GIT_AUTHOR_EMAIL": "demo@example.com", "GIT_COMMITTER_NAME": "Demo",
           "GIT_COMMITTER_EMAIL": "demo@example.com", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=repo, env=env, check=True,
                          capture_output=True, text=True).stdout.strip()


def make_repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "a.txt").write_text("hello\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "base")
    return git(tmp_path, "rev-parse", "HEAD")


def test_scan_text_finds_a_token_and_a_url_password():
    kinds = {finding.kind for finding in scan_text(f"key {TOKEN} and https://demo:pw1@example.com/x")}
    assert kinds == {"token", "password-url"}


def test_scan_text_finds_nothing_in_plain_text():
    assert scan_text("nothing to see") == []


def test_a_value_kept_to_the_head_is_found_in_the_range(tmp_path):
    base = make_repo(tmp_path)
    (tmp_path / "b.txt").write_text(f"key {TOKEN}\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "add b")
    head = git(tmp_path, "rev-parse", "HEAD")
    assert [(f.path, f.kind) for f in scan_range(tmp_path, base, head)] == [("b.txt", "token")]


def test_a_clean_range_has_no_findings(tmp_path):
    base = make_repo(tmp_path)
    (tmp_path / "c.txt").write_text("fine\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "add c")
    assert scan_range(tmp_path, base, git(tmp_path, "rev-parse", "HEAD")) == []
