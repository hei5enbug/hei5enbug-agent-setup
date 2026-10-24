"""Read and validate the JSON input files of merge and delete."""

from __future__ import annotations

import json
import os
from typing import Any

from data_common import HOSTS, Context, InputError

VERDICTS = ("delete", "keep", "unknown")
ITEM_VERDICTS = ("candidate", "report-only", "protected", "offer")


def load_json(path: str, label: str) -> Any:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        raise InputError(f"the {label} file does not exist: {path}") from None
    except (OSError, ValueError) as error:
        raise InputError(f"the {label} file is not readable JSON: {error}") from None


def is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def valid_item(item: Any) -> bool:
    if not isinstance(item, dict) or not is_int(item.get("id")):
        return False
    paths, identity = item.get("paths"), item.get("identity")
    paths_valid = isinstance(paths, list) and bool(paths) and all(isinstance(p, str) and os.path.isabs(p) for p in paths)
    identity_valid = (
        isinstance(identity, list)
        and isinstance(paths, list)
        and len(identity) == len(paths)
        and all(isinstance(pair, list) and len(pair) == 2 and all(is_int(n) for n in pair) for pair in identity)
    )
    text_valid = all(isinstance(item.get(key), str) for key in ("host", "kind", "display"))
    return (
        paths_valid
        and identity_valid
        and text_valid
        and item.get("verdict") in ITEM_VERDICTS
        and is_int(item.get("size"))
        and isinstance(item.get("reasons"), list)
    )


def validate_survey(data: Any, label: str = "survey") -> dict[str, Any]:
    if not isinstance(data, dict) or data.get("command") != "survey":
        raise InputError(f"the {label} file is not a survey output")
    items = data.get("items")
    if not isinstance(items, list) or not all(valid_item(item) for item in items):
        raise InputError(f"the {label} file has an invalid items list")
    ids = [item["id"] for item in items]
    if len(set(ids)) != len(ids):
        raise InputError(f"the {label} file has duplicate item ids")
    Context.from_config(data.get("config"))
    return data


def validate_plan(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or data.get("command") != "merge":
        raise InputError("the plan file is not a merge output")
    items = data.get("items")
    if not isinstance(items, list) or not all(valid_item(item) for item in items):
        raise InputError("the plan file has an invalid items list")
    Context.from_config(data.get("config"))
    return data


def validate_peer(data: Any, self_host: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise InputError("the peer file must hold a JSON object")
    if data.get("host") not in HOSTS:
        raise InputError("the peer file needs a host of claude or codex")
    if data["host"] == self_host:
        raise InputError(
            f"the peer verdict is from {data['host']}, the same host as --self-host; "
            "the second verdict must come from the other host"
        )
    if "model" in data and not isinstance(data["model"], str):
        raise InputError("the peer file model must be a string")
    verdicts = data.get("verdicts")
    if not isinstance(verdicts, list):
        raise InputError("the peer file needs a verdicts list")
    seen: set[int] = set()
    for entry in verdicts:
        valid = (
            isinstance(entry, dict)
            and is_int(entry.get("id"))
            and entry.get("verdict") in VERDICTS
            and isinstance(entry.get("reason"), str)
        )
        if not valid:
            raise InputError("each peer verdict needs an integer id, a verdict of delete, keep, or unknown, and a reason")
        if entry["id"] in seen:
            raise InputError(f"the peer file has a duplicate verdict for id {entry['id']}")
        seen.add(entry["id"])
    return data
