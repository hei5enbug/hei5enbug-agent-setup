from __future__ import annotations

import copy
import io
import json
import os
import re
import shlex
import stat
import subprocess
import tarfile
import tempfile
import tomllib
from pathlib import Path

import refresh_core as core
from refresh_install import bundle_digest, codex_home, hooks_digest

TAG = re.compile(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")
INSTALL_MARKER = ".codex-marketplace-install.json"
UNTAGGED = "codex_marketplace_untagged"


def read_config() -> tuple[Path, str, dict]:
    path = codex_home() / "config.toml"
    try:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        return path, text, tomllib.loads(text)
    except (OSError, ValueError) as error:
        raise core.RefreshError("codex_config_unreadable", "Codex marketplace configuration could not be read.") from error


def remote_tags(source: str) -> dict[str, str]:
    output = core.run([core.executable("git"), "ls-remote", "--tags", "--", source, "refs/tags/v*"], timeout=120)
    tags: dict[str, str] = {}
    for line in output.stdout.splitlines():
        revision, _, ref = line.partition("\t")
        name = ref.removeprefix("refs/tags/").removesuffix("^{}")
        if TAG.fullmatch(name) and re.fullmatch(r"[0-9a-f]{40,64}", revision):
            if ref.endswith("^{}") or name not in tags:
                tags[name] = revision
    return tags


def replace_refs(text: str, refs: dict[str, str]) -> str:
    original = tomllib.loads(text)
    wanted = copy.deepcopy(original)
    lines = text.splitlines(keepends=True)
    for marketplace, tag in refs.items():
        wanted["marketplaces"][marketplace]["ref"] = tag
        start = None
        for index, line in enumerate(lines):
            match = re.fullmatch(r"\s*\[([^\n]+)\]\s*(?:#.*)?\n?", line)
            if not match:
                continue
            try:
                header = tomllib.loads(f"[{match[1]}]\n")
            except ValueError:
                continue
            if header == {"marketplaces": {marketplace: {}}}:
                start = index
                break
        if start is None:
            raise core.RefreshError("codex_config_unsupported", "A marketplace needs its own TOML table before its release ref can be changed.")
        end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
        found = next((i for i in range(start + 1, end) if re.match(r'\s*(?:ref|"ref"|\x27ref\x27)\s*=', lines[i])), None)
        value = f"ref = {json.dumps(tag)}\n"
        if found is None:
            if not lines[start].endswith("\n"):
                lines[start] += "\n"
            lines.insert(start + 1, value)
        else:
            lines[found] = value
    result = "".join(lines)
    if tomllib.loads(result) != wanted:
        raise core.RefreshError("codex_config_unsupported", "Changing the release refs would alter other Codex settings.")
    return result


def prepare_marketplaces(ids: list[str], context: dict, advance: bool = True) -> None:
    path, original, config = read_config()
    pins, errors, refs = {}, {}, {}
    before = {}
    for plugin_id in ids:
        root = cached_root(plugin_id)
        if root:
            folder = Path(root)
            before[plugin_id] = {"root": root, "version": folder.name, "hooks": hooks_digest("codex", folder),
                                 "bundle": bundle_digest(folder)}
            if plugin_id == core.PLUGIN_ID:
                before[plugin_id]["digest"] = core.SESSION_CONTEXT.instructions_digest(folder)
    for name in dict.fromkeys(plugin.partition("@")[2] for plugin in ids):
        entry = config.get("marketplaces", {}).get(name, {})
        if entry.get("source_type") != "git":
            continue
        source = entry.get("source")
        try:
            if not isinstance(source, str) or not source:
                raise core.RefreshError("codex_marketplace_invalid", "The Git marketplace has no source.")
            tags = remote_tags(source)
            if not tags:
                raise core.RefreshError(UNTAGGED, "No release tag is advertised; the ref is unchanged. Any Codex start can still install untagged commits until the marketplace has a tag or its ref is set.")
            tag = max(tags, key=lambda item: tuple(map(int, TAG.fullmatch(item).groups()))) if advance else entry.get("ref")
            if tag not in tags:
                raise core.RefreshError("codex_marketplace_unpinned", "The marketplace is not pinned to an advertised release; its ref stays unchanged while installation is deferred.")
            pins[name] = {"source": source, "ref": tag, "revision": tags[tag]}
            if entry.get("ref") != tag:
                refs[name] = tag
        except core.RefreshError as error:
            errors[name] = error
    if refs:
        revised = replace_refs(original, refs)
        with core.exclusive("codex-marketplace-config", wait_seconds=5):
            if path.read_text(encoding="utf-8") != original:
                raise core.RefreshError("codex_config_changed", "Codex configuration changed while release tags were checked; no ref was written.")
            descriptor, temporary = tempfile.mkstemp(prefix=".release-", dir=path.parent)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    stream.write(revised)
                os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
    context.update(release_pins=pins, release_errors=errors, codex_before=before)


def install_time(root: Path) -> float | None:
    try:
        return (root / INSTALL_MARKER).stat().st_mtime
    except OSError:
        return None


def cached_root(plugin_id: str) -> str | None:
    plugin, _, marketplace = plugin_id.partition("@")
    parent = codex_home() / "plugins" / "cache" / marketplace / plugin
    try:
        roots = [path for path in parent.iterdir() if path.is_dir() and (path / ".codex-plugin/plugin.json").is_file()]
    except OSError:
        return None
    return str(roots[0]) if len(roots) == 1 else None


def verify_files(root: Path, plugin: str, pin: dict) -> None:
    try:
        marker = json.loads((root / INSTALL_MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise core.CODEX_HOOK_TRUST.TrustError("the marketplace install revision is unavailable") from error
    if any(marker.get(key) != pin[value] for key, value in (("source", "source"), ("ref_name", "ref"), ("revision", "revision"))):
        raise core.CODEX_HOOK_TRUST.TrustError("the installed revision does not match the pinned remote release")
    if remote_tags(pin["source"]).get(pin["ref"]) != pin["revision"]:
        raise core.CODEX_HOOK_TRUST.TrustError("the remote release changed during refresh")
    with tempfile.TemporaryDirectory(prefix="refresh-release-") as temporary:
        repo = Path(temporary)
        git = core.executable("git")
        core.run([git, "init", "--bare", "-q", str(repo)])
        core.run([git, "-C", str(repo), "fetch", "--depth=1", "--no-tags", "--", pin["source"], f'refs/tags/{pin["ref"]}'], timeout=120)
        actual = core.run([git, "-C", str(repo), "rev-parse", "FETCH_HEAD^{commit}"]).stdout.strip()
        if actual != pin["revision"]:
            raise core.CODEX_HOOK_TRUST.TrustError("the fetched release does not match the advertised revision")
        catalog = json.loads(core.run([git, "-C", str(repo), "show", f"{actual}:.agents/plugins/marketplace.json"]).stdout)
        sources = [item.get("source") for item in catalog.get("plugins", []) if item.get("name") == plugin]
        source = sources[0] if len(sources) == 1 else None
        relative = source.get("path") if isinstance(source, dict) and source.get("source") == "local" else None
        if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise core.CODEX_HOOK_TRUST.TrustError("the release has no supported local plugin source")
        tree = actual if relative in (".", "./", "") else f"{actual}:{relative.removeprefix('./').rstrip('/')}"
        try:
            archive = subprocess.run([git, "-C", str(repo), "archive", tree], stdin=subprocess.DEVNULL,
                                     capture_output=True, timeout=120, check=True).stdout
        except (OSError, subprocess.SubprocessError) as error:
            raise core.CODEX_HOOK_TRUST.TrustError("the release files could not be read") from error
        expected = set()
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            for member in bundle:
                if member.isdir():
                    continue
                target = root / member.name
                if not member.isfile() or target.is_symlink() or not target.is_file() or not target.resolve().is_relative_to(root.resolve()):
                    raise core.CODEX_HOOK_TRUST.TrustError("the installed release contains an unsupported or missing file")
                if target.read_bytes() != bundle.extractfile(member).read():
                    raise core.CODEX_HOOK_TRUST.TrustError("the installed files differ from the release")
                if bool(target.stat().st_mode & 0o111) != bool(member.mode & 0o111):
                    raise core.CODEX_HOOK_TRUST.TrustError("an installed file has different executable permissions")
                expected.add(member.name)
        actual_files = {item.relative_to(root).as_posix() for item in root.rglob("*")
                        if ".git" not in item.relative_to(root).parts and (item.is_file() or item.is_symlink())}
        if actual_files - {INSTALL_MARKER} != expected:
            raise core.CODEX_HOOK_TRUST.TrustError("the installed release has extra or missing files")


def verify_hook(hook: dict, plugin_id: str, root: Path) -> None:
    key, source, command = hook.get("key"), hook.get("sourcePath"), hook.get("command")
    if (hook.get("pluginId") != plugin_id or not isinstance(key, str) or not key.startswith(f"{plugin_id}:")
            or any(char in key for char in '\"\\\n') or not isinstance(hook.get("currentHash"), str) or not hook["currentHash"]
            or not isinstance(source, str) or not Path(source).is_file()
            or not Path(source).resolve().is_relative_to(root.resolve()) or not isinstance(command, str)):
        raise core.CODEX_HOOK_TRUST.TrustError("the hook identity or source is outside the installed plugin")
    try:
        argv = shlex.split(command)
    except ValueError as error:
        raise core.CODEX_HOOK_TRUST.TrustError("the hook command is unsupported") from error
    if not argv or any(char in command for char in ";&|><\n\r$`"):
        raise core.CODEX_HOOK_TRUST.TrustError("the hook command is unsupported")
    executable = (argv[1] if len(argv) > 1 and Path(argv[0]).name in {"sh", "bash", "python", "python3", "node"}
                  else argv[0] if Path(argv[0]).is_absolute() else "")
    if not executable or not Path(executable).is_file() or not Path(executable).resolve().is_relative_to(root.resolve()):
        raise core.CODEX_HOOK_TRUST.TrustError("the hook command points outside the installed plugin")
    for path in (Path(source), Path(executable)):
        relative = path.resolve().relative_to(root.resolve())
        if ".git" in relative.parts or relative.as_posix() == INSTALL_MARKER:
            raise core.CODEX_HOOK_TRUST.TrustError("the hook uses mutable install metadata")
