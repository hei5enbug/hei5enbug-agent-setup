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

GPT Luna stays at `gpt-6-luna`, `high` by default and `xhigh` under the effort rule (owner decision 2026-11-20, which
replaced the user selection of `gpt-5.6-luna` of 2026-10-20), until the owner explicitly changes it. `gpt-sol` and
`gpt-terra` change only by a recorded role comparison under the owner's 2026-11-20 replacement rules, so a newer Sol
release is not adopted by step 2 alone. `gpt-sol-worker` (`gpt-6.2-sol`) is the second Sol pin: the GPT implementation
worker's hard-work model, while `gpt-sol` (`gpt-6.1-sol`) keeps the opponent and `text_review`.

Runtime files name models only by these full IDs; never add an alias or a runtime lookup of the newest release.
