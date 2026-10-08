# Model routing

This file defines shared routing; host agent rules own its loading trigger and explain how to run and verify
each role. It does not change the selected main model or effort.

## Route by purpose and output

Classify a delegated task by both its purpose and where its output will go.

| Work | Route |
|---|---|
| Main-owned work | Follow [session ownership rules](session/common.md). |
| Implementation that edits the actual repository or skill | Follow the host's implementation execution rules and pinned implementation role. |
| UI code, visual design, or diagrams | Use the host's designer route. A text or style-value edit that keeps layout and component structure may use the implementation worker. |
| Bounded local evidence gathering | Use the host's scout role when delegation is authorized and worthwhile. |
| Public, read-only research | Use the host's researcher role only when its public tools are available and its pinned settings are verified. Otherwise, continue in the main session. |
| Skill research, trial execution, grading, comparison, analysis, or optimization | Apply the skill's evaluation contract before generic skill-worker routing. |
| Disposable trial output | Keep it in the evaluation workspace. Do not treat it as accepted implementation. |

The researcher gathers claims, public URLs or file locations, supporting evidence, contradictions, and gaps. It
does not make planning, architecture, or acceptance decisions. Existing service-access rules still apply.

## Keep role settings fixed

Use these production settings unless a separately approved comparison qualifies for a scoped change:

| Role | Codex | Claude Code |
|---|---|---|
| Local scout | `gpt-6-luna`, `xhigh` | `claude-sonnet-5-5`, `medium` |
| Implementation worker | `gpt-6-luna`, `xhigh` | `codex exec` with `gpt-6-luna`, `xhigh` (default); `claude-sonnet-5-5`, `high` worker when `codex_worker` is off, on request, or as fallback |
| Public researcher | `gpt-6-luna`, `xhigh` | `claude-sonnet-5-5`, `medium` |
| Designer | `claude -p` with `claude-opus-5-5`, `xhigh`; when Claude is unavailable, the `designer` role with `gpt-6-astra`, `xhigh` | `claude-opus-5-5`, `xhigh` |
| Skill Builder evaluation participant | `gpt-6-luna`, `xhigh` | `claude-sonnet-5-5`, `high` |

Verify the role's effective model and effort from host records and relevant non-secret settings before relying
on its result. A requested value, role name, or agent guard acceptance is not evidence of the effective model.
If settings are missing, conflicting, or lower than the role requires, use the authorized main-session fallback
and report the limitation once. Never silently substitute a model or effort, or change user settings to enable
delegation.

For public research, check that the host exposes the required public search and fetch tools and that the
researcher role resolves to its pinned model and effort. If either condition fails, the main session continues
under the existing service-access rules.

## Skill evaluation precedence

For evaluation participants that Skill Builder launches to evaluate a target skill, Skill Builder's required
model and effort table takes precedence over generic host skill-worker routing. The target skill's metadata or
frontmatter does not override that evaluator contract. A native role can run only when its effective settings
match the Skill Builder table. Do not route a `high`-effort evaluator to a `medium` scout, and do not raise a
shared scout's production effort to resolve the mismatch.

When no native role matches, use a Skill Builder-approved evaluation runner only when its actual model and
effort can be verified. Otherwise follow Skill Builder's unavailable-capability path. A runner invocation
alone is not proof of its effective settings.

Ordinary method comparisons keep model and effort fixed on both sides. A specifically approved model or effort
comparison may vary only its one frozen candidate setting, in a disposable evaluation workspace. It cannot
change production role settings or promote its trial output into the repository. Keep an unqualified candidate
inactive; adopt a production change only with matched output-quality and recurring-token evidence that supports
it for the tested workload.

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
