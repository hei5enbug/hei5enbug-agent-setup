"""Trust the exported plugin's hooks inside a run's isolated CODEX_HOME.

A role runner's own Codex child starts without the hook-trust bypass and refuses hooks that Codex reports untrusted. The
harness vets the export itself, so it records each of this plugin's hooks as trusted through a Codex app-server, using
the helpers of the plugin's own trust script and none of its official-checkout verification."""

from __future__ import annotations

import importlib.util
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping

from .config import REPO_ROOT

HOOK_TRUST_SCRIPT = REPO_ROOT / "scripts" / "codex_hook_trust.py"
HOOK_TRUST_TIMEOUT_SECONDS = 60.0


class HookTrustError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def hook_trust_module() -> ModuleType:
    """The plugin's `codex_hook_trust` script, loaded from its file so no folder joins `sys.path`."""
    spec = importlib.util.spec_from_file_location("codex_hook_trust", HOOK_TRUST_SCRIPT)
    if spec is None or spec.loader is None:
        raise HookTrustError(f"cannot load {HOOK_TRUST_SCRIPT.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def plugin_hooks(hooks: list[Any], plugin_id: str) -> list[dict[str, Any]]:
    return [hook for hook in hooks if isinstance(hook, dict) and hook.get("pluginId") == plugin_id]


def trust_plugin_hooks(codex_bin: str, env: Mapping[str, str], cwd: str, timeout: float = HOOK_TRUST_TIMEOUT_SECONDS) -> list[str]:
    """Trust this plugin's untrusted or modified hooks in the CODEX_HOME that `env` names; return the keys it trusted.

    Raise HookTrustError when Codex cannot be asked, no hook of the plugin is listed, or any of them is still not
    trusted after the writes."""
    trust = hook_trust_module()
    command, request = [codex_bin, "app-server"], ("hooks/list", {"cwds": [cwd]})
    try:
        before = trust.listed_hooks(trust.app_server_calls(command, dict(env), cwd, [request], timeout)[0], cwd)
        targets = trust.candidates(before)
        writes = [("config/value/write", params) for params in trust.trust_writes(targets)]
        after = trust.listed_hooks(trust.app_server_calls(command, dict(env), cwd, [*writes, request], timeout)[-1], cwd)
    except trust.TrustError as error:
        raise HookTrustError(str(error)) from error
    ours = plugin_hooks(after, trust.PLUGIN_ID)
    if not ours:
        raise HookTrustError(f"Codex lists no {trust.PLUGIN_ID} hooks in the run's CODEX_HOME")
    pending = [hook.get("key") for hook in ours if hook.get("trustStatus") != "trusted"]
    if pending:
        raise HookTrustError(f"Codex still lists {len(pending)} {trust.PLUGIN_ID} hooks as not trusted: {pending}")
    return [hook["key"] for hook in targets]
