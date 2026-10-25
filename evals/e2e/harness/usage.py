"""Extract per-request token usage from Claude transcripts and Codex rollouts, with list-price costs."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from . import pricing
from .transcript import agent_sources

CLAUDE_FIELDS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")
CODEX_FIELDS = ("input", "output", "cache_read", "cache_write", "reasoning")
SYNTHETIC_MODEL = "<synthetic>"


def claude_usage(usage: dict[str, Any]) -> dict[str, int]:
    created = usage.get("cache_creation")
    if isinstance(created, dict) and ("ephemeral_5m_input_tokens" in created or "ephemeral_1h_input_tokens" in created):
        write_5m = int(created.get("ephemeral_5m_input_tokens") or 0)
        write_1h = int(created.get("ephemeral_1h_input_tokens") or 0)
    else:
        write_5m, write_1h = int(usage.get("cache_creation_input_tokens") or 0), 0
    return {
        "input": int(usage.get("input_tokens") or 0), "output": int(usage.get("output_tokens") or 0),
        "cache_read": int(usage.get("cache_read_input_tokens") or 0), "cache_write_5m": write_5m, "cache_write_1h": write_1h,
    }


def claude_requests(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """One request per assistant message id, keeping the last usage seen for that id."""
    latest: dict[str, dict[str, Any]] = {}
    for event in events:
        message = event.get("message")
        if event.get("type") != "assistant" or not isinstance(message, dict):
            continue
        usage, model = message.get("usage"), message.get("model")
        if not isinstance(usage, dict) or not model or model == SYNTHETIC_MODEL:
            continue
        key = str(message.get("id") or event.get("uuid"))
        latest[key] = {"id": key, "model": str(model), **claude_usage(usage)}
    return list(latest.values())


def split_stream_requests(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group stream assistant events by source; stream output counts are partial, so this is a fallback."""
    launched = agent_sources(events, [])
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        if event.get("type") != "assistant":
            continue
        parent = event.get("parent_tool_use_id")
        if parent is None:
            grouped["main"].append(event)
        else:
            fallback = launched.get(str(parent), "subagent:unknown")
            grouped[f"subagent:{event['subagent_type']}" if event.get("subagent_type") else fallback].append(event)
    return {source: claude_requests(group) for source, group in grouped.items()}


def claude_requests_by_source(
    main_events: list[dict[str, Any]] | None,
    subagents: list[dict[str, Any]],
    stream_events: list[dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], str]:
    """Prefer transcript usage (final output counts); fall back to the stream. Returns the source label too."""
    if main_events:
        by_source: dict[str, list[dict[str, Any]]] = {"main": claude_requests(main_events)}
        for record in subagents:
            source = f"subagent:{(record.get('meta') or {}).get('agentType', 'unknown')}"
            by_source[source] = by_source.get(source, []) + claude_requests(record.get("events", []))
        return by_source, "transcripts"
    return split_stream_requests(stream_events), "stream"


def sum_fields(rows: Iterable[dict[str, Any]], fields: tuple[str, ...]) -> dict[str, int]:
    totals = dict.fromkeys(fields, 0)
    for row in rows:
        for name in fields:
            totals[name] += int(row.get(name, 0))
    return totals


def claude_token_report(by_source: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Tokens by source and model plus the recomputed list cost; unpriced models are listed, not guessed."""
    tokens: dict[str, dict[str, dict[str, int]]] = {}
    cost, unpriced = 0.0, set()
    for source, requests in by_source.items():
        by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for request in requests:
            by_model[request["model"]].append(request)
            price = pricing.claude_cost(request["model"], request)
            if price is None:
                unpriced.add(request["model"])
            else:
                cost += price
        tokens[source] = {model: _with_total_write(sum_fields(rows, CLAUDE_FIELDS)) for model, rows in by_model.items()}
    return {"tokens": tokens, "list_cost_usd": cost, "unpriced_models": sorted(unpriced)}


def _with_total_write(totals: dict[str, int]) -> dict[str, int]:
    return {**totals, "cache_write": totals["cache_write_5m"] + totals["cache_write_1h"]}


def codex_requests(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Distinct Codex requests: each token_count with a new total, priced by its own last_token_usage."""
    requests: list[dict[str, Any]] = []
    model, previous_total = "unknown", None
    for event in events:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if event.get("type") == "turn_context" and payload.get("model"):
            model = str(payload["model"])
        if event.get("type") != "event_msg" or payload.get("type") != "token_count":
            continue
        info = payload.get("info")
        if not isinstance(info, dict) or not isinstance(info.get("last_token_usage"), dict):
            continue
        total = info.get("total_token_usage")
        if total is not None and total == previous_total:
            continue
        previous_total = total
        requests.append({"model": model, **_codex_request(info["last_token_usage"])})
    return requests


def _codex_request(last: dict[str, Any]) -> dict[str, int]:
    cached = int(last.get("cached_input_tokens") or 0)
    written = int(last.get("cache_write_input_tokens") or 0)
    total_input = int(last.get("input_tokens") or 0)
    return {
        "input": max(total_input - cached - written, 0), "cache_read": cached, "cache_write": written,
        "output": int(last.get("output_tokens") or 0), "reasoning": int(last.get("reasoning_output_tokens") or 0),
    }


def codex_token_report(rollouts: list[dict[str, Any]]) -> dict[str, Any]:
    """rollouts: [{role, events}]. Tokens by `codex:<role>` and model, plus an estimated list cost."""
    tokens: dict[str, dict[str, dict[str, int]]] = {}
    cost, unpriced = 0.0, set()
    for rollout in rollouts:
        source = f"codex:{rollout.get('role', 'unknown')}"
        by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for request in codex_requests(rollout.get("events", [])):
            by_model[request["model"]].append(request)
            price = pricing.codex_cost(request["model"], request)
            if price is None:
                unpriced.add(request["model"])
            else:
                cost += price
        for model, rows in by_model.items():
            existing = tokens.setdefault(source, {}).get(model, dict.fromkeys(CODEX_FIELDS, 0))
            added = sum_fields(rows, CODEX_FIELDS)
            tokens[source][model] = {name: existing[name] + added[name] for name in CODEX_FIELDS}
    return {"tokens": tokens, "list_cost_usd_estimate": cost, "unpriced_models": sorted(unpriced)}


def agent_models(subagents: list[dict[str, Any]]) -> dict[str, str]:
    return {
        str((record.get("meta") or {}).get("agentType", "unknown")): str((record.get("meta") or {}).get("model", "unknown"))
        for record in subagents
    }
