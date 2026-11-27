from __future__ import annotations

import os
from pathlib import Path

import refresh_core as core
from refresh_codex_release import verify_files, verify_hook
from refresh_core import CODEX_HOOK_TRUST, RefreshError
from refresh_install import HOOKS_TRUST_WARNING

CODEX_TRUST_TIMEOUT_SECONDS = 60


def trust_codex_hooks() -> str | None:
    """Re-trust this plugin's Codex hooks that the install left untrusted, from a verified official copy only; None when
    none are left untrusted, otherwise why they were not trusted."""
    command, cwd = [core.executable("codex"), "app-server"], str(Path.home())
    try:
        result = CODEX_HOOK_TRUST.app_server_calls(command, dict(os.environ), cwd, [("hooks/list", {"cwds": [cwd]})],
                                                   CODEX_TRUST_TIMEOUT_SECONDS)[0]
        listed = CODEX_HOOK_TRUST.listed_hooks(result, cwd)
        if CODEX_HOOK_TRUST.candidates(listed):
            CODEX_HOOK_TRUST.heal(listed, command, dict(os.environ), cwd, CODEX_TRUST_TIMEOUT_SECONDS)
    except (CODEX_HOOK_TRUST.TrustError, RefreshError) as error:
        return str(error)
    return None


def settle_companion_trust(plugins: list[dict], context: dict) -> list[dict]:
    """Narrow each companion's provisional trust warning to the hooks Codex still lists as untrusted or modified.

    One listing, taken after the last companion install, serves every companion that may have lost trust. Nothing is
    trusted unless the installed files and hook command match a pinned remote release."""
    pending = set(context.get("trust_reset", ()))
    if not pending:
        return plugins
    try:
        command, cwd = [core.executable("codex"), "app-server"], str(Path.home())
        result = CODEX_HOOK_TRUST.app_server_calls(command, dict(os.environ), cwd, [("hooks/list", {"cwds": [cwd]})],
                                                  CODEX_TRUST_TIMEOUT_SECONDS)[0]
        hooks = CODEX_HOOK_TRUST.listed_hooks(result, cwd)
        counts, unread, failures = {}, None, {}
        for plugin in plugins:
            plugin_id = plugin["plugin"]
            targets = [hook for hook in hooks if isinstance(hook, dict) and hook.get("pluginId") == plugin_id
                       and hook.get("trustStatus") in CODEX_HOOK_TRUST.UNTRUSTED]
            counts[plugin_id] = len(targets)
            pin = context.get("release_pins", {}).get(plugin_id.partition("@")[2])
            if plugin_id not in pending or not targets or not pin or not plugin.get("root"):
                continue
            try:
                root = Path(plugin["root"])
                for hook in targets:
                    verify_hook(hook, plugin_id, root)
                verify_files(root, plugin_id.partition("@")[0], pin)
                calls = [("config/value/write", {"keyPath": f'hooks.state."{hook["key"]}".{field}', "value": value,
                                                 "mergeStrategy": "replace"})
                         for hook in targets for field, value in CODEX_HOOK_TRUST.trust_values(hook["currentHash"]).items()]
                checked = CODEX_HOOK_TRUST.app_server_calls(command, dict(os.environ), cwd,
                            [*calls, ("hooks/list", {"cwds": [cwd]})], CODEX_TRUST_TIMEOUT_SECONDS)
                after = CODEX_HOOK_TRUST.listed_hooks(checked[-1], cwd)
                trusted = {hook.get("key") for hook in after if isinstance(hook, dict) and hook.get("trustStatus") == "trusted"}
                if not {hook["key"] for hook in targets} <= trusted:
                    raise CODEX_HOOK_TRUST.TrustError("Codex did not confirm every hook as trusted")
                counts[plugin_id] = 0
                plugin["codex_hooks_trusted"] = True
            except (CODEX_HOOK_TRUST.TrustError, RefreshError, OSError, ValueError) as error:
                failures[plugin_id] = str(error)
    except (CODEX_HOOK_TRUST.TrustError, RefreshError, OSError):
        counts, unread, failures = {}, "Codex hook trust state could not be read", {}
    settled = []
    for plugin in plugins:
        if plugin["plugin"] not in pending:
            settled.append(plugin)
            continue
        count = counts.get(plugin["plugin"], 0)
        kept = [warning for warning in plugin["warnings"] if warning["code"] != HOOKS_TRUST_WARNING["code"]]
        if unread:
            kept.append({**HOOKS_TRUST_WARNING, "detail": unread})
        elif count:
            kept.append({**HOOKS_TRUST_WARNING, "detail": failures.get(plugin["plugin"]) or f"Codex lists {count} hook{'s' if count != 1 else ''} as untrusted or modified"})
        settled.append({**plugin, "warnings": kept})
    return settled
