"""Loopback Anthropic Messages gateway for the claude-gpt helper."""

from __future__ import annotations

import contextlib
import copy
import http.client
import http.server
import json
import math
import os
import queue
import random
import re
import select
import secrets
import socket
import ssl
import stat
import subprocess
import sys
import threading
import time
import tomllib
import urllib.parse
import urllib.request
import uuid
from http.client import IncompleteRead
from pathlib import Path
from typing import Any, Callable, Mapping


def _load_helper():
    import importlib
    import importlib.util

    for name in ("claude_gpt", "claude_gpt_helper"):
        found = sys.modules.get(name)
        if found is not None:
            return found
    try:
        return importlib.import_module("claude_gpt")
    except ModuleNotFoundError as error:
        if error.name != "claude_gpt":
            raise
    path = Path(__file__).with_name("claude_gpt.py")
    spec = importlib.util.spec_from_file_location("claude_gpt_gateway_helper", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("helper unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


helper = _load_helper()

PLUGIN_ID = "hei5enbug-agent-setup@hei5enbug"
CLAUDE_ORIGIN = "https://api.anthropic.com"
RESPONSES_URL = helper.OPENAI_RESPONSES_URL
MAX_BODY_BYTES = helper.MAX_REQUEST_BYTES
MAX_LOG_BYTES = 1_000_000
CALL_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
FORBIDDEN_ENV = frozenset({
    "ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
})
RETRY_PROVIDER_CODES = frozenset({
    "rate_limit_exceeded", "server_error", "subscription_sharing_usage_unavailable",
    "subscription_sharing_user_unavailable",
})
TERMINAL_AUTH_CODES = frozenset({
    "authentication_error", "invalid_api_key", "invalid_profile", "profile_signed_out",
    "missing_direct_scope", "missing_scope", "invalid_id_token", "invalid_token_response",
    "authorization_failed", "access_denied", "terminal_refresh_error",
})
TERMINAL_PERMISSION_CODES = frozenset({
    "permission_denied", "subscription_sharing_user_not_eligible",
    "chatpass_v2_scope_not_authorized", "chatpass_v2_invalid_authorization_context",
    "account_mismatch", "billing_not_confirmed",
})
TERMINAL_QUOTA_CODES = frozenset({"insufficient_quota", "subscription_sharing_usage_limit_exceeded"})
RECOVERABLE_HTTP = frozenset({408, 500, 502, 503, 504})
HOP_HEADERS = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
    "trailer", "transfer-encoding", "upgrade", "proxy-connection",
})
RECOVERY_INSTRUCTION = (
    "Gateway recovery: continue at the end of the assistant text already present in the conversation. "
    "Do not repeat text already delivered to the user, and do not repeat or redo completed tool actions."
)


class GatewayRequestError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class ResponseSink:
    """Small response interface shared by the HTTP handler and in-process tests."""

    def start_response(self, status: int, headers: list[tuple[str, str]]) -> None:
        raise NotImplementedError

    def write(self, data: bytes) -> None:
        raise NotImplementedError


class GatewayRequestBudget:
    """Optional shared limit across gateway requests; deadlines use monotonic time."""

    def __init__(self, *, max_attempts: int | None = None, deadline: float | None = None):
        if max_attempts is not None and (not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or max_attempts < 0):
            raise ValueError("max_attempts must be a nonnegative integer")
        deadline_value = None
        if deadline is not None:
            if not isinstance(deadline, (int, float)) or isinstance(deadline, bool):
                raise ValueError("deadline must be monotonic seconds")
            try:
                deadline_value = float(deadline)
            except (OverflowError, ValueError):
                raise ValueError("deadline must be monotonic seconds") from None
            if not math.isfinite(deadline_value):
                raise ValueError("deadline must be monotonic seconds")
        self.remaining_attempts = max_attempts
        self.deadline = deadline_value
        self._lock = threading.Lock()

    def reserve_attempt(self, now: float) -> bool:
        with self._lock:
            if self.deadline is not None and now >= self.deadline:
                return False
            if self.remaining_attempts is not None:
                if self.remaining_attempts <= 0:
                    return False
                self.remaining_attempts -= 1
            return True

    def has_attempt(self) -> bool:
        with self._lock:
            return self.remaining_attempts is None or self.remaining_attempts > 0

    def deadline_reached(self, now: float) -> bool:
        return self.deadline is not None and now >= self.deadline


class _ManagedStream:
    def __init__(self, stream: Any, *, on_close: Callable[[], None] | None = None):
        self.stream = stream
        self.on_close = on_close
        self._closed = False
        self._lock = threading.Lock()

    def __enter__(self):
        enter = getattr(self.stream, "__enter__", None)
        if callable(enter):
            enter()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        exit_method = getattr(self.stream, "__exit__", None)
        if callable(exit_method):
            return exit_method(exc_type, exc, tb)
        return False

    def readline(self, size: int = -1):
        return self.stream.readline(size)

    def read(self, size: int = -1):
        return self.stream.read(size)

    def read1(self, size: int = -1):
        read_one = getattr(self.stream, "read1", None)
        return read_one(size) if callable(read_one) else self.stream.read(size)

    def _shutdown_socket(self) -> None:
        response = self.stream
        fp = getattr(response, "fp", None)
        raw = getattr(fp, "raw", None)
        sock = getattr(raw, "_sock", None)
        if sock is None:
            sock = getattr(response, "_sock", None)
        if sock is not None:
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)

    def cancel(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        # Shutdown the socket before closing a buffered HTTPResponse.  This
        # interrupts a blocked read without waiting for the buffered reader.
        self._shutdown_socket()
        with contextlib.suppress(Exception):
            self.stream.close()
        if self.on_close is not None:
            with contextlib.suppress(Exception):
                self.on_close()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        with contextlib.suppress(Exception):
            self.stream.close()
        if self.on_close is not None:
            with contextlib.suppress(Exception):
                self.on_close()


class _OwnedHttpsConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, *, read_timeout: float | None, connect_timeout: float,
                 socket_owner: "_DirectHttpClient"):
        super().__init__(host, timeout=connect_timeout, context=ssl.create_default_context())
        self.read_timeout = read_timeout
        self.connect_timeout = connect_timeout
        self.socket_owner = socket_owner

    def connect(self) -> None:
        raw = socket.create_connection((self.host, self.port or 443), self.connect_timeout)
        self.socket_owner._set_socket(raw)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
            self.socket_owner._set_socket(self.sock)
            self.sock.settimeout(self.read_timeout)
        except Exception:
            with contextlib.suppress(OSError):
                raw.close()
            self.socket_owner._set_socket(None)
            raise


class _DirectHttpClient:
    """Minimal direct HTTPS opener with an owned socket for active cancellation."""

    def __init__(self, *, read_timeout: float | None, connect_timeout: float = 15.0):
        self.read_timeout = read_timeout
        self.connect_timeout = connect_timeout
        self._socket: Any = None
        self._lock = threading.Lock()
        self._cancelled = False

    def _set_socket(self, value: Any) -> None:
        with self._lock:
            if self._cancelled and value is not None:
                with contextlib.suppress(OSError):
                    value.shutdown(socket.SHUT_RDWR)
                with contextlib.suppress(OSError):
                    value.close()
            self._socket = value

    def open(self, request: Any):
        parsed = urllib.parse.urlsplit(request.full_url)
        if parsed.scheme != "https" or parsed.hostname not in {
                "api.openai.com", "api.anthropic.com", "auth.openai.com"}:
            raise helper.ClaudeGptError("invalid_upstream", "The gateway upstream destination is not allowed.")
        if self._cancelled:
            raise helper.ClaudeGptError("gateway_cancelled", "Gateway request was cancelled.")
        connection = _OwnedHttpsConnection(
            parsed.hostname, read_timeout=self.read_timeout,
            connect_timeout=self.connect_timeout, socket_owner=self,
        )
        try:
            target = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
            connection.request(request.get_method(), target, body=request.data,
                               headers=dict(request.header_items()))
            response = connection.getresponse()
            headers = {name: value for name, value in response.getheaders()}
            # Claude pass-through must preserve error and redirect bodies as
            # streams. Only OpenAI error bodies are bounded and materialized.
            if not 200 <= response.status < 300 and parsed.hostname != "api.anthropic.com":
                body = response.read(MAX_BODY_BYTES + 1)
                response.close()
                connection.close()
                self._set_socket(None)
                return helper.HttpResponse(response.status, headers, body[:MAX_BODY_BYTES])
            return helper.HttpResponse(response.status, headers, b"", response)
        except (OSError, TimeoutError, ssl.SSLError, http.client.HTTPException) as error:
            self.close()
            if self._cancelled:
                raise helper.ClaudeGptError("gateway_cancelled", "Gateway request was cancelled.") from error
            raise helper.ClaudeGptError("network_error", "Provider transport failed safely.") from error

    def json(self, url: str, **kwargs):
        request = urllib.request.Request(
            url, data=kwargs.get("data"), headers=dict(kwargs.get("headers") or {}),
            method=kwargs.get("method", "GET"),
        )
        response = self.open(request)
        if response.status < 200 or response.status >= 300:
            raise helper._http_error(response.status, response.body, response.headers)
        body = response.body
        if response.stream is not None:
            try:
                with response.stream as stream:
                    body = stream.read(MAX_BODY_BYTES + 1)
            finally:
                self.close()
        if len(body) > MAX_BODY_BYTES:
            raise helper.ClaudeGptError("response_too_large", "Authentication response exceeded the helper limit.")
        try:
            value = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise helper.ClaudeGptError("invalid_response", "Authentication response was invalid.") from error
        if not isinstance(value, dict):
            raise helper.ClaudeGptError("invalid_response", "Authentication response was invalid.")
        return value

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            active = self._socket
        if active is not None:
            with contextlib.suppress(OSError):
                active.shutdown(socket.SHUT_RDWR)
            with contextlib.suppress(OSError):
                active.close()

    def close(self) -> None:
        with self._lock:
            active = self._socket
            self._socket = None
        if active is not None:
            with contextlib.suppress(OSError):
                active.close()


class _ManagedHttpClient:
    def __init__(self, client: Any, *, cancel_event: threading.Event | None = None,
                 on_response_open: Callable[[], None] | None = None):
        self.client = client
        self.cancel_event = cancel_event or threading.Event()
        self.on_response_open = on_response_open
        self._active: _ManagedStream | None = None
        self._lock = threading.Lock()
        self.request_id: str | None = None

    def open(self, request: Any):
        if self.cancel_event.is_set():
            raise helper.ClaudeGptError("gateway_cancelled", "Gateway request was cancelled.")
        response = self.client.open(request)
        self.request_id = helper._response_request_id(response.headers)
        stream = getattr(response, "stream", None)
        close_client = getattr(self.client, "close", None)
        managed = _ManagedStream(stream, on_close=close_client if callable(close_client) else None) if stream is not None else None
        if managed is not None:
            with self._lock:
                self._active = managed
        if (getattr(request, "full_url", None) == RESPONSES_URL and managed is not None and
                200 <= response.status < 300):
            if self.cancel_event.is_set():
                self.cancel()
                raise helper.ClaudeGptError("gateway_cancelled", "Gateway request was cancelled.")
            if self.on_response_open is not None:
                self.on_response_open()
        if managed is None:
            return response
        return helper.HttpResponse(response.status, response.headers, response.body, managed)

    def json(self, url: str, **kwargs):
        if self.cancel_event.is_set():
            raise helper.ClaudeGptError("gateway_cancelled", "Gateway request was cancelled.")
        try:
            result = self.client.json(url, **kwargs)
        except helper.ClaudeGptError as error:
            if self.cancel_event.is_set() or error.code == "gateway_cancelled":
                raise helper.ClaudeGptError("gateway_cancelled", "Gateway request was cancelled.") from None
            raise helper.ClaudeGptError(
                "terminal_refresh_error", "The selected GPT profile could not refresh its authorization.",
                http_status=error.http_status, provider_code=error.provider_code,
                request_id=error.request_id, retry_after=error.retry_after,
            ) from error
        except Exception:
            if self.cancel_event.is_set():
                raise helper.ClaudeGptError("gateway_cancelled", "Gateway request was cancelled.") from None
            raise helper.ClaudeGptError(
                "terminal_refresh_error", "The selected GPT profile could not refresh its authorization.",
            ) from None
        if self.cancel_event.is_set():
            raise helper.ClaudeGptError("gateway_cancelled", "Gateway request was cancelled.")
        return result

    def cancel(self) -> None:
        self.cancel_event.set()
        cancel_client = getattr(self.client, "cancel", None)
        if callable(cancel_client):
            with contextlib.suppress(Exception):
                cancel_client()
        with self._lock:
            active = self._active
        if active is not None:
            active.cancel()


class _RecordQueueWriter:
    def __init__(self, target: queue.Queue):
        self.target = target
        self.pending = ""

    def write(self, value: str) -> int:
        self.pending += value
        while "\n" in self.pending:
            line, self.pending = self.pending.split("\n", 1)
            if line:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    self.target.put(("error", helper.ClaudeGptError("invalid_helper_record", "Gateway helper output was invalid.")))
                else:
                    self.target.put(("record", record))
        return len(value)

    def flush(self) -> None:
        return None


class _Attempt:
    def __init__(self, app: "GatewayApplication", request: dict[str, Any], external_cancel: threading.Event):
        self.app = app
        self.request = request
        self.external_cancel = external_cancel
        self.cancel_event = threading.Event()
        self.opened = threading.Event()
        self.items: queue.Queue = queue.Queue()
        self.http: _ManagedHttpClient | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        client = self.app.openai_http_factory()
        self.http = _ManagedHttpClient(client, cancel_event=self.cancel_event, on_response_open=self.opened.set)
        writer = _RecordQueueWriter(self.items)

        def run() -> None:
            try:
                result = helper.execute_request(
                    _CallIdValidatingStore(self.app.store), self.http, self.request, stream_out=writer,
                )
            except helper.ClaudeGptError as error:
                self.items.put(("error", error))
            except Exception:
                self.items.put(("error", helper.ClaudeGptError("internal_error", "Gateway helper failed safely.")))
            else:
                self.items.put(("success", result))

        self.thread = threading.Thread(target=run, name="claude-gpt-provider", daemon=True)
        self.thread.start()

    def cancel(self) -> None:
        self.cancel_event.set()
        if self.http is not None:
            self.http.cancel()


class PrivateGatewayLog:
    def __init__(self, store: Any, profile_id: str):
        self.path = store.profile_dir(profile_id) / "logs" / "gateway.log"
        self._lock = threading.Lock()

    def _append(self, value: Mapping[str, Any]) -> None:
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            info = self.path.parent.lstat()
            if (stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or
                    info.st_uid != os.getuid() or info.st_mode & 0o077):
                return
            encoded = json.dumps(dict(value), ensure_ascii=True, separators=(",", ":")).encode("ascii") + b"\n"
            with self._lock:
                if self.path.exists() and self.path.stat().st_size + len(encoded) > MAX_LOG_BYTES:
                    backup = self.path.with_name("gateway.log.1")
                    with contextlib.suppress(FileNotFoundError):
                        backup.unlink()
                    self.path.replace(backup)
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600)
                try:
                    os.fchmod(fd, 0o600)
                    os.write(fd, encoded)
                finally:
                    os.close(fd)
        except (OSError, ValueError, TypeError):
            return

    def access(self, *, oauth_capability: bool) -> None:
        self._append({"kind": "claude_request", "anthropic_oauth_capability": bool(oauth_capability)})

    def attempt(self, *, number: int, outcome: str, error: Any = None, record: Any = None) -> None:
        code = getattr(error, "code", None) if error is not None else "completed"
        if not isinstance(code, str) or not helper.SAFE_CODE_RE.fullmatch(code):
            code = "request_failed"
        provider_code = getattr(error, "provider_code", None) if error is not None else None
        if not isinstance(provider_code, str) or provider_code not in helper.SAFE_PROVIDER_ERROR_CODES:
            provider_code = None
        http_status = getattr(error, "http_status", None) if error is not None else None
        if not isinstance(http_status, int) or isinstance(http_status, bool) or not 100 <= http_status <= 599:
            http_status = None
        request_id = getattr(error, "request_id", None) if error is not None else None
        if request_id is None and isinstance(record, Mapping):
            request_id = record.get("request_id")
        if not isinstance(request_id, str) or not helper.SAFE_REQUEST_ID_RE.fullmatch(request_id):
            request_id = None
        usage_source = getattr(error, "provider_usage", None) if error is not None else None
        if isinstance(record, Mapping):
            usage_source = record.get("usage")
        usage: dict[str, int] | str = "unknown"
        if isinstance(usage_source, Mapping):
            if "usage" in usage_source and isinstance(usage_source.get("usage"), Mapping):
                usage_source = usage_source["usage"]
            fields = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens")
            candidate = {field: usage_source.get(field) for field in fields}
            if all(isinstance(value, int) and not isinstance(value, bool) and value >= 0
                   for value in candidate.values()):
                usage = candidate
        self._append({
            "kind": "gpt_attempt", "attempt": max(1, int(number)), "outcome": outcome,
            "code": code, "provider_code": provider_code, "http_status": http_status,
            "request_id": request_id, "usage": usage,
        })


class GatewayApplication:
    """In-process router; upstream clients and clocks can be replaced by fakes."""

    def __init__(self, profile_id: str, secret: str, *, store: Any = None,
                 openai_http_factory: Any = None, claude_http_factory: Any = None,
                 logger: Any = None, clock: Callable[[], float] = time.monotonic,
                 wait: Callable[[threading.Event, float], bool] | None = None,
                 jitter: Callable[[], float] | None = None,
                 max_attempts: int = 3, recovery_seconds: float = 60.0,
                 ping_interval: float = 10.0,
                 request_budget: GatewayRequestBudget | None = None):
        if not isinstance(secret, str) or not secret or "/" in secret:
            raise ValueError("invalid secret path")
        self.profile_id = profile_id
        self.secret = secret
        self.store = store or helper.ProfileStore.default()
        self.openai_http_factory = _client_factory(openai_http_factory, timeout=30.0)
        self.claude_http_factory = _client_factory(claude_http_factory, timeout=None)
        self.logger = logger or PrivateGatewayLog(self.store, profile_id)
        self.clock = clock
        self.wait = wait or (lambda event, seconds: event.wait(seconds))
        self.jitter = jitter or (lambda: random.uniform(0.0, 0.5))
        self.max_attempts = max(1, min(int(max_attempts), 3))
        self.recovery_seconds = max(0.0, float(recovery_seconds))
        self.ping_interval = max(0.1, float(ping_interval))
        self.request_budget = request_budget
        self._active_requests: set[threading.Event] = set()
        self._active_lock = threading.Lock()

    def handle_request(self, method: str, target: str, headers: Mapping[str, str], body: bytes,
                       sink: ResponseSink, *, cancel_event: threading.Event | None = None) -> None:
        cancelled = cancel_event or threading.Event()
        with self._active_lock:
            self._active_requests.add(cancelled)
        try:
            self._handle_request(method, target, headers, body, sink, cancelled)
        finally:
            with self._active_lock:
                self._active_requests.discard(cancelled)

    def cancel_active_requests(self) -> None:
        with self._active_lock:
            active = list(self._active_requests)
        for event in active:
            event.set()

    def _handle_request(self, method: str, target: str, headers: Mapping[str, str], body: bytes,
                        sink: ResponseSink, cancelled: threading.Event) -> None:
        path, separator, query = target.partition("?")
        prefix = "/" + self.secret
        if path != prefix and not path.startswith(prefix + "/"):
            self._send_error(sink, 404, "not_found_error", "Not found.", "not_found")
            return
        if not isinstance(body, bytes):
            self._send_error(sink, 400, "invalid_request_error", "Request body is invalid.", "invalid_request")
            return
        forwarded_path = path[len(prefix):] or "/"
        if not forwarded_path.startswith("/"):
            forwarded_path = "/" + forwarded_path
        if separator:
            forwarded_path += "?" + query

        parsed: Any = None
        if method.upper() == "POST" and forwarded_path.split("?", 1)[0] in {
                "/v1/messages", "/v1/messages/count_tokens"}:
            try:
                parsed = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                parsed = None
        gpt_model = parsed.get("model") if isinstance(parsed, dict) else None
        is_gpt = isinstance(gpt_model, str) and gpt_model in helper.PINNED_MODELS
        if (method.upper() == "POST" and forwarded_path.split("?", 1)[0] == "/v1/messages/count_tokens" and
                is_gpt):
            self._send_error(sink, 404, "not_found_error", "Token counting is unavailable for GPT models.", "count_tokens_unsupported")
            return
        if (method.upper() == "POST" and forwarded_path.split("?", 1)[0] == "/v1/messages" and
                is_gpt):
            if len(body) > MAX_BODY_BYTES:
                self._send_error(sink, 413, "invalid_request_error", "Request body exceeds the gateway limit.", "request_too_large")
                return
            try:
                request = translate_messages_request(parsed, self.profile_id)
            except helper.ClaudeGptError as error:
                self._send_helper_error(sink, error)
                return
            except GatewayRequestError as error:
                self._send_error(sink, 400, "invalid_request_error", error.message, error.code)
                return
            self._handle_gpt(request, sink, cancelled)
            return
        self._handle_claude(method, forwarded_path, headers, body, sink, cancelled)

    def _handle_claude(self, method: str, path: str, headers: Mapping[str, str], body: bytes,
                       sink: ResponseSink, cancel_event: threading.Event) -> None:
        client = _ManagedHttpClient(self.claude_http_factory(), cancel_event=cancel_event)
        watcher_done = threading.Event()

        def stop_upstream_when_cancelled() -> None:
            while not watcher_done.wait(0.05):
                if cancel_event.is_set():
                    client.cancel()
                    return
        oauth_capability = any(name.lower() == "anthropic-beta" and
                               "oauth" in str(value).lower() for name, value in headers.items())
        access = getattr(self.logger, "access", None)
        if callable(access):
            access(oauth_capability=oauth_capability)
        request_headers = _strip_hop_headers(headers, drop_host=True)
        url = CLAUDE_ORIGIN + path
        request = urllib.request.Request(url, data=body if body else None, headers=dict(request_headers), method=method)
        watcher = threading.Thread(target=stop_upstream_when_cancelled, name="claude-gateway-cancel", daemon=True)
        watcher.start()
        try:
            response = client.open(request)
            if cancel_event.is_set():
                client.cancel()
                return
            output_headers = _strip_hop_headers(response.headers)
            sink.start_response(response.status, output_headers)
            if response.stream is None:
                if method.upper() != "HEAD" and response.body:
                    sink.write(response.body)
                return
            with response.stream as stream:
                while method.upper() != "HEAD" and not cancel_event.is_set():
                    read_chunk = getattr(stream, "read1", None)
                    chunk = read_chunk(64 * 1024) if callable(read_chunk) else stream.read(64 * 1024)
                    if not chunk:
                        break
                    sink.write(chunk)
        except (BrokenPipeError, ConnectionResetError, OSError):
            cancel_event.set()
            client.cancel()
        except helper.ClaudeGptError:
            started = _response_started(sink)
            if not cancel_event.is_set() and not started:
                _send_plain_error(sink, 502, "api_error", "The Claude upstream could not be reached.",
                                  "claude_transport_error")
            client.cancel()
        except Exception:
            started = _response_started(sink)
            if not cancel_event.is_set() and not started:
                _send_plain_error(sink, 502, "api_error", "The Claude upstream could not be reached.",
                                  "claude_transport_error")
            client.cancel()
        finally:
            watcher_done.set()
            watcher.join(timeout=0.1)

    def _handle_gpt(self, request: dict[str, Any], sink: ResponseSink,
                    cancel_event: threading.Event) -> None:
        visible_text = ""
        stream_started = False
        text_block_started = False
        block_index = 0
        ping_due: float | None = None
        recovery_deadline: float | None = None
        terminal: helper.ClaudeGptError | None = None

        for number in range(1, self.max_attempts + 1):
            if cancel_event.is_set():
                return
            if self.request_budget is not None and not self.request_budget.reserve_attempt(self.clock()):
                terminal = _request_budget_error()
                break
            attempt_request = copy.deepcopy(request)
            if visible_text:
                attempt_request["history"].append({
                    "role": "assistant", "content": [{"type": "text", "text": visible_text}],
                })
                attempt_request["system"] = _append_recovery_instruction(attempt_request["system"])
            attempt = _Attempt(self, attempt_request, cancel_event)
            try:
                attempt.start()
            except Exception:
                terminal = helper.ClaudeGptError("internal_error", "Gateway provider attempt failed safely.")
                self._log_attempt(number, "failed", error=terminal)
                break

            # Do not commit downstream headers until a real provider stream has
            # opened. Pre-header failures can then be retried or returned as JSON.
            initial_result = None
            pending_result = None
            while not attempt.opened.is_set():
                if cancel_event.is_set():
                    attempt.cancel()
                    self._log_attempt(number, "cancelled", error=_cancelled_error())
                    return
                active_deadline = self._active_deadline(recovery_deadline)
                if active_deadline is not None and self.clock() >= active_deadline:
                    attempt.cancel()
                    terminal = self._deadline_error()
                    break
                try:
                    initial_result = attempt.items.get(timeout=0.05)
                except queue.Empty:
                    if attempt.thread is not None and not attempt.thread.is_alive():
                        initial_result = ("error", helper.ClaudeGptError("internal_error", "Gateway provider worker stopped."))
                        break
                    if stream_started and ping_due is not None and self.clock() >= ping_due:
                        try:
                            self._write_event(sink, "ping", {"type": "ping"})
                        except OSError:
                            cancel_event.set()
                            attempt.cancel()
                            self._log_attempt(number, "cancelled", error=_cancelled_error())
                            return
                        ping_due = self.clock() + self.ping_interval
                    continue
                if attempt.opened.is_set():
                    pending_result = initial_result
                    break
                if initial_result[0] in {"error", "success"}:
                    break
                # Record output before successful open should never occur, but do not leak it.
                initial_result = ("error", helper.ClaudeGptError("invalid_helper_record", "Provider output preceded stream opening."))
                break
            if terminal is not None:
                self._log_attempt(number, "terminal", error=terminal)
                break
            if not attempt.opened.is_set():
                if initial_result is None:
                    continue
                if initial_result[0] == "success":
                    error = helper.ClaudeGptError("invalid_stream", "Provider stream did not open.")
                else:
                    error = initial_result[1]
                self._log_attempt(number, "failed", error=error)
                delay, recovery_deadline, budget_limited = self._recovery_delay(
                    error, number, recovery_deadline,
                )
                if delay is None:
                    terminal = (_request_budget_error() if budget_limited else
                                _retry_exhausted() if _is_recoverable(error) else error)
                    break
                waited = self._wait_retry(delay, recovery_deadline, cancel_event, sink,
                                          stream_started, ping_due)
                if waited == "cancelled":
                    return
                if waited == "deadline":
                    terminal = self._deadline_error()
                    break
                continue

            if not stream_started:
                try:
                    self._start_stream(sink, request["model"])
                except (BrokenPipeError, ConnectionResetError, OSError):
                    cancel_event.set()
                    attempt.cancel()
                    self._log_attempt(number, "cancelled", error=_cancelled_error())
                    return
                stream_started = True
                ping_due = self.clock() + self.ping_interval

            failure: helper.ClaudeGptError | None = None
            completed_record: dict[str, Any] | None = None
            while True:
                if cancel_event.is_set():
                    attempt.cancel()
                    self._log_attempt(number, "cancelled", error=_cancelled_error())
                    return
                active_deadline = self._active_deadline(recovery_deadline)
                if active_deadline is not None and self.clock() >= active_deadline:
                    attempt.cancel()
                    failure = self._deadline_error()
                    break
                timeout = 0.2
                if stream_started and ping_due is not None:
                    timeout = max(0.01, min(timeout, ping_due - self.clock()))
                try:
                    if pending_result is not None:
                        kind, value = pending_result
                        pending_result = None
                    else:
                        kind, value = attempt.items.get(timeout=timeout)
                except queue.Empty:
                    if attempt.thread is not None and not attempt.thread.is_alive():
                        failure = helper.ClaudeGptError("internal_error", "Gateway provider worker stopped.")
                        break
                    if stream_started and ping_due is not None and self.clock() >= ping_due:
                        try:
                            self._write_event(sink, "ping", {"type": "ping"})
                        except (BrokenPipeError, ConnectionResetError, OSError):
                            cancel_event.set()
                            attempt.cancel()
                            self._log_attempt(number, "cancelled", error=_cancelled_error())
                            return
                        ping_due = self.clock() + self.ping_interval
                    continue
                if kind == "record":
                    record = value
                    if not isinstance(record, dict):
                        failure = helper.ClaudeGptError("invalid_helper_record", "Gateway helper output was invalid.")
                        break
                    if record.get("type") == "text_delta":
                        text = record.get("text")
                        if not isinstance(text, str):
                            failure = helper.ClaudeGptError("invalid_helper_record", "Gateway helper output was invalid.")
                            break
                        emit_text = text
                        if emit_text:
                            try:
                                if not text_block_started:
                                    self._write_event(sink, "content_block_start", {
                                        "type": "content_block_start", "index": block_index,
                                        "content_block": {"type": "text", "text": ""},
                                    })
                                    text_block_started = True
                                self._write_event(sink, "content_block_delta", {
                                    "type": "content_block_delta", "index": block_index,
                                    "delta": {"type": "text_delta", "text": emit_text},
                                })
                            except (BrokenPipeError, ConnectionResetError, OSError):
                                cancel_event.set()
                                attempt.cancel()
                                self._log_attempt(number, "cancelled", error=_cancelled_error())
                                return
                            visible_text += emit_text
                        continue
                    if record.get("type") == "completed":
                        completed_record = record
                        break
                    if record.get("type") == "error":
                        failure = helper.ClaudeGptError("invalid_helper_record",
                                                        "Gateway helper reported an error.")
                        break
                    failure = helper.ClaudeGptError("invalid_helper_record", "Gateway helper output was invalid.")
                    break
                if kind == "success":
                    if completed_record is None:
                        failure = helper.ClaudeGptError("invalid_helper_record", "Gateway helper completion was missing.")
                    break
                if kind == "error":
                    failure = value
                    break

            if failure is not None:
                self._log_attempt(number, "failed", error=failure)
                if failure.terminal_after_completion:
                    terminal = failure
                    break
                delay, recovery_deadline, budget_limited = self._recovery_delay(
                    failure, number, recovery_deadline,
                )
                if delay is None:
                    terminal = (_request_budget_error() if budget_limited else
                                _retry_exhausted() if _is_recoverable(failure) else failure)
                    break
                waited = self._wait_retry(delay, recovery_deadline, cancel_event, sink,
                                          stream_started, ping_due)
                if waited == "cancelled":
                    return
                if waited == "deadline":
                    terminal = self._deadline_error()
                    break
                continue

            if completed_record is None:
                terminal = helper.ClaudeGptError("invalid_helper_record", "Gateway helper completion was missing.")
                break
            try:
                calls = _validated_tool_calls(completed_record.get("tool_calls"), request["history"])
                usage = _anthropic_usage(completed_record.get("usage"))
            except GatewayRequestError as error:
                terminal = helper.ClaudeGptError(error.code, error.message)
                self._log_attempt(number, "failed", error=terminal, record=completed_record)
                break
            log_record = dict(completed_record)
            log_record["request_id"] = attempt.http.request_id if attempt.http is not None else None
            self._log_attempt(number, "completed", record=log_record)
            if text_block_started:
                self._write_event(sink, "content_block_stop", {"type": "content_block_stop", "index": block_index})
                block_index += 1
            for call in calls:
                self._write_event(sink, "content_block_start", {
                    "type": "content_block_start", "index": block_index,
                    "content_block": {"type": "tool_use", "id": call["id"], "name": call["name"], "input": {}},
                })
                partial = json.dumps(call["arguments"], ensure_ascii=False, separators=(",", ":"))
                self._write_event(sink, "content_block_delta", {
                    "type": "content_block_delta", "index": block_index,
                    "delta": {"type": "input_json_delta", "partial_json": partial},
                })
                self._write_event(sink, "content_block_stop", {"type": "content_block_stop", "index": block_index})
                block_index += 1
            self._write_event(sink, "message_delta", {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use" if calls else "end_turn", "stop_sequence": None},
                "usage": usage,
            })
            self._write_event(sink, "message_stop", {"type": "message_stop"})
            return

        if terminal is None:
            terminal = helper.ClaudeGptError("gateway_retry_exhausted", "GPT recovery attempts were exhausted.")
        if stream_started:
            if text_block_started:
                with contextlib.suppress(Exception):
                    self._write_event(sink, "content_block_stop", {"type": "content_block_stop", "index": block_index})
            self._send_stream_error(sink, terminal)
        else:
            status, error_type, message, code = _map_error(terminal)
            self._send_error(sink, status, error_type, message, code, error=terminal)

    def _start_stream(self, sink: ResponseSink, model: str) -> None:
        sink.start_response(200, [
            ("Content-Type", "text/event-stream; charset=utf-8"),
            ("Cache-Control", "no-cache"), ("Connection", "close"),
            ("x-accel-buffering", "no"), ("x-should-retry", "false"),
        ])
        self._write_event(sink, "message_start", {
            "type": "message_start", "message": {
                "id": "msg_" + uuid.uuid4().hex, "type": "message", "role": "assistant",
                "model": model, "content": [], "stop_reason": None, "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0},
            },
        })

    def _active_deadline(self, recovery_deadline: float | None) -> float | None:
        shared_deadline = self.request_budget.deadline if self.request_budget is not None else None
        if recovery_deadline is None:
            return shared_deadline
        if shared_deadline is None:
            return recovery_deadline
        return min(recovery_deadline, shared_deadline)

    @staticmethod
    def _write_event(sink: ResponseSink, event: str, data: Mapping[str, Any]) -> None:
        encoded = json.dumps(dict(data), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        sink.write(b"event: " + event.encode("ascii") + b"\ndata: " + encoded + b"\n\n")

    def _recovery_delay(self, error: Any, number: int,
                        existing_deadline: float | None) -> tuple[float | None, float | None, bool]:
        if number >= self.max_attempts or not _is_recoverable(error):
            return None, None, False
        budget_limited = False
        if self.request_budget is not None:
            if not self.request_budget.has_attempt() or self.request_budget.deadline_reached(self.clock()):
                return None, None, True
        now = self.clock()
        deadline = existing_deadline if existing_deadline is not None else now + self.recovery_seconds
        if self.request_budget is not None and self.request_budget.deadline is not None:
            if self.request_budget.deadline < deadline:
                deadline = self.request_budget.deadline
                budget_limited = True
        base = (1.0, 2.0)[min(number - 1, 1)]
        random_extra = max(0.0, min(float(self.jitter()), 0.5))
        delay = base + random_extra
        retry_after = getattr(error, "retry_after", None)
        if isinstance(retry_after, (int, float)) and not isinstance(retry_after, bool) and retry_after > delay:
            delay = float(retry_after)
        if self.recovery_seconds <= 0 or now + delay > deadline:
            return None, None, budget_limited
        return delay, deadline, budget_limited

    def _deadline_error(self) -> helper.ClaudeGptError:
        if self.request_budget is not None and self.request_budget.deadline_reached(self.clock()):
            return _request_budget_error()
        return helper.ClaudeGptError("gateway_recovery_deadline", "Gateway recovery deadline expired.")

    def _wait_retry(self, delay: float, deadline: float, cancel_event: threading.Event,
                    sink: ResponseSink, stream_started: bool, ping_due: float | None) -> str:
        end = self.clock() + delay
        next_ping = ping_due
        while self.clock() < end:
            if cancel_event.is_set():
                return "cancelled"
            now = self.clock()
            if now >= deadline:
                return "deadline"
            until = min(end, deadline) - now
            if stream_started and next_ping is not None:
                until = min(until, max(0.01, next_ping - now))
            cancelled = self.wait(cancel_event, max(0.01, min(until, 0.2)))
            if cancelled or cancel_event.is_set():
                return "cancelled"
            now = self.clock()
            if stream_started and next_ping is not None and now >= next_ping:
                try:
                    self._write_event(sink, "ping", {"type": "ping"})
                except (BrokenPipeError, ConnectionResetError, OSError):
                    cancel_event.set()
                    return "cancelled"
                next_ping = now + self.ping_interval
        return "deadline" if self.clock() >= deadline else "done"

    def _log_attempt(self, number: int, outcome: str, *, error: Any = None, record: Any = None) -> None:
        log = getattr(self.logger, "attempt", None)
        if callable(log):
            with contextlib.suppress(Exception):
                log(number=number, outcome=outcome, error=error, record=record)

    def _send_helper_error(self, sink: ResponseSink, error: Any) -> None:
        status, error_type, message, code = _map_error(error)
        self._send_error(sink, status, error_type, message, code, error=error)

    def _send_error(self, sink: ResponseSink, status: int, error_type: str, message: str,
                    code: str, *, error: Any = None) -> None:
        headers = [("Content-Type", "application/json; charset=utf-8"), ("x-should-retry", "false")]
        request_id = getattr(error, "request_id", None) if error is not None else None
        if isinstance(request_id, str) and helper.SAFE_REQUEST_ID_RE.fullmatch(request_id):
            headers.append(("x-request-id", request_id))
        sink.start_response(status, headers)
        sink.write(json.dumps({
            "type": "error", "error": {"type": error_type, "message": message, "code": code},
        }, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    def _send_stream_error(self, sink: ResponseSink, error: Any) -> None:
        _status, error_type, message, code = _map_error(error)
        self._write_event(sink, "error", {
            "type": "error", "error": {"type": error_type, "message": message, "code": code},
        })

class _CallIdValidatingStore:
    """Refuse provider state with IDs Anthropic cannot safely address."""

    def __init__(self, store: Any):
        self.store = store

    def __getattr__(self, name: str) -> Any:
        return getattr(self.store, name)

    def merge_provider_state(self, profile_id: str, groups: list[dict[str, Any]]) -> None:
        for group in groups:
            ids = group.get("ids") if isinstance(group, dict) else None
            if (not isinstance(ids, list) or any(not isinstance(call_id, str) or not CALL_ID_RE.fullmatch(call_id)
                                                  for call_id in ids)):
                raise helper.ClaudeGptError("unsupported_call_id", "A provider tool-call ID is outside the supported format.")
        self.store.merge_provider_state(profile_id, groups)


def _client_factory(value: Any, *, timeout: float | None):
    if value is None:
        return lambda: _DirectHttpClient(read_timeout=timeout)
    if callable(value) and not hasattr(value, "open"):
        return value
    return lambda: value


def _strip_hop_headers(headers: Mapping[str, Any], *, drop_host: bool = False) -> list[tuple[str, str]]:
    connection_tokens: set[str] = set()
    for name, value in headers.items():
        if str(name).lower() == "connection":
            connection_tokens.update(token.strip().lower() for token in str(value).split(",") if token.strip())
    dropped = HOP_HEADERS | connection_tokens | ({"host"} if drop_host else set())
    return [(str(name), str(value)) for name, value in headers.items() if str(name).lower() not in dropped]


def _text_content(content: Any, *, field: str = "system") -> list[str]:
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        raise GatewayRequestError("invalid_request", f"The {field} field must contain text blocks.")
    values: list[str] = []
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "text" or not isinstance(item.get("text"), str):
            raise GatewayRequestError("invalid_request", f"The {field} field contains an unsupported block.")
        values.append(item["text"])
    return values


def _web_results_text(value: Any) -> str:
    rows: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, list):
            for child in item:
                visit(child)
        elif isinstance(item, dict):
            title = item.get("title")
            url = item.get("url", item.get("link"))
            if isinstance(title, str) or isinstance(url, str):
                rows.append("\n".join(part for part in (title, url) if isinstance(part, str)))
            else:
                for key in ("content", "results", "items"):
                    if key in item:
                        visit(item[key])

    visit(value)
    return "\n".join(rows)


def _canonical_media(block: Mapping[str, Any]) -> dict[str, Any]:
    kind = block.get("type")
    source = block.get("source")
    if not isinstance(source, dict):
        raise GatewayRequestError("invalid_media", "An attachment source is invalid.")
    return {"type": kind, "source": {
        key: source[key] for key in ("type", "media_type", "data") if key in source
    }}


def translate_messages_request(body: Mapping[str, Any], profile_id: str) -> dict[str, Any]:
    if not isinstance(body, Mapping) or body.get("model") not in helper.PINNED_MODELS:
        raise GatewayRequestError("unsupported_model", "The selected model is not supported by the GPT gateway.")
    messages = body.get("messages")
    if not isinstance(messages, list):
        raise GatewayRequestError("invalid_history", "Messages must be an array.")
    system_parts = _text_content(body.get("system", ""), field="system")
    for message in messages:
        if isinstance(message, dict) and message.get("role") == "system":
            system_parts.extend(_text_content(message.get("content"), field="system message"))

    server_call_ids = {
        block.get("id")
        for message in messages if isinstance(message, dict) and message.get("role") == "assistant"
        for block in (message.get("content") if isinstance(message.get("content"), list) else [])
        if isinstance(block, dict) and block.get("type") == "server_tool_use" and isinstance(block.get("id"), str)
    }
    referenced_tools: set[str] = set()
    history: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") not in {"user", "assistant", "system"}:
            raise GatewayRequestError("invalid_history", "A message has an unsupported role or shape.")
        role = message["role"]
        if role == "system":
            continue
        source = message.get("content")
        if isinstance(source, str):
            content: Any = [{"type": "text", "text": source}]
            blocks = None
        elif isinstance(source, list):
            content = []
            blocks = source
        else:
            raise GatewayRequestError("invalid_history", "A message content field has an unsupported shape.")
        if blocks is not None:
            for block in blocks:
                if not isinstance(block, dict) or not isinstance(block.get("type"), str):
                    raise GatewayRequestError("invalid_history", "A message content block is malformed.")
                kind = block["type"]
                if kind == "text" and isinstance(block.get("text"), str):
                    content.append({"type": "text", "text": block["text"]})
                elif kind in {"image", "document"} and role == "user":
                    content.append(_canonical_media(block))
                elif kind in {"thinking", "redacted_thinking", "server_tool_use"}:
                    continue
                elif kind == "tool_reference":
                    name = block.get("tool_name", block.get("name"))
                    if isinstance(name, str):
                        referenced_tools.add(name)
                elif kind == "tool_use" and role == "assistant":
                    content.append({key: block[key] for key in ("type", "id", "name", "input") if key in block})
                elif kind == "tool_result" and role == "user":
                    call_id = block.get("tool_use_id")
                    if call_id in server_call_ids:
                        result_text = _web_results_text(block.get("content"))
                        if result_text:
                            content.append({"type": "text", "text": result_text})
                        continue
                    result: dict[str, Any] = {"type": "tool_result"}
                    for key in ("tool_use_id", "content", "is_error"):
                        if key in block:
                            result[key] = block[key]
                    if isinstance(result.get("content"), list):
                        canonical_content = []
                        for child in result["content"]:
                            if isinstance(child, dict) and child.get("type") in {"image", "document"}:
                                canonical_content.append(_canonical_media(child))
                            elif isinstance(child, dict) and child.get("type") == "text" and isinstance(child.get("text"), str):
                                canonical_content.append({"type": "text", "text": child["text"]})
                            elif isinstance(child, dict) and child.get("type") == "tool_reference":
                                name = child.get("tool_name", child.get("name"))
                                if isinstance(name, str):
                                    referenced_tools.add(name)
                            elif isinstance(child, dict) and child.get("type") in {"web_search_tool_result", "web_search_result"}:
                                rendered = _web_results_text(child)
                                if rendered:
                                    canonical_content.append({"type": "text", "text": rendered})
                            else:
                                raise GatewayRequestError("unsupported_tool_result", "A tool result contains an unsupported block.")
                        result["content"] = canonical_content
                    content.append(result)
                elif kind in {"web_search_tool_result", "web_search_result"}:
                    rendered = _web_results_text(block)
                    if rendered:
                        content.append({"type": "text", "text": rendered})
                else:
                    raise GatewayRequestError("unsupported_history", "A message contains an unsupported content block.")
        history.append({"role": role, "content": content})

    tool_definitions = body.get("tools", [])
    if not isinstance(tool_definitions, list):
        raise GatewayRequestError("invalid_tools", "Tools must be an array.")
    tools: list[dict[str, Any]] = []
    for tool in tool_definitions:
        if not isinstance(tool, dict):
            raise GatewayRequestError("invalid_tools", "A tool definition is malformed.")
        name = tool.get("name")
        schema = tool.get("input_schema")
        if not isinstance(name, str) or schema is None or tool.get("type", "custom") in {
                "web_search", "web_search_20250305", "computer", "bash", "text_editor"}:
            continue
        if tool.get("defer_loading") is True and name not in referenced_tools:
            continue
        description = tool.get("description", "")
        tools.append({"name": name, "description": description, "input_schema": schema})

    choice = None
    if "tool_choice" in body:
        raw_choice = body["tool_choice"]
        if not isinstance(raw_choice, dict):
            raise GatewayRequestError("invalid_tool_choice", "tool_choice is malformed.")
        kind = raw_choice.get("type")
        if kind == "auto":
            choice = "auto"
        elif kind == "any":
            choice = "required"
        elif kind == "none":
            choice = "none"
        elif kind == "tool" and isinstance(raw_choice.get("name"), str):
            choice = {"type": "function", "name": raw_choice["name"]}
        else:
            raise GatewayRequestError("invalid_tool_choice", "tool_choice is unsupported.")

    output_config = body.get("output_config")
    effort = output_config.get("effort") if isinstance(output_config, dict) else None
    request: dict[str, Any] = {
        "protocol_version": helper.PROTOCOL_VERSION,
        "request_id": uuid.uuid4().hex,
        "session_id": uuid.uuid4().hex,
        "turn_id": uuid.uuid4().hex,
        "step_id": uuid.uuid4().hex,
        "model": body["model"],
        "effort": effort,
        "profile_id": profile_id,
        "system": "\n\n".join(system_parts),
        "developer": [],
        "history": history,
        "tools": tools,
    }
    if choice is not None:
        request["tool_choice"] = choice
    return helper.validate_protocol_request(request)


def _append_recovery_instruction(system: str) -> str:
    return system + ("\n\n" if system else "") + RECOVERY_INSTRUCTION


def _retry_exhausted() -> Any:
    return helper.ClaudeGptError("gateway_retry_exhausted", "GPT recovery attempts were exhausted.")


def _request_budget_error() -> Any:
    return helper.ClaudeGptError("gateway_request_budget_exhausted", "The approved gateway request budget was exhausted.")


def _cancelled_error() -> Any:
    return helper.ClaudeGptError("gateway_cancelled", "Gateway request was cancelled.")


def _validated_tool_calls(value: Any, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise GatewayRequestError("invalid_tool_call", "The provider tool-call list is invalid.")
    historical_ids = {
        block.get("id")
        for message in history if isinstance(message, dict) and message.get("role") == "assistant"
        for block in message.get("content", []) if isinstance(message.get("content"), list) and
        isinstance(block, dict) and block.get("type") == "tool_use"
    }
    seen: set[str] = set()
    calls: list[dict[str, Any]] = []
    for call in value:
        if (not isinstance(call, dict) or set(call) != {"id", "name", "arguments"} or
                not isinstance(call.get("id"), str) or not CALL_ID_RE.fullmatch(call["id"]) or
                call["id"] in historical_ids or call["id"] in seen or
                not isinstance(call.get("name"), str) or not isinstance(call.get("arguments"), dict)):
            raise GatewayRequestError("unsupported_call_id", "A provider tool call has an unsupported ID or shape.")
        seen.add(call["id"])
        calls.append(call)
    return calls


def _anthropic_usage(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise GatewayRequestError("invalid_usage", "Validated provider usage is missing.")
    input_tokens = value.get("input_tokens")
    cached = value.get("cached_input_tokens")
    output_tokens = value.get("output_tokens")
    for number in (input_tokens, cached, output_tokens):
        if not isinstance(number, int) or isinstance(number, bool) or number < 0:
            raise GatewayRequestError("invalid_usage", "Validated provider usage is malformed.")
    if cached > input_tokens:
        raise GatewayRequestError("invalid_usage", "Cached input usage exceeds input usage.")
    return {
        "input_tokens": input_tokens - cached,
        "cache_read_input_tokens": cached,
        "output_tokens": output_tokens,
    }


def _exception_chain(error: Any):
    current = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = getattr(current, "__cause__", None) or getattr(current, "reason", None)


def _is_recoverable(error: Any) -> bool:
    if getattr(error, "terminal_after_completion", False):
        return False
    if getattr(error, "code", None) == "terminal_refresh_error":
        return False
    provider_code = getattr(error, "provider_code", None)
    if provider_code == "unknown_provider_error" or getattr(error, "code", None) == "unknown_provider_error":
        return False
    if provider_code is not None:
        return provider_code in RETRY_PROVIDER_CODES
    code = getattr(error, "code", None)
    status = getattr(error, "http_status", None)
    if status == 429:
        return False
    if status in RECOVERABLE_HTTP:
        return True
    if code in {"stream_interrupted", "truncated_stream"}:
        return True
    if code == "network_error":
        import errno
        for cause in _exception_chain(error):
            module = type(cause).__module__
            name = type(cause).__name__
            if module == "ssl" or "Certificate" in name or "SSLCert" in name:
                return False
            if isinstance(cause, socket.gaierror):
                return cause.errno == getattr(socket, "EAI_AGAIN", object())
            if isinstance(cause, TimeoutError):
                return True
            if isinstance(cause, (ConnectionResetError, ConnectionAbortedError, ConnectionRefusedError, BrokenPipeError)):
                return True
            if isinstance(cause, OSError):
                transient = {
                    errno.ECONNABORTED, errno.ECONNREFUSED, errno.ECONNRESET,
                    errno.EPIPE, errno.ETIMEDOUT,
                    getattr(errno, "EAGAIN", -1), getattr(errno, "EWOULDBLOCK", -2),
                    getattr(errno, "EHOSTUNREACH", -3), getattr(errno, "ENETUNREACH", -4),
                }
                if cause.errno is not None:
                    return cause.errno in transient
        return False
    return False


def _map_error(error: Any) -> tuple[int, str, str, str]:
    raw_code = getattr(error, "code", "request_failed")
    if raw_code == "terminal_refresh_error":
        return 401, "authentication_error", "The selected GPT profile could not refresh its authorization.", raw_code
    provider_code = getattr(error, "provider_code", None)
    code = provider_code or getattr(error, "code", "request_failed")
    if not isinstance(code, str) or not helper.SAFE_CODE_RE.fullmatch(code):
        code = "request_failed"
    if code in TERMINAL_AUTH_CODES:
        return 401, "authentication_error", "The selected GPT profile could not authenticate.", code
    if code in TERMINAL_PERMISSION_CODES:
        return 403, "permission_error", "The selected account is not eligible for this GPT request.", code
    if code in TERMINAL_QUOTA_CODES:
        return 429, "rate_limit_error", "ChatGPT plan usage is unavailable. Check ChatGPT Settings > Usage.", code
    if provider_code is None and raw_code == "http_error":
        status = getattr(error, "http_status", None)
        if status == 401:
            return 401, "authentication_error", "The selected GPT profile could not authenticate.", raw_code
        if status == 403:
            return 403, "permission_error", "The selected account is not eligible for this GPT request.", raw_code
    if code == "gateway_retry_exhausted":
        return 429, "rate_limit_error", "Temporary GPT service failures exhausted the gateway retry limit.", code
    if code in {"gateway_recovery_deadline", "gateway_request_budget_exhausted"}:
        return 429, "rate_limit_error", "The gateway's approved request limit was reached.", code
    if code == "gateway_cancelled":
        return 408, "invalid_request_error", "The GPT request was cancelled.", code
    if code == "unsupported_call_id":
        return 400, "invalid_request_error", "The provider returned a tool-call ID outside the supported format.", code
    return 400, "invalid_request_error", f"The GPT request failed validation ({code}).", code


def _send_plain_error(sink: ResponseSink, status: int, error_type: str, message: str, code: str) -> None:
    sink.start_response(status, [("Content-Type", "application/json; charset=utf-8"), ("x-should-retry", "false")])
    sink.write(json.dumps({"type": "error", "error": {"type": error_type, "message": message, "code": code}},
                          ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _response_started(sink: ResponseSink) -> bool:
    started = getattr(sink, "started", False)
    if isinstance(started, threading.Event):
        started = started.is_set()
    return bool(started) or getattr(sink, "status", None) is not None


class _HandlerResponse(ResponseSink):
    def __init__(self, handler: "GatewayRequestHandler"):
        self.handler = handler
        self.started = False

    def start_response(self, status: int, headers: list[tuple[str, str]]) -> None:
        if self.started:
            raise RuntimeError("response already started")
        self.started = True
        self.handler.send_response(status)
        lowered = {name.lower() for name, _value in headers}
        for name, value in headers:
            self.handler.send_header(name, value)
        if "connection" not in lowered:
            self.handler.send_header("Connection", "close")
        self.handler.close_connection = True
        self.handler.end_headers()

    def write(self, data: bytes) -> None:
        if self.handler.command.upper() == "HEAD":
            return
        self.handler.wfile.write(data)
        self.handler.wfile.flush()


class GatewayRequestHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    application: GatewayApplication

    def log_message(self, format: str, *args: Any) -> None:
        # The default server logger would include the secret URL path.
        return None

    def _dispatch(self) -> None:
        secret_prefix = "/" + self.application.secret
        request_path = self.path.partition("?")[0]
        if request_path != secret_prefix and not request_path.startswith(secret_prefix + "/"):
            self._safe_error(404, "not_found_error", "Not found.", "not_found")
            return
        try:
            body = self._read_request_body()
        except (ValueError, OSError, OverflowError):
            self._safe_error(400, "invalid_request_error", "Request body framing is invalid.", "invalid_request")
            return
        cancelled = threading.Event()
        monitor_done = threading.Event()
        monitor = threading.Thread(target=self._monitor_disconnect, args=(cancelled, monitor_done),
                                   name="claude-gateway-disconnect", daemon=True)
        monitor.start()
        response = _HandlerResponse(self)
        try:
            self.application.handle_request(self.command, self.path, self.headers, body,
                                             response, cancel_event=cancelled)
        except (BrokenPipeError, ConnectionResetError, OSError):
            cancelled.set()
            with contextlib.suppress(Exception):
                self.close_connection = True
        except Exception:
            cancelled.set()
            self.close_connection = True
            if not response.started:
                with contextlib.suppress(Exception):
                    _send_plain_error(response, 400, "invalid_request_error", "The local gateway failed safely.",
                                      "gateway_internal_error")
        finally:
            monitor_done.set()
            monitor.join(timeout=0.2)
            self.close_connection = True

    def _safe_error(self, status: int, error_type: str, message: str, code: str) -> None:
        try:
            _send_plain_error(_HandlerResponse(self), status, error_type, message, code)
        except Exception:
            self.close_connection = True

    def _read_request_body(self) -> bytes:
        get_all = getattr(self.headers, "get_all", None)
        lengths = get_all("Content-Length") if callable(get_all) else None
        encodings = get_all("Transfer-Encoding") if callable(get_all) else None
        if lengths is None:
            raw_length = self.headers.get("Content-Length")
            lengths = [] if raw_length is None else [raw_length]
        if encodings is None:
            raw_encoding = self.headers.get("Transfer-Encoding")
            encodings = [] if raw_encoding is None else [raw_encoding]
        if len(lengths) > 1 or len(encodings) > 1 or (lengths and encodings):
            raise ValueError("ambiguous request framing")
        if encodings:
            if str(encodings[0]).strip().lower() != "chunked":
                raise ValueError("unsupported transfer encoding")
            return self._read_chunked_body()
        if not lengths:
            return b""
        raw_length = str(lengths[0]).strip()
        if not re.fullmatch(r"[0-9]+", raw_length):
            raise ValueError("invalid content length")
        remaining = int(raw_length)
        result = bytearray()
        while remaining:
            chunk = self.rfile.read(min(remaining, 64 * 1024))
            if not chunk:
                raise ValueError("truncated request body")
            result.extend(chunk)
            remaining -= len(chunk)
        return bytes(result)

    def _read_chunked_body(self) -> bytes:
        result = bytearray()
        while True:
            line = self.rfile.readline(8192)
            if len(line) >= 8192 or not line.endswith(b"\r\n"):
                raise ValueError("invalid chunk size line")
            size_text = line[:-2].split(b";", 1)[0]
            if not size_text or len(size_text) > 16 or not re.fullmatch(rb"[0-9A-Fa-f]+", size_text):
                raise ValueError("invalid chunk size")
            size = int(size_text, 16)
            if size == 0:
                while True:
                    trailer = self.rfile.readline(8192)
                    if len(trailer) >= 8192 or not trailer.endswith(b"\r\n"):
                        raise ValueError("invalid chunk trailer")
                    if trailer == b"\r\n":
                        return bytes(result)
                    name, separator, _value = trailer[:-2].partition(b":")
                    if (not separator or not re.fullmatch(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name) or
                            trailer[:1] in b" \t"):
                        raise ValueError("invalid chunk trailer")
            remaining = size
            while remaining:
                chunk = self.rfile.read(min(remaining, 64 * 1024))
                if not chunk:
                    raise ValueError("truncated chunk")
                result.extend(chunk)
                remaining -= len(chunk)
            if self.rfile.read(2) != b"\r\n":
                raise ValueError("invalid chunk terminator")

    def _monitor_disconnect(self, cancelled: threading.Event, done: threading.Event) -> None:
        connection = self.connection
        while not done.wait(0.05):
            try:
                readable, _writable, _exceptional = select.select([connection], [], [], 0)
                if not readable:
                    continue
                try:
                    data = connection.recv(1, socket.MSG_PEEK | getattr(socket, "MSG_DONTWAIT", 0))
                except BlockingIOError:
                    continue
                if not data:
                    cancelled.set()
                    return
            except (OSError, ValueError):
                cancelled.set()
                return

    do_GET = _dispatch
    do_POST = _dispatch
    do_PUT = _dispatch
    do_PATCH = _dispatch
    do_DELETE = _dispatch
    do_OPTIONS = _dispatch

    def __getattr__(self, name: str):
        if name.startswith("do_"):
            return self._dispatch
        raise AttributeError(name)


class GatewayRuntime:
    def __init__(self, server: http.server.ThreadingHTTPServer, base_url: str,
                 cancel_active: Callable[[], None] | None = None):
        self.server = server
        self.base_url = base_url
        self.cancel_active = cancel_active
        self.thread: threading.Thread | None = None

    def start(self) -> "GatewayRuntime":
        if self.thread is None:
            self.thread = threading.Thread(target=self.server.serve_forever, name="claude-gpt-gateway", daemon=True)
            self.thread.start()
        return self

    def stop(self) -> None:
        if self.cancel_active is not None:
            with contextlib.suppress(Exception):
                self.cancel_active()
        if self.thread is not None:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=5)
            self.thread = None
        else:
            self.server.server_close()


def start_gateway(profile_id: str, *, store: Any = None, openai_http_factory: Any = None,
                  claude_http_factory: Any = None, logger: Any = None,
                  server_factory: Any = http.server.ThreadingHTTPServer,
                  request_budget: GatewayRequestBudget | None = None) -> GatewayRuntime:
    secret = secrets.token_urlsafe(32)
    application = GatewayApplication(
        profile_id, secret, store=store, openai_http_factory=openai_http_factory,
        claude_http_factory=claude_http_factory, logger=logger, request_budget=request_budget,
    )
    handler = type("BoundGatewayRequestHandler", (GatewayRequestHandler,), {"application": application})
    server = server_factory(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    return GatewayRuntime(server, f"http://127.0.0.1:{port}/{secret}", application.cancel_active_requests)


def _source_version() -> str:
    path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with path.open("rb") as stream:
        return tomllib.load(stream)["project"]["version"].split("+", 1)[0]


def _plugin_enabled(stdout: str, expected_version: str) -> bool:
    try:
        value = json.loads(stdout)
    except (TypeError, json.JSONDecodeError):
        return False
    plugins = value if isinstance(value, list) else value.get("plugins") if isinstance(value, dict) else None
    if not isinstance(plugins, list):
        return False
    for plugin in plugins:
        if not isinstance(plugin, dict) or plugin.get("id") != PLUGIN_ID or plugin.get("enabled") is not True:
            continue
        version = plugin.get("version")
        if isinstance(version, str) and version.split("+", 1)[0] == expected_version:
            return True
    return False


def _project_config_root(arguments: list[str], cwd: Path) -> Path | None:
    selected: str | None = None
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--project-config-root":
            if index + 1 < len(arguments):
                selected = arguments[index + 1]
                index += 1
        elif argument.startswith("--project-config-root="):
            selected = argument.split("=", 1)[1]
        index += 1
    if not selected:
        return None
    candidate = Path(selected).expanduser()
    if not candidate.is_absolute():
        return None
    return candidate.resolve()


def _managed_settings_root(environ: Mapping[str, str]) -> Path:
    if sys.platform == "darwin":
        return Path("/Library/Application Support/ClaudeCode")
    if os.name == "nt":
        return Path(r"C:\Program Files\ClaudeCode")
    return Path("/etc/claude-code")


def _settings_paths(environ: Mapping[str, str], cwd: Path,
                    claude_args: list[str] | None = None) -> list[Path]:
    config_root = Path(environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))).expanduser()
    override_root = _project_config_root(claude_args or [], cwd)
    paths = [config_root / "settings.json"]
    if override_root is not None:
        paths.extend([
            override_root / ".claude" / "settings.json",
            override_root / ".claude" / "settings.local.json",
        ])
    else:
        paths.extend([
            cwd / ".claude" / "settings.json",
            cwd / ".claude" / "settings.local.json",
        ])
        project_root: Path | None = None
        for candidate in (cwd, *cwd.parents):
            if (candidate / ".git").exists():
                project_root = candidate.resolve()
                break
        if project_root is not None:
            try:
                same_as_home = project_root == Path.home().resolve()
                wrong_owner = hasattr(os, "getuid") and project_root.stat().st_uid != os.getuid()
            except OSError:
                same_as_home = True
                wrong_owner = True
            if not same_as_home and not wrong_owner and project_root != cwd.resolve():
                paths.append(project_root / ".claude" / "settings.local.json")
    managed_root = _managed_settings_root(environ)
    paths.append(managed_root / "managed-settings.json")
    managed_directory = managed_root / "managed-settings.d"
    if managed_directory.is_dir():
        paths.extend(sorted((path for path in managed_directory.glob("*.json") if not path.name.startswith(".")),
                            key=lambda path: path.name))
    return paths


def _settings_conflict(environ: Mapping[str, str], cwd: Path,
                       claude_args: list[str] | None = None) -> bool:
    for path in _settings_paths(environ, cwd, claude_args):
        try:
            with path.open("r", encoding="utf-8") as stream:
                value = json.load(stream)
        except FileNotFoundError:
            continue
        except (OSError, UnicodeError):
            continue
        except json.JSONDecodeError:
            # Readable but malformed settings cannot be checked for an
            # authentication override safely.
            return True
        if not isinstance(value, dict):
            return True
        if "apiKeyHelper" in value:
            return True
        env = value.get("env")
        if isinstance(env, dict) and any(key in env for key in FORBIDDEN_ENV):
            return True
    return False


def _blocked_claude_args(arguments: list[str]) -> bool:
    for argument in arguments:
        if argument in {"--settings", "--setting-sources", "--bare"}:
            return True
        if any(argument.startswith(option + "=") for option in ("--settings", "--setting-sources", "--bare")):
            return True
    return False


def launch(profile_id: str, claude_args: list[str], *, store: Any = None,
           environ: Mapping[str, str] | None = None, cwd: Path | None = None,
           run: Callable[..., Any] = subprocess.run, gateway_factory: Callable[..., GatewayRuntime] = start_gateway,
           source_version: str | None = None, http_client: Any = None,
           request_budget: GatewayRequestBudget | None = None) -> int:
    env = os.environ if environ is None else environ
    current_dir = Path.cwd() if cwd is None else Path(cwd)
    if any(name in env for name in FORBIDDEN_ENV) or _settings_conflict(env, current_dir, claude_args):
        raise helper.ClaudeGptError("launcher_auth_conflict", "Remove conflicting Claude authentication settings before using the GPT launcher.")
    if _blocked_claude_args(claude_args):
        raise helper.ClaudeGptError("launcher_argument_conflict", "The GPT launcher cannot use --settings, --setting-sources, or --bare.")

    version = source_version or _source_version()
    try:
        plugin_result = run(["claude", "plugin", "list", "--json"], capture_output=True,
                            text=True, timeout=15, check=False, env=dict(env), cwd=current_dir)
    except (OSError, subprocess.SubprocessError):
        raise helper.ClaudeGptError("plugin_not_enabled", "Enable the matching hei5enbug-agent-setup plugin before launching GPT.") from None
    if getattr(plugin_result, "returncode", 1) != 0 or not _plugin_enabled(getattr(plugin_result, "stdout", ""), version):
        raise helper.ClaudeGptError("plugin_not_enabled", "Enable the matching hei5enbug-agent-setup plugin before launching GPT.")

    profile_store = store or helper.ProfileStore.default()
    openai_http = http_client or helper.HttpClient(timeout=30.0)
    profile, _credentials = helper._refresh_if_needed(profile_store, openai_http, profile_id)
    gateway_kwargs = {"store": profile_store}
    if request_budget is not None:
        gateway_kwargs["request_budget"] = request_budget
    runtime = gateway_factory(profile_id, **gateway_kwargs)
    try:
        runtime.start()
        child_env = dict(env)
        child_env["ANTHROPIC_BASE_URL"] = runtime.base_url
        child_env["HEI5ENBUG_GPT_GATEWAY_URL"] = runtime.base_url
        child_env["ANTHROPIC_CUSTOM_MODEL_OPTION"] = "gpt-6.1-sol"
        child_env["ANTHROPIC_CUSTOM_MODEL_OPTION_NAME"] = "gpt-6.1-sol"
        mode = profile.get("mode")
        description = ("ChatGPT plan via local gateway; press s to keep your default"
                       if mode == "subscription" else
                       "OpenAI API key via local gateway; press s to keep your default")
        child_env["ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION"] = description
        child_env["CLAUDE_CODE_ALWAYS_ENABLE_EFFORT"] = "1"
        child_env["CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK"] = "1"
        result = run(["claude", *claude_args], env=child_env, cwd=current_dir, check=False)
        return int(getattr(result, "returncode", 1))
    finally:
        runtime.stop()


def main() -> int:
    raise SystemExit("Use scripts/claude_gpt.py launch --profile <profile-id>.")


if __name__ == "__main__":
    main()
