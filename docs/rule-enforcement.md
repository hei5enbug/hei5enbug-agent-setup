# Rule enforcement

This table pairs each written rule of this repository with the check that enforces it. A rule missing from it relies
only on an agent reading it. `tests/test_rule_enforcement.py` fails when a test file is missing from the table.

When a repeated mistake breaks a written rule that has no check, raise it one level in the same change: remove the
possibility through structure, make it unrepresentable through a type or schema, or add a test whose error names the
correct alternative. Prove a new check fails on a real past instance of the mistake. Once a check makes a mistake
impossible, remove the written rule it replaces and update its row.

## Repository rules

| Enforcer | Rule it enforces | Written in |
|---|---|---|
| `tests/test_public_boundary.py` | No local paths, real names, secrets, or private content in tracked files and commit messages; the protected section stays unchanged and last. | `AGENTS.md` (Public boundary) |
| `tests/test_release_version.py` | One planned version since the baseline tag, the same in every manifest, never below the baseline, and no version-only commit. | `AGENTS.md` (release baseline) |
| `tests/test_model_pins.py` | Runtime files name models only by the pinned full IDs, and the pins are reverified within 14 days. | `AGENTS.md` (model pins) |
| `tests/test_korean_mirrors.py` | Every human-readable English Markdown file has a linked, non-authoritative Korean mirror outside executable folders. | `AGENTS.md` (Korean mirrors) |
| `tests/test_instruction_duplication.py` | A shared rule lives in one canonical file; host and repository files do not copy core or common rules. | `AGENTS.md` (one canonical source) |
| `tests/test_rule_enforcement.py` | This table names every test file. | This file |
| `tests/test_file_size_limit.py` | Python files under `scripts/` and `skills/*/scripts/` stay within 800 lines. | This file (owner rule: at most 800 lines per file) |

## Session instructions and delegation

| Enforcer | Rule it enforces | Written in |
|---|---|---|
| `tests/test_session_context.py` | The session hook renders core, common, and host instructions under the size caps, with the settings and route notices. | `instructions/session/`, `README.md` (Automatic instructions) |
| `tests/test_session_settings_notice.py` | A settings notice appears only when the announced settings change. | `README.md` (Automatic instructions) |
| `tests/test_commit_routing.py` | Every new commit goes through `suggest-commit` commit mode. | `instructions/session/common.md` |
| `tests/test_planning_contract.py` | Planning and design workflows stay separate, model selection has one source, independent validation runs automatically once in the final stage while an earlier review needs approval, and it is one read-only pass. | `instructions/implementation-planning.md`, `instructions/independent-model-validation.md` |
| `tests/test_delegation_contract.py` | Hosts receive the delegation contract, and earlier unmodified role files are replaced while user-edited ones stay. | `instructions/session/common.md`, `instructions/implementation-delegation.md` |
| `tests/test_claude_worker_contract.py` | Claude Code worker and agent definitions keep their declared tools, models, and adapter rules. | `agents/`, `instructions/claude-agents.md` |
| `tests/test_codex_worker_contract.py` | Codex worker and designer roles follow the assigned-worker rules and their adapter. | `standalone-agents/`, `instructions/codex-agents.md`, `README.md` (Structure) |
| `tests/test_reviewer_contract.py` | Reviewers pin their model and read-only tools, the independent validation table names the registry's reviewers per family, and the scout handles only local investigation. | `agents/`, `standalone-agents/`, `instructions/model-routing.md` |
| `tests/test_worker_route_accept.py` | The `auto` implementation worker route appears in the Claude session context and manifest. | `README.md` (Feature options) |
| `tests/test_worker_setting.py` | The worker model and effort come from the environment, the saved option, then the manifest default. | `README.md` (Feature options) |
| `tests/test_role_runner.py` | The role runner passes each role's sandbox, model, effort, and tools, and verifies the actual run. | `instructions/claude-agents.md`, `instructions/model-routing.md` |
| `tests/test_verify_spawn.py` | A spawned Codex agent counts only when its records show the expected model and effort. | `instructions/codex-agents.md` |
| `tests/test_agent_guard.py` | Codex built-in agents are denied, and installed roles run only with their pinned model and effort. | `instructions/codex-agents.md` |
| `tests/test_runtime_regressions.py` | Concurrent role-file creation keeps a user's file. | `README.md` (Structure) |
| `tests/test_codex_usage.py`, `tests/test_codex_usage_accept.py` | The Codex weekly usage reading is parsed safely and reports unknown as `null`. | `scripts/codex_usage.py`, `hooks/mod/board.js` |
| `tests/test_language_guard.py` | User-facing replies and progress updates use the response language. | `instructions/session/common.md`, `README.md` (Response language) |
| `tests/test_host_settings.py` | The session start reports effective host permission settings briefly. | `README.md` (Host settings) |
| `tests/test_hook_python.py` | Hooks pick the configured Python interpreter and fall back to `python3`. | `README.md` (Feature options) |
| `tests/test_codex_hook_trust.py` | The plugin re-trusts only its own untrusted Codex hooks, only from a clean official checkout whose HEAD the official remote currently advertises for `main` or a `v*` tag or contains in `main`, and confirms the trust through `hooks/list`. | `README.md` (Automatic instructions, Situation-based delegation) |

## Approval and data guards

| Enforcer | Rule it enforces | Written in |
|---|---|---|
| `tests/test_approval_guard.py` | Reads pass, writes need approval, destructive calls ask every time, and secret output is denied. | `instructions/session/core.md`, `README.md` (Approval guard) |
| `tests/test_approval_guard_modules.py` | The approval guard's split modules import in layers without cycles, own each swappable name once, and are denied as programs or imports exactly like the entry point. | `README.md` (Approval guard) |
| `tests/test_approval_policy_tiers.py` | The read, session approval, and every-time tiers keep their boundaries. | `README.md` (Approval guard) |
| `tests/test_approval_one_approval.py`, `tests/test_approval_session_write.py` | One approval per session covers non-destructive writes; irreversible calls still ask. | `instructions/session/core.md`, `README.md` (Approval guard) |
| `tests/test_approval_session_scope.py` | The `session` scope asks once per session except for its critical kinds. | `README.md` (Approval guard) |
| `tests/test_approval_local_scope.py`, `tests/test_approval_removal_targets.py` | Disposable local actions do not ask every time, and recursive removals resolve their targets. | `README.md` (Approval guard) |
| `tests/test_approval_recorded_reads.py` | Recorded mistake-free reads do not ask: a script that a quoted heredoc writes and the same command runs, xargs readers that print only names or counts, `env \| grep` over non-secret values, and local docker metadata; nearby content-printing or secret shapes still do. | `README.md` (Approval guard) |
| `tests/test_approval_recorded_removals.py` | Recorded mistake-free removals do not ask: targets fixed by `${VAR:?}`, a literal `for` list, `bash -c` arguments, or `mktemp` tracking kept across `unset`/`export`, a `.[!.]*` glob without a `.git`, the plugin's evaluation workspace outside `runs`, a stash drop that loses nothing, and a temp-only removal answered on Claude's dangerous-removal prompt; nearby unresolved, protected, or lossy shapes still ask. | `README.md` (Approval guard) |
| `tests/test_approval_recorded_replay.py` | Every approval-guard ask recorded without an agent mistake, replayed through the hook, neither asks nor denies, while the kept `$PWD` removal still asks. | `README.md` (Approval guard) |
| `tests/test_approval_python_risks.py` | Python code that reads a credential file or prints a secret-named environment value gets the sensitive-read decision that `cat` gets, while presence tests, names, search text, and ordinary reads and writes stay silent. | `README.md` (Approval guard) |
| `tests/test_approval_installed_code.py` | Writes into the plugin caches or the running plugin root through redirects, `tee`, `sed -i`, `cp`, `mv`, `install`, `rsync`, Python, or the native file tools are denied as self-modification after path resolution, also when a cache is a symbolic link into a git work tree, while reads of that code and writes elsewhere stay allowed. | `README.md` (Approval guard) |
| `tests/test_approval_python_sensitive_writes.py` | Python writes to `~/.ssh`, `~/.aws`, `~/.gnupg`, shell startup files, git hooks, and the Claude and Codex settings files ask every time, also under their symbolic-link names and targets and after a session-wide approval, while ordinary Python writes in the work tree and temporary space stay silent. | `README.md` (Approval guard) |
| `tests/test_approval_python_exec.py` | `exec` and `eval` of a string literal are judged like the same code written in place, including nested literals and escaped guard module names, with a literal dict namespace bound to the names the code reads, while a non-literal namespace or an `exec` of a variable, `input()`, or stdin keeps asking and still draws the other Python decisions. | `README.md` (Approval guard) |
| `tests/test_approval_false_positives.py`, `tests/test_approval_classification_safety.py` | Benign calls and secret-metadata reads are not mistaken for writes or secret output. | `README.md` (Approval guard) |
| `tests/test_approval_extensions.py`, `tests/test_approval_reuse.py` | Preapproval keys and sensitive-read approvals cover only what they name. | `README.md` (Approval guard) |
| `tests/test_approval_retries.py` | Repeated unanswered approval requests are denied until a new prompt. | `README.md` (Approval guard) |
| `tests/test_approval_heartbeat.py` | The guard confirms that the current hooks checked a tool. | `README.md` (Approval guard) |
| `tests/test_approval_risk_record.py`, `tests/test_approval_wording.py` | Write and critical calls are recorded, and approval wording follows the language setting. | `README.md` (Claude Code mod, Approval guard) |
| `tests/test_approval_review_fixes.py` | Wrapper forms, credentials in `curl`, redaction, and executable MCP input are classified safely. | `README.md` (Approval guard) |
| `tests/test_approval_tabularis.py` | Tabularis queries follow connection metadata and the matching SQL classifier. | `README.md` (Approval guard) |
| `tests/test_codex_native_approval.py`, `tests/test_permission_request_claude.py` | Each host's own approval prompt carries the session's first write approval. | `README.md` (Approval guard) |
| `tests/test_datagrip_guard.py`, `tests/test_db_read_policy.py` | Database queries run without asking only when they are reads. | `instructions/infrastructure-access.md`, `README.md` (DataGrip query guard) |
| `tests/test_limits_file_protection.py` | The database read limits file stays protected. | `README.md` (Approval guard) |
| `tests/test_secret_exec.py`, `tests/test_secret_patterns.py` | Secrets reach a command without being printed, and shared patterns redact them. | `instructions/protected-values.md` |

## Skills

| Enforcer | Rule it enforces | Written in |
|---|---|---|
| `skills/skill-builder/tests/test_metadata.py` | Skill metadata parses and validates. | `skills/skill-builder/SKILL.md` |
| `skills/skill-builder/tests/test_sibling_references.py` | A skill reads a sibling reference only as declared and never invokes a sibling skill. | `skills/skill-builder/SKILL.md` (Portability contract) |
| `skills/skill-builder/tests/test_schema_single_source.py` | Agent prompts that emit JSON follow the one schema source. | `skills/skill-builder/references/schemas.md` |
| `skills/skill-builder/tests/test_benchmark.py`, `skills/skill-builder/tests/test_evaluation.py` | Benchmarks never invent token values, and trigger evaluation works without a real model. | `skills/skill-builder/SKILL.md` |
| `skills/skill-builder/tests/test_implementation_worker_scope.py`, `skills/skill-builder/tests/test_model_runner.py` | The evaluation model adapter and runner keep their scope and process contract. | `skills/skill-builder/references/execution-methods.md` |
| `skills/skill-builder/tests/test_package_skill.py`, `skills/skill-builder/tests/test_viewer.py` | Packaging keeps file boundaries, and the eval viewer escapes HTML and saves feedback. | `skills/skill-builder/SKILL.md` |
| `skills/session-retro/tests/test_list_sessions.py` | The session list respects the day boundary, host filters, output format, and errors. | `skills/session-retro/SKILL.md` |
| `skills/decision-navigator/tests/test_local_lock.py`, `skills/decision-navigator/tests/test_decision_eval_fixtures.py` | One ticket claim wins at a time, and eval fixtures stay usable. | `skills/decision-navigator/SKILL.md` |
| `skills/deep-interview/tests/test_interview_eval_fixtures.py` | Interview eval cases keep their state flow and input files. | `skills/deep-interview/SKILL.md` |
| `skills/document-to-confluence/tests/test_column_widths.py`, `skills/document-to-confluence/tests/test_image_size.py`, `skills/document-to-confluence/tests/test_text_parity.py`, `skills/document-to-confluence/tests/test_validate_body.py` | Converted pages keep column widths, image sizes, and text parity, and never carry local paths. | `skills/document-to-confluence/SKILL.md` |
| `skills/document-to-confluence/tests/test_render_diagrams.mjs` | Diagram capture uses valid, unique file names, keeps the browser sandbox on unless asked, and always closes the browser. | `skills/document-to-confluence/references/diagrams.md` (Naming and browser flags) |
| `skills/orca-plugin-refresh/tests/test_orca_plugin_refresh.py` | Refresh sends input only to idle sessions with an empty prompt. | `skills/orca-plugin-refresh/SKILL.md` |
| `skills/tiki-taka/tests/test_runner.py`, `skills/tiki-taka/tests/test_stream_agent.py`, `skills/tiki-taka/tests/test_detached_job.py`, `skills/tiki-taka/tests/test_questions.py` | The debate runner keeps its state, completion, cleanup, and question-file rules. | `skills/tiki-taka/SKILL.md` |
| `skills/local-data-cleanup/tests/test_survey_kinds.py`, `skills/local-data-cleanup/tests/test_survey_checks.py`, `skills/local-data-cleanup/tests/test_merge_delete.py` | The survey stays read-only and turns unsafe candidates into report-only or protected items, and deletion removes only selected items that both verdicts allow. | `skills/local-data-cleanup/SKILL.md` |
| `skills/report-skill-gap/tests/test_find_tracker.py` | The tracker lookup finds the plugin root, validates its `issue-target.json`, and reports an undeclared or invalid declaration instead of guessing a tracker. | `skills/report-skill-gap/SKILL.md` |
| `tests/test_issue_target.py` | This plugin's root `issue-target.json` declares its public GitHub tracker. | `README.md` (report-skill-gap) |
| `skills/skill-builder/scripts/quick_validate.py` run over every skill | Every skill folder validates. | `README.md` (Development checks) |

## Evaluation harness

| Enforcer | Rule it enforces | Written in |
|---|---|---|
| `tests/test_e2e_eval_harness.py` | End-to-end runs load the plugin revision under test, never bypass permissions or the plugin's hooks, resume after a usage limit, and record tokens, cost, and outcomes the same way for every variant. | `evals/e2e/README.md` |
| `tests/test_e2e_eval_graders.py` | Each golden task's graders fail the unmodified fixture, pass the reference solution, and never change the graded repository. | `evals/e2e/README.md` (Graders) |
