# Execution record: token and context efficiency

This record follows the plan's no-regression gate. `B0` is commit
`72f66ac69cf02ac7b7f64bfba0a11adc8736ed04`. A shorter Markdown file or fewer bytes in a
single prompt is not, by itself, evidence of a cheaper complete skill run. The source snapshot,
candidate instructions, fixtures, and checks were compared before deciding what to retain.
The compact per-pair [native trial metrics](trial-metrics.json) omit prompt and answer text.

## Disposition by finding

| Finding | Outcome and reason |
|---|---|
| F01 | Retained B0. Two accuracy-first prompt revisions produced sampled descriptions with trigger and exclusion boundaries, but neither passed the native completion-time gate on both hosts. The B0 instruction that permits accuracy loss remains a known defect. |
| F02 | Captured separate native model, effort, usage, cache, and wall-time receipts during development. No shipping metrics framework or unmeasured token-saving claim was added. |
| F03 | Added runnable evaluation cases, files, operator guides, and deterministic fixture checks across the affected skills. These are coverage inputs, not successful native skill-behavior trials. |
| F04 | Kept discovery descriptions at B0. Shortening them without the required positive/negative native routing matrix would risk missed or false skill selection. |
| F05 | Reverted the Deep Interview reference-read candidate: the tested one-question and post-compaction routes loaded more bytes. Kept the multi-round and recovery fixtures. |
| F06 | Kept the host UI reference at B0 because F05 left no demonstrated residual saving and the native UI operator case was unavailable. |
| F07 | Kept interview history and review handling at B0; the required native long-round and recovery comparison was unavailable. |
| F08 | Reverted the renderer split because SVG-to-PNG work loaded more bytes. Kept diagram evaluation inputs. |
| F09 | Reverted the Skill Builder mode split: the small-edit route saved bytes, but the formal routes gained a reference read and did not show a complete-path saving. |
| F10 | Retained schema reads at B0 after the F09 dependency and route comparison; no correct, measured narrower schema route was established. |
| F11 | Reverted prompt-data deduplication after both native hosts failed at least one completion-time gate. |
| F12 | Retained result-printing behavior at B0; no measured complete-path gain justified a changed parent output. |
| F13 | Kept B0. A focused test confirms the packager validates metadata and bundled checks once per call; removing the preceding standalone validation requires native complete-path evidence that was unavailable. |
| F14 | Reverted the suggest-commit collection rewrite. Its native trial missed the time gate and broadened a precise HTTP 503 change into a general transient-error claim. Added isolated Git fixtures for scope and convention tests. |
| F15 | Reverted the combined suggest-commit prose compression with F14; kept new style and scope evaluation cases. |
| F16 | Reverted the docs-rewrite strict/follow-up split because the added reference read outweighed the small ordinary-route saving. Kept a long Korean input fixture. |
| F17 | Preserved the existing scoped Korean design pattern read. Corrected evaluation cases for independent-review approval and related branches. |
| F18 | Reverted the Decision Navigator body split despite a static byte saving: required native human-in-the-loop trials were unavailable. Kept a 100-ticket fixture and operator guide. |
| F19 | Reverted the expanded frontier procedure because its tested scan loaded about 19 KB more than B0. Kept the frontier/race cases. |
| F20 | Reverted the Confluence source-body split after the heavy route gained a read and bytes. Kept format/source fixtures. |
| F21 | Reverted asset batching and renderer edits: three local paired Chrome trials did not improve median time. Kept update/asset fixtures. |
| F22 | Reverted the debate recovery split: the unresolved route gained 1,222 bytes and a reference read. Kept recovery cases and focused runner tests. |
| F23 | Reverted the refresh recovery split: the recovery route gained 1,853 bytes and a reference read. Kept transaction/preview cases. |
| F24 | Reverted OmO instructions: the proposed route added 622 bytes while still requiring 20 source reads. Added a pinned upstream source manifest and verified materializer. |
| F25 | Reverted prompt-prefix reordering: Sonnet/high improved median but worsened observed maximum and output usage. |
| F26 | Retained the existing host/tool discovery contract. Additional recurring service instructions had no demonstrated savings. |
| F27 | Retained existing recovery checkpoints. Extra text did not pass the route-wise cost and native recovery gates. |

## Native comparison evidence

For each row below, three matched `old/new`, `new/old`, `old/new` pairs used the same
synthetic task and requested model/effort. Values are seconds from request to the usable
artifact. These are small local samples, not a general latency bound. The full source for
each candidate stayed outside shipping skill paths. The exact Codex model selector was
`gpt-5.6-luna` at `xhigh`; its local event stream did not echo a resolved model ID.

| Candidate and host | B0/old median | Candidate median | B0/old max | Candidate max | Decision |
|---|---:|---:|---:|---:|---|
| F01 first prompt, Sonnet 5/high | 9.407 | 10.460 | 10.090 | 13.971 | Reject. |
| F01 first prompt, Codex Luna/xhigh | 32.040 | 26.526 | 43.171 | 32.108 | Host passed time only; insufficient to adopt. |
| F01 second prompt, Sonnet 5/high | 7.098 | 7.392 | 13.948 | 8.793 | Reject. |
| F01 second prompt, Codex Luna/xhigh | 21.778 | 10.607 | 21.901 | 32.749 | Reject. |
| F11 deduplication, Sonnet 5/high | 8.387 | 9.568 | 22.867 | 15.001 | Reject. |
| F11 deduplication, Codex Luna/xhigh | 19.239 | 31.344 | 25.142 | 39.208 | Reject. |
| F14–F15 compression, Sonnet 5/high | 15.246 | 17.492 | 15.681 | 17.538 | Reject; also lost meaning. |
| F14–F15 compression, Codex Luna/xhigh | 14.247 | 12.581 | 16.287 | 18.379 | Reject. |
| F25 prefix order, Sonnet 5/high | 8.396 | 7.739 | 8.507 | 10.876 | Reject. |

The F21 local renderer trial used three paired Chrome runs with two images. Old median/max
were 1.853/2.513 seconds; candidate median/max were 1.860/1.868 seconds. Both produced
byte-identical images, and the candidate's partial-failure path reported the failed item.
The median gate still failed. This browser test does not establish a hosted Confluence result.

## Coverage and limits

New evaluation data covers Deep Interview, diagrams, commit suggestions, decision maps,
Confluence source/update cases, document rewriting, design review, debate recovery,
refresh, and OmO configuration. The OmO materializer verified 20 mandatory and 13
conditional files against the pinned upstream `dev` revision
`c18ab758961b88bc07f7578ddcbcb286810a524f`. Source code from that project was
not copied into this repository. Confluence connector responses in the local fixtures
are simulated; no hosted page was written. The user did not supply a human operator for
the native question UI trials, so their dependent candidates stayed at B0.

The development checks passed: `quick_validate.py` for all 11 skills, the complete Python
test suite, and all 10 Node diagram-renderer tests. All 103 evaluation cases parse and
their listed local inputs exist. The plan's local links resolve, the English/Korean mirror
checks pass, and `git diff --check` reports no whitespace errors.

No output-quality or token-saving guarantee is inferred from structural tests, file size,
or these limited native trials. Findings left at B0 remain opportunities for a separately
authorized evaluation with representative tasks and the missing native capabilities.
