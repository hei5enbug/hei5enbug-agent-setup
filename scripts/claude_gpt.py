from __future__ import annotations

import argparse
import base64
import contextlib
import datetime as dt
import fcntl
import getpass
import hashlib
import http.server
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
from pathlib import Path
from typing import Any, BinaryIO, Callable, Iterator, Mapping


PROTOCOL_VERSION = 1
PINNED_MODELS = frozenset({"gpt-6.1-sol", "gpt-6-luna"})
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
FUNCTION_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SAFE_CODE_RE = re.compile(r"^[a-z0-9_-]{1,80}$")
SAFE_PROVIDER_ERROR_CODES = frozenset({
    "authentication_error", "context_length_exceeded", "insufficient_quota", "invalid_api_key",
    "invalid_request_error", "model_not_found", "permission_denied", "rate_limit_exceeded",
    "server_error", "unsupported_parameter",
})
JSON_SCHEMA_KEYS = frozenset({
    "type", "properties", "required", "additionalProperties", "items", "enum", "description",
})


class ClaudeGptError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


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
            raise _http_error(response.status, body)
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
    return code if isinstance(code, str) and code in SAFE_PROVIDER_ERROR_CODES else None


def _http_error(status: int, body: bytes) -> ClaudeGptError:
    code = _error_code_from_body(body)
    suffix = f" ({code})" if code else ""
    return ClaudeGptError("http_error", f"OpenAI 서비스 요청이 HTTP {status}로 실패했습니다{suffix}.")


def _json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ClaudeGptError("invalid_json", "요청에 JSON으로 전달할 수 없는 값이 있습니다.") from error


def emit_record(value: Mapping[str, Any], stream: Any = None) -> None:
    target = stream or sys.stdout
    target.write(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")
    target.flush()


def protocol_error(code: str) -> dict[str, Any]:
    safe = code if SAFE_CODE_RE.fullmatch(code) else "request_failed"
    return {"protocol_version": PROTOCOL_VERSION, "type": "error", "code": safe}


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

    def remove_credentials(self, profile_id: str) -> None:
        path = self.profile_dir(profile_id) / "credentials.json"
        if path.exists() or path.is_symlink():
            info = path.lstat()
            if (stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or
                    info.st_uid != _current_uid() or info.st_mode & 0o077):
                raise ClaudeGptError("unsafe_permissions", "기존 인증 정보 파일이 안전하지 않습니다.")
        with contextlib.suppress(FileNotFoundError):
            path.unlink()


def _validate_json_schema(schema: Any, path: str = "input_schema") -> None:
    if not isinstance(schema, dict) or set(schema) - JSON_SCHEMA_KEYS:
        raise ClaudeGptError("unsupported_schema", f"지원하지 않는 도구 입력 스키마입니다: {path}")
    schema_type = schema.get("type")
    if schema_type not in {"object", "string", "number", "integer", "boolean", "array", "null"}:
        raise ClaudeGptError("unsupported_schema", f"지원하지 않는 도구 입력 스키마입니다: {path}")
    if "description" in schema and not isinstance(schema["description"], str):
        raise ClaudeGptError("unsupported_schema", f"지원하지 않는 도구 입력 스키마입니다: {path}")
    if schema_type == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        extra = schema.get("additionalProperties", False)
        if (not isinstance(properties, dict) or not all(isinstance(key, str) for key in properties) or
                not isinstance(required, list) or any(not isinstance(item, str) for item in required) or
                len(required) != len(set(required)) or not set(required).issubset(properties) or
                not isinstance(extra, bool)):
            raise ClaudeGptError("unsupported_schema", f"지원하지 않는 도구 입력 스키마입니다: {path}")
        for name, child in properties.items():
            _validate_json_schema(child, f"{path}.{name}")
    elif schema_type == "array":
        if "items" not in schema:
            raise ClaudeGptError("unsupported_schema", f"지원하지 않는 도구 입력 스키마입니다: {path}")
        _validate_json_schema(schema["items"], f"{path}[]")
    elif "properties" in schema or "required" in schema or "additionalProperties" in schema or "items" in schema:
        raise ClaudeGptError("unsupported_schema", f"지원하지 않는 도구 입력 스키마입니다: {path}")
    if "enum" in schema:
        values = schema["enum"]
        if not isinstance(values, list) or not values or len(_json_bytes(values)) > 65536:
            raise ClaudeGptError("unsupported_schema", f"지원하지 않는 도구 입력 스키마입니다: {path}")


def _validate_schema_value(value: Any, schema: dict[str, Any], path: str) -> None:
    kind = schema["type"]
    valid = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }[kind]
    if not valid or ("enum" in schema and value not in schema["enum"]):
        raise ClaudeGptError("invalid_tool_call", f"도구 입력이 제공된 스키마와 일치하지 않습니다: {path}")
    if kind == "object":
        properties = schema.get("properties", {})
        missing = set(schema.get("required", [])) - set(value)
        extra = set(value) - set(properties)
        if missing or (schema.get("additionalProperties", False) is False and extra):
            raise ClaudeGptError("invalid_tool_call", f"도구 입력이 제공된 스키마와 일치하지 않습니다: {path}")
        for name, child in value.items():
            if name in properties:
                _validate_schema_value(child, properties[name], f"{path}.{name}")
    elif kind == "array":
        for index, child in enumerate(value):
            _validate_schema_value(child, schema["items"], f"{path}[{index}]")


def validate_protocol_request(value: Any) -> dict[str, Any]:
    fields = {
        "protocol_version", "request_id", "session_id", "turn_id", "step_id", "model", "effort",
        "profile_id", "system", "developer", "history", "tools",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ClaudeGptError("invalid_request", "요청 버전 또는 필수 필드가 잘못되었습니다.")
    if value["protocol_version"] != PROTOCOL_VERSION:
        raise ClaudeGptError("unsupported_protocol", "지원하지 않는 요청 프로토콜 버전입니다.")
    for field in ("request_id", "session_id", "turn_id", "step_id"):
        if not isinstance(value[field], str) or not SAFE_ID_RE.fullmatch(value[field]):
            raise ClaudeGptError("invalid_request", f"요청 식별자가 잘못되었습니다: {field}")
    if value["model"] not in PINNED_MODELS:
        raise ClaudeGptError("unsupported_model", "지원하지 않는 GPT 모델 ID입니다.")
    effort = value["effort"]
    if effort is not None and (not isinstance(effort, str) or effort not in SUPPORTED_EFFORTS):
        raise ClaudeGptError("unsupported_effort", "선택한 GPT 모델이 지원하지 않는 추론 강도입니다.")
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
            if item["name"] != expected["name"] or arguments != expected["arguments"]:
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
        text_blocks: list[dict[str, str]] = []

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
                if block.get("is_error", False):
                    raise ClaudeGptError("unsupported_tool_result", "실패한 도구 결과 형식은 아직 지원하지 않습니다.")
                output = _input_text(block.get("content"))
                seen_results.add(call_id)
                flush_text()
                mapped.append({"type": "function_call_output", "call_id": call_id, "output": output})
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
    session_id = request["session_id"]
    state = store.read_session_state(profile_id, session_id)
    raw_groups = state["groups"]
    # map_history prunes state that is no longer represented in host history.
    schemas = {tool["name"]: tool["input_schema"] for tool in request["tools"]}
    _, retained = map_history(request["history"], schemas, raw_groups)
    def save(groups: list[dict[str, Any]]) -> None:
        with store.locked():
            if store.read_profile(profile_id).get("status") != "connected":
                raise ClaudeGptError("profile_signed_out", "요청 도중 선택한 프로필이 로그아웃되었습니다.")
            store.write_session_state(profile_id, session_id, groups)
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
    raise ClaudeGptError("unsupported_response", f"Responses API가 지원하지 않는 출력 항목을 반환했습니다: {kind}")


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


def stream_responses(http: HttpClient, *, payload: dict[str, Any], api_key: str,
                     expected_model: str, requested_effort: str | None,
                     tool_schemas: dict[str, dict[str, Any]], prior_call_ids: set[str],
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
        raise _http_error(response.status, response.body)
    if response.stream is None:
        raise ClaudeGptError("invalid_stream", "Responses API가 스트리밍 연결을 열지 않았습니다.")
    output = stream_out or sys.stdout
    streamed_text = ""
    terminal: dict[str, Any] | None = None
    completion: dict[str, Any] | None = None
    try:
        with response.stream as stream:
            for event in _sse_events(stream):
                kind = event["type"]
                if terminal is not None:
                    raise ClaudeGptError("event_after_terminal", "Responses API 종료 이벤트 뒤에 데이터가 있습니다.")
                if kind in {"response.output_text.delta", "response.refusal.delta"}:
                    delta = event.get("delta")
                    if not isinstance(delta, str):
                        raise ClaudeGptError("invalid_stream", "Responses API 텍스트 이벤트가 잘못되었습니다.")
                    if delta:
                        streamed_text += delta
                        emit_record({"protocol_version": PROTOCOL_VERSION, "type": "text_delta", "text": delta}, output)
                    continue
                if kind == "response.completed":
                    response_value = event.get("response")
                    completion, _ = _extract_completed(response_value, expected_model=expected_model,
                                                        tool_schemas=tool_schemas, prior_ids=prior_call_ids)
                    reported_effort = completion["provider_reported_effort"]
                    if requested_effort is not None and reported_effort is not None and reported_effort != requested_effort:
                        raise ClaudeGptError("effort_mismatch", "Responses API가 요청한 reasoning 수준과 다른 수준을 반환했습니다.")
                    _validate_text_from_completion(completion, streamed_text)
                    _save_provider_state(completion, prior_groups or [], store_state)
                    terminal = {
                        "protocol_version": PROTOCOL_VERSION,
                        "type": "completed",
                        "response_id": completion["response_id"],
                        "model": completion["model"],
                        "usage": completion["usage"],
                        "tool_calls": completion["tool_calls"],
                        "provider_reported_effort": completion["provider_reported_effort"],
                    }
                    emit_record(terminal, output)
                    continue
                if kind in {"response.failed", "response.incomplete", "error"}:
                    terminal = {"protocol_version": PROTOCOL_VERSION, "type": "error", "code": _failure_code(event)}
                    raise ClaudeGptError(terminal["code"], "Responses API 응답이 완료되지 않았습니다.")
        if terminal is None or completion is None:
            raise ClaudeGptError("truncated_stream", "Responses API 스트림에 완료 이벤트가 없습니다.")
    except ClaudeGptError:
        raise
    except (OSError, TimeoutError, UnicodeError) as error:
        raise ClaudeGptError("stream_interrupted", "Responses API 스트림이 중단되었습니다.") from error
    return 0


def _failure_code(event: Mapping[str, Any]) -> str:
    response = event.get("response")
    error = response.get("error") if isinstance(response, dict) else event.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, str) and code in SAFE_PROVIDER_ERROR_CODES else "provider_failed"


def _save_provider_state(completion: Mapping[str, Any], prior_groups: list[dict[str, Any]],
                         save: Callable[[list[dict[str, Any]]], None] | None) -> None:
    if save is None:
        return
    groups = list(prior_groups)
    group = _new_state_group(completion)
    if group is not None:
        groups.append(group)
    save(groups)


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


def _launch_refusal() -> None:
    raise ClaudeGptError(
        "unsupported_host",
        "GPT 경로가 비활성화되었습니다. 호스트에 완전한 도구 입력 스키마가 없고 재개 후 고정된 시스템 프롬프트 접근도 미검증이므로 GPT 모델 선택기를 만들지 않았습니다.",
    )


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
    subparsers.add_parser("launch")
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
        _launch_refusal()
    if args.command == "request":
        if args.protocol_version != PROTOCOL_VERSION:
            raise ClaudeGptError("unsupported_protocol", "지원하지 않는 헬퍼 프로토콜 버전입니다.")
        store = ProfileStore.default()
        http = HttpClient()
        try:
            return execute_request(store, http, _read_stdin_request())
        except ClaudeGptError as error:
            emit_record(protocol_error(error.code))
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
            emit_record(protocol_error(error.code))
        else:
            print(error.message, file=sys.stderr)
        raise SystemExit(1)
    except Exception:
        if sys.argv[1:2] == ["request"]:
            emit_record(protocol_error("internal_error"))
        else:
            print("GPT helper failed safely.", file=sys.stderr)
        raise SystemExit(1)
