# Release and versions

These repository development rules extend `AGENTS.md`.

## Baseline and planned version

- The release baseline is the newest `v<major>.<minor>.<patch>` tag reachable from `HEAD`. A version that appears
  only in the manifests is the planned next version, never a baseline, even when it is already on `main` or installed
  locally.
- Keep all unreleased work on that one planned version: the first change after the baseline sets it in the same
  commit, and a later change folds into it and re-chooses its level from the table below within its own commit
  instead of bumping again. Never bump the semantic version for local iterations.
- Before changing any version, state the baseline tag and the planned version to the user.
- Keep both plugin manifests, `pyproject.toml`, and `uv.lock` on the same version.
- `tests/test_release_version.py` rejects a version below the baseline, more than one planned version since it other
  than a lower-level next version later re-chosen upward, a change since it while the planned version still equals
  it, and a commit since it that changes only version files.

## Install and release

- Install only a tagged release: when the user asks to install unreleased work, tag it first, so the next change
  starts the next planned version and no reinstall needs a cachebuster.
- A release is a tag only; never make a separate commit to release or to change only the version.
- When the user publishes a release, run every development check in `README.md` on `HEAD`, tag `HEAD` `v<version>`,
  and push the tag.

## Version level

Choose the next semantic version from the highest-impact unreleased change:

| Component | Use when |
|---|---|
| Major | The harness architecture or core control logic changes enough to replace its operating contract. |
| Minor | A skill is added, removed, or merged, or its objective, requirements, or external contract changes. |
| Patch | Existing skills keep their objectives and requirements while performance, reliability, evaluation quality, or output quality improves. Multiple such changes still produce one patch bump. |
