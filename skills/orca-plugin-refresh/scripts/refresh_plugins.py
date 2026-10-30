from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Sequence

import refresh_core as core
from refresh_core import PLUGIN_ID, RefreshError, load_plugin_script, run_json
from refresh_install import (HOOKS_TRUST_WARNING, bundle_digest, check_hooks, codex_home, codex_trust_reset, hooks_digest, inside,
                             read_manifest, run_install)


COMPANION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}@[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
COMPANION_LIMIT = 10
COMPANION_ENV = "HEI5ENBUG_REFRESH_PLUGINS"


def local_source(host: str, plugin_id: str, item: object, context: dict) -> dict | None:
    """{version, note?} when the plugin loads from a local source, which is never installed; None otherwise."""
    name, _, marketplace = plugin_id.partition("@")
    if not isinstance(item, dict):
        return None
    if host == "claude":
        entry = claude_marketplace(context, marketplace)
        if entry and entry.get("source") in ("directory", "file"):
            return {"version": folder_version(entry, name), "note": "loads_from_folder_on_reload"}
        return None
    source = item.get("marketplaceSource")
    if (source.get("sourceType") if isinstance(source, dict) else None) != "git":
        return {"version": item.get("version") if isinstance(item.get("version"), str) else None}
    return None


def companion_entries(value: object) -> list:
    if value is None:
        return []
    if isinstance(value, str):
        return [part for part in re.split(r"[,\s]+", value) if part]
    return list(value) if isinstance(value, list) else [value]


def companion_ids(also: Sequence[str]) -> tuple[list[str], dict]:
    """The companion plugin IDs: --also, else the environment variable, else the saved Claude option."""
    extra: dict = {}
    entries = list(also) or companion_entries(os.environ.get(COMPANION_ENV))
    if not entries:
        saved, problem = load_plugin_script("plugin_toggles").saved_options(("refresh_plugins",))
        if problem:
            extra["notice"] = f"Ignored the saved refresh_plugins option: {problem}."
        entries = companion_entries(saved.get("refresh_plugins"))
    ids: list[str] = []
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, str) or not COMPANION_ID.fullmatch(entry):
            raise RefreshError("plugin_id_invalid", "A refresh plugin entry is not a valid plugin@marketplace ID.", {"entry": index})
        if entry != PLUGIN_ID and entry not in ids:
            ids.append(entry)
    if len(ids) > COMPANION_LIMIT:
        extra["companions_dropped"] = len(ids) - COMPANION_LIMIT
    return ids[:COMPANION_LIMIT], extra


def claude_marketplace(context: dict, marketplace: str) -> dict | None:
    if "marketplaces" not in context:
        payload = run_json([core.executable("claude"), "plugin", "marketplace", "list", "--json"])
        context["marketplaces"] = [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []
    entries = [item for item in context["marketplaces"] if item.get("name") == marketplace]
    return entries[0] if len(entries) == 1 else None


def folder_version(entry: dict, name: str) -> str | None:
    """The version of a plugin that loads from a local marketplace folder, or None when any lookup step fails."""
    location = entry.get("installLocation")
    if not isinstance(location, str) or not location:
        return None
    base = Path(location)
    try:
        catalog = json.loads((base / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        source = next(item["source"] for item in catalog["plugins"] if isinstance(item, dict) and item.get("name") == name)
        if not isinstance(source, str):
            return None
        folder = base / source
        if not inside(base, folder):
            return None
        version = json.loads((folder / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, StopIteration):
        return None
    return version if isinstance(version, str) and version else None


def describe_plugin(host: str, plugin_id: str, context: dict) -> dict | None:
    """The plugin's listing on `host` as {version, root, local, note?}, or None unless it is installed and enabled exactly once."""
    name, _, marketplace = plugin_id.partition("@")
    payload = run_json([core.executable(host), "plugin", "list", "--json"])
    if host == "claude":
        items = [item for item in payload if isinstance(item, dict) and item.get("id") == plugin_id] if isinstance(payload, list) else []
    else:
        listed = payload.get("installed") if isinstance(payload, dict) else None
        items = [item for item in listed if isinstance(item, dict) and item.get("pluginId") == plugin_id] if isinstance(listed, list) else []
    if len(items) != 1 or items[0].get("enabled") is not True:
        return None
    item = items[0]
    local = local_source(host, plugin_id, item, context)
    if local:
        return {"root": None, "local": True, **local}
    if host == "claude":
        root = Path(str(item.get("installPath") or ""))
    else:
        root = codex_home() / "plugins" / "cache" / marketplace / name / str(item.get("version"))
    version = item.get("version")
    if not isinstance(version, str) or not version or not root.is_absolute() or not root.is_dir():
        raise RefreshError(f"{host}_root_missing", f"The installed {host} plugin directory is unavailable.")
    return {"version": version, "root": root.resolve(), "local": False}


def validate_companion(host: str, plugin_id: str, found: dict) -> str | None:
    """Check the installed manifest and every plugin-root hook target; return the hook files digest, None without one."""
    root = found["root"]
    manifest = read_manifest(host, root, plugin_id.partition("@")[0], found["version"])
    hooks_bytes, _ = check_hooks(host, root, strict=False, manifest=manifest)
    return hashlib.sha256(hooks_bytes).hexdigest() if hooks_bytes is not None else None


def refresh_companion(host: str, plugin_id: str, update: bool, context: dict) -> dict:
    result = {"plugin": plugin_id, "status": "error", "before_version": None, "after_version": None, "warnings": []}
    try:
        found = describe_plugin(host, plugin_id, context)
        if found is None:
            result["status"] = "not_installed"
            return result
        result["before_version"] = result["after_version"] = found["version"]
        if found["local"]:
            result["status"] = "local_source"
            if found.get("note"):
                result["note"] = found["note"]
            return result
        before_hooks = hooks_digest(host, found["root"])
        before_bundle = bundle_digest(found["root"]) if host == "codex" else None
        if update:
            blocked = run_install(host, plugin_id, context)
            if blocked:
                result.update(status="deferred", code=blocked.code, message=blocked.message)
                return result
            found = describe_plugin(host, plugin_id, context)
            if found is None or found["local"]:
                raise RefreshError(f"{host}_plugin_missing", f"The {host} plugin is not installed and enabled exactly once after the update.")
            result["after_version"] = found["version"]
        after_hooks = validate_companion(host, plugin_id, found)
        result["status"] = "updated" if result["after_version"] != result["before_version"] else "current"
        if update and host == "codex" and codex_trust_reset(before_hooks, after_hooks, before_bundle,
                                                            bundle_digest(found["root"])):
            result["warnings"].append(dict(HOOKS_TRUST_WARNING))
            context.setdefault("trust_reset", []).append(plugin_id)
    except RefreshError as error:
        result.update(status="error", code=error.code, message=error.message)
    except (OSError, ValueError):
        result.update(status="error", code="plugin_check_failed", message=f"A {host} plugin file could not be checked.")
    return result
