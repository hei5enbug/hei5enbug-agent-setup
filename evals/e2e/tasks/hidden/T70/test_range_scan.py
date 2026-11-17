import subprocess

from guardkit.boundary import Finding, scan_range, scan_text

TOKEN = "demo_tok_" + "Q9w8E7r6T5y4U3i2"
URL = "https://demo:hunter2@example.com/repo"


def git(repo, *args):
    env = {"GIT_AUTHOR_NAME": "Demo", "GIT_AUTHOR_EMAIL": "demo@example.com", "GIT_COMMITTER_NAME": "Demo",
           "GIT_COMMITTER_EMAIL": "demo@example.com", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=repo, env=env, check=True,
                          capture_output=True, text=True).stdout.strip()


def commit(repo, files, message, remove=()):
    for name, text in files.items():
        (repo / name).write_text(text)
    for name in remove:
        (repo / name).unlink()
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def start(repo, files=None):
    git(repo, "init", "-q", "-b", "main")
    return commit(repo, files or {"a.txt": "hello\n"}, "base")


def test_a_value_added_and_removed_inside_the_range_is_still_found(tmp_path):
    base = start(tmp_path)
    added = commit(tmp_path, {"b.txt": f"key {TOKEN}\nmore\n"}, "add key")
    head = commit(tmp_path, {"b.txt": "more\n"}, "remove key")
    assert scan_range(tmp_path, base, head) == [Finding("b.txt", "token", added)]


def test_a_value_in_a_deleted_file_is_found_in_the_commit_that_added_it(tmp_path):
    base = start(tmp_path)
    added = commit(tmp_path, {"x.txt": f"key {TOKEN}\n"}, "add x")
    head = commit(tmp_path, {}, "delete x", remove=["x.txt"])
    assert scan_range(tmp_path, base, head) == [Finding("x.txt", "token", added)]


def test_a_value_already_in_the_base_is_not_reported_and_its_removal_is_not_an_addition(tmp_path):
    base = start(tmp_path, {"a.txt": f"key {TOKEN}\n"})
    head = commit(tmp_path, {"a.txt": "clean\n"}, "clean up")
    assert scan_range(tmp_path, base, head) == []


def test_context_lines_next_to_an_added_line_are_not_scanned(tmp_path):
    base = start(tmp_path, {"a.txt": f"key {TOKEN}\nplain\n"})
    head = commit(tmp_path, {"a.txt": f"key {TOKEN}\nplain\nnew line\n"}, "append")
    assert scan_range(tmp_path, base, head) == []


def test_findings_come_oldest_commit_first_then_by_path(tmp_path):
    base = start(tmp_path)
    first = commit(tmp_path, {"z.txt": f"k {TOKEN}\n", "m.txt": f"k {TOKEN}\n"}, "two files")
    second = commit(tmp_path, {"a.txt": f"see {URL}\n"}, "url")
    assert scan_range(tmp_path, base, second) == [
        Finding("m.txt", "token", first), Finding("z.txt", "token", first), Finding("a.txt", "password-url", second)]


def test_the_same_value_twice_in_one_commit_and_file_is_one_finding(tmp_path):
    base = start(tmp_path)
    added = commit(tmp_path, {"b.txt": f"{TOKEN}\n{TOKEN}\n"}, "twice")
    assert scan_range(tmp_path, base, added) == [Finding("b.txt", "token", added)]


def test_the_commit_is_the_full_sha_and_an_empty_range_has_no_findings(tmp_path):
    base = start(tmp_path)
    added = commit(tmp_path, {"b.txt": f"{TOKEN}\n"}, "add")
    assert len(added) == 40 and scan_range(tmp_path, base, added)[0].commit == added
    assert scan_range(tmp_path, added, added) == []


def test_scan_text_is_unchanged():
    assert scan_text(f"x {TOKEN}", "p", "c") == [Finding("p", "token", "c")]
