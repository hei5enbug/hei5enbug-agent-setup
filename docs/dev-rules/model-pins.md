# Model pins

These repository development rules extend `AGENTS.md`. Apply them before changing this repository when
`PINS_VERIFIED_ON` in `tests/test_model_pins.py` is more than 14 days old.

1. Resolve the newest generally available model of every family in `pins` in `config/model-registry.json`, except GPT
   Luna, then set `PINS_VERIFIED_ON` to that date. Use the official
   [Claude models overview](https://platform.claude.com/docs/en/about-claude/models/overview), the
   [OpenAI model catalog](https://developers.openai.com/api/docs/models), and each host's model catalog, and exclude
   previews.
2. When a family has a newer release, update `pins` in `config/model-registry.json` and every reference in the same
   change until `tests/test_model_pins.py` passes.

GPT Luna stays at the user-selected `gpt-5.6-luna`, `high` by default and `xhigh` under the effort rule (user selection
2026-10-20), until the user explicitly changes that selection.

Runtime files name models only by these full IDs; never add an alias or a runtime lookup of the newest release.
