"""Acceptance checks of issue 76 that need no session state: which declared entries a grant keeps, which grant values it
accepts, and which write or MCP call a kept entry matches. Every target is fictional and nothing runs; the guard only
classifies."""
import pytest

from test_approval_guard import SCRIPTS, fake_bin, state  # noqa: F401

from approval_state_declared import (  # noqa: E402
    grant_values, keep_verdict, match_command, match_mcp, merge_grants,
)
from approval_state_entries import Entry  # noqa: E402

SKILL = "demo-run"
DEV = ("dev-ctx",)


def command(example, *, never=None, destructive=False):
    return Entry(SKILL, command=example, never=never or {}, destructive=destructive)


def tool(name, arguments, *, destructive=False):
    return Entry(SKILL, tool=name, arguments=arguments, destructive=destructive)


def kept(*entries, cwd):
    """The entries a grant keeps, so a test matches against what the guard would hold."""
    return [entry for entry in entries if keep_verdict(entry, str(cwd)).kept]


def runs(text, entries, cwd, grants=None):
    return match_command(text, entries, {SKILL: grants or {}}, str(cwd))


AZ_PR = command("az repos pr update --status completed")
PUSH_BRANCH = command("git push -u origin <branch:feature/*>")
PUSH_TAG = command("git push upstream <tag:v*-stg>")
RESTART = command("kubectl rollout restart <workload> -n <ns:demo> --context <ctx:dev-ctx|stg-ctx>")
RESTART_OPEN = command("kubectl rollout restart <workload> -n <ns:demo> --context <ctx>")
RESTART_GRANT = command("kubectl rollout restart <workload> -n <ns:@grant> --context <ctx:@grant>",
                        never={"ctx": ("prod-ctx",)})
DELETE_HOSTS = "curl -X DELETE https://<host:api.dev.example.com|api.stg.example.com>/<path>"
MERGE_BODY = (
    "az rest --method patch --uri https://dev.example.com/<project>/pulls/<id> --body "
    "'{\"status\":\"completed\",\"completionOptions\":{\"mergeStrategy\":\"<strategy:rebase>\","
    "\"deleteSourceBranch\":false}}'"
)
POST_TOOL = "mcp__demo__demo_post_message"
RECORDS_TOOL = "mcp__demo__demo_records"


def test_완료_예시는_추가_옵션이_붙은_완료_명령과_일치하고_포기_명령과는_일치하지_않는다(state, fake_bin):
    # given
    held = kept(AZ_PR, cwd=state)
    # when
    completed = runs("az repos pr update --id 1 --status completed --squash true", held, state)
    abandoned = runs("az repos pr update --id 1 --status abandoned", held, state)
    # then
    assert completed is AZ_PR
    assert abandoned is None


def test_브랜치_푸시_예시는_feature_브랜치만_일치시키고_강제_푸시는_일치시키지_않는다(state, fake_bin):
    # given
    held = kept(PUSH_BRANCH, cwd=state)
    # when
    feature = runs("git push -u origin feature/ABC-9", held, state)
    default_branch = runs("git push -u origin main", held, state)
    forced = runs("git push --force origin feature/ABC-9", held, state)
    # then
    assert (feature, default_branch, forced) == (PUSH_BRANCH, None, None)


@pytest.mark.parametrize("example", [
    "git push --force -u origin <branch:feature/*>",
    "git push --force-with-lease origin <branch:feature/*>",
    "git push -f origin <branch:feature/*>",
    "git push --delete origin <branch:feature/*>",
    "git push -d origin <branch:feature/*>",
    "git push --mirror origin",
    "git push origin +<branch:feature/*>",
    "git push origin :<branch:feature/*>",
    "git push",
    "git push -u",
    "git push origin",
    "git push <remote> <branch:feature/*>",
])
def test_강제_삭제_푸시와_원격이나_refspec을_밝히지_않은_푸시_예시는_버려진다(state, fake_bin, example):
    # given
    entry = command(example)
    # when
    verdict = keep_verdict(entry, str(state))
    # then
    assert verdict.kept is False
    assert verdict.reason


def test_인수_없는_git_push는_예시가_있어도_일치하지_않는다(state, fake_bin):
    # given
    held = kept(PUSH_BRANCH, command("git push"), cwd=state)
    # when
    matched = runs("git push", held, state)
    # then
    assert matched is None


def test_태그_푸시_예시는_스테이징_태그만_일치시킨다(state, fake_bin):
    # given
    held = kept(PUSH_TAG, cwd=state)
    # when
    staging = runs("git push upstream v2.0.1-stg", held, state)
    release = runs("git push upstream v2.0.1", held, state)
    # then
    assert (staging, release) == (PUSH_TAG, None)


@pytest.mark.parametrize("text", [
    "git push origin +feature/demo",
    "git push origin feature/demo:main",
    "git push origin staging-1:refs/tags/release-1",
])
def test_열린_ref_푸시_예시는_유지되지만_강제_또는_콜론_refspec_푸시는_일치하지_않는다(state, fake_bin, text):
    # given
    open_ref = command("git push origin <ref>")
    held = kept(open_ref, cwd=state)
    # when
    matched = runs(text, held, state)
    # then
    assert held == [open_ref]
    assert matched is None


def test_열린_ref_푸시_예시는_일반_브랜치_푸시와_일치한다(state, fake_bin):
    # given
    open_ref = command("git push origin <ref>")
    held = kept(open_ref, cwd=state)
    # when
    matched = runs("git push origin feature/demo", held, state)
    # then
    assert matched is open_ref


def test_태그_예시는_콜론이_든_태그_값과_일치하지_않는다(state, fake_bin):
    # given
    held = kept(PUSH_TAG, cwd=state)
    # when
    matched = runs("git push upstream v2-stg:refs/tags/v2", held, state)
    # then
    assert matched is None


@pytest.mark.parametrize(("text", "expected"), [
    ("kubectl rollout restart deployment/demo -n demo --context dev-ctx", True),
    ("kubectl rollout restart statefulset/other -n demo --context stg-ctx", True),
    ("kubectl rollout restart deployment/demo -n demo --context prod-ctx", False),
    ("kubectl rollout restart deployment/demo -n demo", False),
    ("kubectl rollout restart deployment/demo -n other --context dev-ctx", False),
    ("kubectl rollout restart deployment/demo --namespace=demo --context dev-ctx", False),
    ("kubectl rollout restart deployment/demo -n demo --context=dev-ctx", True),
])
def test_재시작_예시는_나열한_컨텍스트와_네임스페이스에서만_일치한다(state, fake_bin, text, expected):
    # given
    held = kept(RESTART, cwd=state)
    # when
    matched = runs(text, held, state)
    # then
    assert (matched is RESTART) is expected


def test_컨텍스트가_열린_재시작_예시는_버려지고_prod_재시작은_일치하지_않는다(state, fake_bin):
    # given
    verdict = keep_verdict(RESTART_OPEN, str(state))
    held = kept(RESTART_OPEN, cwd=state)
    # when
    matched = runs("kubectl rollout restart deployment/demo -n demo --context prod-ctx", held, state)
    # then
    assert verdict.kept is False
    assert "ctx" in verdict.reason
    assert matched is None


def test_삭제_예시는_destructive가_참이고_호스트를_나열했을_때만_그_호스트의_삭제와_일치한다(state, fake_bin):
    # given
    held = kept(command(DELETE_HOSTS, destructive=True), cwd=state)
    # when
    dev = runs("curl -X DELETE https://api.dev.example.com/records/one", held, state)
    other = runs("curl -X DELETE https://api.example.com/records/one", held, state)
    # then
    assert dev is held[0]
    assert other is None


def test_destructive가_없는_삭제_예시는_버려지고_삭제는_일치하지_않는다(state, fake_bin):
    # given
    entry = command(DELETE_HOSTS)
    held = kept(entry, cwd=state)
    # when
    matched = runs("curl -X DELETE https://api.dev.example.com/records/one", held, state)
    # then
    assert held == []
    assert matched is None


def test_호스트가_글롭인_삭제_예시는_destructive여도_버려진다(state, fake_bin):
    # given
    entry = command("curl -X DELETE https://<host:*.example.com>/<path>", destructive=True)
    # when
    verdict = keep_verdict(entry, str(state))
    # then
    assert verdict.kept is False
    assert "host" in verdict.reason


def test_경로가_고정된_삭제_예시는_다른_경로의_삭제와_일치하지_않는다(state, fake_bin):
    # given
    entry = command("curl -X DELETE https://api.dev.example.com/records/one", destructive=True)
    held = kept(entry, cwd=state)
    # when
    same = runs("curl -X DELETE https://api.dev.example.com/records/one", held, state)
    other = runs("curl -X DELETE https://api.dev.example.com/records/two", held, state)
    # then
    assert (same, other) == (entry, None)


@pytest.mark.parametrize(("arguments", "expected"), [
    ({"channel": "C123", "text": "hello"}, True),
    ({"channel": "C999", "text": "hello"}, False),
    ({"text": "hello"}, False),
])
def test_채널_인수를_적은_MCP_항목은_그_채널의_호출만_일치시킨다(state, fake_bin, arguments, expected):
    # given
    entry = tool(POST_TOOL, {"channel": "C123"})
    held = kept(entry, cwd=state)
    # when
    matched = match_mcp(POST_TOOL, arguments, held, {SKILL: {}}, str(state))
    # then
    assert held == [entry]
    assert (matched is entry) is expected


def test_다른_서버의_같은_이름_MCP_도구는_일치하지_않는다(state, fake_bin):
    # given
    entry = tool(POST_TOOL, {"channel": "C123"})
    # when
    matched = match_mcp("mcp__other__demo_post_message", {"channel": "C123"}, [entry], {SKILL: {}}, str(state))
    # then
    assert matched is None


def test_destructive가_없는_MCP_항목은_파괴적으로_분류된_호출과_일치하지_않는다(state, fake_bin):
    # given
    entry = tool(RECORDS_TOOL, {"table": "qa_items"})
    held = kept(entry, cwd=state)
    # when
    update = match_mcp(RECORDS_TOOL, {"table": "qa_items", "action": "update"}, held, {SKILL: {}}, str(state))
    delete = match_mcp(RECORDS_TOOL, {"table": "qa_items", "action": "delete"}, held, {SKILL: {}}, str(state))
    # then
    assert (update, delete) == (entry, None)


def test_destructive가_참인_MCP_항목은_파괴적_호출과_일치하되_치명적_SQL_호출과는_일치하지_않는다(state, fake_bin):
    # given
    entry = tool(RECORDS_TOOL, {"table": "qa_items"}, destructive=True)
    held = kept(entry, cwd=state)
    # when
    delete = match_mcp(RECORDS_TOOL, {"table": "qa_items", "action": "delete"}, held, {SKILL: {}}, str(state))
    critical = match_mcp(RECORDS_TOOL, {"table": "qa_items", "sql": "delete from qa_items"}, held, {SKILL: {}},
                         str(state))
    # then
    assert (delete, critical) == (entry, None)


def test_grant에서_받는_재시작_예시는_grant한_값에서만_일치한다(state, fake_bin):
    # given
    held = kept(RESTART_GRANT, cwd=state)
    grants = {"ctx": ("dev-ctx",), "ns": ("demo",)}
    # when
    granted = runs("kubectl rollout restart deployment/demo -n demo --context dev-ctx", held, state, grants)
    not_granted = runs("kubectl rollout restart deployment/demo -n demo --context stg-ctx", held, state, grants)
    nothing = runs("kubectl rollout restart deployment/demo -n demo --context dev-ctx", held, state)
    # then
    assert held == [RESTART_GRANT]
    assert (granted, not_granted, nothing) == (RESTART_GRANT, None, None)


def test_never_목록의_값은_grant가_거절하고_일치도_허용하지_않으며_나중_grant가_값을_더한다(state, fake_bin):
    # given
    first = grant_values([RESTART_GRANT], {"ctx": ["dev-ctx", "prod-ctx"], "ns": ["demo"]})
    held_grants = merge_grants({}, first.accepted)
    later = grant_values([RESTART_GRANT], {"ctx": ["stg-ctx"]})
    merged = merge_grants(held_grants, later.accepted)
    held = kept(RESTART_GRANT, cwd=state)
    # when
    forged = runs("kubectl rollout restart deployment/demo -n demo --context prod-ctx", held, state,
                  {"ctx": ("prod-ctx",), "ns": ("demo",)})
    added = runs("kubectl rollout restart deployment/demo -n demo --context stg-ctx", held, state, merged)
    # then
    assert first.accepted == {"ctx": ("dev-ctx",), "ns": ("demo",)}
    assert [(name, value) for name, value, _ in first.refused] == [("ctx", "prod-ctx")]
    assert merged == {"ctx": ("dev-ctx", "stg-ctx"), "ns": ("demo",)}
    assert (forged, added) == (None, RESTART_GRANT)


@pytest.mark.parametrize(("name", "value"), [
    ("unknown", "dev-ctx"),
    ("ctx", ""),
    ("ctx", "dev ctx"),
    ("ctx", "$(id)"),
])
def test_grant는_받는_이름이_아니거나_쓸_수_없는_값을_거절하고_이유를_알린다(name, value):
    # given
    requested = {name: [value]}
    # when
    result = grant_values([RESTART_GRANT], requested)
    # then
    assert result.accepted == {}
    assert [(refused, text) for refused, text, _ in result.refused] == [(name, value)]


@pytest.mark.parametrize(("body", "expected"), [
    ('{"status":"completed","completionOptions":{"mergeStrategy":"rebase","deleteSourceBranch":false}}', True),
    ('{"completionOptions":{"deleteSourceBranch":false,"mergeStrategy":"rebase"},"status":"completed"}', True),
    ('{"status":"completed","completionOptions":{"mergeStrategy":"rebase","deleteSourceBranch":true}}', False),
    ('{"status":"completed","extra":1,"completionOptions":{"mergeStrategy":"rebase","deleteSourceBranch":false}}',
     False),
    ('{"status":"completed","completionOptions":{"mergeStrategy":"rebase"}}', False),
    ('{"status":"abandoned","completionOptions":{"mergeStrategy":"rebase","deleteSourceBranch":false}}', False),
    ('{"status":"completed","completionOptions":{"mergeStrategy":"squash","deleteSourceBranch":false}}', False),
    ('{"status":"completed","completionOptions":{"mergeStrategy":"rebase","deleteSourceBranch":0}}', False),
    ('{"status":"abandoned","status":"completed","completionOptions":{"mergeStrategy":"rebase",'
     '"deleteSourceBranch":false}}', False),
    ("@body.json", False),
])
def test_JSON_본문_예시는_키와_값이_정확히_같은_인라인_본문만_일치시킨다(state, fake_bin, body, expected):
    # given
    entry = command(MERGE_BODY)
    held = kept(entry, cwd=state)
    text = f"az rest --method patch --uri https://dev.example.com/demo/pulls/5 --body '{body}'"
    # when
    matched = runs(text, held, state)
    # then
    assert held == [entry]
    assert (matched is entry) is expected


def test_따옴표_없는_파일_본문_옵션_등호_형태도_일치하지_않는다(state, fake_bin):
    # given
    held = kept(command(MERGE_BODY), cwd=state)
    # when
    matched = runs("az rest --method patch --uri https://dev.example.com/demo/pulls/5 --body=@body.json", held, state)
    # then
    assert matched is None


@pytest.mark.parametrize("text", [
    "az repos pr update --id 1 --status completed | cat",
    "az repos pr update --id 1 --status completed > out.txt",
    "az repos pr update --id $(id) --status completed",
    "az repos pr update --id 1 --status completed && az repos pr update --id 2 --status abandoned",
    "az repos pr update --id 1 --status completed --subscription other-sub",
    "az repos pr update extra --id 1 --status completed",
    "FOO=1 az repos pr update --id 1 --status completed",
])
def test_파이프_치환_연결_다른_구독_추가_위치_인수가_붙은_명령은_일치하지_않는다(state, fake_bin, text):
    # given
    held = kept(AZ_PR, cwd=state)
    # when
    matched = runs(text, held, state)
    # then
    assert matched is None


def test_치명적으로_분류된_삭제는_destructive_항목과_grant가_있어도_일치하지_않는다(state, fake_bin):
    # given
    entry = command("kubectl delete deployment <name> -n <ns:@grant> --context <ctx:@grant>", destructive=True)
    held = kept(entry, cwd=state)
    grants = {"ctx": ("prod-ctx", "dev-ctx"), "ns": ("demo",)}
    # when
    production = runs("kubectl delete deployment demo -n demo --context prod-ctx", held, state, grants)
    development = runs("kubectl delete deployment demo -n demo --context dev-ctx", held, state, grants)
    # then
    assert held == [entry]
    assert (production, development) == (None, entry)


@pytest.mark.parametrize("example", [
    "kubectl get pods -n <ns:demo>",
    "kubectl describe pod <name> -n <ns:demo>",
    "cat <file>",
    "mytool --apply <thing>",
])
def test_읽기이거나_분류되지_않는_명령_예시는_버려진다(state, fake_bin, example):
    # given
    entry = command(example)
    # when
    verdict = keep_verdict(entry, str(state))
    # then
    assert verdict.kept is False


@pytest.mark.parametrize("entry", [
    tool("mcp__demo__demo_get_message", {"channel": "C123"}),
    tool(RECORDS_TOOL, {"table": "qa_items", "action": "delete"}),
])
def test_읽기이거나_파괴적으로_분류된_MCP_항목은_destructive_없이는_버려진다(state, fake_bin, entry):
    # given
    # when
    verdict = keep_verdict(entry, str(state))
    # then
    assert verdict.kept is False


def test_선언이_없으면_어떤_쓰기도_일치하지_않는다(state, fake_bin):
    # given
    entries = []
    # when
    command_match = runs("git push -u origin feature/ABC-9", entries, state)
    mcp_match = match_mcp(POST_TOOL, {"channel": "C123"}, entries, {}, str(state))
    # then
    assert (command_match, mcp_match) == (None, None)


@pytest.mark.parametrize("extra", [
    "--config /tmp/work/extra.conf", "-K /tmp/work/extra.conf", "--url https://api.example.com/records/one",
    "--next", "--data @/tmp/work/body.json",
])
def test_다른_곳에서_설정이나_입력을_읽는_추가_옵션이_있으면_일치하지_않는다(state, fake_bin, extra):
    # given
    held = kept(command(DELETE_HOSTS, destructive=True), cwd=state)
    # when
    matched = runs(f"curl -X DELETE https://api.dev.example.com/records/one {extra}", held, state)
    # then
    assert matched is None


def test_설정을_읽지_않는_추가_옵션은_여전히_일치한다(state, fake_bin):
    # given
    held = kept(AZ_PR, cwd=state)
    # when
    matched = runs("az repos pr update --id 1 --status completed --squash true", held, state)
    # then
    assert matched is held[0]
