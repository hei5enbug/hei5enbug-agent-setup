import { expect, test } from "claude-code/testing";
import {
  DESTRUCTIVE_REASON,
  READ_VERBS,
  UNVERIFIABLE_REASON,
  classify,
  lex,
  registerApproval,
  toolWordList,
  toolWords,
} from "./approval.js";

const REPO_WITH_V1 = "/repos/with-v1";
const REPO_WITHOUT = "/repos/without-tags";
const NO_REMOTE_REPO = "/repos/no-remote";
const REPOS = {
  [REPO_WITH_V1]: { tags: ["v1"], remotes: ["origin"] },
  [REPO_WITHOUT]: { tags: [], remotes: ["origin"] },
  [NO_REMOTE_REPO]: { tags: [], remotes: [] },
};
const TAG = ["git:tag"];
const PUSH_TAG = ["git:push-tag"];
const TAG_PUSH = ["git:push-tag", "git:tag"];
const RELEASE = ["gh:release"];
const NONE = [];

const NOW = Date.UTC(2026, 9, 7, 12, 0, 0);
const DAY = 24 * 60 * 60 * 1000;
const CORE = { decision: "ask", reason: "core" };
const OK_RESULT = { result: "ok", text: "ok", ref: 1 };

const BASH_CASES = [
  ["tag-plain", `git tag v2`, REPO_WITH_V1, TAG, false, true],
  ["tag-annotated", `git tag -a v2 -m "release notes with $ and * and ;"`, REPO_WITH_V1, TAG, false, true],
  ["tag-annotated-message-flag-long", `git tag -a v2 --message=text`, REPO_WITH_V1, TAG, false, true],
  ["tag-signed", `git tag -s v2 -m notes`, REPO_WITH_V1, TAG, false, true],
  ["tag-with-commit", `git tag v2 HEAD`, REPO_WITH_V1, TAG, false, true],
  ["tag-list-short", `git tag -l`, REPO_WITH_V1, NONE, false, true],
  ["tag-list-long", `git tag --list 'v*'`, REPO_WITH_V1, NONE, false, true],
  ["tag-no-arguments", `git tag`, REPO_WITH_V1, NONE, false, true],
  ["tag-contains", `git tag --contains HEAD`, REPO_WITH_V1, NONE, false, true],
  ["tag-points-at", `git tag --points-at HEAD`, REPO_WITH_V1, NONE, false, true],
  ["tag-names-with-count", `git tag -n5`, REPO_WITH_V1, NONE, false, true],
  ["tag-delete-short", `git tag -d v1`, REPO_WITH_V1, NONE, true, true],
  ["tag-delete-long", `git tag --delete v1`, REPO_WITH_V1, NONE, true, true],
  ["tag-delete-after-name", `git tag v1 -d`, REPO_WITH_V1, NONE, true, true],
  ["tag-delete-in-cluster", `git tag -ad v1`, REPO_WITH_V1, NONE, true, true],
  ["tag-force-moves-a-tag", `git tag -f v1`, REPO_WITH_V1, NONE, true, true],
  ["tag-force-long", `git tag --force v1`, REPO_WITH_V1, NONE, true, true],
  ["tag-dash-c-directory", `git -C ${REPO_WITHOUT} tag x`, REPO_WITH_V1, TAG, false, true],
  ["tag-global-options", `git --no-pager -P -c k=v tag v2`, REPO_WITH_V1, TAG, false, true],
  ["tag-git-dir-option", `git --git-dir=.git tag v2`, REPO_WITH_V1, TAG, false, true],
  ["tag-unsafe-expansion", `git tag $VERSION`, REPO_WITH_V1, NONE, false, false],
  ["tag-unsafe-glob", `git tag v*`, REPO_WITH_V1, NONE, false, false],
  ["tag-unsafe-flag-expansion", `git tag $FLAGS v2`, REPO_WITH_V1, NONE, false, false],
  ["push-tags-with-config", `git -c k=v push --tags`, REPO_WITH_V1, PUSH_TAG, false, true],
  ["push-follow-tags", `git push --follow-tags origin`, REPO_WITH_V1, PUSH_TAG, false, true],
  ["push-refs-tags", `git push origin refs/tags/v1`, REPO_WITH_V1, PUSH_TAG, false, true],
  ["push-refs-tags-missing-locally", `git push origin refs/tags/never-made`, REPO_WITHOUT, PUSH_TAG, false, true],
  ["push-existing-tag-name", `git push origin v1`, REPO_WITH_V1, PUSH_TAG, false, true],
  ["push-existing-tag-with-upstream-flag", `git push -u origin v1`, REPO_WITH_V1, PUSH_TAG, false, true],
  ["push-missing-tag-name-is-ordinary", `git push origin v1`, REPO_WITHOUT, NONE, false, false],
  ["push-existing-tag-in-other-directory", `git -C ${REPO_WITH_V1} push origin v1`, REPO_WITHOUT, PUSH_TAG, false, true],
  ["push-existing-tag-after-cd", `cd ${REPO_WITH_V1} && git push origin v1`, REPO_WITHOUT, PUSH_TAG, false, true],
  ["push-tag-created-earlier", `git tag v7 && git push origin v7`, REPO_WITHOUT, TAG_PUSH, false, true],
  ["push-branch-and-tag-is-ordinary", `git push origin main v1`, REPO_WITH_V1, NONE, false, false],
  ["cd-then-tag-then-push", `cd ${REPO_WITHOUT} && git tag v4 && git push origin v4`, REPO_WITH_V1, TAG_PUSH, false, true],
  ["cd-to-unknown-directory-then-tag-then-push", `cd r && git tag v1 && git push origin v1`, REPO_WITHOUT, TAG_PUSH, false, false],
  ["push-tags-without-remote", `git push --tags`, REPO_WITH_V1, PUSH_TAG, false, true],
  ["push-tags-to-listed-remote", `git push origin --tags`, REPO_WITH_V1, PUSH_TAG, false, true],
  ["push-tags-to-url", `git push https://x.example/r.git --tags`, REPO_WITH_V1, PUSH_TAG, false, false],
  ["push-tags-to-ssh-url", `git push git@x.example:r.git --tags`, REPO_WITH_V1, PUSH_TAG, false, false],
  ["push-tags-to-unlisted-name", `git push evil --tags`, REPO_WITH_V1, PUSH_TAG, false, false],
  ["push-tags-to-path", `git push /tmp/evil --tags`, REPO_WITH_V1, PUSH_TAG, false, false],
  ["push-tags-to-relative-path", `git push ../evil --tags`, REPO_WITH_V1, PUSH_TAG, false, false],
  ["push-tags-with-repo-equals", `git push --repo=evil --tags`, REPO_WITH_V1, PUSH_TAG, false, false],
  ["push-tags-with-repo-flag", `git push --repo evil --tags`, REPO_WITH_V1, PUSH_TAG, false, false],
  ["push-tags-with-repo-flag-after", `git push --tags --repo=https://x.example/r.git`, REPO_WITH_V1, PUSH_TAG, false, false],
  ["push-tags-with-branch-refspec", `git push origin main --tags`, REPO_WITH_V1, PUSH_TAG, false, false],
  ["push-follow-tags-with-branch-refspec", `git push --follow-tags origin main`, REPO_WITH_V1, PUSH_TAG, false, false],
  ["push-tags-with-tag-refspec", `git push origin --tags v1`, REPO_WITH_V1, PUSH_TAG, false, false],
  ["push-existing-tag-to-url", `git push https://x.example/r.git v1`, REPO_WITH_V1, PUSH_TAG, false, false],
  ["push-existing-tag-to-unlisted-name", `git push evil v1`, REPO_WITH_V1, PUSH_TAG, false, false],
  ["push-refs-tags-to-unlisted-name", `git push evil refs/tags/v1`, REPO_WITH_V1, PUSH_TAG, false, false],
  ["push-tags-unknown-option", `git push --receive-pack=evil --tags`, REPO_WITH_V1, PUSH_TAG, false, false],
  ["push-tags-remote-expansion", `git push $REMOTE --tags`, REPO_WITH_V1, PUSH_TAG, false, false],
  ["push-tags-outside-a-repository", `git push origin --tags`, "/", PUSH_TAG, false, false],
  ["push-tags-in-repository-without-remote", `git -C ${NO_REMOTE_REPO} push origin --tags`, REPO_WITH_V1, PUSH_TAG, false, false],
  ["push-plain", `git push`, REPO_WITH_V1, NONE, false, false],
  ["push-branch", `git push origin main`, REPO_WITH_V1, NONE, false, false],
  ["push-single-positional-is-a-remote", `git push v1`, REPO_WITH_V1, NONE, false, false],
  ["push-unknown-option", `git push --receive-pack=evil origin v1`, REPO_WITH_V1, NONE, false, false],
  ["push-tag-name-expansion", `git push origin $TAG`, REPO_WITH_V1, NONE, false, false],
  ["push-risky-config", `git -c core.sshCommand=evil push --tags`, REPO_WITH_V1, NONE, false, false],
  ["push-risky-config-hooks", `git -c core.hooksPath=x push --tags`, REPO_WITH_V1, NONE, false, false],
  ["push-config-alias", `git -c alias.x=y push --tags`, REPO_WITH_V1, NONE, false, false],
  ["push-force-short", `git push -f origin v1`, REPO_WITH_V1, NONE, true, true],
  ["push-force-long", `git push --force origin v1`, REPO_WITH_V1, NONE, true, true],
  ["push-force-with-lease", `git push --force-with-lease origin main`, REPO_WITH_V1, NONE, true, true],
  ["push-force-with-lease-value", `git push --force-with-lease=main:abc origin main`, REPO_WITH_V1, NONE, true, true],
  ["push-force-if-includes", `git push --force-if-includes origin main`, REPO_WITH_V1, NONE, true, true],
  ["push-delete-long", `git push --delete origin v1`, REPO_WITH_V1, NONE, true, true],
  ["push-delete-short", `git push -d origin v1`, REPO_WITH_V1, NONE, true, true],
  ["push-mirror", `git push --mirror`, REPO_WITH_V1, NONE, true, true],
  ["push-prune", `git push --prune origin`, REPO_WITH_V1, NONE, true, true],
  ["push-plus-refspec", `git push origin +main`, REPO_WITH_V1, NONE, true, true],
  ["push-plus-tag-refspec", `git push origin +refs/tags/v1`, REPO_WITH_V1, NONE, true, true],
  ["push-empty-source-refspec", `git push origin :v1`, REPO_WITH_V1, NONE, true, true],
  ["push-empty-source-tag-refspec", `git push origin :refs/tags/v1`, REPO_WITH_V1, NONE, true, true],
  ["push-force-in-cluster", `git push -fu origin v1`, REPO_WITH_V1, NONE, true, true],
  ["push-tags-and-force", `git push --tags --force`, REPO_WITH_V1, NONE, true, true],
  ["push-force-after-tag-creation", `git tag v2 && git push --force origin v2`, REPO_WITH_V1, TAG, true, true],
  ["git-status", `git status`, REPO_WITH_V1, NONE, false, false],
  ["git-log", `git log --oneline`, REPO_WITH_V1, NONE, false, false],
  ["git-without-subcommand", `git`, REPO_WITH_V1, NONE, false, false],
  ["ls", `ls`, REPO_WITH_V1, NONE, false, false],
  ["release-create", `gh release create v1 --notes 'x $y *'`, REPO_WITH_V1, RELEASE, false, true],
  ["release-create-notes-equals", `gh release create v2 --notes=x`, REPO_WITH_V1, RELEASE, false, true],
  ["release-create-all-allowed-flags", `gh release create v2 -t 'T' -n x --generate-notes --notes-from-tag --latest --draft --prerelease --target main --verify-tag`, REPO_WITH_V1, RELEASE, false, true],
  ["release-create-long-title-and-target-equals", `gh release create v2 --title=T --target=main`, REPO_WITH_V1, RELEASE, false, true],
  ["release-create-flags-before-tag", `gh release create --draft v2`, REPO_WITH_V1, RELEASE, false, true],
  ["release-edit-title", `gh release edit v2 --title new`, REPO_WITH_V1, RELEASE, false, true],
  ["release-create-asset", `gh release create v6 ~/.ssh/id_rsa`, REPO_WITH_V1, RELEASE, false, false],
  ["release-create-plain-asset", `gh release create v6 dist.zip`, REPO_WITH_V1, RELEASE, false, false],
  ["release-create-notes-file", `gh release create v6 --notes-file ~/.ssh/id_rsa`, REPO_WITH_V1, RELEASE, false, false],
  ["release-create-notes-file-short", `gh release create v6 -F ~/.ssh/id_rsa`, REPO_WITH_V1, RELEASE, false, false],
  ["release-create-notes-file-equals", `gh release create v6 --notes-file=notes.md`, REPO_WITH_V1, RELEASE, false, false],
  ["release-create-discussion-category", `gh release create v6 --discussion-category general`, REPO_WITH_V1, RELEASE, false, false],
  ["release-create-repo-flag", `gh release create v6 --repo owner/other`, REPO_WITH_V1, RELEASE, false, false],
  ["release-create-repo-short-flag", `gh release create v6 -R owner/other`, REPO_WITH_V1, RELEASE, false, false],
  ["release-create-without-tag", `gh release create --notes x`, REPO_WITH_V1, RELEASE, false, false],
  ["release-create-two-positionals", `gh release create v6 v7`, REPO_WITH_V1, RELEASE, false, false],
  ["release-create-value-flag-without-value", `gh release create v6 --notes`, REPO_WITH_V1, RELEASE, false, false],
  ["release-create-tag-expansion", `gh release create $TAG --notes x`, REPO_WITH_V1, RELEASE, false, false],
  ["release-create-attached-short-flag", `gh release create v6 -tTitle`, REPO_WITH_V1, RELEASE, false, false],
  ["release-edit-asset", `gh release edit v6 ~/.ssh/id_rsa`, REPO_WITH_V1, RELEASE, false, false],
  ["release-edit-notes-file", `gh release edit v6 -F ~/.ssh/id_rsa`, REPO_WITH_V1, RELEASE, false, false],
  ["release-upload-home-file", `gh release upload v1 ~/.ssh/id_rsa`, REPO_WITH_V1, RELEASE, false, false],
  ["release-edit", `gh release edit v1 --draft=false`, REPO_WITH_V1, RELEASE, false, true],
  ["release-upload-is-never-known", `gh release upload v1 file.zip`, REPO_WITH_V1, RELEASE, false, false],
  ["release-delete", `gh release delete v1 --yes`, REPO_WITH_V1, NONE, true, true],
  ["release-delete-asset", `gh release delete-asset v1 file.zip`, REPO_WITH_V1, NONE, true, true],
  ["repo-delete", `gh repo delete owner/name --yes`, REPO_WITH_V1, NONE, true, true],
  ["release-list", `gh release list`, REPO_WITH_V1, NONE, false, false],
  ["pr-create", `gh pr create --fill`, REPO_WITH_V1, NONE, false, false],
  ["release-with-global-flag", `gh -R owner/name release create v1`, REPO_WITH_V1, NONE, false, false],
  ["release-expansion-in-action", `gh release $ACTION v1`, REPO_WITH_V1, NONE, false, false],
  ["compound-with-unknown-command", `git tag v1 && rm -rf x`, REPO_WITH_V1, TAG, false, false],
  ["compound-unknown-first", `make build && git tag v1`, REPO_WITH_V1, TAG, false, false],
  ["compound-gh-and-unknown", `gh release create v1; ls`, REPO_WITH_V1, RELEASE, false, false],
  ["compound-gh-and-echo", `gh release create v1; echo done`, REPO_WITH_V1, RELEASE, false, true],
  ["echo-after-tag", `git tag v1 && echo done`, REPO_WITH_V1, TAG, false, true],
  ["echo-after-push", `git -C ${REPO_WITH_V1} push origin --tags && echo "pushed"`, REPO_WITH_V1, PUSH_TAG, false, true],
  ["echo-with-flags-and-words", `git tag v1 && echo -n a b c`, REPO_WITH_V1, TAG, false, true],
  ["echo-alone", `echo hello`, REPO_WITH_V1, NONE, false, true],
  ["echo-before-tag", `echo start && git tag v1`, REPO_WITH_V1, TAG, false, true],
  ["echo-substitution", `git tag v1 && echo $(id)`, REPO_WITH_V1, TAG, false, false],
  ["echo-variable", `git tag v1 && echo $HOME`, REPO_WITH_V1, TAG, false, false],
  ["echo-braced-variable", `git tag v1 && echo \${HOME}`, REPO_WITH_V1, TAG, false, false],
  ["echo-redirect", `git tag v1 && echo hi > /tmp/x`, REPO_WITH_V1, TAG, false, false],
  ["echo-append-redirect", `git tag v1 && echo hi >> /tmp/x`, REPO_WITH_V1, TAG, false, false],
  ["echo-pipe", `git tag v1 && echo hi | sh`, REPO_WITH_V1, TAG, false, false],
  ["echo-quoted-substitution", `echo "$(git tag -d v1)"`, REPO_WITH_V1, TAG, true, false],
  ["echo-glob", `echo *`, REPO_WITH_V1, NONE, false, false],
  ["echo-question-glob", `echo a?`, REPO_WITH_V1, NONE, false, false],
  ["echo-bracket-glob", `echo [ab]`, REPO_WITH_V1, NONE, false, false],
  ["echo-backticks-after-tag", `git tag v1 && echo \`id\``, REPO_WITH_V1, TAG, false, false],
  ["echo-tilde", `git tag v1 && echo ~/x`, REPO_WITH_V1, TAG, false, false],
  ["echo-brace", `git tag v1 && echo {a,b}`, REPO_WITH_V1, TAG, false, false],
  ["echo-history-bang", `git tag v1 && echo hi!`, REPO_WITH_V1, TAG, false, false],
  ["echo-literal-backslash", `git tag v1 && echo 'a\\b'`, REPO_WITH_V1, TAG, false, false],
  ["echo-escaped-space-has-no-backslash-left", `git tag v1 && echo a\\ b`, REPO_WITH_V1, TAG, false, true],
  ["echo-escaped-dollar", `git tag v1 && echo \\$HOME`, REPO_WITH_V1, TAG, false, false],
  ["echo-destructive-tag", `git tag -d v1 && echo ok`, REPO_WITH_V1, NONE, true, true],
  ["echo-destructive-push", `git push --force origin v1 && echo ok`, REPO_WITH_V1, NONE, true, true],
  ["echo-then-destructive", `echo ok && gh release delete v1`, REPO_WITH_V1, NONE, true, true],
  ["echo-with-unknown-neighbor", `git tag v1 && echo ok && ls`, REPO_WITH_V1, TAG, false, false],
  ["echo-background", `git tag v1 && echo ok &`, REPO_WITH_V1, TAG, false, true],
  ["echo-uppercase-is-not-echo", `git tag v1 && ECHO ok`, REPO_WITH_V1, TAG, false, false],
  ["printf-is-not-harmless", `git tag v1 && printf ok`, REPO_WITH_V1, TAG, false, false],
  ["command-substitution", `echo $(git tag v1)`, REPO_WITH_V1, TAG, false, false],
  ["backticks", `echo \`git tag v1\``, REPO_WITH_V1, TAG, false, false],
  ["heredoc", `cat <<EOF\ngit tag v1\nEOF`, REPO_WITH_V1, TAG, false, false],
  ["bash-c", `bash -c 'git tag v1'`, REPO_WITH_V1, TAG, false, false],
  ["sh-c", `sh -c 'git push --tags'`, REPO_WITH_V1, PUSH_TAG, false, false],
  ["zsh-c", `zsh -c 'gh release create v1'`, REPO_WITH_V1, RELEASE, false, false],
  ["eval", `eval git tag v1`, REPO_WITH_V1, TAG, false, false],
  ["xargs", `echo v1 | xargs git tag`, REPO_WITH_V1, TAG, false, false],
  ["shlex-error-unterminated-quote", `git tag 'v1`, REPO_WITH_V1, TAG, false, false],
  ["backslash-newline-continuation", `git tag v1 \\\n&& rm x`, REPO_WITH_V1, TAG, false, false],
  ["opaque-with-destructive-force", `bash -c 'git push --force origin v1'`, REPO_WITH_V1, PUSH_TAG, true, false],
  ["opaque-with-destructive-delete", `eval 'git tag -d v1'`, REPO_WITH_V1, TAG, true, false],
  ["opaque-with-gh-delete", `sh -c 'gh release delete v1'`, REPO_WITH_V1, RELEASE, true, false],
  ["redirect", `git tag v2 > out.txt`, REPO_WITH_V1, NONE, false, false],
  ["redirect-stderr", `git push origin v1 2>&1`, REPO_WITH_V1, NONE, false, false],
  ["subshell", `(git tag v2)`, REPO_WITH_V1, NONE, false, false],
  ["brace-group", `{ git tag v2; }`, REPO_WITH_V1, NONE, false, false],
  ["process-substitution", `git tag v2 <(echo x)`, REPO_WITH_V1, NONE, false, false],
  ["env-prefix", `FOO=1 git tag v2`, REPO_WITH_V1, NONE, false, false],
  ["absolute-git-path", `/usr/bin/git tag v2`, REPO_WITH_V1, NONE, false, false],
  ["comment-hides-rest", `git tag v2 # && rm x`, REPO_WITH_V1, TAG, false, false],
  ["hash-inside-word-hides-nothing", `git push origin v1#x; rm x`, REPO_WITH_V1, NONE, false, false],
  ["quoted-separator-splits-conservatively", `git tag -m ";" v2`, REPO_WITH_V1, TAG, false, false],
  ["pipe-to-cat", `git tag v2 | cat`, REPO_WITH_V1, TAG, false, false],
  ["cd-two-arguments", `cd a b && git tag v2`, REPO_WITH_V1, TAG, false, false],
  ["cd-only", `cd somewhere`, REPO_WITH_V1, NONE, false, true],
  ["empty", ``, REPO_WITH_V1, NONE, false, false],
  ["whitespace", `   \n  `, REPO_WITH_V1, NONE, false, false],
];

const SEPARATOR_CASES = [
  ["and", "&&"],
  ["or", "||"],
  ["semicolon", ";"],
  ["background", "&"],
  ["newline", "\n"],
  ["crlf", "\r\n"],
  ["blank-lines", "\n\n"],
];

const MCP_WRITE = [
  "mcp__claude_ai_Slack__slack_send_message",
  "mcp__claude_ai_Slack__slack_send_message_draft",
  "mcp__claude_ai_Slack__slack_schedule_message",
  "mcp__claude_ai_Gmail__reply",
  "mcp__claude_ai_Gmail__create_draft",
  "mcp__claude_ai_Gmail__label_message",
  "mcp__claude_ai_Gmail__apply_sensitive_message_label",
  "mcp__claude_ai_Gmail__forward",
  "mcp__claude_ai_Gmail__mark_message_spam",
  "mcp__claude_ai_Gmail__unmark_thread_spam",
  "mcp__claude_ai_Atlassian__createJiraIssue",
  "mcp__claude_ai_Atlassian__editJiraIssue",
  "mcp__claude_ai_Atlassian__transitionJiraIssue",
  "mcp__claude_ai_Atlassian__addCommentToJiraIssue",
  "mcp__claude_ai_Atlassian__updateConfluencePage",
  "mcp__claude_ai_Google_Drive__create_file",
  "mcp__claude_ai_Google_Drive__share_file",
  "mcp__claude_ai_Google_Drive__copy_file",
  "mcp__azure-devops__wit_work_item_comment_write",
  "mcp__azure-devops__repo_create_branch",
  "mcp__azure-devops__wiki_upsert_page",
  "mcp__tool__merge-pull-request",
  "mcp__tool__rename_item",
  "mcp__tool__assign_user",
  "mcp__tool__invite_member",
  "mcp__tool__react_to_message",
  "mcp__tool__publishPage",
  "mcp__tool__patch_resource",
  "mcp__tool__closeIssue",
  "mcp__tool__reopenIssue",
  "mcp__tool__linkIssues",
];
const MCP_DESTRUCTIVE = [
  "mcp__claude_ai_Gmail__trash_message",
  "mcp__claude_ai_Gmail__delete_draft",
  "mcp__claude_ai_Google_Drive__trash_file",
  "mcp__claude_ai_Claude_Docs__delete",
  "mcp__tool__removeMember",
  "mcp__tool__destroy_everything",
  "mcp__tool__purge_cache",
  "mcp__tool__drop_table",
  "mcp__tool__unshare_file",
  "mcp__tool__revoke_token",
  "mcp__tool__delete_and_create",
];
const MCP_READ_VERB_SILENT = [
  "mcp__claude_ai_Atlassian__getIssueLinkTypes",
  "mcp__claude_ai_Atlassian__getJiraIssueRemoteIssueLinks",
  "mcp__claude_ai_Atlassian__getTransitionsForJiraIssue",
  "mcp__claude_ai_Atlassian__getAccessibleAtlassianResources",
  "mcp__claude_ai_Slack__slack_read_thread",
  "mcp__claude_ai_Google_Drive__get_file_permissions",
  "mcp__claude_ai_Google_Drive__search_files",
  "mcp__claude_ai_Google_Drive__list_recent_files",
  "mcp__claude_ai_Google_Drive__download_file_content",
  "mcp__datagrip__preview_table_data",
];
const MCP_WRITE_KEPT = [
  "mcp__claude_ai_Atlassian__createJiraIssue",
  "mcp__claude_ai_Atlassian__editJiraIssue",
  "mcp__claude_ai_Atlassian__transitionJiraIssue",
  "mcp__claude_ai_Atlassian__addCommentToJiraIssue",
  "mcp__claude_ai_Atlassian__createIssueLink",
  "mcp__claude_ai_Slack__slack_send_message",
  "mcp__claude_ai_Slack__slack_schedule_message",
  "mcp__claude_ai_Google_Drive__create_file",
  "mcp__claude_ai_Google_Drive__update_file",
  "mcp__claude_ai_Google_Drive__share_file",
  "mcp__claude_ai_Google_Drive__copy_file",
  "mcp__tool__send_message",
  "mcp__claude_ai_Gmail__reply",
  "mcp__claude_ai_Gmail__forward",
  "mcp__claude_ai_Gmail__label_message",
  "mcp__claude_ai_Gmail__create_draft",
];
const MCP_DESTRUCTIVE_WINS = [
  "mcp__claude_ai_Google_Drive__trash_file",
  "mcp__claude_ai_Gmail__delete_draft",
  "mcp__claude_ai_Gmail__trash_message",
  "mcp__tool__get_and_delete_item",
  "mcp__tool__getOrDeleteThing",
];
const MCP_READ = [
  "mcp__claude_ai_Atlassian__getJiraIssue",
  "mcp__claude_ai_Atlassian__searchJiraIssuesUsingJql",
  "mcp__claude_ai_Atlassian__getVisibleJiraProjects",
  "mcp__claude_ai_Slack__slack_read_channel",
  "mcp__claude_ai_Slack__slack_search_public",
  "mcp__claude_ai_Gmail__list_labels",
  "mcp__claude_ai_Gmail__get_thread",
  "mcp__claude_ai_Gmail__search_threads",
  "mcp__claude_ai_Google_Drive__read_file_content",
  "mcp__azure-devops__repo_pull_request",
  "mcp__tool__fetch_page",
  "mcp__tool__query_rows",
  "mcp__tool__getJiraIssueRemoteIssueLinks",
  "mcp__datagrip__execute_sql_query",
  "mcp__datagrip__list_database_connections",
  "mcp__broken",
  "mcp__only__",
];

const LEX_CASES = [
  ["git tag v1", ["git", "tag", "v1"]],
  ["git tag -a v2 -m \"a b\\\"c\"", ["git", "tag", "-a", "v2", "-m", "a b\"c"]],
  ["echo 'a\\b' \"x\\y\" \"x\\\\y\" \"x\\$y\"", ["echo", "a\\b", "x\\y", "x\\y", "x\\$y"]],
  ["a\\ b c", ["a b", "c"]],
  ["x\"y\"z w", ["xyz", "w"]],
  ["''", [""]],
  ["\"\" a", ["", "a"]],
  ["a;b", ["a", ";", "b"]],
  ["a&b&&c||d|&e", ["a", "&", "b", "&&", "c", "||", "d", "|&", "e"]],
  ["(a) {b}", ["(", "a", ")", "{b}"]],
  ["echo hi 2>&1", ["echo", "hi", "2", ">&", "1"]],
  ["cat >> f < g", ["cat", ">>", "f", "<", "g"]],
  ["a;;b", ["a", ";;", "b"]],
  ["a &&& b", ["a", "&&&", "b"]],
  ["git tag v1\ngit push\r\nx\ry", ["git", "tag", "v1", ";", "git", "push", ";", "x", ";", "y"]],
  ["a #b c", ["a", "#b", "c"]],
  ["echo hi!", ["echo", "hi!"]],
  ["tab\tsep", ["tab", "sep"]],
  ["é ü 日本語 😀", ["é", "ü", "日本語", "😀"]],
  ["a<(b)", ["a", "<(", "b", ")"]],
  ["git tag 'v1", null],
  ["git tag v1 \\", null],
  ["x \"a\\", null],
  ["a\\\\b", ["a\\b"]],
  ["'a b'c\"d e\"", ["a bcd e"]],
  ["a\"b'c\"d", ["ab'cd"]],
  ["$HOME ${X}", ["$HOME", "${X}"]],
  [" lead  trail ", ["lead", "trail"]],
  ["", []],
  ["   ", []],
  ["a|b", ["a", "|", "b"]],
  ["|", ["|"]],
  ["&", ["&"]],
  ["a&", ["a", "&"]],
  ["a ;b", ["a", ";", "b"]],
  ["a;\"q\"", ["a", ";", "q"]],
  ["a'b'", ["ab"]],
  ["a\\;b", ["a;b"]],
  ["a\\&&b", ["a&", "&", "b"]],
  ["a'' b", ["a", "b"]],
  ["a\"\"", ["a"]],
  ["\\", null],
  ["\"", null],
  ["''''", [""]],
  ["a\\\nb", ["a ", ";", "b"]],
  ["x>'y z'", ["x", ">", "y z"]],
  ["\"a\"\"b\"", ["ab"]],
  ["echo \"it's\"", ["echo", "it's"]],
  ["echo 'say \"hi\"'", ["echo", "say \"hi\""]],
  ["a\\'b", ["a'b"]],
];

function firstTime(keys) {
  return `First time in this session: approving it allows ${keys} for the rest of the session.`;
}

function approved(keys) {
  return `Approved earlier in this session: ${keys}`;
}

function gitRunner(argv) {
  const repo = REPOS[argv[2]];
  if (repo === undefined) return { exitCode: 128, stdout: "", stderr: "fatal: not a git repository" };
  if (argv[3] === "remote") return { exitCode: 0, stdout: repo.remotes.map(name => `${name}\n`).join(""), stderr: "" };
  if (argv[3] === "rev-parse") {
    const name = argv[argv.length - 1].replace("refs/tags/", "");
    return { exitCode: repo.tags.includes(name) ? 0 : 1, stdout: "", stderr: "" };
  }
  throw new Error(`unexpected command: ${argv.join(" ")}`);
}

function createEnv(options = {}) {
  const env = {
    cwd: "cwd" in options ? options.cwd : REPO_WITH_V1,
    sessionId: "sessionId" in options ? options.sessionId : "sess-1",
    now: options.now ?? NOW,
    data: options.data ?? {},
    run: options.run ?? gitRunner,
    failGet: options.failGet ?? false,
    failSet: options.failSet ?? false,
    calls: [],
    writes: [],
  };
  env.$ = {
    session: {
      cwd: async () => {
        if (env.cwd instanceof Error) throw env.cwd;
        return env.cwd;
      },
      id: async () => {
        if (env.sessionId instanceof Error) throw env.sessionId;
        return env.sessionId;
      },
    },
    process: {
      run: async (argv, init) => {
        env.calls.push({ argv, init });
        return env.run(argv, init);
      },
    },
    clock: { now: async () => env.now },
    store: {
      get: async key => {
        if (env.failGet) throw new Error("store unavailable");
        return key in env.data ? JSON.parse(JSON.stringify(env.data[key])) : undefined;
      },
      set: async (key, value) => {
        if (env.failSet) throw new Error("store unavailable");
        env.writes.push(key);
        env.data[key] = JSON.parse(JSON.stringify(value));
      },
    },
  };
  return env;
}

function registerHooks() {
  const entries = [];
  const on = (event, matcher, handler) => {
    const entry = { event, matcher, handler, catcher: undefined };
    entries.push(entry);
    return {
      catch(catcher) {
        entry.catcher = catcher;
        return this;
      },
    };
  };
  registerApproval(on);

  async function dispatch(event, env, e, answer) {
    const entry = entries.find(candidate => candidate.event === event);
    let called = false;
    let settled;
    const next = async () => {
      if (!called) {
        called = true;
        settled = answer;
      }
      return settled;
    };
    try {
      return await entry.handler(env.$, e, next);
    } catch (error) {
      const caught = async () => next();
      Object.defineProperty(caught, "called", { get: () => called });
      caught.error = error;
      return entry.catcher(env.$, e, caught);
    }
  }

  return {
    entries,
    check: (env, e, answer = CORE) => dispatch("tool.check", env, e, answer),
    call: (env, e, answer = OK_RESULT) => dispatch("tool.call", env, e, answer),
  };
}

function checkEvent(command, extra = {}) {
  return { tool: "Bash", input: { command }, tool_use_id: "toolu-1", ...extra };
}

function callEvent(command, extra = {}) {
  return { tool: "Bash", command, tool_use_id: "toolu-1", ...extra };
}

function mcpCheckEvent(tool, extra = {}) {
  return { tool, input: {}, tool_use_id: "toolu-1", ...extra };
}

function mcpCallEvent(tool, extra = {}) {
  return { tool, tool_use_id: "toolu-1", ...extra };
}

async function approve(hooks, env, ...commands) {
  for (const command of commands) await hooks.call(env, callEvent(command));
}

function summary(result) {
  return { keys: [...result.keys].sort(), destructive: result.destructive, known: result.known };
}

function quote(text) {
  return /^[\w@%+=:,./-]+$/.test(text) ? text : `'${text.replaceAll("'", `'"'"'`)}'`;
}

async function classifyBash(command, options = {}) {
  const env = createEnv(options);
  return summary(await classify(env.$, "Bash", { command }));
}

for (const [name, command, cwd, keys, destructive, known] of BASH_CASES) {
  test(`Bash 명령 ${name}은 키와 되돌릴 수 없는 작업 여부, 모두 이해했는지 여부로 분류된다`, async () => {
    // given
    const options = { cwd };

    // when
    const result = await classifyBash(command, options);

    // then
    expect(result).toEqual({ keys: [...keys].sort(), destructive, known });
  });
}

for (const padding of [" ", ""]) {
  for (const [name, separator] of SEPARATOR_CASES) {
    test(`구분자 ${name}(앞뒤 공백 ${padding === " " ? "있음" : "없음"})로 이은 알려진 하위 명령은 키를 합치고 모두 이해한 것으로 본다`, async () => {
      // given
      const command = `git tag v2${padding}${separator}${padding}gh release create v2`;

      // when
      const result = await classifyBash(command);

      // then
      expect(result).toEqual({ keys: [...TAG, ...RELEASE].sort(), destructive: false, known: true });
    });
  }
}

for (const separator of ["&&", "||", ";", "|", "|&", "&", "\n"]) {
  const label = JSON.stringify(separator);

  test(`구분자 ${label} 뒤에 알 수 없는 명령이 오면 모두 이해한 것으로 보지 않는다`, async () => {
    // given
    const command = `git tag v2 ${separator} rm -rf x`;

    // when
    const result = await classifyBash(command);

    // then
    expect(result).toEqual({ keys: TAG, destructive: false, known: false });
  });

  test(`구분자 ${label} 뒤에 되돌릴 수 없는 하위 명령이 오면 전체가 되돌릴 수 없는 작업이다`, async () => {
    // given
    const command = `git tag v2 ${separator} git push --force origin v2`;

    // when
    const result = await classifyBash(command);

    // then
    expect(result.destructive).toBe(true);
  });
}

for (const [label, input] of [
  ["입력 없음", undefined],
  ["문자열 입력", "git tag v1"],
  ["배열 입력", []],
  ["빈 객체", {}],
  ["command가 null", { command: null }],
  ["command가 숫자", { command: 5 }],
  ["command가 빈 문자열", { command: "" }],
]) {
  test(`Bash 입력이 ${label}이면 키가 없는 결과를 낸다`, async () => {
    // given
    const env = createEnv();

    // when
    const result = summary(await classify(env.$, "Bash", input));

    // then
    expect(result.keys).toEqual([]);
    expect(result.destructive).toBe(false);
  });
}

test("세션 디렉터리를 알 수 없어도 분류는 예외 없이 끝난다", async () => {
  // given
  const command = "git tag v2";

  // when
  const result = await classifyBash(command, { cwd: new Error("no directory") });

  // then
  expect(result).toEqual({ keys: TAG, destructive: false, known: true });
});

test("git 저장소가 아닌 디렉터리에서는 태그 조회가 실패해 일반 푸시로 본다", async () => {
  // given
  const command = "git push origin v1";

  // when
  const result = await classifyBash(command, { cwd: "/elsewhere" });

  // then
  expect(result).toEqual({ keys: NONE, destructive: false, known: false });
});

test("태그 조회가 시간 초과로 거부되면 태그가 아닌 것으로 본다", async () => {
  // given
  const run = () => {
    throw new Error("timed out");
  };

  // when
  const result = await classifyBash("git push origin v1", { run });

  // then
  expect(result).toEqual({ keys: NONE, destructive: false, known: false });
});

test("태그 조회와 원격 목록 조회는 git을 3초 제한으로 실행한다", async () => {
  // given
  const env = createEnv();

  // when
  const result = summary(await classify(env.$, "Bash", { command: "git push origin v1" }));

  // then
  expect(result).toEqual({ keys: PUSH_TAG, destructive: false, known: true });
  const commands = env.calls.map(call => call.argv);
  expect(commands).toContainEqual(["git", "-C", REPO_WITH_V1, "rev-parse", "-q", "--verify", "refs/tags/v1"]);
  expect(commands).toContainEqual(["git", "-C", REPO_WITH_V1, "remote"]);
  expect(env.calls.every(call => call.init.timeoutMs === 3000)).toBe(true);
});

for (const [label, run] of [
  ["시간 초과", () => {
    throw new Error("timed out");
  }],
  ["실행 실패", () => {
    throw new Error("no git");
  }],
  ["비정상 종료", () => ({ exitCode: 1, stdout: "", stderr: "" })],
]) {
  test(`원격 목록 조회가 ${label}이면 태그 푸시는 모두 이해한 것으로 보지 않는다`, async () => {
    // given
    const command = "git push origin --tags";

    // when
    const result = await classifyBash(command, { run });

    // then
    expect(result).toEqual({ keys: PUSH_TAG, destructive: false, known: false });
  });
}

test("원격을 생략한 태그 푸시는 git을 실행하지 않고 모두 이해한 것으로 본다", async () => {
  // given
  const run = () => {
    throw new Error("git must not run");
  };

  // when
  const result = await classifyBash("git push --tags", { run });

  // then
  expect(result).toEqual({ keys: PUSH_TAG, destructive: false, known: true });
});

for (const name of MCP_WRITE) {
  test(`쓰기 동작 MCP 도구 ${name}는 도구 전체 이름으로 키를 만들고 모두 이해한 것으로 본다`, async () => {
    // given
    const env = createEnv();

    // when
    const result = summary(await classify(env.$, name, {}));

    // then
    expect(result).toEqual({ keys: [`mcp:${name}`], destructive: false, known: true });
  });
}

for (const name of MCP_DESTRUCTIVE) {
  test(`삭제 계열 단어가 든 MCP 도구 ${name}는 되돌릴 수 없는 작업이다`, async () => {
    // given
    const env = createEnv();

    // when
    const result = await classify(env.$, name, {});

    // then
    expect(result.destructive).toBe(true);
    expect(result.known).toBe(true);
  });
}

for (const name of MCP_READ) {
  test(`조회 계열이거나 DataGrip 쿼리 도구이거나 이름이 모자란 MCP 도구 ${name}는 키가 없다`, async () => {
    // given
    const env = createEnv();

    // when
    const result = await classify(env.$, name, {});

    // then
    expect(result.keys.size).toBe(0);
    expect(result.destructive).toBe(false);
  });
}

for (const name of MCP_READ_VERB_SILENT) {
  test(`읽기 동사로 시작하는 MCP 도구 ${name}는 키가 없는 결과를 낸다`, async () => {
    // given
    const env = createEnv();

    // when
    const result = summary(await classify(env.$, name, {}));

    // then
    expect(result).toEqual({ keys: [], destructive: false, known: false });
  });
}

for (const verb of [...READ_VERBS].sort()) {
  test(`첫 단어가 읽기 동사 ${verb}이면 뒤에 쓰기 단어가 있어도 키가 없는 결과를 낸다`, async () => {
    // given
    const env = createEnv();
    const name = `mcp__tool__${verb}_comment_link`;

    // when
    const result = summary(await classify(env.$, name, {}));

    // then
    expect(result).toEqual({ keys: [], destructive: false, known: false });
  });

  test(`읽기 동사 ${verb}가 첫 단어가 아니면 쓰기 단어가 있는 도구는 그대로 쓰기다`, async () => {
    // given
    const env = createEnv();
    const name = `mcp__tool__create_${verb}`;

    // when
    const result = summary(await classify(env.$, name, {}));

    // then
    expect(result).toEqual({ keys: [`mcp:${name}`], destructive: false, known: true });
  });
}

for (const name of MCP_WRITE_KEPT) {
  test(`읽기 동사로 시작하지 않는 쓰기 도구 ${name}는 키를 만들고 되돌릴 수 없는 작업이 아니다`, async () => {
    // given
    const env = createEnv();

    // when
    const result = summary(await classify(env.$, name, {}));

    // then
    expect(result).toEqual({ keys: [`mcp:${name}`], destructive: false, known: true });
  });
}

for (const name of MCP_DESTRUCTIVE_WINS) {
  test(`삭제 계열 단어는 읽기 동사보다 우선해 ${name}를 되돌릴 수 없는 작업으로 남긴다`, async () => {
    // given
    const env = createEnv();

    // when
    const result = summary(await classify(env.$, name, {}));

    // then
    expect(result).toEqual({ keys: [`mcp:${name}`], destructive: true, known: true });
  });
}

for (const [toolPart, ordered] of [
  ["getOrDeleteThing", ["get", "or", "delete", "thing"]],
  ["slack_read_thread", ["slack", "read", "thread"]],
  ["merge-pull-request", ["merge", "pull", "request"]],
  ["createJiraIssue", ["create", "jira", "issue"]],
  ["", []],
]) {
  test(`단어 목록은 "${toolPart}"에서 나온 순서를 그대로 지키고 집합과 같은 단어를 낸다`, () => {
    // given
    const part = toolPart;

    // when
    const result = toolWordList(part);

    // then
    expect(result).toEqual(ordered);
    expect([...toolWords(part)].sort()).toEqual([...new Set(ordered)].sort());
  });
}

for (const [toolPart, words] of [
  ["createJiraIssue", ["create", "jira", "issue"]],
  ["slack_send_message", ["slack", "send", "message"]],
  ["wit_work_item_comment_write", ["wit", "work", "item", "comment", "write"]],
  ["merge-pull-request", ["merge", "pull", "request"]],
  ["getJiraIssueRemoteIssueLinks", ["get", "jira", "issue", "remote", "links"]],
  ["HTTPRequest", ["http", "request"]],
]) {
  test(`도구 이름 "${toolPart}"는 밑줄, 하이픈, camelCase 경계에서 소문자 단어로 나뉜다`, () => {
    // given
    const part = toolPart;

    // when
    const result = [...toolWords(part)].sort();

    // then
    expect(result).toEqual([...words].sort());
  });
}

for (const tool of ["Read", "Edit", "Write", "WebFetch", "Task", undefined, 5]) {
  test(`Bash도 MCP도 아닌 도구 ${String(tool)}는 키가 없다`, async () => {
    // given
    const env = createEnv();

    // when
    const result = await classify(env.$, tool, { command: "git tag v1" });

    // then
    expect(result.keys.size).toBe(0);
    expect(result.destructive).toBe(false);
  });
}

for (const [source, expected] of LEX_CASES) {
  test(`렉서는 ${JSON.stringify(source)}를 Python shlex와 같은 토큰으로 나눈다`, () => {
    // given
    const text = source;

    // when
    let tokens = null;
    try {
      tokens = lex(text);
    } catch {
      tokens = null;
    }

    // then
    expect(tokens).toEqual(expected);
  });
}

test("처음 확인은 묻고, 성공한 호출이 키를 기록한 뒤 두 번째 확인은 허용한다", async () => {
  // given
  const hooks = registerHooks();
  const env = createEnv();

  // when
  const first = await hooks.check(env, checkEvent("git tag v2"));
  const recorded = await hooks.call(env, callEvent("git tag v2"));
  const second = await hooks.check(env, checkEvent("git tag v3"));

  // then
  expect(first).toEqual({ decision: "ask", reason: firstTime("git:tag") });
  expect(recorded).toBe(OK_RESULT);
  expect(env.data.approvals).toEqual({ "sess-1": { time: NOW, keys: ["git:tag"] } });
  expect(second).toEqual({ decision: "allow", reason: approved("git:tag") });
});

test("다른 세션에서는 같은 종류의 작업도 다시 묻는다", async () => {
  // given
  const hooks = registerHooks();
  const env = createEnv();
  await approve(hooks, env, "git tag v2");
  const other = createEnv({ data: env.data, sessionId: "sess-2" });

  // when
  const otherResult = await hooks.check(other, checkEvent("git tag v3"));
  const sameResult = await hooks.check(env, checkEvent("git tag v3"));

  // then
  expect(otherResult.decision).toBe("ask");
  expect(sameResult.decision).toBe("allow");
});

test("기록된 키와 다른 종류의 작업은 묻는다", async () => {
  // given
  const hooks = registerHooks();
  const env = createEnv();
  await approve(hooks, env, "git tag v2");

  // when
  const release = await hooks.check(env, checkEvent("gh release create v2"));
  const push = await hooks.check(env, checkEvent("git push origin v1"));

  // then
  expect(release.decision).toBe("ask");
  expect(push.decision).toBe("ask");
});

test("여러 키가 든 명령은 모든 키가 기록돼야 허용된다", async () => {
  // given
  const hooks = registerHooks();
  const env = createEnv();
  const command = "git tag v2 && git push origin v2";
  await approve(hooks, env, "git tag v3");

  // when
  const partial = await hooks.check(env, checkEvent(command));
  await approve(hooks, env, command);
  const complete = await hooks.check(env, checkEvent(command));

  // then
  expect(partial.decision).toBe("ask");
  expect(env.data.approvals["sess-1"].keys).toEqual(["git:push-tag", "git:tag"]);
  expect(complete).toEqual({ decision: "allow", reason: approved("git:push-tag, git:tag") });
});

for (const command of [
  "git push --force origin v1",
  "git tag -d v1",
  "gh release delete v1",
  "gh repo delete x",
  "git push origin :v1",
]) {
  test(`관련 키가 기록돼 있어도 되돌릴 수 없는 작업 "${command}"는 항상 묻는다`, async () => {
    // given
    const hooks = registerHooks();
    const env = createEnv();
    await approve(hooks, env, "git tag v2", "git push origin v1", "gh release create v2");

    // when
    const asked = await hooks.check(env, checkEvent(command));
    await hooks.call(env, callEvent(command));

    // then
    expect(asked).toEqual({ decision: "ask", reason: DESTRUCTIVE_REASON });
    expect(env.data.approvals["sess-1"].keys).toEqual(["gh:release", "git:push-tag", "git:tag"]);
  });
}

test("되돌릴 수 없는 하위 명령이 든 명령은 묻고 키를 기록하지 않는다", async () => {
  // given
  const hooks = registerHooks();
  const env = createEnv();
  const command = "git tag v2 && git push --force origin v2";

  // when
  const asked = await hooks.check(env, checkEvent(command));
  await hooks.call(env, callEvent(command));

  // then
  expect(asked).toEqual({ decision: "ask", reason: DESTRUCTIVE_REASON });
  expect("approvals" in env.data).toBe(false);
});

test("기록된 키가 있어도 이해하지 못하는 하위 명령이 섞이면 묻는다", async () => {
  // given
  const hooks = registerHooks();
  const env = createEnv();
  await approve(hooks, env, "git tag v2");

  // when
  const asked = await hooks.check(env, checkEvent("git tag v3 && rm -rf x"));

  // then
  expect(asked).toEqual({ decision: "ask", reason: UNVERIFIABLE_REASON });
});

for (const command of [
  "echo $(git tag v3)",
  "bash -c 'git tag v3'",
  "eval git tag v3",
  "cat <<EOF\ngit tag v3\nEOF",
  "git tag v3 | cat",
]) {
  test(`셸 치환, 하위 셸, heredoc, 파이프가 든 명령 ${JSON.stringify(command)}는 키가 기록돼 있어도 허용하지 않는다`, async () => {
    // given
    const hooks = registerHooks();
    const env = createEnv();
    await approve(hooks, env, "git tag v2");

    // when
    const asked = await hooks.check(env, checkEvent(command));

    // then
    expect(asked).toEqual({ decision: "ask", reason: UNVERIFIABLE_REASON });
  });
}

for (const command of [
  "git push https://x.example/r.git --tags",
  "git push evil --tags",
  "git push --repo=evil --tags",
  "git push origin main --tags",
  "git push --follow-tags origin main",
  "git push https://x.example/r.git v1",
]) {
  test(`git:push-tag가 기록돼 있어도 확인되지 않은 대상이거나 브랜치가 섞인 푸시 "${command}"는 묻는다`, async () => {
    // given
    const hooks = registerHooks();
    const env = createEnv();
    await approve(hooks, env, "git push origin --tags");

    // when
    const asked = await hooks.check(env, checkEvent(command));

    // then
    expect(asked).toEqual({ decision: "ask", reason: UNVERIFIABLE_REASON });
  });
}

for (const command of [
  "git push origin --tags",
  "git push origin v1",
  "git push --tags",
  "git push --follow-tags origin",
  "git push origin refs/tags/v1",
]) {
  test(`원격을 생략했거나 목록에 있는 원격으로의 태그 푸시 "${command}"는 키가 기록된 뒤 허용된다`, async () => {
    // given
    const hooks = registerHooks();
    const env = createEnv();
    await approve(hooks, env, "git push origin --tags");

    // when
    const allowed = await hooks.check(env, checkEvent(command));

    // then
    expect(allowed).toEqual({ decision: "allow", reason: approved("git:push-tag") });
  });
}

test("저장소로 cd한 뒤 태그를 만들고 푸시하는 명령은 두 키가 기록된 뒤 허용된다", async () => {
  // given
  const hooks = registerHooks();
  const env = createEnv();
  const command = `cd ${quote(REPO_WITHOUT)} && git tag v4 && git push origin v4`;
  await approve(hooks, env, command);

  // when
  const allowed = await hooks.check(env, checkEvent(command));

  // then
  expect(allowed).toEqual({ decision: "allow", reason: approved("git:push-tag, git:tag") });
});

for (const command of [
  "gh release upload v1 ~/.ssh/id_rsa",
  "gh release upload v1 file.zip",
  "gh release create v6 ~/.ssh/id_rsa",
  "gh release create v6 --notes-file ~/.ssh/id_rsa",
  "gh release create v6 -F ~/.ssh/id_rsa",
  "gh release create v6 --discussion-category general",
  "gh release create v6 --repo owner/other",
  "gh release edit v6 -R owner/other",
  "gh release create v6 v7",
]) {
  test(`gh:release가 기록돼 있어도 파일, 추가 인자, 허용 목록 밖의 플래그가 든 릴리스 명령 "${command}"는 묻는다`, async () => {
    // given
    const hooks = registerHooks();
    const env = createEnv();
    await approve(hooks, env, "gh release create v2 --notes x");

    // when
    const asked = await hooks.check(env, checkEvent(command));

    // then
    expect(asked).toEqual({ decision: "ask", reason: UNVERIFIABLE_REASON });
  });
}

for (const command of [
  "gh release create v2 --notes x",
  "gh release create v3 --title T --notes=body --draft",
  "gh release edit v2 --prerelease --latest",
  "gh release create v4 --generate-notes --target main --verify-tag",
]) {
  test(`태그 하나와 허용 목록의 플래그만 쓰는 릴리스 명령 "${command}"는 키가 기록된 뒤 허용된다`, async () => {
    // given
    const hooks = registerHooks();
    const env = createEnv();
    await approve(hooks, env, "gh release create v2 --notes x");

    // when
    const allowed = await hooks.check(env, checkEvent(command));

    // then
    expect(allowed).toEqual({ decision: "allow", reason: approved("gh:release") });
  });
}

test("하위 에이전트의 확인은 기록된 키가 있어도 허용하지 않고 호출도 기록하지 않는다", async () => {
  // given
  const hooks = registerHooks();
  const env = createEnv();
  await approve(hooks, env, "git tag v2");
  const before = JSON.parse(JSON.stringify(env.data.approvals));
  const writesBefore = env.writes.length;

  // when
  const pre = await hooks.check(env, checkEvent("git tag v3", { agentId: "agent-1" }));
  const post = await hooks.call(env, callEvent("gh release create v1", { agentId: "agent-1" }));

  // then
  expect(pre).toEqual({ decision: "ask", reason: firstTime("git:tag") });
  expect(post).toBe(OK_RESULT);
  expect(env.data.approvals).toEqual(before);
  expect(env.writes.length).toBe(writesBefore);
});

test("하위 에이전트도 되돌릴 수 없는 작업에는 같은 사유로 묻는다", async () => {
  // given
  const hooks = registerHooks();
  const env = createEnv();

  // when
  const result = await hooks.check(env, checkEvent("git push --force origin v1", { agentId: "agent-1" }));

  // then
  expect(result).toEqual({ decision: "ask", reason: DESTRUCTIVE_REASON });
});

test("저장소를 읽을 수 없으면 허용도 기록도 없이 계속 묻는다", async () => {
  // given
  const hooks = registerHooks();
  const env = createEnv({ failGet: true });
  const command = "git tag v2";

  // when
  const first = await hooks.check(env, checkEvent(command));
  const recorded = await hooks.call(env, callEvent(command));
  const second = await hooks.check(env, checkEvent(command));

  // then
  expect(first).toEqual({ decision: "ask", reason: firstTime("git:tag") });
  expect(recorded).toBe(OK_RESULT);
  expect(second.decision).toBe("ask");
  expect(env.writes).toEqual([]);
});

test("저장소에 쓸 수 없어도 호출 결과는 그대로 돌아오고 오류를 내지 않는다", async () => {
  // given
  const hooks = registerHooks();
  const env = createEnv({ failSet: true });

  // when
  const recorded = await hooks.call(env, callEvent("git tag v2"));
  const asked = await hooks.check(env, checkEvent("git tag v2"));

  // then
  expect(recorded).toBe(OK_RESULT);
  expect(asked.decision).toBe("ask");
  expect(env.writes).toEqual([]);
});

for (const [label, sessionId] of [
  ["없음", undefined],
  ["숫자", 5],
  ["빈 문자열", ""],
  ["배열", ["x"]],
  ["객체", { a: 1 }],
  ["조회 실패", new Error("no session")],
]) {
  test(`세션 id가 ${label}이면 허용도 기록도 하지 않는다`, async () => {
    // given
    const hooks = registerHooks();
    const real = createEnv({ sessionId: "real" });
    await approve(hooks, real, "git tag v2");
    const before = JSON.parse(JSON.stringify(real.data));
    const env = createEnv({ data: real.data, sessionId });

    // when
    const asked = await hooks.check(env, checkEvent("git tag v3"));
    const post = await hooks.call(env, callEvent("git tag v3"));

    // then
    expect(asked.decision).toBe("ask");
    expect(post).toBe(OK_RESULT);
    expect(env.data).toEqual(before);
  });
}

test("7일이 지난 세션은 쓸 때 지우고 허용 판단에도 쓰지 않는다", async () => {
  // given
  const hooks = registerHooks();
  const data = {
    approvals: {
      old: { time: NOW - 8 * DAY, keys: ["git:tag"] },
      recent: { time: NOW - 6 * DAY, keys: ["gh:release"] },
      broken: { time: "x", keys: "y" },
      list: [1],
    },
  };
  const oldSession = createEnv({ data, sessionId: "old" });
  const newSession = createEnv({ data, sessionId: "new" });

  // when
  const stale = await hooks.check(oldSession, checkEvent("git tag v2"));
  await hooks.call(newSession, callEvent("git tag v2"));

  // then
  expect(stale.decision).toBe("ask");
  expect(Object.keys(data.approvals).sort()).toEqual(["new", "recent"]);
  expect(data.approvals.recent.keys).toEqual(["gh:release"]);
});

test("기록할 때마다 세션 시간을 갱신하고 기존 키와 합친다", async () => {
  // given
  const hooks = registerHooks();
  const data = { approvals: { "sess-1": { time: NOW - 3 * DAY, keys: ["gh:release"] } } };
  const env = createEnv({ data });

  // when
  await hooks.call(env, callEvent("git tag v2"));

  // then
  expect(env.data.approvals["sess-1"]).toEqual({ time: NOW, keys: ["gh:release", "git:tag"] });
});

for (const [label, value] of [
  ["문자열", "{broken"],
  ["배열", [1]],
  ["null", null],
  ["숫자", 7],
]) {
  test(`저장된 값이 ${label}처럼 깨져 있어도 비어 있는 것으로 보고 묻고, 기록할 때 새로 만든다`, async () => {
    // given
    const hooks = registerHooks();
    const env = createEnv({ data: { approvals: value } });

    // when
    const asked = await hooks.check(env, checkEvent("git tag v2"));
    await hooks.call(env, callEvent("git tag v2"));

    // then
    expect(asked.decision).toBe("ask");
    expect(env.data.approvals).toEqual({ "sess-1": { time: NOW, keys: ["git:tag"] } });
  });
}

test("기록은 approvals 키 하나에 한 번만 쓴다", async () => {
  // given
  const hooks = registerHooks();
  const env = createEnv();

  // when
  await hooks.call(env, callEvent("git tag v2"));

  // then
  expect(env.writes).toEqual(["approvals"]);
  expect(Object.keys(env.data)).toEqual(["approvals"]);
});

test("키가 없는 명령은 확인과 호출 모두 호스트의 판단과 결과를 그대로 두고 기록하지 않는다", async () => {
  // given
  const hooks = registerHooks();
  const env = createEnv();
  const commands = ["ls", "git status", "git push", "git push origin main", "git tag -l", "gh pr create", "cd x"];

  // when
  const checks = [];
  const calls = [];
  for (const command of commands) {
    checks.push(await hooks.check(env, checkEvent(command)));
    calls.push(await hooks.call(env, callEvent(command)));
  }

  // then
  expect(checks.every(result => result === CORE)).toBe(true);
  expect(calls.every(result => result === OK_RESULT)).toBe(true);
  expect(env.writes).toEqual([]);
});

for (const tool of ["Read", "Edit", "Write", "Task", "WebFetch"]) {
  test(`Bash도 MCP도 아닌 도구 ${tool}는 호스트의 판단과 결과를 그대로 둔다`, async () => {
    // given
    const hooks = registerHooks();
    const env = createEnv();

    // when
    const checked = await hooks.check(env, { tool, input: { command: "git tag v1" }, tool_use_id: "toolu-1" });
    const called = await hooks.call(env, { tool, command: "git tag v1", tool_use_id: "toolu-1" });

    // then
    expect(checked).toBe(CORE);
    expect(called).toBe(OK_RESULT);
    expect(env.writes).toEqual([]);
  });
}

for (const [label, event] of [
  ["입력이 없는", { tool: "Bash" }],
  ["입력이 null인", { tool: "Bash", input: null }],
  ["command가 배열인", { tool: "Bash", input: { command: ["git"] } }],
  ["입력이 문자열인", { tool: "Bash", input: "x" }],
  ["도구 이름이 숫자인", { tool: 5, input: {} }],
]) {
  test(`${label} 확인 이벤트는 호스트의 판단을 그대로 둔다`, async () => {
    // given
    const hooks = registerHooks();
    const env = createEnv();

    // when
    const result = await hooks.check(env, event);

    // then
    expect(result).toBe(CORE);
  });
}

for (const [label, event] of [
  ["command가 없는", { tool: "Bash" }],
  ["command가 배열인", { tool: "Bash", command: ["git"] }],
  ["도구 이름이 숫자인", { tool: 5 }],
]) {
  test(`${label} 호출 이벤트는 결과를 그대로 두고 기록하지 않는다`, async () => {
    // given
    const hooks = registerHooks();
    const env = createEnv();

    // when
    const result = await hooks.call(env, event);

    // then
    expect(result).toBe(OK_RESULT);
    expect(env.writes).toEqual([]);
  });
}

test("어떤 시나리오에서도 가드는 deny를 만들지 않는다", async () => {
  // given
  const hooks = registerHooks();
  const env = createEnv();
  const commands = [
    "git tag v2", "git tag -d v1", "git push --force origin v1", "gh release create v1", "gh repo delete x",
    "git tag v1 && rm -rf x", "echo $(git tag v1)", "ls",
  ];

  // when
  const decisions = [];
  for (const command of commands) {
    decisions.push(await hooks.check(env, checkEvent(command)));
    await hooks.call(env, callEvent(command));
    decisions.push(await hooks.check(env, checkEvent(command)));
  }

  // then
  expect(decisions.every(result => result.decision !== "deny")).toBe(true);
});

test("호스트가 이미 거부한 확인은 분류 없이 그대로 돌려준다", async () => {
  // given
  const hooks = registerHooks();
  const env = createEnv();
  const denied = { decision: "deny", reason: "rules" };

  // when
  const plain = await hooks.check(env, checkEvent("git tag v2"), denied);
  const destructive = await hooks.check(env, checkEvent("git tag -d v1"), denied);

  // then
  expect(plain).toBe(denied);
  expect(destructive).toBe(denied);
  expect(env.calls).toEqual([]);
});

test("거부되거나 오류로 끝난 호출은 키를 기록하지 않는다", async () => {
  // given
  const hooks = registerHooks();
  const env = createEnv();
  const denied = { deny: "blocked" };
  const failed = { result: "boom", text: "boom", isError: true };

  // when
  const deniedResult = await hooks.call(env, callEvent("git tag v2"), denied);
  const failedResult = await hooks.call(env, callEvent("git tag v3"), failed);

  // then
  expect(deniedResult).toBe(denied);
  expect(failedResult).toBe(failed);
  expect(env.writes).toEqual([]);
});

test("오류 없이 끝난 호출도 되돌릴 수 없는 작업이면 기록하지 않는다", async () => {
  // given
  const hooks = registerHooks();
  const env = createEnv();

  // when
  await hooks.call(env, callEvent("git tag -d v1"));

  // then
  expect(env.writes).toEqual([]);
});

test("MCP 쓰기 도구는 도구마다 세션에서 한 번 묻고, 기록한 뒤에는 같은 도구를 허용한다", async () => {
  // given
  const hooks = registerHooks();
  const env = createEnv();
  const tool = "mcp__claude_ai_Slack__slack_send_message";
  const other = "mcp__claude_ai_Atlassian__createJiraIssue";
  const otherSession = createEnv({ data: env.data, sessionId: "sess-2" });

  // when
  const first = await hooks.check(env, mcpCheckEvent(tool, { input: { channel: "c" } }));
  await hooks.call(env, mcpCallEvent(tool, { channel: "c" }));
  const second = await hooks.check(env, mcpCheckEvent(tool, { input: { channel: "d" } }));
  const differentTool = await hooks.check(env, mcpCheckEvent(other));
  const differentSession = await hooks.check(otherSession, mcpCheckEvent(tool));

  // then
  expect(first).toEqual({ decision: "ask", reason: firstTime(`mcp:${tool}`) });
  expect(second).toEqual({ decision: "allow", reason: approved(`mcp:${tool}`) });
  expect(differentTool.decision).toBe("ask");
  expect(differentSession.decision).toBe("ask");
});

test("MCP 삭제 도구는 항상 묻고 기록하지 않는다", async () => {
  // given
  const hooks = registerHooks();
  const env = createEnv();
  const tool = "mcp__claude_ai_Google_Drive__trash_file";

  // when
  const first = await hooks.check(env, mcpCheckEvent(tool));
  await hooks.call(env, mcpCallEvent(tool));
  const second = await hooks.check(env, mcpCheckEvent(tool));

  // then
  expect(first).toEqual({ decision: "ask", reason: DESTRUCTIVE_REASON });
  expect(second).toEqual({ decision: "ask", reason: DESTRUCTIVE_REASON });
  expect("approvals" in env.data).toBe(false);
});

for (const tool of MCP_READ) {
  test(`조회 도구와 DataGrip 쿼리 도구 ${tool}는 호스트의 판단과 결과를 그대로 두고 기록하지 않는다`, async () => {
    // given
    const hooks = registerHooks();
    const env = createEnv();

    // when
    const checked = await hooks.check(env, mcpCheckEvent(tool));
    const called = await hooks.call(env, mcpCallEvent(tool));

    // then
    expect(checked).toBe(CORE);
    expect(called).toBe(OK_RESULT);
    expect(env.writes).toEqual([]);
  });
}

test("하위 에이전트의 MCP 쓰기는 허용도 기록도 하지 않는다", async () => {
  // given
  const hooks = registerHooks();
  const env = createEnv();
  const tool = "mcp__claude_ai_Slack__slack_send_message";
  await hooks.call(env, mcpCallEvent(tool));
  const writesBefore = env.writes.length;

  // when
  const pre = await hooks.check(env, mcpCheckEvent(tool, { agentId: "a" }));
  await hooks.call(env, mcpCallEvent(tool, { agentId: "a" }));

  // then
  expect(pre).toEqual({ decision: "ask", reason: firstTime(`mcp:${tool}`) });
  expect(env.writes.length).toBe(writesBefore);
});

for (const tool of MCP_READ_VERB_SILENT) {
  test(`읽기 동사로 시작하는 MCP 도구 ${tool}는 확인과 호출 모두 그대로 두고 기록하지 않는다`, async () => {
    // given
    const hooks = registerHooks();
    const env = createEnv();

    // when
    const checked = await hooks.check(env, mcpCheckEvent(tool));
    const called = await hooks.call(env, mcpCallEvent(tool));

    // then
    expect(checked).toBe(CORE);
    expect(called).toBe(OK_RESULT);
    expect(env.writes).toEqual([]);
  });
}

for (const tool of MCP_WRITE_KEPT) {
  test(`쓰기 도구 ${tool}는 처음에 묻고, 기록한 뒤에는 같은 도구를 허용한다`, async () => {
    // given
    const hooks = registerHooks();
    const env = createEnv();

    // when
    const first = await hooks.check(env, mcpCheckEvent(tool));
    await hooks.call(env, mcpCallEvent(tool));
    const second = await hooks.check(env, mcpCheckEvent(tool));

    // then
    expect(first.decision).toBe("ask");
    expect(second).toEqual({ decision: "allow", reason: approved(`mcp:${tool}`) });
  });
}

for (const tool of MCP_DESTRUCTIVE_WINS) {
  test(`읽기 동사가 든 삭제 도구 ${tool}도 항상 묻고 기록하지 않는다`, async () => {
    // given
    const hooks = registerHooks();
    const env = createEnv();

    // when
    const first = await hooks.check(env, mcpCheckEvent(tool));
    await hooks.call(env, mcpCallEvent(tool));
    const second = await hooks.check(env, mcpCheckEvent(tool));

    // then
    expect(first).toEqual({ decision: "ask", reason: DESTRUCTIVE_REASON });
    expect(second).toEqual({ decision: "ask", reason: DESTRUCTIVE_REASON });
    expect("approvals" in env.data).toBe(false);
  });
}

for (const command of [
  "git tag v1 && echo done",
  `git -C ${quote(REPO_WITH_V1)} push origin --tags && echo "pushed"`,
  "git tag v9 && echo a b c",
]) {
  test(`관련 키가 기록된 뒤에는 끝에 단순 echo가 붙은 명령 ${JSON.stringify(command)}도 허용된다`, async () => {
    // given
    const hooks = registerHooks();
    const env = createEnv();
    await approve(hooks, env, "git tag v0", "git push origin --tags");

    // when
    const allowed = await hooks.check(env, checkEvent(command));

    // then
    expect(allowed.decision).toBe("allow");
  });
}

for (const command of [
  "git tag v1 && echo $(id)",
  "git tag v1 && echo $HOME",
  "git tag v1 && echo hi > /tmp/x",
  "git tag v1 && echo hi | sh",
  "git tag v1 && echo `id`",
  "git tag v1 && echo *",
  "git tag v1 && echo ~/x",
  "git tag v1 && echo ok && ls",
]) {
  test(`echo에 치환, 변수, 리다이렉트, 파이프, 글롭이 있는 명령 ${JSON.stringify(command)}는 키가 기록돼 있어도 묻는다`, async () => {
    // given
    const hooks = registerHooks();
    const env = createEnv();
    await approve(hooks, env, "git tag v0");

    // when
    const asked = await hooks.check(env, checkEvent(command));

    // then
    expect(asked).toEqual({ decision: "ask", reason: UNVERIFIABLE_REASON });
  });
}

for (const command of ['echo "$(git tag -d v1)"', "echo *"]) {
  test(`echo만 있는 명령 ${JSON.stringify(command)}은 치환이나 글롭이 있으면 허용하지 않는다`, async () => {
    // given
    const hooks = registerHooks();
    const env = createEnv();
    await approve(hooks, env, "git tag v0");

    // when
    const result = await hooks.check(env, checkEvent(command));

    // then
    expect(result.decision).not.toBe("allow");
  });
}

for (const command of [
  "git tag -d v1 && echo ok",
  "git push --force origin v1 && echo ok",
  "echo ok && gh release delete v1",
]) {
  test(`되돌릴 수 없는 명령 뒤에 echo가 붙은 ${JSON.stringify(command)}도 되돌릴 수 없는 작업으로 묻는다`, async () => {
    // given
    const hooks = registerHooks();
    const env = createEnv();
    await approve(hooks, env, "git tag v0", "git push origin --tags", "gh release create v2 --notes x");

    // when
    const asked = await hooks.check(env, checkEvent(command));

    // then
    expect(asked).toEqual({ decision: "ask", reason: DESTRUCTIVE_REASON });
  });
}

test("기록되지 않은 키가 든 명령은 끝에 echo가 붙어도 처음이라 묻는다", async () => {
  // given
  const hooks = registerHooks();
  const env = createEnv();

  // when
  const asked = await hooks.check(env, checkEvent("git tag v1 && echo ok"));

  // then
  expect(asked).toEqual({ decision: "ask", reason: firstTime("git:tag") });
});

test("키가 없는 echo 명령은 확인과 호출 모두 그대로 두고 기록하지 않는다", async () => {
  // given
  const hooks = registerHooks();
  const env = createEnv();

  // when
  const checked = await hooks.check(env, checkEvent("echo hello"));
  const called = await hooks.call(env, callEvent("echo hello"));

  // then
  expect(checked).toBe(CORE);
  expect(called).toBe(OK_RESULT);
  expect(env.writes).toEqual([]);
});

test("확인과 호출 hook 두 개만 Bash와 MCP 도구에 걸어 등록한다", () => {
  // given
  const hooks = registerHooks();

  // when
  const registered = hooks.entries.map(entry => [entry.event, entry.matcher]);

  // then
  expect(registered).toHaveLength(2);
  expect(registered.map(([event]) => event).sort()).toEqual(["tool.call", "tool.check"]);
  expect(registered.every(([, matcher]) => matcher.tool instanceof RegExp)).toBe(true);
  expect(hooks.entries.every(entry => typeof entry.catcher === "function")).toBe(true);
});

test("matcher는 Bash와 mcp__로 시작하는 도구만 고른다", () => {
  // given
  const hooks = registerHooks();
  const names = ["Bash", "mcp__a__b", "mcp__", "Read", "BashOutput", "xmcp__a__b", "Task"];

  // when
  const matches = hooks.entries.map(entry => names.map(name => entry.matcher.tool.test(name)));

  // then
  for (const row of matches) expect(row).toEqual([true, true, true, false, false, false, false]);
});

for (const event of ["tool.check", "tool.call"]) {
  test(`${event} hook이 실패하면 호스트의 원래 결과를 그대로 돌려준다`, async () => {
    // given
    const hooks = registerHooks();
    const env = createEnv();
    const entry = hooks.entries.find(candidate => candidate.event === event);
    const answer = event === "tool.check" ? CORE : OK_RESULT;
    const next = async () => answer;
    next.called = true;

    // when
    const result = await entry.catcher(env.$, {}, next);

    // then
    expect(result).toBe(answer);
  });
}
