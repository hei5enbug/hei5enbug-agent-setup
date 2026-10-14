from __future__ import annotations

import argparse
import base64
import contextlib
import datetime as dt
import email.utils
import fcntl
import getpass
import hashlib
import http.server
import importlib
import json
import math
import os
import re
import secrets
import stat
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import warnings
import webbrowser
from dataclasses import dataclass
from http.client import IncompleteRead
from pathlib import Path
from typing import Any, BinaryIO, Callable, Iterator, Mapping


PROTOCOL_VERSION = 1
PINNED_MODELS = frozenset({"gpt-6.1-sol", "gpt-5.6-luna"})
SUPPORTED_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})
REQUIRED_SUBSCRIPTION_SCOPE = "chatgpt.tokens.use.direct"
OAUTH_ISSUER = "https://auth.openai.com"
DISCOVERY_URL = f"{OAUTH_ISSUER}/.well-known/openid-configuration"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
OPENAI_RESOURCE = "https://api.openai.com/v1"
OAUTH_DYNAMIC_CLIENT = "dynamic_agent_client"
OAUTH_AGENT_NAME = "Hei5enbug Agent Setup"
OAUTH_SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
MAX_REQUEST_BYTES = 16 * 1024 * 1024
MAX_PROTOCOL_LINE = 1024 * 1024
MAX_STATE_BYTES = 2 * 1024 * 1024
PROFILE_ID_RE = re.compile(r"^p_[0-9a-f]{32}$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")
SAFE_REQUEST_ID_RE = re.compile(
    r"^(?:req_[A-Za-z0-9-]{1,120}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$",
    re.IGNORECASE,
)
FUNCTION_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SAFE_CODE_RE = re.compile(r"^[a-z0-9_-]{1,80}$")
SAFE_PROVIDER_ERROR_CODES = frozenset({
    "authentication_error", "context_length_exceeded", "insufficient_quota", "invalid_api_key",
    "invalid_request_error", "model_not_found", "permission_denied", "rate_limit_exceeded",
    "server_error", "unsupported_parameter", "subscription_sharing_user_not_eligible",
    "subscription_sharing_usage_limit_exceeded", "subscription_sharing_usage_unavailable",
    "subscription_sharing_unsupported_capability", "subscription_sharing_route_not_supported",
    "subscription_sharing_invalid_user", "subscription_sharing_user_unavailable",
    "chatpass_v2_scope_not_authorized", "chatpass_v2_invalid_authorization_context",
})
JSON_SCHEMA_TYPES = frozenset({"object", "string", "number", "integer", "boolean", "array", "null"})
IMAGE_MEDIA_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})
DOCUMENT_MEDIA_TYPES = frozenset({"application/pdf"})
MAX_DIAGNOSTIC_PARTS = 64
MAX_DIAGNOSTIC_INTEGER = MAX_REQUEST_BYTES * 4
DIAGNOSTIC_EVENT_TYPES = (
    "response.created", "response.queued", "response.in_progress", "response.completed",
    "response.failed", "response.incomplete", "response.output_item.added", "response.output_item.done",
    "response.content_part.added", "response.content_part.done", "response.output_text.delta",
    "response.output_text.done", "response.refusal.delta", "response.refusal.done",
    "response.reasoning_text.delta", "response.reasoning_text.done",
    "response.function_call_arguments.delta", "response.function_call_arguments.done",
    "response.reasoning_summary_part.added", "response.reasoning_summary_part.done",
    "response.reasoning_summary_text.delta", "response.reasoning_summary_text.done",
    "response.file_search_call.in_progress", "response.file_search_call.searching",
    "response.file_search_call.completed", "response.web_search_call.in_progress",
    "response.web_search_call.searching", "response.web_search_call.completed",
    "response.code_interpreter_call.in_progress", "response.code_interpreter_call.interpreting",
    "response.code_interpreter_call.completed", "response.image_generation_call.completed",
    "response.mcp_call_arguments.delta", "response.mcp_call_arguments.done",
    "response.mcp_list_tools.in_progress", "response.mcp_list_tools.completed",
    "response.mcp_list_tools.failed", "response.custom_tool_call_input.delta",
    "response.custom_tool_call_input.done", "error",
)
DIAGNOSTIC_PART_COUNTERS = (
    "delta_events", "delta_characters", "added_events", "added_characters",
    "text_done_events", "text_done_characters", "part_done_events", "part_done_characters",
)
DIAGNOSTIC_OUTPUT_ITEM_TYPES = (
    "message", "function_call", "reasoning", "web_search_call", "file_search_call",
    "computer_call", "code_interpreter_call", "image_generation_call", "mcp_call",
    "mcp_list_tools", "local_shell_call", "shell_call", "custom_tool_call",
)


def _diagnostic_integer(value: Any) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return None
    return min(value, MAX_DIAGNOSTIC_INTEGER)


def _diagnostic_index(value: Any) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > MAX_DIAGNOSTIC_INTEGER:
        return None
    return value


def _sanitize_provider_usage(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    model = value.get("model")
    raw_usage = value.get("usage")
    if not isinstance(model, str) or model not in PINNED_MODELS or not isinstance(raw_usage, Mapping):
        return None
    if "model" in raw_usage and raw_usage.get("model") != model:
        return None
    fields = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens")
    usage: dict[str, int] = {}
    for field in fields:
        number = raw_usage.get(field)
        if not isinstance(number, int) or isinstance(number, bool) or number < 0:
            return None
        usage[field] = number
    if usage["cached_input_tokens"] > usage["input_tokens"]:
        return None
    effort = value.get("provider_reported_effort")
    if effort is not None and (not isinstance(effort, str) or effort not in SUPPORTED_EFFORTS):
        effort = None
    return {"model": model, "usage": usage, "provider_reported_effort": effort}


def _sanitize_stream_diagnostics(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    raw_events = value.get("event_counts")
    raw_items = value.get("output_item_counts")
    events = {
        kind: _diagnostic_integer(raw_events.get(kind)) or 0
        for kind in DIAGNOSTIC_EVENT_TYPES
    } if isinstance(raw_events, Mapping) else {kind: 0 for kind in DIAGNOSTIC_EVENT_TYPES}
    events["unknown_events"] = (
        _diagnostic_integer(raw_events.get("unknown_events")) or 0
        if isinstance(raw_events, Mapping) else 0
    )
    items = {
        kind: _diagnostic_integer(raw_items.get(kind)) or 0
        for kind in DIAGNOSTIC_OUTPUT_ITEM_TYPES
    } if isinstance(raw_items, Mapping) else {kind: 0 for kind in DIAGNOSTIC_OUTPUT_ITEM_TYPES}
    items["unknown"] = (
        _diagnostic_integer(raw_items.get("unknown")) or 0
        if isinstance(raw_items, Mapping) else 0
    )

    raw_parts = value.get("part_summaries")
    parts: list[dict[str, int | None]] = []
    part_positions: dict[tuple[int | None, int | None], int] = {}
    overflow = _diagnostic_integer(value.get("part_summaries_overflow")) or 0
    if isinstance(raw_parts, list):
        for raw_part in raw_parts:
            if not isinstance(raw_part, Mapping):
                overflow = min(MAX_DIAGNOSTIC_INTEGER, overflow + 1)
                continue
            output_index = _diagnostic_index(raw_part.get("output_index"))
            content_index = _diagnostic_index(raw_part.get("content_index"))
            counters = {
                field: _diagnostic_integer(raw_part.get(field)) or 0
                for field in DIAGNOSTIC_PART_COUNTERS
            }
            if not any(counters[field] for field in DIAGNOSTIC_PART_COUNTERS if field.endswith("_events")):
                overflow = min(MAX_DIAGNOSTIC_INTEGER, overflow + 1)
                continue
            key = (output_index, content_index)
            if key in part_positions:
                part = parts[part_positions[key]]
                for field in DIAGNOSTIC_PART_COUNTERS:
                    part[field] = min(MAX_DIAGNOSTIC_INTEGER, int(part[field]) + counters[field])
            elif len(parts) < MAX_DIAGNOSTIC_PARTS:
                part_positions[key] = len(parts)
                parts.append({"output_index": output_index, "content_index": content_index, **counters})
            else:
                overflow = min(MAX_DIAGNOSTIC_INTEGER, overflow + 1)

    result: dict[str, Any] = {
        "event_counts": events,
        "streamed_characters": _diagnostic_integer(value.get("streamed_characters")) or 0,
        "output_item_counts": items,
        "part_summaries": parts,
        "part_summaries_overflow": overflow,
    }
    for field in ("completed_visible_characters", "first_mismatch_offset"):
        number = _diagnostic_integer(value.get(field))
        if number is not None:
            result[field] = number
    reconstructed = _diagnostic_integer(value.get("reconstructed_output_items"))
    if reconstructed is not None:
        result["reconstructed_output_items"] = reconstructed
    return result


class ClaudeGptError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int | None = None,
                 provider_code: str | None = None, request_id: str | None = None,
                 retry_after: float | None = None, terminal_after_completion: bool = False,
                 provider_usage: Any = None, stream_diagnostics: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.provider_code = (provider_code if isinstance(provider_code, str) and
                              provider_code in SAFE_PROVIDER_ERROR_CODES else None)
        self.request_id = request_id if isinstance(request_id, str) and SAFE_REQUEST_ID_RE.fullmatch(request_id) else None
        try:
            delay = float(retry_after) if isinstance(retry_after, (int, float)) and not isinstance(retry_after, bool) else None
        except (OverflowError, ValueError):
            delay = None
        self.retry_after = delay if delay is not None and math.isfinite(delay) and delay >= 0 else None
        self.terminal_after_completion = terminal_after_completion
        self.provider_usage = _sanitize_provider_usage(provider_usage)
        self.stream_diagnostics = _sanitize_stream_diagnostics(stream_diagnostics)


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes
    stream: BinaryIO | None = None


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HttpClient:
    def __init__(self, opener: Any | None = None, timeout: float = 30.0):
        self.opener = opener or urllib.request.build_opener(NoRedirectHandler())
        self.timeout = timeout

    def open(self, request: urllib.request.Request) -> HttpResponse:
        try:
            response = self.opener.open(request, timeout=self.timeout)
        except urllib.error.HTTPError as error:
            body = error.read(MAX_REQUEST_BYTES + 1)
            return HttpResponse(error.code, dict(error.headers.items()), body)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise ClaudeGptError("network_error", "OpenAI 서비스에 연결하지 못했습니다.") from error
        return HttpResponse(response.status, dict(response.headers.items()), b"", response)

    def json(self, url: str, *, method: str = "GET", data: bytes | None = None,
             headers: Mapping[str, str] | None = None) -> dict[str, Any]:
        request = urllib.request.Request(url, data=data, headers=dict(headers or {}), method=method)
        response = self.open(request)
        if response.stream is not None:
            with response.stream as stream:
                body = stream.read(MAX_REQUEST_BYTES + 1)
        else:
            body = response.body
        if len(body) > MAX_REQUEST_BYTES:
            raise ClaudeGptError("response_too_large", "OpenAI 서비스 응답이 너무 큽니다.")
        if response.status < 200 or response.status >= 300:
            raise _http_error(response.status, body, response.headers)
        try:
            value = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ClaudeGptError("invalid_json", "OpenAI 서비스가 올바른 JSON을 반환하지 않았습니다.") from error
        if not isinstance(value, dict):
            raise ClaudeGptError("invalid_json", "OpenAI 서비스 응답 형식이 잘못되었습니다.")
        return value


def _error_code_from_body(body: bytes) -> str | None:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    error = value.get("error") if isinstance(value, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    if code is None:
        return None
    return code if isinstance(code, str) and code in SAFE_PROVIDER_ERROR_CODES else "unknown_provider_error"


def _header_value(headers: Mapping[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == name.lower() and isinstance(value, str):
            return value
    return None


def _response_request_id(headers: Mapping[str, str]) -> str | None:
    value = _header_value(headers, "x-request-id")
    return value if isinstance(value, str) and SAFE_REQUEST_ID_RE.fullmatch(value) else None


def _retry_after(headers: Mapping[str, str], *, now: dt.datetime | None = None) -> float | None:
    value = _header_value(headers, "retry-after")
    if value is None:
        return None
    value = value.strip()
    if re.fullmatch(r"[0-9]+", value):
        if len(value) > 20:
            return None
        return float(int(value))
    try:
        retry_at = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if retry_at is None:
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=dt.timezone.utc)
    current = now or dt.datetime.now(dt.timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=dt.timezone.utc)
    return max(0.0, (retry_at - current).total_seconds())


def _http_error(status: int, body: bytes, headers: Mapping[str, str] | None = None) -> ClaudeGptError:
    code = _error_code_from_body(body)
    suffix = f" ({code})" if code else ""
    headers = headers or {}
    return ClaudeGptError(
        "unknown_provider_error" if code == "unknown_provider_error" else "http_error",
        f"OpenAI 서비스 요청이 HTTP {status}로 실패했습니다{suffix}.",
        http_status=status, provider_code=code, request_id=_response_request_id(headers),
        retry_after=_retry_after(headers),
    )


def _json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ClaudeGptError("invalid_json", "요청에 JSON으로 전달할 수 없는 값이 있습니다.") from error


def emit_record(value: Mapping[str, Any], stream: Any = None) -> None:
    target = stream or sys.stdout
    target.write(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")
    target.flush()


def protocol_error(error: ClaudeGptError | str) -> dict[str, Any]:
    code = error.code if isinstance(error, ClaudeGptError) else error
    safe = code if SAFE_CODE_RE.fullmatch(code) else "request_failed"
    record: dict[str, Any] = {"protocol_version": PROTOCOL_VERSION, "type": "error", "code": safe}
    if isinstance(error, ClaudeGptError):
        for key in ("http_status", "provider_code", "request_id", "retry_after"):
            value = getattr(error, key)
            if value is not None:
                record[key] = value
        provider_usage = _sanitize_provider_usage(error.provider_usage)
        stream_diagnostics = _sanitize_stream_diagnostics(error.stream_diagnostics)
        if provider_usage is not None:
            record["provider_usage"] = provider_usage
        if stream_diagnostics is not None:
            record["stream_diagnostics"] = stream_diagnostics
        if error.terminal_after_completion:
            record["terminal_after_completion"] = True
    return record


def _current_uid() -> int:
    if not hasattr(os, "getuid"):
        raise ClaudeGptError("unsupported_platform", "이 운영체제의 소유자 검증을 지원하지 않습니다.")
    return os.getuid()


def _check_owned_directory(path: Path, *, private: bool) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        raise ClaudeGptError("unsafe_path", f"보호 경로가 없습니다: {path.name}")
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or info.st_uid != _current_uid():
        raise ClaudeGptError("unsafe_path", f"안전하지 않은 설정 경로입니다: {path.name}")
    if private and info.st_mode & 0o077:
        raise ClaudeGptError("unsafe_permissions", f"설정 디렉터리 권한이 너무 넓습니다: {path.name}")
    if not private and info.st_mode & 0o022:
        raise ClaudeGptError("unsafe_permissions", f"설정 경로를 다른 사용자가 수정할 수 있습니다: {path.name}")


def _ensure_directory(path: Path, *, private: bool) -> None:
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    except OSError as error:
        raise ClaudeGptError("storage_error", "보호된 설정 디렉터리를 만들 수 없습니다.") from error
    _check_owned_directory(path, private=private)


def _read_private_json(path: Path, *, limit: int = MAX_STATE_BYTES) -> Any:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as error:
        raise ClaudeGptError("unsafe_path", f"보호된 파일을 열 수 없습니다: {path.name}") from error
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != _current_uid() or info.st_mode & 0o077:
            raise ClaudeGptError("unsafe_permissions", f"보호된 파일 권한이 안전하지 않습니다: {path.name}")
        if info.st_size > limit:
            raise ClaudeGptError("file_too_large", f"보호된 파일이 허용 크기를 넘었습니다: {path.name}")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            data = handle.read(limit + 1)
        if len(data) > limit:
            raise ClaudeGptError("file_too_large", f"보호된 파일이 허용 크기를 넘었습니다: {path.name}")
        try:
            return json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ClaudeGptError("invalid_profile", f"보호된 파일 형식이 잘못되었습니다: {path.name}") from error
    finally:
        os.close(fd)


def _atomic_private_json(path: Path, value: Any) -> None:
    parent = path.parent
    _check_owned_directory(parent, private=True)
    if path.exists() or path.is_symlink():
        try:
            existing = path.lstat()
        except OSError as error:
            raise ClaudeGptError("unsafe_path", f"보호된 파일을 확인할 수 없습니다: {path.name}") from error
        if (stat.S_ISLNK(existing.st_mode) or not stat.S_ISREG(existing.st_mode) or
                existing.st_uid != _current_uid() or existing.st_mode & 0o077):
            raise ClaudeGptError("unsafe_permissions", f"기존 보호 파일이 안전하지 않습니다: {path.name}")
    data = _json_bytes(value)
    fd, temp_name = tempfile.mkstemp(prefix=".write-", dir=parent)
    temp_path = Path(temp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        dir_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            temp_path.unlink()
        raise


class ProfileStore:
    def __init__(self, root: Path):
        self.root = root

    @classmethod
    def default(cls) -> ProfileStore:
        home = Path.home()
        if home.is_symlink() or not home.is_dir() or home.stat().st_uid != _current_uid():
            raise ClaudeGptError("unsafe_path", "사용자 홈 디렉터리 소유자를 확인할 수 없습니다.")
        config = home / ".config"
        vendor = config / "hei5enbug-agent-setup"
        root = vendor / "claude-gpt"
        _ensure_directory(config, private=False)
        _ensure_directory(vendor, private=True)
        _ensure_directory(root, private=True)
        return cls(root)

    def ensure(self) -> None:
        if not self.root.parent.exists():
            raise ClaudeGptError("unsafe_path", "보호된 설정 경로의 상위 디렉터리가 없습니다.")
        _check_owned_directory(self.root.parent, private=True)
        _ensure_directory(self.root, private=True)
        profiles = self.root / "profiles"
        _ensure_directory(profiles, private=True)

    @contextlib.contextmanager
    def locked(self) -> Iterator[None]:
        self.ensure()
        lock_path = self.root / ".lock"
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(lock_path, flags, 0o600)
        except OSError as error:
            raise ClaudeGptError("unsafe_path", "보호된 설정 잠금을 열 수 없습니다.") from error
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != _current_uid() or info.st_mode & 0o077:
                raise ClaudeGptError("unsafe_permissions", "보호된 설정 잠금 권한이 안전하지 않습니다.")
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def profile_dir(self, profile_id: str) -> Path:
        if not isinstance(profile_id, str) or not PROFILE_ID_RE.fullmatch(profile_id):
            raise ClaudeGptError("invalid_profile", "프로필 참조가 잘못되었습니다.")
        return self.root / "profiles" / profile_id

    def read_profile(self, profile_id: str) -> dict[str, Any]:
        directory = self.profile_dir(profile_id)
        _check_owned_directory(directory, private=True)
        value = _read_private_json(directory / "profile.json")
        if not isinstance(value, dict) or value.get("profile_id") != profile_id:
            raise ClaudeGptError("invalid_profile", "프로필 형식이 잘못되었습니다.")
        return value

    def read_credentials(self, profile_id: str) -> dict[str, Any]:
        value = _read_private_json(self.profile_dir(profile_id) / "credentials.json")
        if not isinstance(value, dict):
            raise ClaudeGptError("invalid_profile", "인증 정보 형식이 잘못되었습니다.")
        return value

    def write_profile(self, profile: dict[str, Any]) -> None:
        directory = self.profile_dir(profile["profile_id"])
        _ensure_directory(directory, private=True)
        _atomic_private_json(directory / "profile.json", profile)

    def write_credentials(self, profile_id: str, credentials: dict[str, Any]) -> None:
        directory = self.profile_dir(profile_id)
        _check_owned_directory(directory, private=True)
        _atomic_private_json(directory / "credentials.json", credentials)

    def set_active(self, profile_id: str) -> None:
        self.read_profile(profile_id)
        _atomic_private_json(self.root / "active.json", {"profile_id": profile_id})

    def active_profile_id(self) -> str | None:
        path = self.root / "active.json"
        if not path.exists() and not path.is_symlink():
            return None
        value = _read_private_json(path)
        profile_id = value.get("profile_id") if isinstance(value, dict) else None
        if not isinstance(profile_id, str) or not PROFILE_ID_RE.fullmatch(profile_id):
            raise ClaudeGptError("invalid_profile", "선택된 프로필 참조가 잘못되었습니다.")
        return profile_id

    def host_id(self, *, create: bool) -> str:
        path = self.root / "host.json"
        if path.exists() or path.is_symlink():
            value = _read_private_json(path)
            host_id = value.get("ext_agent_host_id") if isinstance(value, dict) else None
            if not isinstance(host_id, str) or not host_id.startswith("urn:uuid:"):
                raise ClaudeGptError("invalid_profile", "저장된 호스트 식별자가 잘못되었습니다.")
            return host_id
        if not create:
            raise ClaudeGptError("missing_host_id", "구독 로그인을 시작하기 전에 호스트 식별자를 만들 수 없습니다.")
        host_id = f"urn:uuid:{uuid.uuid4()}"
        _atomic_private_json(path, {"ext_agent_host_id": host_id})
        return host_id

    def state_path(self, profile_id: str, session_id: str) -> Path:
        directory = self.profile_dir(profile_id) / "state"
        if not directory.exists() and not directory.is_symlink():
            _ensure_directory(directory, private=True)
        else:
            _check_owned_directory(directory, private=True)
        digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
        return directory / f"{digest}.json"

    def read_session_state(self, profile_id: str, session_id: str) -> dict[str, Any]:
        path = self.state_path(profile_id, session_id)
        if not path.exists() and not path.is_symlink():
            return {"version": 1, "profile_id": profile_id, "groups": []}
        value = _read_private_json(path)
        if (not isinstance(value, dict) or value.get("version") != 1 or
                value.get("profile_id") != profile_id or not isinstance(value.get("groups"), list)):
            raise ClaudeGptError("invalid_state", "보호된 대화 상태가 잘못되었습니다.")
        return value

    def write_session_state(self, profile_id: str, session_id: str, groups: list[dict[str, Any]]) -> None:
        path = self.state_path(profile_id, session_id)
        if groups:
            _atomic_private_json(path, {"version": 1, "profile_id": profile_id, "groups": groups})
        else:
            if path.exists() or path.is_symlink():
                info = path.lstat()
                if (stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or
                        info.st_uid != _current_uid() or info.st_mode & 0o077):
                    raise ClaudeGptError("unsafe_permissions", "저장된 GPT 대화 상태 파일이 안전하지 않습니다.")
            with contextlib.suppress(FileNotFoundError):
                path.unlink()

    def provider_state_path(self, profile_id: str) -> Path:
        directory = self.profile_dir(profile_id) / "state"
        if not directory.exists() and not directory.is_symlink():
            _ensure_directory(directory, private=True)
        else:
            _check_owned_directory(directory, private=True)
        return directory / "provider.json"

    def read_provider_state(self, profile_id: str) -> list[dict[str, Any]]:
        path = self.provider_state_path(profile_id)
        if not path.exists() and not path.is_symlink():
            return []
        value = _read_private_json(path)
        if (not isinstance(value, dict) or value.get("version") != 1 or
                value.get("profile_id") != profile_id or not isinstance(value.get("groups"), list)):
            raise ClaudeGptError("invalid_state", "보호된 GPT 공급자 상태가 잘못되었습니다.")
        return value["groups"]

    def merge_provider_state(self, profile_id: str, groups: list[dict[str, Any]]) -> None:
        path = self.provider_state_path(profile_id)
        existing = self.read_provider_state(profile_id)
        merged = [
            group for group in existing
            if isinstance(group, dict) and isinstance(group.get("ids"), list) and
            group["ids"] and all(isinstance(call_id, str) for call_id in group["ids"])
        ]
        added: list[dict[str, Any]] = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("ids"), list):
                raise ClaudeGptError("invalid_state", "저장할 GPT 공급자 상태가 잘못되었습니다.")
            ids = group["ids"]
            if any(not isinstance(call_id, str) for call_id in ids) or not ids:
                raise ClaudeGptError("invalid_state", "저장할 GPT 도구 ID가 잘못되었습니다.")
            encoded = _json_bytes(group)
            matching = next((item for item in merged if _json_bytes(item) == encoded), None)
            if matching is not None:
                continue
            merged = [item for item in merged if not set(ids).intersection(item.get("ids", []))]
            merged.append(group)
            added.append(group)
        if not added:
            return

        def encoded_state(items: list[dict[str, Any]]) -> bytes:
            return _json_bytes({"version": 1, "profile_id": profile_id, "groups": items})

        if len(encoded_state(added)) > MAX_STATE_BYTES:
            return
        while len(encoded_state(merged)) > MAX_STATE_BYTES and merged:
            merged.pop(0)
        if len(encoded_state(merged)) <= MAX_STATE_BYTES:
            _atomic_private_json(path, {"version": 1, "profile_id": profile_id, "groups": merged})

    def remove_credentials(self, profile_id: str) -> None:
        path = self.profile_dir(profile_id) / "credentials.json"
        if path.exists() or path.is_symlink():
            info = path.lstat()
            if (stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or
                    info.st_uid != _current_uid() or info.st_mode & 0o077):
                raise ClaudeGptError("unsafe_permissions", "기존 인증 정보 파일이 안전하지 않습니다.")
        with contextlib.suppress(FileNotFoundError):
            path.unlink()


def _validate_json_schema(schema: Any, path: str = "input_schema", depth: int = 0) -> None:
    if depth > 128:
        raise ClaudeGptError("unsupported_schema", f"도구 입력 스키마가 너무 깊습니다: {path}")
    if isinstance(schema, bool):
        return
    if not isinstance(schema, dict):
        raise ClaudeGptError("unsupported_schema", f"도구 입력 스키마 형식이 잘못되었습니다: {path}")
    if "type" in schema:
        schema_type = schema["type"]
        types = [schema_type] if isinstance(schema_type, str) else schema_type
        if (not isinstance(types, list) or not types or
                any(not isinstance(item, str) or item not in JSON_SCHEMA_TYPES for item in types) or
                len(types) != len(set(types))):
            raise ClaudeGptError("unsupported_schema", f"도구 입력 스키마 형식이 잘못되었습니다: {path}")
    if "properties" in schema:
        properties = schema["properties"]
        if not isinstance(properties, dict) or not all(isinstance(key, str) for key in properties):
            raise ClaudeGptError("unsupported_schema", f"도구 입력 스키마 형식이 잘못되었습니다: {path}")
        for name, child in properties.items():
            _validate_json_schema(child, f"{path}.{name}", depth + 1)
    if "required" in schema:
        required = schema["required"]
        if (not isinstance(required, list) or any(not isinstance(item, str) for item in required) or
                len(required) != len(set(required))):
            raise ClaudeGptError("unsupported_schema", f"도구 입력 스키마 형식이 잘못되었습니다: {path}")
    if "items" in schema:
        _validate_json_schema(schema["items"], f"{path}[]", depth + 1)
    if "additionalProperties" in schema:
        _validate_json_schema(schema["additionalProperties"], f"{path}.*", depth + 1)
    if "enum" in schema:
        values = schema["enum"]
        if not isinstance(values, list) or not values or len(_json_bytes(values)) > 65536:
            raise ClaudeGptError("unsupported_schema", f"도구 입력 스키마 형식이 잘못되었습니다: {path}")


def _json_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left is right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isfinite(left) and math.isfinite(right) and left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_json_equal(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_json_equal(a, b) for a, b in zip(left, right))
    return type(left) is type(right) and left == right


def _schema_type_matches(value: Any, kind: str) -> bool:
    if kind == "object":
        return isinstance(value, dict)
    if kind == "array":
        return isinstance(value, list)
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return (isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and
                (isinstance(value, int) or value.is_integer()))
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    if kind == "boolean":
        return isinstance(value, bool)
    return kind == "null" and value is None


def _validate_schema_value(value: Any, schema: Any, path: str) -> None:
    if schema is False:
        raise ClaudeGptError("invalid_tool_call", f"도구 입력이 제공된 스키마와 일치하지 않습니다: {path}")
    if schema is True:
        return
    if "type" in schema:
        schema_type = schema["type"]
        types = [schema_type] if isinstance(schema_type, str) else schema_type
        if not any(_schema_type_matches(value, kind) for kind in types):
            raise ClaudeGptError("invalid_tool_call", f"도구 입력이 제공된 스키마와 일치하지 않습니다: {path}")
    if "enum" in schema and not any(_json_equal(value, allowed) for allowed in schema["enum"]):
        raise ClaudeGptError("invalid_tool_call", f"도구 입력이 제공된 스키마와 일치하지 않습니다: {path}")
    if isinstance(value, dict):
        required = set(schema.get("required", []))
        if not required.issubset(value):
            raise ClaudeGptError("invalid_tool_call", f"도구 입력이 제공된 스키마와 일치하지 않습니다: {path}")
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for name, child in value.items():
            if name in properties:
                _validate_schema_value(child, properties[name], f"{path}.{name}")
            elif additional is False:
                raise ClaudeGptError("invalid_tool_call", f"도구 입력이 제공된 스키마와 일치하지 않습니다: {path}.{name}")
            elif isinstance(additional, dict):
                _validate_schema_value(child, additional, f"{path}.{name}")
    if isinstance(value, list) and "items" in schema:
        for index, child in enumerate(value):
            _validate_schema_value(child, schema["items"], f"{path}[{index}]")


def validate_protocol_request(value: Any) -> dict[str, Any]:
    fields = {
        "protocol_version", "request_id", "session_id", "turn_id", "step_id", "model", "effort",
        "profile_id", "system", "developer", "history", "tools",
    }
    if not isinstance(value, dict) or not fields.issubset(value) or set(value) - fields - {"tool_choice"}:
        raise ClaudeGptError("invalid_request", "요청 버전 또는 필수 필드가 잘못되었습니다.")
    if value["protocol_version"] != PROTOCOL_VERSION:
        raise ClaudeGptError("unsupported_protocol", "지원하지 않는 요청 프로토콜 버전입니다.")
    for field in ("request_id", "session_id", "turn_id", "step_id"):
        if not isinstance(value[field], str) or not SAFE_ID_RE.fullmatch(value[field]):
            raise ClaudeGptError("invalid_request", f"요청 식별자가 잘못되었습니다: {field}")
    if not isinstance(value["model"], str) or value["model"] not in PINNED_MODELS:
        raise ClaudeGptError("unsupported_model", "지원하지 않는 GPT 모델 ID입니다.")
    effort = value["effort"]
    if effort is not None and (not isinstance(effort, str) or effort not in SUPPORTED_EFFORTS):
        raise ClaudeGptError("unsupported_effort", "선택한 GPT 모델이 지원하지 않는 추론 강도입니다.")
    if value["model"] == "gpt-5.6-luna" and effort != "xhigh":
        raise ClaudeGptError("unsupported_effort", "GPT Luna는 xhigh로만 실행할 수 있습니다.")
    if not isinstance(value["profile_id"], str) or not PROFILE_ID_RE.fullmatch(value["profile_id"]):
        raise ClaudeGptError("invalid_profile", "프로필 참조가 잘못되었습니다.")
    if not isinstance(value["system"], str) or len(value["system"]) > 2_000_000:
        raise ClaudeGptError("invalid_request", "시스템 내용이 없거나 허용 크기를 넘었습니다.")
    if not isinstance(value["developer"], list) or any(not isinstance(item, str) for item in value["developer"]):
        raise ClaudeGptError("invalid_request", "개발자 지시 내용 형식이 잘못되었습니다.")
    if not isinstance(value["history"], list) or not value["history"] or len(value["history"]) > 4096:
        raise ClaudeGptError("invalid_history", "대화 기록이 비어 있거나 허용 범위를 넘었습니다.")
    if not isinstance(value["tools"], list) or len(value["tools"]) > 1000:
        raise ClaudeGptError("invalid_tools", "도구 목록 형식이 잘못되었습니다.")
    names: set[str] = set()
    for tool in value["tools"]:
        if (not isinstance(tool, dict) or set(tool) != {"name", "description", "input_schema"} or
                not isinstance(tool["name"], str) or not FUNCTION_NAME_RE.fullmatch(tool["name"]) or
                tool["name"] in names or not isinstance(tool["description"], str) or
                len(tool["description"]) > 8192):
            raise ClaudeGptError("invalid_tools", "도구 설명 또는 이름이 잘못되었습니다.")
        names.add(tool["name"])
        _validate_json_schema(tool["input_schema"])
    if "tool_choice" in value:
        choice = value["tool_choice"]
        if isinstance(choice, str):
            if choice not in {"auto", "required", "none"} or (choice == "required" and not names):
                raise ClaudeGptError("invalid_tool_choice", "도구 선택 값이 잘못되었습니다.")
        elif (not isinstance(choice, dict) or set(choice) != {"type", "name"} or
              choice.get("type") != "function" or not isinstance(choice.get("name"), str) or
              choice["name"] not in names):
            raise ClaudeGptError("invalid_tool_choice", "도구 선택 값이 잘못되었습니다.")
    if len(_json_bytes(value)) > MAX_REQUEST_BYTES:
        raise ClaudeGptError("request_too_large", "GPT 요청이 허용 크기를 넘었습니다.")
    return value


def _input_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        result: list[str] = []
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "text" or not isinstance(item.get("text"), str):
                raise ClaudeGptError("unsupported_history", "텍스트가 아닌 도구 결과는 GPT 대화 기록으로 옮길 수 없습니다.")
            result.append(item["text"])
        return "".join(result)
    raise ClaudeGptError("unsupported_history", "지원하지 않는 도구 결과 형식입니다.")


def _media_input(block: Mapping[str, Any]) -> dict[str, Any]:
    kind = block.get("type")
    source = block.get("source")
    if (kind not in {"image", "document"} or not isinstance(source, dict) or
            source.get("type") != "base64" or not isinstance(source.get("media_type"), str) or
            not isinstance(source.get("data"), str)):
        raise ClaudeGptError("invalid_media", "대화의 첨부 데이터 형식이 잘못되었습니다.")
    media_type = source["media_type"]
    allowed = IMAGE_MEDIA_TYPES if kind == "image" else DOCUMENT_MEDIA_TYPES
    data = source["data"]
    if media_type not in allowed or not data or len(data) > MAX_REQUEST_BYTES:
        raise ClaudeGptError("invalid_media", "지원하지 않는 첨부 유형이거나 첨부 데이터가 너무 큽니다.")
    try:
        decoded = base64.b64decode(data, validate=True)
    except (ValueError, base64.binascii.Error) as error:
        raise ClaudeGptError("invalid_media", "대화의 첨부 데이터가 올바른 base64가 아닙니다.") from error
    if not decoded or len(decoded) > MAX_REQUEST_BYTES:
        raise ClaudeGptError("invalid_media", "대화의 첨부 데이터 크기가 허용 범위를 넘었습니다.")
    data_url = f"data:{media_type};base64,{data}"
    if kind == "image":
        return {"type": "input_image", "image_url": data_url}
    return {"type": "input_file", "filename": "attachment.pdf", "file_data": data_url}


def _history_parts(content: Any, *, allow_media: bool) -> tuple[list[str], list[dict[str, Any]]]:
    if isinstance(content, str):
        return [content], []
    if not isinstance(content, list):
        raise ClaudeGptError("unsupported_history", "지원하지 않는 대화 내용 형식입니다.")
    text: list[str] = []
    media: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            raise ClaudeGptError("unsupported_history", "대화 내용 블록 형식이 잘못되었습니다.")
        if item.get("type") == "text" and isinstance(item.get("text"), str):
            text.append(item["text"])
        elif allow_media and item.get("type") in {"image", "document"}:
            media.append(_media_input(item))
        else:
            raise ClaudeGptError("unsupported_history", "도구 결과에 지원하지 않는 내용이 있습니다.")
    return text, media


def _validate_tool_input(value: Any, schema: dict[str, Any], path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ClaudeGptError("invalid_tool_call", "도구 입력은 JSON 객체여야 합니다.")
    _json_bytes(value)
    _validate_schema_value(value, schema, path)
    return value


def _validated_provider_groups(groups: list[dict[str, Any]],
                               tool_schemas: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(groups, list):
        raise ClaudeGptError("invalid_state", "저장된 GPT 도구 상태가 잘못되었습니다.")
    validated: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for group in groups:
        if (not isinstance(group, dict) or set(group) != {"ids", "calls", "items"} or
                not isinstance(group["ids"], list) or not group["ids"] or
                not isinstance(group["calls"], dict) or not isinstance(group["items"], list)):
            raise ClaudeGptError("invalid_state", "저장된 GPT 도구 상태가 잘못되었습니다.")
        ids = group["ids"]
        if (any(not isinstance(call_id, str) or not SAFE_ID_RE.fullmatch(call_id) for call_id in ids) or
                len(ids) != len(set(ids)) or seen_ids.intersection(ids) or set(group["calls"]) != set(ids)):
            raise ClaudeGptError("invalid_state", "저장된 GPT 도구 ID가 잘못되었습니다.")
        seen_ids.update(ids)
        calls: dict[str, dict[str, Any]] = {}
        for call_id in ids:
            call = group["calls"][call_id]
            if not isinstance(call, dict) or set(call) != {"name", "arguments"}:
                raise ClaudeGptError("invalid_state", "저장된 GPT 도구 호출이 잘못되었습니다.")
            name = call["name"]
            if not isinstance(name, str) or name not in tool_schemas:
                raise ClaudeGptError("invalid_state", "저장된 GPT 도구가 현재 요청에 없습니다.")
            arguments = _validate_tool_input(call["arguments"], tool_schemas[name], f"state.{name}")
            calls[call_id] = {"name": name, "arguments": arguments}

        item_calls: dict[str, dict[str, Any]] = {}
        for item in group["items"]:
            if not isinstance(item, dict):
                raise ClaudeGptError("invalid_state", "저장된 GPT 공급자 상태가 잘못되었습니다.")
            kind = item.get("type")
            if kind == "reasoning":
                if not isinstance(item.get("id"), str) or not item["id"]:
                    raise ClaudeGptError("invalid_state", "저장된 GPT 추론 상태가 잘못되었습니다.")
                _json_bytes(item)
                continue
            if (kind != "function_call" or set(item) != {"type", "call_id", "namespace", "name", "arguments"} or
                    item.get("namespace") != "claude" or not isinstance(item.get("call_id"), str) or
                    item["call_id"] not in calls or item["call_id"] in item_calls or
                    not isinstance(item.get("name"), str) or not isinstance(item.get("arguments"), str)):
                raise ClaudeGptError("invalid_state", "저장된 GPT 도구 상태 항목이 잘못되었습니다.")
            try:
                arguments = json.loads(item["arguments"])
            except json.JSONDecodeError as error:
                raise ClaudeGptError("invalid_state", "저장된 GPT 도구 입력이 잘못되었습니다.") from error
            call_id = item["call_id"]
            expected = calls[call_id]
            if item["name"] != expected["name"] or not _json_equal(arguments, expected["arguments"]):
                raise ClaudeGptError("invalid_state", "저장된 GPT 도구 입력이 대화 기록과 다릅니다.")
            item_calls[call_id] = expected
        if list(item_calls) != ids:
            raise ClaudeGptError("invalid_state", "저장된 GPT 도구 항목 순서가 호출 순서와 다릅니다.")
        validated.append({"ids": list(ids), "calls": calls, "items": group["items"]})
    return validated


def map_history(history: list[dict[str, Any]], tool_schemas: dict[str, dict[str, Any]], groups: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not history or not isinstance(history[0], dict) or history[0].get("role") != "user":
        raise ClaudeGptError("invalid_history", "대화 기록은 사용자 메시지로 시작해야 합니다.")
    known_groups: dict[str, dict[str, Any]] = {}
    for group in _validated_provider_groups(groups, tool_schemas):
        for call_id in group["ids"]:
            if not isinstance(call_id, str) or call_id in known_groups:
                raise ClaudeGptError("invalid_state", "저장된 GPT 도구 ID가 중복되었습니다.")
            known_groups[call_id] = group

    seen_calls: dict[str, dict[str, Any]] = {}
    seen_results: set[str] = set()
    mapped: list[dict[str, Any]] = []
    emitted_groups: set[int] = set()
    retained_groups: list[dict[str, Any]] = []
    group_visibility: dict[int, set[str]] = {}
    group_by_identity: dict[int, dict[str, Any]] = {}
    for message_index, message in enumerate(history):
        if (not isinstance(message, dict) or set(message) != {"role", "content"} or
                message["role"] not in {"user", "assistant"} or not isinstance(message["content"], list)):
            raise ClaudeGptError("invalid_history", "대화 메시지 형식이 잘못되었습니다.")
        role = message["role"]
        text_blocks: list[dict[str, Any]] = []

        def flush_text() -> None:
            if text_blocks:
                mapped.append({"role": role, "content": list(text_blocks)})
                text_blocks.clear()

        for block in message["content"]:
            if not isinstance(block, dict) or not isinstance(block.get("type"), str):
                raise ClaudeGptError("unsupported_history", "대화 내용 블록 형식이 잘못되었습니다.")
            kind = block["type"]
            if kind == "text" and isinstance(block.get("text"), str):
                text_blocks.append({"type": "input_text" if role == "user" else "output_text", "text": block["text"]})
                continue
            if kind in {"image", "document"} and role == "user":
                text_blocks.append(_media_input(block))
                continue
            if kind in {"thinking", "redacted_thinking"}:
                continue
            if kind == "tool_use" and role == "assistant":
                call_id = block.get("id")
                name = block.get("name")
                arguments = block.get("input")
                if not isinstance(call_id, str) or not SAFE_ID_RE.fullmatch(call_id) or call_id in seen_calls:
                    raise ClaudeGptError("invalid_tool_call", "대화 기록에 중복되거나 잘못된 도구 호출 ID가 있습니다.")
                if not isinstance(name, str) or name not in tool_schemas:
                    raise ClaudeGptError("unknown_tool", "대화 기록에 현재 제공되지 않은 도구 호출이 있습니다.")
                arguments = _validate_tool_input(arguments, tool_schemas[name], f"history.{name}")
                call = {"name": name, "arguments": arguments, "message_index": message_index}
                seen_calls[call_id] = call
                flush_text()
                group = known_groups.get(call_id)
                if group is None:
                    mapped.append({
                        "type": "function_call", "call_id": call_id, "namespace": "claude",
                        "name": name, "arguments": json.dumps(arguments, ensure_ascii=False, separators=(",", ":")),
                    })
                else:
                    group_key = id(group)
                    group_visibility.setdefault(group_key, set()).add(call_id)
                    group_by_identity[group_key] = group
                    saved = group["calls"].get(call_id)
                    if saved != {"name": name, "arguments": arguments}:
                        raise ClaudeGptError("state_mismatch", "현재 대화의 GPT 도구 호출이 저장된 프로필 상태와 다릅니다.")
                    if group_key not in emitted_groups:
                        mapped.extend(group["items"])
                        emitted_groups.add(group_key)
                continue
            if kind == "tool_result" and role == "user":
                call_id = block.get("tool_use_id")
                if not isinstance(call_id, str) or call_id not in seen_calls or call_id in seen_results:
                    raise ClaudeGptError("mismatched_tool_result", "도구 결과가 이전의 유일한 호출과 일치하지 않습니다.")
                is_error = block.get("is_error", False)
                if not isinstance(is_error, bool):
                    raise ClaudeGptError("unsupported_tool_result", "도구 결과 오류 표시 형식이 잘못되었습니다.")
                result_text, attachments = _history_parts(block.get("content"), allow_media=True)
                output = "".join(result_text)
                if attachments:
                    notice = "도구 결과에 첨부 파일이 있어 다음 사용자 메시지에 전달했습니다."
                    output = f"{output}\n{notice}" if output else notice
                if is_error:
                    output = f"Tool error: {output}"
                seen_results.add(call_id)
                flush_text()
                mapped.append({"type": "function_call_output", "call_id": call_id, "output": output})
                if attachments:
                    mapped.append({"role": "user", "content": attachments})
                continue
            raise ClaudeGptError("unsupported_history", f"지원하지 않는 대화 내용 블록입니다: {kind}")
        flush_text()

    if set(seen_calls) != seen_results:
        raise ClaudeGptError("unfinished_tool_call", "대화 기록에 결과가 없는 도구 호출이 있습니다.")
    for group_key, group in group_by_identity.items():
        if group_visibility[group_key] != set(group["ids"]):
            raise ClaudeGptError("incomplete_provider_state", "저장된 GPT 도구 호출 묶음이 대화 기록과 일치하지 않습니다.")
        retained_groups.append(group)
    return mapped, retained_groups


def build_responses_payload(request: dict[str, Any], *, subscription: bool,
                            provider_groups: list[dict[str, Any]] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    request = validate_protocol_request(request)
    tools = request["tools"]
    tool_schemas = {tool["name"]: tool["input_schema"] for tool in tools}
    mapped_history, retained_groups = map_history(request["history"], tool_schemas, provider_groups or [])
    input_items: list[dict[str, Any]] = [
        {"role": "developer", "content": [{"type": "input_text", "text": item}]}
        for item in request["developer"]
    ]
    input_items.extend(mapped_history)
    payload: dict[str, Any] = {
        "model": request["model"],
        "instructions": request["system"],
        "input": input_items,
        "store": False,
        "stream": True,
    }
    if request["effort"] is not None:
        payload["reasoning"] = {"effort": request["effort"]}
    if "tool_choice" in request:
        payload["tool_choice"] = request["tool_choice"]
    if tools:
        namespace = {
            "type": "namespace",
            "name": "claude",
            "description": "Tools offered by the current Claude Code request.",
            "tools": [
                {
                    "type": "function",
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["input_schema"],
                    "strict": False,
                }
                for tool in tools
            ],
        }
        payload["tools"] = [namespace]
    return payload, retained_groups


def _normalize_discovery(value: dict[str, Any]) -> dict[str, str]:
    if value.get("issuer") != OAUTH_ISSUER:
        raise ClaudeGptError("invalid_discovery", "OpenAI 로그인 서버의 발급자 주소를 확인할 수 없습니다.")
    expected = {
        "authorization_endpoint", "token_endpoint", "jwks_uri", "revocation_endpoint",
    }
    result: dict[str, str] = {"issuer": OAUTH_ISSUER}
    for name in expected:
        endpoint = value.get(name)
        parsed = urllib.parse.urlsplit(endpoint) if isinstance(endpoint, str) else None
        if (parsed is None or parsed.scheme != "https" or parsed.hostname != "auth.openai.com" or parsed.port not in {None, 443} or
                parsed.username is not None or parsed.password is not None or parsed.fragment):
            raise ClaudeGptError("invalid_discovery", "OpenAI 로그인 서버 주소가 안전하지 않습니다.")
        result[name] = endpoint
    return result


def fetch_discovery(http: HttpClient) -> dict[str, str]:
    return _normalize_discovery(http.json(DISCOVERY_URL))


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def create_authorization_attempt(*, client_id: str, host_id: str, redirect_uri: str,
                                 existing_id_token: str | None = None,
                                 login_hint: str | None = None) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(redirect_uri)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.path != "/auth/callback" or parsed.query or parsed.fragment:
        raise ClaudeGptError("invalid_redirect", "로그인 콜백 주소가 안전하지 않습니다.")
    if not isinstance(host_id, str) or not re.fullmatch(r"urn:uuid:[0-9a-fA-F-]{36}", host_id):
        raise ClaudeGptError("invalid_host_id", "ChatGPT 로그인을 위한 호스트 식별자가 잘못되었습니다.")
    if not isinstance(client_id, str) or not client_id or len(client_id) > 256:
        raise ClaudeGptError("invalid_client_id", "ChatGPT 등록 클라이언트 ID가 잘못되었습니다.")
    state = _b64url(secrets.token_bytes(32))
    nonce = _b64url(secrets.token_bytes(32))
    verifier = _b64url(secrets.token_bytes(64))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    params = {
        "client_id": client_id,
        "ext_agent_host_id": host_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": OAUTH_SCOPES,
        "resource": OPENAI_RESOURCE,
        "state": state,
        "nonce": nonce,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
    }
    if client_id == OAUTH_DYNAMIC_CLIENT:
        params["agent_name_hint"] = OAUTH_AGENT_NAME
    else:
        if existing_id_token:
            params["id_token_hint"] = existing_id_token
        if login_hint:
            params["login_hint"] = login_hint
    return {
        "state": state,
        "nonce": nonce,
        "verifier": verifier,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "url_params": params,
    }


def parse_oauth_callback(callback_url: str, attempt: Mapping[str, Any]) -> dict[str, str]:
    parsed = urllib.parse.urlsplit(callback_url)
    expected = urllib.parse.urlsplit(str(attempt["redirect_uri"]))
    if (parsed.scheme != expected.scheme or parsed.hostname != expected.hostname or parsed.port != expected.port or
            parsed.path != "/auth/callback" or parsed.fragment or parsed.username or parsed.password):
        raise ClaudeGptError("invalid_callback", "로그인 응답을 확인할 수 없습니다.")
    try:
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
    except ValueError as error:
        raise ClaudeGptError("invalid_callback", "로그인 응답을 확인할 수 없습니다.") from error
    if any(len(values) != 1 for values in query.values()):
        raise ClaudeGptError("invalid_callback", "로그인 응답을 확인할 수 없습니다.")
    state = query.get("state", [None])[0]
    if not isinstance(state, str) or not secrets.compare_digest(state, str(attempt["state"])):
        raise ClaudeGptError("invalid_state", "로그인 응답의 상태 검증에 실패했습니다.")
    if query.get("error"):
        error = query["error"][0]
        if error == "access_denied":
            raise ClaudeGptError("access_denied", "ChatGPT 사용 권한이 승인되지 않았습니다.")
        raise ClaudeGptError("authorization_failed", "ChatGPT 로그인을 완료하지 못했습니다.")
    code = query.get("code", [None])[0]
    client_id = query.get("client_id", [None])[0]
    if not isinstance(code, str) or not code or len(code) > 8192:
        raise ClaudeGptError("missing_code", "로그인 응답에 인증 코드가 없습니다.")
    expected_client_id = attempt["client_id"]
    if expected_client_id == OAUTH_DYNAMIC_CLIENT:
        if not isinstance(client_id, str) or not client_id or client_id == OAUTH_DYNAMIC_CLIENT:
            raise ClaudeGptError("missing_client_id", "새 등록 응답에 발급된 클라이언트 ID가 없습니다.")
    elif client_id is not None and client_id != expected_client_id:
        raise ClaudeGptError("client_mismatch", "로그인 응답이 선택한 계정 등록과 일치하지 않습니다.")
    return {
        "code": code,
        "client_id": client_id or expected_client_id,
        "scope": query.get("scope", [""])[0],
    }


def exchange_authorization_code(http: HttpClient, discovery: Mapping[str, str], callback: Mapping[str, str],
                               attempt: Mapping[str, Any]) -> dict[str, Any]:
    form = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": callback["code"],
        "redirect_uri": attempt["redirect_uri"],
        "client_id": callback["client_id"],
        "code_verifier": attempt["verifier"],
        "resource": OPENAI_RESOURCE,
    }).encode("ascii")
    return http.json(discovery["token_endpoint"], method="POST", data=form,
                     headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"})


def verify_id_token(id_token: str, *, client_id: str, nonce: str, discovery: Mapping[str, str], http: HttpClient,
                    now: int | None = None) -> dict[str, Any]:
    try:
        import jwt
    except ImportError as error:
        raise ClaudeGptError("jwt_dependency_missing", "구독 로그인에는 PyJWT와 cryptography가 필요합니다. 선택적 claude-gpt 의존성을 명시적으로 설치한 뒤 다시 실행하세요.") from error
    try:
        header = jwt.get_unverified_header(id_token)
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str) or not header["kid"]:
            raise ValueError("unsupported JWT header")
        jwks = http.json(discovery["jwks_uri"])
        keys = jwks.get("keys")
        if not isinstance(keys, list):
            raise ValueError("invalid JWKS")
        candidates = [key for key in keys if isinstance(key, dict) and key.get("kid") == header["kid"] and
                      key.get("kty") == "RSA" and key.get("use") in {None, "sig"} and
                      key.get("alg") in {None, "RS256"} and key.get("key_ops", ["verify"]) == ["verify"]]
        if len(candidates) != 1:
            raise ValueError("unknown signing key")
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(candidates[0]))
        options = {
            "require": ["iss", "aud", "exp", "iat", "sub", "nonce"],
            "verify_exp": now is None,
            "verify_iat": now is None,
        }
        kwargs: dict[str, Any] = {
            "algorithms": ["RS256"], "issuer": discovery["issuer"], "audience": client_id,
            "leeway": 5, "options": options,
        }
        claims = jwt.decode(id_token, public_key, **kwargs)
        if now is not None:
            issued_at, expires_at = claims.get("iat"), claims.get("exp")
            if (not isinstance(issued_at, (int, float)) or isinstance(issued_at, bool) or
                    not isinstance(expires_at, (int, float)) or isinstance(expires_at, bool) or
                    issued_at > now + 5 or expires_at <= now - 5):
                raise ValueError("token time claims are invalid")
    except ClaudeGptError:
        raise
    except Exception as error:
        raise ClaudeGptError("invalid_id_token", "ChatGPT 계정의 서명된 신원을 확인할 수 없습니다.") from error
    token_nonce = claims.get("nonce")
    if (not isinstance(token_nonce, str) or not secrets.compare_digest(token_nonce, nonce) or
            not isinstance(claims.get("sub"), str) or not claims["sub"]):
        raise ClaudeGptError("invalid_id_token", "ChatGPT 계정의 신원 또는 nonce 검증에 실패했습니다.")
    return claims


def _validated_scopes(scope: Any) -> list[str]:
    if not isinstance(scope, str):
        raise ClaudeGptError("missing_scope", "로그인 응답에 승인된 권한 범위가 없습니다.")
    scopes = sorted(set(scope.split()))
    if REQUIRED_SUBSCRIPTION_SCOPE not in scopes:
        raise ClaudeGptError("missing_direct_scope", "ChatGPT 플랜 사용 권한이 승인되지 않았습니다.")
    return scopes


def _token_expiry(token_response: Mapping[str, Any], now: int | None = None) -> int:
    expires_in = token_response.get("expires_in")
    if not isinstance(expires_in, (int, float)) or isinstance(expires_in, bool) or expires_in <= 0 or expires_in > 31_536_000:
        raise ClaudeGptError("invalid_token_response", "로그인 응답의 토큰 만료 정보가 잘못되었습니다.")
    return int(now if now is not None else time.time()) + int(expires_in)


def _validated_tokens(token_response: Mapping[str, Any], *, fallback_scopes: list[str] | None = None,
                      now: int | None = None) -> tuple[dict[str, Any], list[str]]:
    access = token_response.get("access_token")
    refresh = token_response.get("refresh_token")
    token_type = token_response.get("token_type", "Bearer")
    if not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh or token_type.lower() != "bearer":
        raise ClaudeGptError("invalid_token_response", "로그인 응답에 필요한 갱신 토큰이 없습니다.")
    scope_value = token_response.get("scope")
    scopes = _validated_scopes(scope_value) if scope_value is not None else _validated_scopes(" ".join(fallback_scopes or []))
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "Bearer",
        "expires_at": _token_expiry(token_response, now),
    }, scopes


def finish_subscription_login(store: ProfileStore, http: HttpClient, *, profile_id: str | None,
                              attempt: Mapping[str, Any], callback_url: str,
                              now: int | None = None) -> dict[str, Any]:
    callback = parse_oauth_callback(callback_url, attempt)
    discovery = fetch_discovery(http)
    tokens = exchange_authorization_code(http, discovery, callback, attempt)
    credentials, scopes = _validated_tokens(tokens, now=now)
    id_token = tokens.get("id_token")
    if not isinstance(id_token, str) or not id_token:
        raise ClaudeGptError("invalid_token_response", "로그인 응답에 검증할 ID 토큰이 없습니다.")
    claims = verify_id_token(id_token, client_id=callback["client_id"], nonce=attempt["nonce"], discovery=discovery,
                             http=http, now=now)
    profile: dict[str, Any]
    is_new = profile_id is None
    if is_new:
        profile_id = f"p_{uuid.uuid4().hex}"
        profile = {
            "profile_id": profile_id,
            "mode": "subscription",
            "issuer": discovery["issuer"],
            "client_id": callback["client_id"],
            "subject": claims["sub"],
            "email": claims.get("email") if isinstance(claims.get("email"), str) else None,
            "scopes": scopes,
            "created_at": _utc_now(now),
            "status": "connected",
        }
    else:
        old = store.read_profile(profile_id)
        if old.get("mode") != "subscription" or old.get("issuer") != discovery["issuer"] or old.get("client_id") != callback["client_id"] or old.get("subject") != claims["sub"]:
            raise ClaudeGptError("account_mismatch", "새 로그인 결과가 선택한 ChatGPT 계정과 일치하지 않습니다.")
        profile = {**old, "email": claims.get("email") if isinstance(claims.get("email"), str) else old.get("email"),
                   "scopes": scopes, "status": "connected"}
    credentials.update({"id_token": id_token, "scopes": scopes})
    with store.locked():
        store.write_profile(profile)
        store.write_credentials(profile_id, credentials)
        store.set_active(profile_id)
    return {"profile_id": profile_id, "mode": "subscription", "status": "connected"}


def _utc_now(now: int | None = None) -> str:
    moment = dt.datetime.fromtimestamp(now if now is not None else time.time(), tz=dt.timezone.utc)
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


def create_api_key_profile(store: ProfileStore, api_key: str, *, confirmed_usage_billing: bool,
                           now: int | None = None) -> dict[str, Any]:
    if not confirmed_usage_billing:
        raise ClaudeGptError("billing_not_confirmed", "API 사용량 과금 동의가 필요합니다.")
    if not isinstance(api_key, str) or not api_key.strip() or len(api_key) > 8192 or "\n" in api_key or "\r" in api_key:
        raise ClaudeGptError("invalid_api_key", "API 키가 비어 있거나 형식이 잘못되었습니다.")
    profile_id = f"p_{uuid.uuid4().hex}"
    consent_at = _utc_now(now)
    profile = {
        "profile_id": profile_id,
        "mode": "api_key",
        "created_at": consent_at,
        "api_billing_consent_at": consent_at,
        "status": "connected",
    }
    with store.locked():
        store.write_profile(profile)
        store.write_credentials(profile_id, {"api_key": api_key})
        store.set_active(profile_id)
    return {"profile_id": profile_id, "mode": "api_key", "status": "connected"}


def _key_for_profile(store: ProfileStore, profile_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    profile = store.read_profile(profile_id)
    if profile.get("status") != "connected":
        raise ClaudeGptError("profile_signed_out", "선택한 프로필이 연결되어 있지 않습니다.")
    credentials = store.read_credentials(profile_id)
    if profile.get("mode") == "api_key":
        if not profile.get("api_billing_consent_at") or not isinstance(credentials.get("api_key"), str) or not credentials["api_key"]:
            raise ClaudeGptError("invalid_profile", "API 키 프로필의 과금 동의 또는 인증 정보가 없습니다.")
        return profile, credentials
    if profile.get("mode") != "subscription" or REQUIRED_SUBSCRIPTION_SCOPE not in profile.get("scopes", []):
        raise ClaudeGptError("invalid_profile", "구독 프로필의 ChatGPT 플랜 사용 권한이 없습니다.")
    if any(not isinstance(credentials.get(key), str) or not credentials[key] for key in ("access_token", "refresh_token", "id_token")):
        raise ClaudeGptError("invalid_profile", "구독 프로필의 토큰이 완전하지 않습니다.")
    return profile, credentials


def _refresh_if_needed(store: ProfileStore, http: HttpClient, profile_id: str,
                       now: int | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    with store.locked():
        profile, credentials = _key_for_profile(store, profile_id)
        if profile["mode"] != "subscription":
            return profile, credentials
        current = int(now if now is not None else time.time())
        expires = credentials.get("expires_at")
        if not isinstance(expires, int) or isinstance(expires, bool):
            raise ClaudeGptError("invalid_profile", "구독 프로필의 만료 정보가 잘못되었습니다.")
        if expires > current + 60:
            return profile, credentials
        discovery = fetch_discovery(http)
        form = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "client_id": profile["client_id"],
            "refresh_token": credentials["refresh_token"],
            "resource": OPENAI_RESOURCE,
        }).encode("ascii")
        refreshed = http.json(discovery["token_endpoint"], method="POST", data=form,
                              headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"})
        replacement, scopes = _validated_tokens(refreshed, fallback_scopes=credentials.get("scopes", []), now=current)
        replacement["id_token"] = credentials["id_token"]
        replacement["scopes"] = scopes
        store.write_credentials(profile_id, replacement)
        updated_profile = {**profile, "scopes": scopes, "status": "connected"}
        store.write_profile(updated_profile)
        return updated_profile, replacement


def _session_state_groups(store: ProfileStore, request: dict[str, Any]) -> tuple[list[dict[str, Any]], Callable[[list[dict[str, Any]]], None]]:
    profile_id = request["profile_id"]
    schemas = {tool["name"]: tool["input_schema"] for tool in request["tools"]}
    history_calls: dict[str, dict[str, Any]] = {}
    for message in request["history"]:
        if not isinstance(message, dict) or message.get("role") != "assistant" or not isinstance(message.get("content"), list):
            continue
        for block in message["content"]:
            if (isinstance(block, dict) and block.get("type") == "tool_use" and
                    isinstance(block.get("id"), str)):
                history_calls[block["id"]] = {"name": block.get("name"), "arguments": block.get("input")}
    retained: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    for group in store.read_provider_state(profile_id):
        if (not isinstance(group, dict) or not isinstance(group.get("ids"), list) or
                not isinstance(group.get("calls"), dict)):
            continue
        ids = group["ids"]
        if (not ids or any(not isinstance(call_id, str) or call_id in selected_ids for call_id in ids) or
                set(group["calls"]) != set(ids)):
            continue
        if any(call_id not in history_calls or not isinstance(group["calls"].get(call_id), dict) or
               set(group["calls"][call_id]) != {"name", "arguments"} or
               group["calls"][call_id]["name"] != history_calls[call_id]["name"] or
               not _json_equal(group["calls"][call_id]["arguments"], history_calls[call_id]["arguments"])
               for call_id in ids):
            continue
        try:
            validated = _validated_provider_groups([group], schemas)
        except ClaudeGptError:
            continue
        retained.extend(validated)
        selected_ids.update(ids)
    map_history(request["history"], schemas, retained)

    def save(groups: list[dict[str, Any]]) -> None:
        with store.locked():
            if store.read_profile(profile_id).get("status") != "connected":
                raise ClaudeGptError("profile_signed_out", "요청 도중 선택한 프로필이 로그아웃되었습니다.")
            store.merge_provider_state(profile_id, groups)
    return retained, save


def _flatten_provider_item(item: Any, *, tool_schemas: dict[str, dict[str, Any]], current_call_ids: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(item, dict) or not isinstance(item.get("type"), str):
        raise ClaudeGptError("invalid_response", "Responses API가 출력 항목 형식 오류를 반환했습니다.")
    kind = item["type"]
    if kind == "reasoning":
        if not isinstance(item.get("id"), str):
            raise ClaudeGptError("invalid_response", "Responses API 추론 상태를 안전하게 보존할 수 없습니다.")
        _json_bytes(item)
        return [], [], [item]
    if kind == "function_call":
        call_id = item.get("call_id")
        name = item.get("name")
        namespace = item.get("namespace")
        raw_arguments = item.get("arguments")
        if (not isinstance(call_id, str) or not SAFE_ID_RE.fullmatch(call_id) or call_id in current_call_ids or
                not isinstance(name, str) or name not in tool_schemas or namespace != "claude" or
                not isinstance(raw_arguments, str)):
            raise ClaudeGptError("invalid_tool_call", "Responses API가 알 수 없거나 중복된 도구 호출을 반환했습니다.")
        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError as error:
            raise ClaudeGptError("invalid_tool_call", "Responses API 도구 입력 JSON이 잘못되었습니다.") from error
        arguments = _validate_tool_input(arguments, tool_schemas[name], f"response.{name}")
        current_call_ids.add(call_id)
        canonical = {"type": "function_call", "call_id": call_id, "namespace": "claude", "name": name,
                     "arguments": json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))}
        calls = [{"id": call_id, "name": name, "arguments": arguments}]
        return [], calls, [canonical]
    if kind == "message":
        content = item.get("content")
        if not isinstance(content, list):
            raise ClaudeGptError("invalid_response", "Responses API 메시지 형식이 잘못되었습니다.")
        visible: list[dict[str, Any]] = []
        for part in content:
            if not isinstance(part, dict):
                raise ClaudeGptError("invalid_response", "Responses API 메시지 내용이 잘못되었습니다.")
            if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                visible.append({"kind": "text", "text": part["text"]})
            elif part.get("type") == "refusal" and isinstance(part.get("refusal"), str):
                visible.append({"kind": "refusal", "text": part["refusal"]})
            else:
                raise ClaudeGptError("unsupported_response", "Responses API가 지원하지 않는 메시지 콘텐츠를 반환했습니다.")
        return visible, [], []
    raise ClaudeGptError("unsupported_response", "Responses API가 지원하지 않는 출력 항목을 반환했습니다.")


def _usage_record(response: Mapping[str, Any]) -> dict[str, Any]:
    usage = response.get("usage")
    model = response.get("model")
    if not isinstance(usage, dict) or not isinstance(model, str) or model not in PINNED_MODELS:
        raise ClaudeGptError("invalid_usage", "Responses API 사용량 또는 실제 모델 ID가 없습니다.")
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    details_in = usage.get("input_tokens_details", {})
    details_out = usage.get("output_tokens_details", {})
    cached = details_in.get("cached_tokens", 0) if isinstance(details_in, dict) else None
    reasoning = details_out.get("reasoning_tokens", 0) if isinstance(details_out, dict) else None
    for number in (input_tokens, output_tokens, cached, reasoning):
        if not isinstance(number, int) or isinstance(number, bool) or number < 0:
            raise ClaudeGptError("invalid_usage", "Responses API 사용량 숫자가 잘못되었습니다.")
    if cached > input_tokens:
        raise ClaudeGptError("invalid_usage", "Responses API 캐시 사용량이 입력 사용량보다 큽니다.")
    return {"input_tokens": input_tokens, "cached_input_tokens": cached, "output_tokens": output_tokens,
            "reasoning_tokens": reasoning, "model": model}


def _extract_completed(response: Any, *, expected_model: str, tool_schemas: dict[str, dict[str, Any]],
                       prior_ids: set[str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(response, dict) or response.get("status") != "completed" or response.get("model") != expected_model:
        raise ClaudeGptError("invalid_completion", "Responses API 완료 상태 또는 모델 ID가 요청과 일치하지 않습니다.")
    output = response.get("output")
    if not isinstance(output, list):
        raise ClaudeGptError("invalid_completion", "Responses API 완료 응답에 출력 항목이 없습니다.")
    current_ids = set(prior_ids)
    visible: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    saved_items: list[dict[str, Any]] = []
    for item in output:
        item_visible, item_calls, state_items = _flatten_provider_item(item, tool_schemas=tool_schemas,
                                                                       current_call_ids=current_ids)
        visible.extend(item_visible)
        calls.extend(item_calls)
        saved_items.extend(state_items)
    if response.get("id") is None or not isinstance(response["id"], str) or not response["id"]:
        raise ClaudeGptError("invalid_completion", "Responses API 응답 ID가 없습니다.")
    usage = _usage_record(response)
    return {
        "response_id": response["id"],
        "model": response["model"],
        "usage": usage,
        "tool_calls": calls,
        "provider_items": saved_items,
        "visible": visible,
        "provider_reported_effort": _provider_effort(response),
    }, calls


def _provider_effort(response: Mapping[str, Any]) -> str | None:
    value = response.get("reasoning")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ClaudeGptError("invalid_effort", "Responses API가 보고한 reasoning 설정이 잘못되었습니다.")
    effort = value.get("effort")
    if effort is None:
        return None
    if not isinstance(effort, str) or effort not in SUPPORTED_EFFORTS:
        raise ClaudeGptError("invalid_effort", "Responses API가 지원하지 않는 reasoning 설정을 보고했습니다.")
    return effort


def _new_state_group(completion: Mapping[str, Any]) -> dict[str, Any] | None:
    calls = completion["tool_calls"]
    if not calls:
        return None
    items = completion["provider_items"]
    return {
        "ids": [call["id"] for call in calls],
        "calls": {call["id"]: {"name": call["name"], "arguments": call["arguments"]} for call in calls},
        "items": items,
    }


def _sse_events(stream: BinaryIO) -> Iterator[dict[str, Any]]:
    data_lines: list[str] = []
    event_name: str | None = None
    total = 0
    while True:
        raw = stream.readline(MAX_PROTOCOL_LINE + 1)
        if len(raw) > MAX_PROTOCOL_LINE:
            raise ClaudeGptError("stream_line_too_large", "Responses API 스트림 줄이 허용 크기를 넘었습니다.")
        if raw == b"":
            break
        total += len(raw)
        if total > MAX_REQUEST_BYTES * 4:
            raise ClaudeGptError("stream_too_large", "Responses API 스트림이 허용 크기를 넘었습니다.")
        try:
            line = raw.decode("utf-8", errors="strict").rstrip("\r\n")
        except UnicodeDecodeError as error:
            raise ClaudeGptError("invalid_stream", "Responses API 스트림이 올바른 UTF-8이 아닙니다.") from error
        if not line:
            if data_lines:
                data = "\n".join(data_lines)
                if data != "[DONE]":
                    try:
                        value = json.loads(data)
                    except json.JSONDecodeError as error:
                        raise ClaudeGptError("invalid_stream", "Responses API 스트림 JSON이 잘못되었습니다.") from error
                    if not isinstance(value, dict) or not isinstance(value.get("type"), str):
                        raise ClaudeGptError("invalid_stream", "Responses API 이벤트 형식이 잘못되었습니다.")
                    if event_name is not None and event_name != value["type"]:
                        raise ClaudeGptError("invalid_stream", "Responses API 이벤트 이름과 본문이 다릅니다.")
                    yield value
            data_lines = []
            event_name = None
            continue
        if line.startswith(":"):
            continue
        field, separator, value = line.partition(":")
        if not separator:
            value = ""
        elif value.startswith(" "):
            value = value[1:]
        if field == "data":
            data_lines.append(value)
        elif field == "event":
            event_name = value
    if data_lines:
        raise ClaudeGptError("truncated_stream", "Responses API 스트림이 이벤트 경계에서 끝나지 않았습니다.")


def _validate_text_from_completion(completion: Mapping[str, Any], streamed_text: str) -> None:
    final_text = "".join(part["text"] for part in completion["visible"])
    if final_text != streamed_text:
        raise ClaudeGptError("stream_mismatch", "Responses API 스트림과 완료 메시지 내용이 일치하지 않습니다.")


def _provider_usage_metadata(response: Any, expected_model: str, *, completed: bool) -> dict[str, Any] | None:
    if (not isinstance(response, dict) or response.get("model") != expected_model or
            expected_model not in PINNED_MODELS or
            (completed and response.get("status") != "completed")):
        return None
    try:
        usage = _usage_record(response)
    except ClaudeGptError:
        return None
    try:
        effort = _provider_effort(response)
    except ClaudeGptError:
        effort = None
    return {"model": expected_model, "usage": usage, "provider_reported_effort": effort}


def _first_mismatch_offset(left: str, right: str) -> int:
    for index, (left_char, right_char) in enumerate(zip(left, right)):
        if left_char != right_char:
            return index
    return min(len(left), len(right))


class _StreamDiagnostics:
    def __init__(self):
        self.event_counts = {kind: 0 for kind in DIAGNOSTIC_EVENT_TYPES}
        self.event_counts["unknown_events"] = 0
        self.output_item_counts = {kind: 0 for kind in DIAGNOSTIC_OUTPUT_ITEM_TYPES}
        self.output_item_counts["unknown"] = 0
        self.streamed_characters = 0
        self.completed_visible_characters: int | None = None
        self.first_mismatch_offset: int | None = None
        self.reconstructed_output_items: int | None = None
        self.part_summaries: dict[tuple[int | None, int | None], dict[str, int | None]] = {}
        self.part_summaries_overflow = 0

    def observe_event(self, event: Mapping[str, Any]) -> None:
        kind = event.get("type")
        if isinstance(kind, str) and kind in self.event_counts and kind != "unknown_events":
            self.event_counts[kind] += 1
        else:
            self.event_counts["unknown_events"] += 1
        self._observe_text_part(event, kind)

    def observe_output_items(self, response: Any) -> None:
        output = response.get("output") if isinstance(response, dict) else None
        if not isinstance(output, list):
            return
        for item in output:
            kind = item.get("type") if isinstance(item, dict) else None
            if isinstance(kind, str) and kind in DIAGNOSTIC_OUTPUT_ITEM_TYPES:
                self.output_item_counts[kind] += 1
            else:
                self.output_item_counts["unknown"] += 1

    def _observe_text_part(self, event: Mapping[str, Any], kind: Any) -> None:
        text: str | None = None
        phase: str | None = None
        if kind in {"response.output_text.delta", "response.refusal.delta"}:
            candidate = event.get("delta")
            text = candidate if isinstance(candidate, str) else None
            phase = "delta"
        elif kind in {"response.content_part.added", "response.content_part.done"}:
            part = event.get("part")
            if isinstance(part, dict):
                if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                    text = part["text"]
                elif part.get("type") == "refusal" and isinstance(part.get("refusal"), str):
                    text = part["refusal"]
            phase = "added" if kind == "response.content_part.added" else "part_done"
        elif kind == "response.output_text.done":
            candidate = event.get("text")
            text = candidate if isinstance(candidate, str) else None
            phase = "text_done"
        elif kind == "response.refusal.done":
            candidate = event.get("refusal")
            text = candidate if isinstance(candidate, str) else None
            phase = "text_done"
        if text is None or phase is None:
            return
        output_index = _diagnostic_index(event.get("output_index"))
        content_index = _diagnostic_index(event.get("content_index"))
        key = (output_index, content_index)
        summary = self.part_summaries.get(key)
        if summary is None:
            if len(self.part_summaries) >= MAX_DIAGNOSTIC_PARTS:
                self.part_summaries_overflow = min(
                    MAX_DIAGNOSTIC_INTEGER, self.part_summaries_overflow + 1,
                )
                return
            summary = {"output_index": output_index, "content_index": content_index,
                       **{counter: 0 for counter in DIAGNOSTIC_PART_COUNTERS}}
            self.part_summaries[key] = summary
        event_counter = f"{phase}_events"
        character_counter = f"{phase}_characters"
        summary[event_counter] = min(MAX_DIAGNOSTIC_INTEGER, int(summary[event_counter]) + 1)
        summary[character_counter] = min(
            MAX_DIAGNOSTIC_INTEGER, int(summary[character_counter]) + len(text),
        )

    def snapshot(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "event_counts": dict(self.event_counts),
            "streamed_characters": self.streamed_characters,
            "output_item_counts": dict(self.output_item_counts),
            "part_summaries": [dict(part) for part in self.part_summaries.values()],
            "part_summaries_overflow": self.part_summaries_overflow,
        }
        if self.completed_visible_characters is not None:
            result["completed_visible_characters"] = self.completed_visible_characters
        if self.first_mismatch_offset is not None:
            result["first_mismatch_offset"] = self.first_mismatch_offset
        if self.reconstructed_output_items is not None:
            result["reconstructed_output_items"] = self.reconstructed_output_items
        return result


class _StreamOutputItems:
    def __init__(self):
        self.saw_events = False
        self.added_by_index: dict[int, dict[str, str]] = {}
        self.added_ids: set[str] = set()
        self.done_by_index: dict[int, dict[str, Any]] = {}
        self.done_ids: set[str] = set()

    def observe(self, event: Mapping[str, Any]) -> None:
        kind = event.get("type")
        if kind not in {"response.output_item.added", "response.output_item.done"}:
            return
        self.saw_events = True
        output_index = event.get("output_index")
        item = event.get("item")
        if (not isinstance(output_index, int) or isinstance(output_index, bool) or output_index < 0 or
                not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"] or
                not isinstance(item.get("type"), str) or not item["type"]):
            raise ClaudeGptError(
                "invalid_output_item_event", "Responses API 출력 항목 이벤트가 잘못되었습니다.",
            )
        item_id = item["id"]
        item_type = item["type"]
        if kind == "response.output_item.added":
            if output_index in self.added_by_index or item_id in self.added_ids:
                raise ClaudeGptError(
                    "duplicate_output_item_event", "Responses API 출력 항목 인덱스 또는 ID가 중복되었습니다.",
                )
            self.added_by_index[output_index] = {"id": item_id, "type": item_type}
            self.added_ids.add(item_id)
            return
        if output_index in self.done_by_index or item_id in self.done_ids:
            raise ClaudeGptError(
                "duplicate_output_item_event", "Responses API 출력 항목 인덱스 또는 ID가 중복되었습니다.",
            )
        expected = self.added_by_index.get(output_index)
        if expected is None:
            raise ClaudeGptError(
                "output_item_identity_mismatch", "Responses API 완료 항목이 추가된 항목과 일치하지 않습니다.",
            )
        if expected["id"] != item_id or expected["type"] != item_type:
            raise ClaudeGptError(
                "output_item_identity_mismatch", "Responses API 출력 항목 ID 또는 종류가 변경되었습니다.",
            )
        if "status" in item and item["status"] != "completed":
            raise ClaudeGptError(
                "invalid_output_item_snapshot", "Responses API 출력 항목 스냅샷이 완료 상태가 아닙니다.",
            )
        if item_type == "message" and "role" in item and item["role"] != "assistant":
            raise ClaudeGptError(
                "invalid_output_item_snapshot", "Responses API 메시지 항목이 assistant 역할이 아닙니다.",
            )
        self.done_by_index[output_index] = dict(item)
        self.done_ids.add(item_id)

    def reconcile(self, response: Any) -> tuple[Any, int | None]:
        if not self.saw_events:
            return response, None
        if not isinstance(response, dict) or not isinstance(response.get("output"), list):
            raise ClaudeGptError(
                "output_item_completion_mismatch", "Responses API 완료 출력이 관찰된 항목 이벤트와 일치하지 않습니다.",
            )
        output = response["output"]
        if not output:
            indices = sorted(self.added_by_index)
            if not indices or set(indices) != set(self.done_by_index):
                raise ClaudeGptError(
                    "incomplete_output_items", "Responses API 출력 항목 이벤트에 완료된 스냅샷이 없습니다.",
                )
            if indices != list(range(len(indices))):
                raise ClaudeGptError(
                    "output_item_index_gap", "Responses API 출력 항목 인덱스에 간격이 있습니다.",
                )
            copy = dict(response)
            copy["output"] = [self.done_by_index[index] for index in indices]
            return copy, len(indices)

        for output_index, identity in self.added_by_index.items():
            if output_index >= len(output):
                raise ClaudeGptError(
                    "output_item_completion_mismatch", "Responses API 완료 출력에 관찰된 항목이 없습니다.",
                )
            final_item = output[output_index]
            if (not isinstance(final_item, dict) or final_item.get("id") != identity["id"] or
                    final_item.get("type") != identity["type"]):
                raise ClaudeGptError(
                    "output_item_completion_mismatch", "Responses API 완료 항목 ID 또는 종류가 이벤트와 다릅니다.",
                )
            done_item = self.done_by_index.get(output_index)
            if done_item is not None and not _json_equal(done_item, final_item):
                raise ClaudeGptError(
                    "output_item_completion_mismatch", "Responses API 완료 항목 스냅샷이 이벤트와 다릅니다.",
                )
        return response, None


def stream_responses(http: HttpClient, *, payload: dict[str, Any], api_key: str,
                     expected_model: str, requested_effort: str | None,
                     tool_schemas: dict[str, Any], prior_call_ids: set[str],
                     store_state: Callable[[dict[str, Any]], None] | None = None,
                     prior_groups: list[dict[str, Any]] | None = None,
                     stream_out: Any = None) -> int:
    body = _json_bytes(payload)
    request = urllib.request.Request(
        OPENAI_RESPONSES_URL,
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    response = http.open(request)
    if response.status < 200 or response.status >= 300:
        raise _http_error(response.status, response.body, response.headers)
    if response.stream is None:
        raise ClaudeGptError(
            "invalid_stream", "Responses API가 스트리밍 연결을 열지 않았습니다.",
            http_status=response.status, request_id=_response_request_id(response.headers),
            retry_after=_retry_after(response.headers),
        )
    output = stream_out or sys.stdout
    streamed_text = ""
    completion: dict[str, Any] | None = None
    completion_record: dict[str, Any] | None = None
    completion_seen = False
    diagnostics = _StreamDiagnostics()
    output_items = _StreamOutputItems()
    known_provider_usage: dict[str, Any] | None = None
    request_id = _response_request_id(response.headers)
    retry_after = _retry_after(response.headers)

    def with_response_fields(error: ClaudeGptError, *, terminal: bool = False) -> ClaudeGptError:
        return ClaudeGptError(
            error.code, error.message, http_status=error.http_status or response.status,
            provider_code=error.provider_code, request_id=error.request_id or request_id,
            retry_after=error.retry_after if error.retry_after is not None else retry_after,
            terminal_after_completion=terminal or error.terminal_after_completion,
            provider_usage=(error.provider_usage if error.provider_usage is not None else known_provider_usage),
            stream_diagnostics=(error.stream_diagnostics if error.stream_diagnostics is not None
                                else diagnostics.snapshot()),
        )

    try:
        with response.stream as stream:
            for event in _sse_events(stream):
                kind = event["type"]
                diagnostics.observe_event(event)
                if completion_seen:
                    raise ClaudeGptError(
                        "event_after_completion", "Responses API 완료 이벤트 뒤에 데이터가 있습니다.",
                        terminal_after_completion=True,
                    )
                if kind in {"response.output_item.added", "response.output_item.done"}:
                    output_items.observe(event)
                    continue
                if kind in {"response.output_text.delta", "response.refusal.delta"}:
                    delta = event.get("delta")
                    if not isinstance(delta, str):
                        raise ClaudeGptError("invalid_stream", "Responses API 텍스트 이벤트가 잘못되었습니다.")
                    if delta:
                        streamed_text += delta
                        diagnostics.streamed_characters = len(streamed_text)
                        emit_record({"protocol_version": PROTOCOL_VERSION, "type": "text_delta", "text": delta}, output)
                    continue
                if kind == "response.completed":
                    completion_seen = True
                    try:
                        response_value = event.get("response")
                        diagnostics.observe_output_items(response_value)
                        known_provider_usage = _provider_usage_metadata(
                            response_value, expected_model, completed=True,
                        )
                        validation_response, reconstructed_count = output_items.reconcile(response_value)
                        if reconstructed_count is not None:
                            diagnostics.reconstructed_output_items = reconstructed_count
                        completion, _ = _extract_completed(validation_response, expected_model=expected_model,
                                                            tool_schemas=tool_schemas, prior_ids=prior_call_ids)
                        diagnostics.completed_visible_characters = sum(
                            len(part["text"]) for part in completion["visible"]
                        )
                        reported_effort = completion["provider_reported_effort"]
                        if (requested_effort is not None and reported_effort is not None and
                                reported_effort != requested_effort):
                            raise ClaudeGptError("effort_mismatch", "Responses API가 요청한 reasoning 수준과 다른 수준을 반환했습니다.")
                        _validate_text_from_completion(completion, streamed_text)
                        completion_record = {
                            "protocol_version": PROTOCOL_VERSION,
                            "type": "completed",
                            "response_id": completion["response_id"],
                            "model": completion["model"],
                            "usage": completion["usage"],
                            "tool_calls": completion["tool_calls"],
                            "provider_reported_effort": completion["provider_reported_effort"],
                        }
                    except ClaudeGptError as error:
                        if error.code == "stream_mismatch" and completion is not None:
                            final_text = "".join(part["text"] for part in completion["visible"])
                            diagnostics.first_mismatch_offset = _first_mismatch_offset(streamed_text, final_text)
                        raise with_response_fields(error, terminal=True) from error
                    continue
                if kind in {"response.failed", "response.incomplete", "error"}:
                    code = _failure_code(event)
                    failure_response = event.get("response")
                    known_provider_usage = _provider_usage_metadata(
                        failure_response, expected_model, completed=False,
                    )
                    raise ClaudeGptError(
                        code, "Responses API 응답이 완료되지 않았습니다.",
                        http_status=response.status,
                        provider_code=code if code in SAFE_PROVIDER_ERROR_CODES else None,
                        request_id=request_id, retry_after=retry_after,
                        provider_usage=known_provider_usage,
                    )
        if not completion_seen or completion is None or completion_record is None:
            raise ClaudeGptError(
                "truncated_stream", "Responses API 스트림에 완료 이벤트가 없습니다.",
                http_status=response.status, request_id=request_id, retry_after=retry_after,
            )
    except (OSError, TimeoutError, UnicodeError, IncompleteRead) as error:
        code = "stream_after_completion" if completion_seen else "stream_interrupted"
        raise ClaudeGptError(
            code, "Responses API 스트림이 완료 뒤 중단되었습니다." if completion_seen else "Responses API 스트림이 중단되었습니다.",
            http_status=response.status, request_id=request_id, retry_after=retry_after,
            terminal_after_completion=completion_seen,
            provider_usage=known_provider_usage, stream_diagnostics=diagnostics.snapshot(),
        ) from error
    except ClaudeGptError as error:
        if completion_seen:
            if error.code in {"truncated_stream", "stream_interrupted"}:
                error = ClaudeGptError(
                    "stream_after_completion", "Responses API 스트림이 완료 뒤 중단되었습니다.",
                    http_status=error.http_status or response.status, provider_code=error.provider_code,
                    request_id=error.request_id or request_id,
                    retry_after=error.retry_after if error.retry_after is not None else retry_after,
                    terminal_after_completion=True,
                    provider_usage=(error.provider_usage if error.provider_usage is not None else known_provider_usage),
                    stream_diagnostics=(error.stream_diagnostics if error.stream_diagnostics is not None
                                        else diagnostics.snapshot()),
                )
            else:
                error = with_response_fields(error, terminal=True)
        else:
            error = with_response_fields(error)
        raise error
    try:
        _save_provider_state(completion, prior_groups or [], store_state)
    except ClaudeGptError as error:
        raise with_response_fields(error, terminal=True) from error
    emit_record(completion_record, output)
    return 0


def _failure_code(event: Mapping[str, Any]) -> str:
    code = event.get("code")
    if code is not None:
        if not isinstance(code, str):
            return "provider_failed"
        return code if code in SAFE_PROVIDER_ERROR_CODES else "provider_failed"
    response = event.get("response")
    error = response.get("error") if isinstance(response, dict) else event.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, str) and code in SAFE_PROVIDER_ERROR_CODES else "provider_failed"


def _save_provider_state(completion: Mapping[str, Any], prior_groups: list[dict[str, Any]],
                         save: Callable[[list[dict[str, Any]]], None] | None) -> None:
    if save is None:
        return
    group = _new_state_group(completion)
    if group is not None:
        save([*prior_groups, group])


def execute_request(store: ProfileStore, http: HttpClient, request: Any, *, now: int | None = None,
                    stream_out: Any = None) -> int:
    request = validate_protocol_request(request)
    profile_id = request["profile_id"]
    prior_groups, save_session_state = _session_state_groups(store, request)
    profile, credentials = _refresh_if_needed(store, http, profile_id, now=now)
    if profile["mode"] == "api_key":
        if not profile.get("api_billing_consent_at"):
            raise ClaudeGptError("billing_not_confirmed", "API 사용량 과금 동의가 없습니다.")
        api_key = credentials.get("api_key")
        payload, _ = build_responses_payload(request, subscription=False, provider_groups=prior_groups)
    else:
        if REQUIRED_SUBSCRIPTION_SCOPE not in profile.get("scopes", []):
            raise ClaudeGptError("missing_direct_scope", "선택한 구독 프로필에 ChatGPT 플랜 사용 권한이 없습니다.")
        api_key = credentials.get("access_token")
        payload, prior_groups = build_responses_payload(request, subscription=True, provider_groups=prior_groups)
    if not isinstance(api_key, str) or not api_key:
        raise ClaudeGptError("invalid_profile", "선택한 프로필에 유효한 인증 정보가 없습니다.")
    tool_schemas = {tool["name"]: tool["input_schema"] for tool in request["tools"]}
    prior_call_ids = {
        block["id"]
        for message in request["history"]
        if message["role"] == "assistant"
        for block in message["content"]
        if block["type"] == "tool_use"
    }
    # A user-provided API key and a plan token share the public Responses route; no fallback occurs.
    return stream_responses(
        http, payload=payload, api_key=api_key, expected_model=request["model"], requested_effort=request["effort"],
        tool_schemas=tool_schemas,
        prior_call_ids=prior_call_ids, store_state=lambda groups: save_session_state(groups),
        prior_groups=prior_groups, stream_out=stream_out,
    )


def build_revocation_request(discovery: Mapping[str, str], profile: Mapping[str, Any], credentials: Mapping[str, Any]) -> urllib.request.Request:
    endpoint = discovery.get("revocation_endpoint")
    parsed = urllib.parse.urlsplit(endpoint) if isinstance(endpoint, str) else None
    if parsed is None or parsed.scheme != "https" or parsed.hostname != "auth.openai.com":
        raise ClaudeGptError("invalid_discovery", "OpenAI 세션 취소 주소를 확인할 수 없습니다.")
    form = urllib.parse.urlencode({
        "token": credentials["refresh_token"],
        "token_type_hint": "refresh_token",
        "client_id": profile["client_id"],
    }).encode("ascii")
    return urllib.request.Request(endpoint, data=form,
                                  headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
                                  method="POST")


def logout_profile(store: ProfileStore, http: HttpClient, profile_id: str) -> dict[str, Any]:
    with store.locked():
        profile = store.read_profile(profile_id)
        credentials = store.read_credentials(profile_id)
        revoked = True
        if profile.get("mode") == "subscription":
            try:
                discovery = fetch_discovery(http)
                request = build_revocation_request(discovery, profile, credentials)
                response = http.open(request)
                revoked = response.status == 200
                if response.stream is not None:
                    response.stream.close()
            except ClaudeGptError:
                revoked = False
        store.remove_credentials(profile_id)
        updated = {**profile, "status": "signed_out"}
        store.write_profile(updated)
        if store.active_profile_id() == profile_id:
            active_path = store.root / "active.json"
            if active_path.is_symlink():
                raise ClaudeGptError("unsafe_path", "선택된 프로필 파일이 심볼릭 링크입니다.")
            with contextlib.suppress(FileNotFoundError):
                active_path.unlink()
        state_path = store.profile_dir(profile_id) / "state"
        if state_path.exists() or state_path.is_symlink():
            _check_owned_directory(state_path, private=True)
            for entry in state_path.iterdir():
                info = entry.lstat()
                if (stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or
                        info.st_uid != _current_uid() or info.st_mode & 0o077):
                    raise ClaudeGptError("unsafe_permissions", "저장된 GPT 대화 상태 파일이 안전하지 않습니다.")
                entry.unlink()
            state_path.rmdir()
    return {"profile_id": profile_id, "mode": profile.get("mode"), "status": "signed_out", "revocation_confirmed": revoked}


def _callback_server() -> tuple[http.server.HTTPServer, str, dict[str, str]]:
    received: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if urllib.parse.urlsplit(self.path).path != "/auth/callback":
                self.send_error(404)
                return
            received["url"] = f"http://127.0.0.1:{self.server.server_port}{self.path}"
            body = b"Login response received. Return to the terminal."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 600
    port = server.server_port
    return server, f"http://127.0.0.1:{port}/auth/callback", received


def run_subscription_login(store: ProfileStore, http: HttpClient, *, profile_id: str | None) -> dict[str, Any]:
    if profile_id is not None:
        profile = store.read_profile(profile_id)
        if profile.get("mode") != "subscription":
            raise ClaudeGptError("profile_mode_mismatch", "선택한 프로필은 구독 로그인이 아닙니다.")
        client_id = profile.get("client_id")
        credentials_path = store.profile_dir(profile_id) / "credentials.json"
        if not isinstance(client_id, str) or not client_id:
            raise ClaudeGptError("invalid_profile", "선택한 구독 프로필을 다시 인증할 수 없습니다.")
        if credentials_path.exists() or credentials_path.is_symlink():
            credentials = store.read_credentials(profile_id)
            id_hint = credentials.get("id_token")
            if not isinstance(id_hint, str) and profile.get("status") != "signed_out":
                raise ClaudeGptError("invalid_profile", "선택한 구독 프로필을 다시 인증할 수 없습니다.")
        elif profile.get("status") == "signed_out":
            id_hint = None
        else:
            raise ClaudeGptError("invalid_profile", "선택한 구독 프로필을 다시 인증할 수 없습니다.")
        email_hint = profile.get("email")
    else:
        client_id = OAUTH_DYNAMIC_CLIENT
        id_hint = None
        email_hint = None
    with store.locked():
        host_id = store.host_id(create=True)
    discovery = fetch_discovery(http)
    server, redirect_uri, received = _callback_server()
    attempt = create_authorization_attempt(client_id=client_id, host_id=host_id, redirect_uri=redirect_uri,
                                           existing_id_token=id_hint, login_hint=email_hint)
    url = discovery["authorization_endpoint"] + "?" + urllib.parse.urlencode(attempt["url_params"])
    try:
        if not webbrowser.open(url, new=2, autoraise=True):
            raise ClaudeGptError("browser_unavailable", "기본 브라우저를 열 수 없습니다. 다시 로그인 명령을 실행하세요.")
        server.handle_request()
    finally:
        server.server_close()
    if "url" not in received:
        raise ClaudeGptError("callback_timeout", "10분 안에 ChatGPT 로그인 응답을 받지 못했습니다.")
    return finish_subscription_login(store, http, profile_id=profile_id, attempt=attempt, callback_url=received["url"])


def _billing_confirmation(input_fn: Callable[[str], str] = input) -> bool:
    answer = input_fn("API 키 요청은 OpenAI API 사용량 과금이 발생합니다. 이 과금에 동의합니까? [y/N] ")
    return answer.strip().lower() == "y"


def run_api_key_setup(store: ProfileStore, *, env_name: str | None,
                      input_fn: Callable[[str], str] = input,
                      password_fn: Callable[[str], str] = getpass.getpass) -> dict[str, Any]:
    if not _billing_confirmation(input_fn):
        raise ClaudeGptError("billing_not_confirmed", "API 사용량 과금 동의가 없어 API 키를 저장하지 않았습니다.")
    if env_name is not None:
        if not ENV_NAME_RE.fullmatch(env_name):
            raise ClaudeGptError("invalid_env_name", "환경 변수 이름이 잘못되었습니다.")
        api_key = os.environ.get(env_name)
        if api_key is None:
            raise ClaudeGptError("missing_env_key", "명시한 환경 변수에 API 키가 없습니다.")
    else:
        if password_fn is getpass.getpass and not sys.stdin.isatty():
            raise ClaudeGptError("terminal_required", "API 키는 입력을 가릴 수 있는 로컬 터미널에서 설정하세요.")
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            try:
                api_key = password_fn("OpenAI API 키를 입력하세요: ")
            except getpass.GetPassWarning as error:
                raise ClaudeGptError("terminal_required", "API 키 입력을 가릴 수 없어 설정을 중단했습니다.") from error
    result = create_api_key_profile(store, api_key, confirmed_usage_billing=True)
    return result


def _launch(profile_id: str, claude_args: list[str]) -> int:
    try:
        gateway = importlib.import_module("claude_gpt_gateway")
    except ModuleNotFoundError as error:
        if error.name != "claude_gpt_gateway":
            raise
        raise ClaudeGptError("gateway_not_available", "이 체크아웃에서는 GPT gateway를 사용할 수 없습니다.") from error
    launch = getattr(gateway, "launch", None)
    if not callable(launch):
        raise ClaudeGptError("gateway_not_available", "GPT gateway 시작 기능을 사용할 수 없습니다.")
    return launch(profile_id, claude_args)


def _status(store: ProfileStore, profile_id: str | None) -> dict[str, Any]:
    selected = profile_id or store.active_profile_id()
    if selected is None:
        return {"status": "not_configured"}
    profile = store.read_profile(selected)
    return {"profile_id": selected, "mode": profile.get("mode"), "status": profile.get("status")}


def _read_stdin_request(stream: Any = None) -> Any:
    source = stream or sys.stdin.buffer
    raw = source.read(MAX_REQUEST_BYTES + 1)
    if len(raw) > MAX_REQUEST_BYTES:
        raise ClaudeGptError("request_too_large", "GPT 요청이 허용 크기를 넘었습니다.")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ClaudeGptError("invalid_request", "헬퍼 표준 입력이 올바른 JSON이 아닙니다.") from error


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="claude_gpt.py")
    subparsers = parser.add_subparsers(dest="command", required=True)
    launch_parser = subparsers.add_parser("launch")
    launch_parser.add_argument("--profile", required=True)
    launch_parser.add_argument("claude_args", nargs=argparse.REMAINDER)
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--profile")
    auth_parser = subparsers.add_parser("auth")
    auth_sub = auth_parser.add_subparsers(dest="auth_mode", required=True)
    subscription = auth_sub.add_parser("subscription")
    subscription.add_argument("--profile")
    api_key = auth_sub.add_parser("api-key")
    api_key.add_argument("--from-env")
    request_parser = subparsers.add_parser("request")
    request_parser.add_argument("--protocol-version", type=int, default=PROTOCOL_VERSION)
    logout_parser = subparsers.add_parser("logout")
    logout_parser.add_argument("--profile", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.command == "launch":
        claude_args = args.claude_args[1:] if args.claude_args[:1] == ["--"] else args.claude_args
        return _launch(args.profile, claude_args)
    if args.command == "request":
        if args.protocol_version != PROTOCOL_VERSION:
            raise ClaudeGptError("unsupported_protocol", "지원하지 않는 헬퍼 프로토콜 버전입니다.")
        store = ProfileStore.default()
        http = HttpClient()
        try:
            return execute_request(store, http, _read_stdin_request())
        except ClaudeGptError as error:
            emit_record(protocol_error(error))
            return 1
    store = ProfileStore.default()
    if args.command == "status":
        print(json.dumps(_status(store, args.profile), ensure_ascii=False, separators=(",", ":")))
        return 0
    if args.command == "auth" and args.auth_mode == "api-key":
        result = run_api_key_setup(store, env_name=args.from_env)
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0
    if args.command == "auth" and args.auth_mode == "subscription":
        result = run_subscription_login(store, HttpClient(), profile_id=args.profile)
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0
    if args.command == "logout":
        result = logout_profile(store, HttpClient(), args.profile)
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        if not result["revocation_confirmed"]:
            print("원격 취소를 확인하지 못했습니다. ChatGPT 설정에서 연결을 해제하세요.", file=sys.stderr)
        return 0
    return 2

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ClaudeGptError as error:
        if sys.argv[1:2] == ["request"]:
            emit_record(protocol_error(error))
        else:
            print(error.message, file=sys.stderr)
        raise SystemExit(1)
    except Exception:
        if sys.argv[1:2] == ["request"]:
            emit_record(protocol_error("internal_error"))
        else:
            print("GPT helper failed safely.", file=sys.stderr)
        raise SystemExit(1)
