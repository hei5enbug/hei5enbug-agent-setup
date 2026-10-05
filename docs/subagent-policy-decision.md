# Subagent policy decision

**Status: the operating policy has been adopted, implemented, and installed locally in both hosts.**
The previous comparison experiment was closed by user decision. Its unfinished schedule is not a pending
implementation task.

## Decision and rationale

Use situation-based delegation. Keep the routing criteria in the
[session rules](../instructions/session/common.md), ownership and recovery in
[implementation execution](../instructions/implementation-execution.md), and the optional final review in
[independent model validation](../instructions/independent-model-validation.md).

The collected evidence did not establish a cost or quality advantage for delegating every task.
The adopted policy therefore weighs coordination overhead, independent execution, and main-session context
for each task. This is an engineering judgment, not a statistically confirmed winning policy.

## Applied changes

The plugin now supports direct main-session work, bounded delegation, safe main-session fallback, and one
optional cross-family review with user approval. The documentation and planning defects found during the
experiment were addressed in the shared instructions. English sources and Korean mirrors were updated together.

Local structural and regression checks passed, and both installed runtime bundles matched the source files.
These checks verify the shipped rules and installation. Actual cost, quality, and model adherence under the
changed policy have not been measured in live use.

## Experiment closure

The evaluator, detailed results, judgments, and original plan were archived outside the repository with a
SHA-256 inventory and restore instructions. Experiment-only files were removed from the product tree.
This document records the operating decision and its limits; the archive retains the experimental evidence.
A new paid evaluation requires an explicit user decision. The old schedule will not resume automatically.
