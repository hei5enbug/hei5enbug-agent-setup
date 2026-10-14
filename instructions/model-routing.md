# Model routing

This file defines shared routing; host agent rules own its loading trigger and explain how to run and verify
each role. It does not change the selected main model or effort.

## Route by purpose and output

Classify a delegated task by both its purpose and where its output will go.

| Work | Route |
|---|---|
| Main-owned work | Follow [session ownership rules](session/common.md). |
| Implementation that edits the actual repository or skill | Follow the host's implementation execution rules and pinned implementation role. |
| UI code, visual design, or diagrams | Use the host's designer route, except the kinds the host session file assigns to the main session. A text or style-value edit that keeps layout and component structure may use the implementation worker. |
| Bounded local evidence gathering | Use the host's scout role when delegation is authorized and worthwhile. |
| Public, read-only research | Use the host's researcher role only when its public tools are available and its pinned settings are verified. Otherwise, continue in the main session. |
| Skill review role (review persona, grader, comparator, analyzer) | Use the reviewer route in the table below. |
| Skill Builder trial execution and other non-review participants | Use the host's upper model from the Skill Builder adapter below. |
| Disposable trial output | Keep it in the evaluation workspace. Do not treat it as accepted implementation. |

The researcher gathers claims, public URLs or file locations, supporting evidence, contradictions, and gaps. It
does not make planning, architecture, or acceptance decisions. Existing service-access rules still apply.

## Keep role settings fixed

GPT Luna is explicitly pinned to `gpt-5.6-luna` and `xhigh`. Never select another Luna release or effort,
including through a saved default or resume. If the host cannot verify these settings, stop that delegation
and use the named cross-family fallback or the main session. Automatic newest-release refresh excludes this
user-selected pin.

Use these production settings unless a separately approved comparison qualifies for a scoped change:

| Role | Codex | Claude Code |
|---|---|---|
| Local scout | `gpt-5.6-luna`, `xhigh` | `role_runner.py scout` with `gpt-5.6-luna`, `xhigh`, read-only; fallback `scout` with `claude-sonnet-5-5`, `medium` |
| Implementation worker | `gpt-5.6-luna`, `xhigh` | `sonnet-worker` with `claude-sonnet-5-5`, `high` (default, `implementation_worker` is `sonnet`); `role_runner.py worker` with `gpt-5.6-luna`, `xhigh` when it is `codex` or on request; `worker` with `claude-haiku-5-5`, `high` when it is `haiku`, on request, or as the runner fallback |
| Public researcher | `gpt-5.6-luna`, `xhigh` | `role_runner.py researcher` with `gpt-5.6-luna`, `xhigh`, web search; fallback `researcher` with `claude-haiku-5-5`, `medium` |
| Designer | `claude -p` with `claude-opus-5-5`, `xhigh`; when Claude is unavailable, the `designer` role with `gpt-6-astra`, `xhigh` | `claude-opus-5-5`, `xhigh` |
| Skill Builder trial execution and other non-review participants | `gpt-6.1-sol`, `xhigh` | `claude-opus-5-5`, `high` |
| Skill review role (review persona, grader, comparator, analyzer) | `claude -p` with `claude-opus-5-5`, `high`; fallback `reviewer` with `gpt-6.1-sol`, `xhigh` | `role_runner.py reviewer` with the `review_model` setting (default `gpt-6-astra`), `xhigh`; fallback `reviewer` with `claude-opus-5-5`, `high` |

Verify the role's effective model and effort from host records and relevant non-secret settings before relying
on its result, or rely on the enforcement the host's agent rules name, such as the mod's role pinning or the role
runner's verification. A requested value, role name, or agent guard acceptance is not evidence of the effective
model. If settings are missing, conflicting, or lower than the role requires, use the authorized main-session
fallback. Never silently substitute a model or effort, or change user settings to enable delegation.

For public research, check that the host exposes the required public search and fetch tools and that the
researcher role resolves to its pinned model and effort. If either condition fails, the main session continues
under the existing service-access rules.

## Skill review and execution

A skill review role is read-only judgment work, including a review persona, grader, comparator, or analyzer. Use the
reviewer route from the table first, following the host's skill-worker instructions. If it is missing,
unauthenticated, limited, fails to start the pinned model, times out, or lacks model evidence, use the plugin
`reviewer` role with the fallback model from the table. The reviewer returns findings only. The main session reviews
the same material once and makes the final decision. Do not run another review round.

Skill Builder's trial execution and other non-review participants use the host's upper model from the table. A review
role follows the reviewer route even when Skill Builder requests grading, comparison, or analysis. Target-skill
metadata and frontmatter do not override these settings. Do not use `scout` as a review role or `reviewer` to write
trial output.

Ordinary method comparisons keep model and effort fixed on both sides. A specifically approved model or effort
comparison may vary only its one frozen candidate setting, in a disposable evaluation workspace. It cannot change
production role settings or promote its trial output into the repository. Keep an unqualified candidate inactive;
adopt a production change only with matched output-quality and recurring-token evidence that supports it for the
tested workload.

## Keep host and model identity separate

The execution host remains the same when the main model changes. Selecting GPT in Claude Code keeps Claude
Code's tools, permissions, agent definitions, and execution rules active. It does not turn Claude Code into
Codex or change a Claude worker's pinned settings.

Before dispatching after a main-model or profile switch, and after session resume, revalidate the effective
role settings and relevant tool availability. Preserve each role's pinned model and effort. Never rewrite a
worker's model to match the main model.

Choose the optional independent reviewer from the actual model family that authored the deliverable, not from
the execution host. Follow the existing reviewer approval and model-mapping rules. When both families materially
contributed, record that contribution; the final authoring family still selects the single approved reviewer.
Do not claim independence from every contributor or add another review call.
