"""List-price computation for Claude token usage and Codex rollout requests."""

from __future__ import annotations

from typing import Any

MTOK = 1_000_000
HAIKU_LONG_PROMPT = 100_000
CODEX_LONG_CONTEXT = 272_000

CLAUDE_PRICES: dict[str, dict[str, float]] = {
    "claude-fable-5-1": {"input": 10.0, "write_5m": 12.5, "write_1h": 20.0, "read": 0.25, "output": 50.0},
    "claude-opus-5-5": {"input": 4.0, "write_5m": 5.0, "write_1h": 8.0, "read": 0.20, "output": 20.0},
    "claude-sonnet-5-5": {"input": 2.0, "write_5m": 2.5, "write_1h": 4.0, "read": 0.10, "output": 10.0},
    "claude-haiku-5-5": {"input": 0.10, "write_5m": 0.125, "write_1h": 0.20, "read": 0.01, "output": 0.50},
}
CLAUDE_LONG_PRICES: dict[str, dict[str, float]] = {
    "claude-haiku-5-5": {"input": 0.50, "write_5m": 0.625, "write_1h": 1.0, "read": 0.05, "output": 2.50},
}

CODEX_PRICES: dict[str, dict[str, float]] = {
    "gpt-6-astra": {"input": 10.0, "cached": 1.0, "write": 12.5, "output": 50.0},
    "gpt-6.1-sol": {"input": 2.0, "cached": 0.10, "write": 2.5, "output": 10.0},
    "gpt-5.6-luna": {"input": 0.20, "cached": 0.02, "write": 0.25, "output": 1.20},
}
CODEX_LONG_PRICES: dict[str, dict[str, float]] = {
    "gpt-6-astra": {"input": 20.0, "cached": 2.0, "write": 25.0, "output": 75.0},
    "gpt-6.1-sol": {"input": 4.0, "cached": 0.20, "write": 5.0, "output": 15.0},
    "gpt-5.6-luna": {"input": 0.40, "cached": 0.04, "write": 0.50, "output": 1.80},
}


def claude_prompt_tokens(usage: dict[str, Any]) -> int:
    return int(usage.get("input", 0)) + int(usage.get("cache_read", 0)) + int(usage.get("cache_write_5m", 0)) + int(
        usage.get("cache_write_1h", 0)
    )


def claude_cost(model: str, usage: dict[str, Any]) -> float | None:
    """Return the list cost of one request's usage, or None when the model has no listed price."""
    prices = CLAUDE_PRICES.get(model)
    if prices is None:
        return None
    if model in CLAUDE_LONG_PRICES and claude_prompt_tokens(usage) > HAIKU_LONG_PROMPT:
        prices = CLAUDE_LONG_PRICES[model]
    total = (
        int(usage.get("input", 0)) * prices["input"]
        + int(usage.get("cache_write_5m", 0)) * prices["write_5m"]
        + int(usage.get("cache_write_1h", 0)) * prices["write_1h"]
        + int(usage.get("cache_read", 0)) * prices["read"]
        + int(usage.get("output", 0)) * prices["output"]
    )
    return total / MTOK


def codex_cost(model: str, request: dict[str, Any]) -> float | None:
    """Return the list cost of one Codex request, priced by its own input size."""
    prices = CODEX_PRICES.get(model)
    if prices is None:
        return None
    uncached = int(request.get("input", 0))
    cached = int(request.get("cache_read", 0))
    written = int(request.get("cache_write", 0))
    if uncached + cached + written > CODEX_LONG_CONTEXT:
        prices = CODEX_LONG_PRICES[model]
    total = (
        uncached * prices["input"]
        + cached * prices["cached"]
        + written * prices["write"]
        + int(request.get("output", 0)) * prices["output"]
    )
    return total / MTOK
