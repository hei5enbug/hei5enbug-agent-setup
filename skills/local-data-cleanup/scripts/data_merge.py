"""Merge: combine a survey with the other host's verdicts."""

from __future__ import annotations

from typing import Any

from data_common import InputError, reason


def unavailable_peer(why: str) -> dict[str, Any]:
    """Stand in for a peer file when the other host's verdict could not be obtained."""
    if not why.strip():
        raise InputError("--peer-unavailable needs a reason")
    return {"host": None, "model": None, "unavailable": why.strip(), "verdicts": []}


def peer_decision(entry: dict[str, Any] | None) -> dict[str, str]:
    if entry is None:
        return {"verdict": "unknown", "reason": "no verdict was given"}
    return {"verdict": entry["verdict"], "reason": entry["reason"]}


def merged_item(item: dict[str, Any], entry: dict[str, Any] | None, unavailable: str | None) -> dict[str, Any]:
    if item["verdict"] != "candidate":
        return dict(item)
    peer = peer_decision(entry)
    if peer["verdict"] == "delete":
        return {**item, "verdict": "offer", "peer": peer}
    if peer["verdict"] == "keep":
        detail = f"the other host's verdict differs: {peer['reason']}"
    elif unavailable:
        detail = f"the other host's verdict is unknown: {unavailable}"
    else:
        detail = "the other host's verdict is unknown"
    return {**item, "verdict": "report-only", "reasons": [*item["reasons"], reason("peer", detail)], "peer": peer}


def peer_summary(peer: dict[str, Any]) -> dict[str, Any]:
    summary = {"host": peer["host"], "model": peer.get("model")}
    return {**summary, "unavailable": peer["unavailable"]} if "unavailable" in peer else summary


def merge(survey: dict[str, Any], peer: dict[str, Any], self_host: str) -> dict[str, Any]:
    by_id = {entry["id"]: entry for entry in peer["verdicts"]}
    candidates = {item["id"] for item in survey["items"] if item["verdict"] == "candidate"}
    return {
        **survey,
        "command": "merge",
        "self_host": self_host,
        "peer": peer_summary(peer),
        "ignored": sorted(identifier for identifier in by_id if identifier not in candidates),
        "items": [merged_item(item, by_id.get(item["id"]), peer.get("unavailable")) for item in survey["items"]],
    }
