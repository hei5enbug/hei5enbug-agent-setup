from __future__ import annotations

import io
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import claude_gpt as helper
import claude_gpt_gateway as gateway


def _schema() -> dict:
    return {
        "type": "object", "properties": {"file_path": {"type": "string"}},
        "required": ["file_path"], "additionalProperties": False,
    }


def _anthropic_request(**overrides) -> dict:
    request = {
        "model": "gpt-5.6-luna", "max_tokens": 512,
        "system": "System instruction.",
        "messages": [{"role": "user", "content": "Please answer."}],
    }
    request.update(overrides)
    return request


def _sse(*events: dict) -> bytes:
    return b"".join(
        f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n".encode("utf-8")
        for event in events
    )


def _completion(output=None, *, text: str | None = None, model="gpt-5.6-luna", status="completed") -> dict:
    items = output if output is not None else []
    if text is not None and output is None:
        items = [{"id": "msg-provider", "type": "message", "role": "assistant",
                  "content": [{"type": "output_text", "text": text}]}]
    return {"type": "response.completed", "response": {
        "id": "resp-provider", "status": status, "model": model, "output": items,
        "usage": {"input_tokens": 8, "input_tokens_details": {"cached_tokens": 2},
                  "output_tokens": 3, "output_tokens_details": {"reasoning_tokens": 1}},
    }}


class FakeProvider:
    def __init__(self, *, stream=None, status=200, body=b"{}", headers=None):
        self.stream = stream
        self.status = status
        self.body = body
        self.headers = headers or {}
        self.open_calls = []
        self.json_calls = []
        self.cancel_calls = 0

    def open(self, request):
        self.open_calls.append(request)
        stream = self.stream
        if isinstance(stream, bytes):
            stream = io.BytesIO(stream)
        return helper.HttpResponse(
            self.status, self.headers, self.body,
            stream if 200 <= self.status < 300 else None,
        )

    def json(self, url, **kwargs):
        self.json_calls.append((url, kwargs))
        raise AssertionError("unexpected token endpoint request")


class CaptureSink(gateway.ResponseSink):
    def __init__(self):
        self.status = None
        self.headers = []
        self.body = bytearray()
        self.started = threading.Event()

    def start_response(self, status, headers):
        self.status = status
        self.headers = list(headers)
        self.started.set()

    def write(self, data):
        self.body.extend(data)

    def events(self):
        records = []
        for frame in bytes(self.body).split(b"\n\n"):
            if not frame:
                continue
            event_name = None
            data = None
            for line in frame.splitlines():
                if line.startswith(b"event: "):
                    event_name = line[7:].decode("ascii")
                elif line.startswith(b"data: "):
                    data = json.loads(line[6:].decode("utf-8"))
            if data is not None:
                records.append((event_name, data))
        return records


class FakeLog:
    def __init__(self):
        self.accesses = []
        self.attempts = []

    def access(self, **record):
        self.accesses.append(record)

    def attempt(self, **record):
        self.attempts.append(record)


class FakeClock:
    def __init__(self):
        self.value = 0.0
        self.waits = []

    def __call__(self):
        return self.value

    def wait(self, event, seconds):
        self.waits.append(seconds)
        self.value += seconds
        return event.is_set()


class GatewayTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="gateway-s4-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = helper.ProfileStore(self.root / "claude-gpt")
        profile = helper.create_api_key_profile(self.store, "sk-test-local", confirmed_usage_billing=True)
        self.profile_id = profile["profile_id"]

    def _app(self, provider_factory, **kwargs):
        return gateway.GatewayApplication(
            self.profile_id, "test-secret", store=self.store,
            openai_http_factory=provider_factory, logger=kwargs.pop("logger", FakeLog()), **kwargs,
        )

    def test_Luna의_누락되거나_다른_추론_강도를_xhigh로_고정한다(self):
        """게이트웨이는 Luna 요청의 기존 추론 강도와 관계없이 xhigh로 공급자 요청을 만든다."""
        # Given
        requests = [_anthropic_request(output_config={"effort": effort})
                    for effort in (None, "low", "medium", "high", "xhigh", "max")]
        requests.append(_anthropic_request())

        # When
        payloads = [helper.build_responses_payload(gateway.translate_messages_request(request, self.profile_id),
                                                   subscription=False)[0] for request in requests]

        # Then
        self.assertEqual(["gpt-5.6-luna"] * 7, [payload["model"] for payload in payloads])
        self.assertEqual([{"effort": "xhigh"}] * 7, [payload["reasoning"] for payload in payloads])

    def _post(self, app, request=None, *, sink=None, target="/test-secret/v1/messages", cancel_event=None):
        sink = sink or CaptureSink()
        body = json.dumps(request or _anthropic_request(), separators=(",", ":")).encode()
        app.handle_request("POST", target, {"Content-Type": "application/json"}, body, sink,
                           cancel_event=cancel_event)
        return sink

    def _dispatch_handler(self, app, wire_body, headers, *, command="POST", path="/test-secret/v1/raw?q=1"):
        handler = object.__new__(gateway.GatewayRequestHandler)
        handler.application = app
        handler.command = command
        handler.path = path
        handler.headers = headers
        handler.rfile = io.BytesIO(wire_body)
        handler.wfile = io.BytesIO()
        handler.close_connection = False
        statuses = []
        output_headers = []
        handler.send_response = statuses.append
        handler.send_header = lambda name, value: output_headers.append((name, value))
        handler.end_headers = lambda: None
        handler._monitor_disconnect = lambda _cancelled, _done: None
        handler._dispatch()
        return handler, statuses, output_headers, handler.wfile.getvalue()

    def test_작업자_종료_직전_큐에_들어온_완료와_오류를_보존한다(self):
        for opened_first in (False, True):
            for outcome in ("completed", "quota", "empty"):
                with self.subTest(opened_first=opened_first, outcome=outcome):
                    # Given
                    app = self._app(lambda: None)
                    request = _anthropic_request(tools=[{
                        "name": "Read", "input_schema": _schema(),
                    }])
                    starts = []
                    final_record = {"type": "completed", "tool_calls": [{
                        "id": "call_exit_race", "name": "Read", "arguments": {"file_path": "a.txt"},
                    }], "usage": {"input_tokens": 8, "cached_input_tokens": 0, "output_tokens": 3}}
                    quota = helper.ClaudeGptError("insufficient_quota", "safe",
                                                  provider_code="insufficient_quota")

                    def start(attempt):
                        starts.append(attempt)
                        if opened_first:
                            attempt.opened.set()

                        def finish_after_empty():
                            if outcome == "completed":
                                attempt.opened.set()
                                attempt.items.put(("record", final_record))
                                attempt.items.put(("success", 0))
                            elif outcome == "quota":
                                attempt.items.put(("error", quota))
                            return False

                        attempt.thread = SimpleNamespace(is_alive=finish_after_empty)

                    # When
                    with patch.object(gateway._Attempt, "start", start):
                        sink = self._post(app, request)

                    # Then
                    self.assertEqual(1, len(starts))
                    if outcome == "completed":
                        events = sink.events()
                        self.assertEqual("message_stop", events[-1][0])
                        calls = [data["content_block"] for name, data in events
                                 if name == "content_block_start"]
                        self.assertEqual(["call_exit_race"], [call["id"] for call in calls])
                        self.assertNotIn("error", [name for name, _data in events])
                    else:
                        error = (sink.events()[-1][1]["error"] if opened_first
                                 else json.loads(bytes(sink.body))["error"])
                        expected = "insufficient_quota" if outcome == "quota" else "internal_error"
                        self.assertEqual(expected, error["code"])
                        self.assertNotIn("message_stop", [name for name, _data in sink.events()])

    def test_시스템_도구_미디어와_tool_choice를_Responses_요청으로_변환한다(self):
        # Given
        request = _anthropic_request(
            system=[{"type": "text", "text": "Top system", "cache_control": {"type": "ephemeral"}}],
            messages=[
                {"role": "user", "content": [
                    {"type": "text", "text": "Inspect these."},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AQ=="}},
                ]},
                {"role": "system", "content": [{"type": "text", "text": "Message system"}]},
                {"role": "assistant", "content": [
                    {"type": "tool_reference", "tool_name": "Deferred"},
                    {"type": "tool_use", "id": "call-old", "name": "Read", "input": {"file_path": "a.txt"}},
                ]},
                {"role": "user", "content": [{
                    "type": "tool_result", "tool_use_id": "call-old", "is_error": True,
                    "content": [
                        {"type": "text", "text": "permission denied"},
                        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "Ag=="}},
                        {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": "Aw=="}},
                    ],
                }]},
                {"role": "assistant", "content": [{"type": "thinking", "thinking": "private"}]},
                {"role": "user", "content": [{"type": "web_search_tool_result", "content": [
                    {"title": "Result", "url": "https://example.test/result"},
                ]}]},
            ],
            tools=[
                {"name": "Read", "description": "Read files", "input_schema": _schema()},
                {"name": "Deferred", "description": "Deferred file action", "input_schema": _schema(), "defer_loading": True},
                {"name": "web_search", "type": "web_search_20250305", "input_schema": {"type": "object"}},
            ],
            tool_choice={"type": "tool", "name": "Deferred"},
            output_config={"effort": "xhigh"},
        )

        # When
        translated = gateway.translate_messages_request(request, self.profile_id)
        payload, _ = helper.build_responses_payload(translated, subscription=False)

        # Then
        self.assertEqual("Top system\n\nMessage system", payload["instructions"])
        self.assertEqual({"effort": "xhigh"}, payload["reasoning"])
        self.assertEqual({"type": "function", "name": "Deferred"}, payload["tool_choice"])
        self.assertEqual({"Read", "Deferred"}, {tool["name"] for tool in translated["tools"]})
        input_types = [block.get("type") for item in payload["input"]
                       for block in item.get("content", []) if isinstance(item, dict)]
        self.assertIn("input_image", input_types)
        self.assertIn("input_file", input_types)
        outputs = [item for item in payload["input"] if item.get("type") == "function_call_output"]
        self.assertTrue(outputs[0]["output"].startswith("Tool error: permission denied"))
        self.assertEqual("Result\nhttps://example.test/result",
                         payload["input"][-1]["content"][0]["text"])
        self.assertNotIn("private", json.dumps(payload))

    def test_effort이_없으면_helper가_reasoning을_요청하지_않는다(self):
        # Given
        request = _anthropic_request(model="gpt-6.1-sol")

        # When
        translated = gateway.translate_messages_request(request, self.profile_id)
        payload, _ = helper.build_responses_payload(translated, subscription=False)

        # Then
        self.assertIsNone(translated["effort"])
        self.assertNotIn("reasoning", payload)

    def test_ToolSearch_tool_result의_중첩_tool_reference는_deferred_schema를_열고_결과_텍스트는_보존한다(self):
        # Given
        request = _anthropic_request(
            messages=[
                {"role": "user", "content": "Start a file search."},
                {"role": "assistant", "content": [{"type": "tool_use", "id": "call_search",
                 "name": "Search", "input": {"file_path": "index.txt"}}]},
                {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call_search",
                 "content": [
                     {"type": "text", "text": "Search completed."},
                     {"type": "tool_reference", "tool_name": "ReadDeferred"},
                 ]}]},
            ],
            tools=[
                {"name": "Search", "input_schema": _schema()},
                {"name": "ReadDeferred", "input_schema": _schema(), "defer_loading": True},
            ],
        )

        # When
        translated = gateway.translate_messages_request(request, self.profile_id)
        payload, _ = helper.build_responses_payload(translated, subscription=False)

        # Then
        self.assertEqual({"Search", "ReadDeferred"}, {tool["name"] for tool in translated["tools"]})
        result = next(item for item in payload["input"] if item.get("type") == "function_call_output")
        self.assertEqual("Search completed.", result["output"])
        self.assertNotIn("ReadDeferred", result["output"])

    def test_정확한_secret_prefix가_없으면_요청을_forward하지_않는다(self):
        # Given
        provider = FakeProvider(stream=_sse(_completion(text="unused")))
        app = self._app(lambda: provider)
        sink = CaptureSink()
        body = json.dumps(_anthropic_request()).encode()

        # When
        app.handle_request("POST", "/wrong-secret/v1/messages", {}, body, sink)

        # Then
        self.assertEqual(404, sink.status)
        self.assertEqual([], provider.open_calls)
        self.assertEqual("not_found", json.loads(bytes(sink.body))["error"]["code"])

    def test_GPT_count_tokens는_404이고_provider를_호출하지_않는다(self):
        # Given
        provider = FakeProvider(stream=_sse(_completion(text="unused")))
        app = self._app(lambda: provider)
        sink = CaptureSink()
        body = json.dumps(_anthropic_request()).encode()

        # When
        app.handle_request("POST", "/test-secret/v1/messages/count_tokens", {}, body, sink)

        # Then
        self.assertEqual(404, sink.status)
        self.assertEqual([], provider.open_calls)
        self.assertEqual("count_tokens_unsupported", json.loads(bytes(sink.body))["error"]["code"])

    def test_비_GPT_요청은_hop_header만_제거하고_Claude에_원문으로_전달한다(self):
        # Given
        upstream = FakeProvider(
            stream=io.BytesIO(b"chunk-onechunk-two"), status=201,
            headers={"Connection": "X-Private-Hop", "X-Private-Hop": "hop-value", "X-Pass": "kept"},
        )
        log = FakeLog()
        app = self._app(lambda: FakeProvider(), claude_http_factory=lambda: upstream, logger=log)
        body = b'{ "model" : "claude-opus-5-5", "keep":true }'
        sink = CaptureSink()

        # When
        app.handle_request("POST", "/test-secret/v1/messages?q=1",
                           {"Host": "127.0.0.1", "Connection": "X-Private-Hop", "X-Private-Hop": "local",
                            "anthropic-beta": "oauth-feature; other-beta", "X-Keep": "yes"}, body, sink)

        # Then
        self.assertEqual(201, sink.status)
        self.assertEqual(b"chunk-onechunk-two", bytes(sink.body))
        sent = upstream.open_calls[0]
        self.assertEqual("https://api.anthropic.com/v1/messages?q=1", sent.full_url)
        self.assertEqual("POST", sent.get_method())
        self.assertEqual(body, sent.data)
        self.assertNotIn("host", {key.lower() for key in sent.headers})
        self.assertNotIn("x-private-hop", {key.lower() for key in sent.headers})
        self.assertEqual("yes", sent.get_header("X-keep"))
        self.assertEqual([("X-Pass", "kept")], sink.headers)
        self.assertEqual([{"oauth_capability": True}], log.accesses)

    def test_Claude_transport_exception은_safe_502로_변환하고_진단문을_숨긴다(self):
        # Given
        secret_diagnostic = "provider-auth-secret-must-not-leak"

        class FailingClaude:
            def open(self, _request):
                raise helper.ClaudeGptError("network_error", secret_diagnostic)

        app = self._app(lambda: FakeProvider(), claude_http_factory=lambda: FailingClaude())
        sink = CaptureSink()

        # When
        app.handle_request(
            "POST", "/test-secret/v1/messages", {"Content-Type": "application/json"},
            b'{"model":"claude-opus-5-5"}', sink,
        )

        # Then
        self.assertEqual(502, sink.status)
        error = json.loads(bytes(sink.body))["error"]
        self.assertEqual("claude_transport_error", error["code"])
        self.assertNotIn(secret_diagnostic, bytes(sink.body).decode("utf-8"))

    def test_Claude_큰_body와_stream_chunk를_끝까지_그대로_전달하고_첫_chunk를_먼저_쓴다(self):
        # Given
        first_written = threading.Event()
        release_second = threading.Event()

        class PausedStream:
            def __init__(self):
                self.read_count = 0

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read1(self, _size=-1):
                self.read_count += 1
                if self.read_count == 1:
                    return b"first-chunk"
                if self.read_count == 2:
                    release_second.wait(2)
                    return b"second-chunk"
                return b""

        class IncrementalSink(CaptureSink):
            def write(self, data):
                super().write(data)
                if data == b"first-chunk":
                    first_written.set()

        upstream = FakeProvider(stream=PausedStream(), status=201, headers={"X-Pass": "kept"})
        app = self._app(lambda: FakeProvider(), claude_http_factory=lambda: upstream)
        body = b'{"model":"claude-opus-5-5","padding":"' + b"x" * (gateway.MAX_BODY_BYTES + 1) + b'"}'
        sink = IncrementalSink()
        worker = threading.Thread(target=app.handle_request, args=(
            "POST", "/test-secret/v1/messages", {"Content-Type": "application/json"}, body, sink,
        ))

        # When
        worker.start()
        self.assertTrue(first_written.wait(2))

        # Then
        self.assertEqual(b"first-chunk", bytes(sink.body))
        self.assertTrue(worker.is_alive())
        self.assertEqual(body, upstream.open_calls[0].data)
        release_second.set()
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(b"first-chunksecond-chunk", bytes(sink.body))

    def test_Claude_요청이_blocked_read중_취소되면_upstream_stream을_닫는다(self):
        # Given
        entered = threading.Event()
        closed = threading.Event()

        class BlockingStream:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.close()

            def read1(self, _size=-1):
                entered.set()
                closed.wait(2)
                raise OSError("cancelled")

            def close(self):
                closed.set()

        upstream = FakeProvider(stream=BlockingStream())
        app = self._app(lambda: FakeProvider(), claude_http_factory=lambda: upstream)
        cancel_event = threading.Event()
        sink = CaptureSink()
        body = json.dumps({"model": "claude-opus-5-5"}).encode()
        worker = threading.Thread(target=app.handle_request, args=(
            "POST", "/test-secret/v1/messages", {"Content-Type": "application/json"}, body, sink,
        ), kwargs={"cancel_event": cancel_event})

        # When
        worker.start()
        self.assertTrue(entered.wait(2))
        cancel_event.set()
        worker.join(timeout=2)

        # Then
        self.assertFalse(worker.is_alive())
        self.assertTrue(closed.is_set())

    def test_Claude_error와_redirect_response를_buffering이나_redirect_없이_stream으로_받는다(self):
        # Given
        class UpstreamResponse:
            status = 302

            def getheaders(self):
                return [("Location", "https://private.invalid/redirect"), ("Content-Type", "text/plain")]

            def read(self, *_args):
                raise AssertionError("Claude response must remain streamed")

            def close(self):
                return None

        class Connection:
            def __init__(self):
                self.response = UpstreamResponse()
                self.request_args = None

            def request(self, *args, **kwargs):
                self.request_args = (args, kwargs)

            def getresponse(self):
                return self.response

            def close(self):
                return None

        connection = Connection()
        client = gateway._DirectHttpClient(read_timeout=None)
        request = gateway.urllib.request.Request(
            "https://api.anthropic.com/v1/messages", data=b"unchanged", method="POST",
        )

        # When
        with patch.object(gateway, "_OwnedHttpsConnection", return_value=connection):
            response = client.open(request)

        # Then
        self.assertEqual(302, response.status)
        self.assertEqual(b"", response.body)
        self.assertIs(connection.response, response.stream)
        self.assertEqual("/v1/messages", connection.request_args[0][1])
        self.assertEqual(b"unchanged", connection.request_args[1]["body"])

    def test_handler는_chunked_request를_decode하고_hop_framing을_전달하지_않는다(self):
        # Given
        upstream = FakeProvider(status=202, body=b"ok")
        app = self._app(lambda: FakeProvider(), claude_http_factory=lambda: upstream)
        headers = {"Transfer-Encoding": "chunked", "X-Pass": "yes"}
        wire_body = b"5\r\nhello\r\n6\r\n world\r\n0\r\n\r\n"

        # When
        _handler, statuses, _response_headers, response_body = self._dispatch_handler(app, wire_body, headers)

        # Then
        self.assertEqual([202], statuses)
        self.assertEqual(b"ok", response_body)
        sent = upstream.open_calls[0]
        self.assertEqual(b"hello world", sent.data)
        self.assertNotIn("transfer-encoding", {name.lower() for name, _value in sent.header_items()})
        self.assertEqual("yes", sent.get_header("X-pass"))

    def test_handler는_Content_Length와_chunked가_함께오면_upstream을_호출하지_않는다(self):
        # Given
        upstream = FakeProvider(status=202, body=b"unexpected")
        app = self._app(lambda: FakeProvider(), claude_http_factory=lambda: upstream)
        headers = {"Content-Length": "5", "Transfer-Encoding": "chunked"}

        # When
        _handler, statuses, _response_headers, body = self._dispatch_handler(
            app, b"5\r\nhello\r\n0\r\n\r\n", headers,
        )

        # Then
        self.assertEqual([400], statuses)
        self.assertEqual([], upstream.open_calls)
        self.assertEqual("invalid_request", json.loads(body)["error"]["code"])

    def test_handler는_잘못된_chunk_terminator를_safe_400으로_거부한다(self):
        # Given
        upstream = FakeProvider(status=202, body=b"unexpected")
        app = self._app(lambda: FakeProvider(), claude_http_factory=lambda: upstream)

        # When
        _handler, statuses, _response_headers, body = self._dispatch_handler(
            app, b"5\r\nhelloXX0\r\n\r\n", {"Transfer-Encoding": "chunked"},
        )

        # Then
        self.assertEqual([400], statuses)
        self.assertEqual([], upstream.open_calls)
        self.assertEqual("invalid_request", json.loads(body)["error"]["code"])

    def test_HEAD_pass_through는_response_body를_쓰지_않는다(self):
        # Given
        upstream = FakeProvider(stream=io.BytesIO(b"must-not-be-written"), status=200)
        app = self._app(lambda: FakeProvider(), claude_http_factory=lambda: upstream)
        sink = CaptureSink()

        # When
        app.handle_request("HEAD", "/test-secret/v1/raw", {}, b"", sink)

        # Then
        self.assertEqual(200, sink.status)
        self.assertEqual(b"", bytes(sink.body))

    def test_Claude_요청의_blocked_open도_취소되면_transport_cancel을_호출한다(self):
        # Given
        entered = threading.Event()
        closed = threading.Event()

        class BlockingOpen:
            def open(self, _request):
                entered.set()
                if not closed.wait(2):
                    raise TimeoutError("not cancelled")
                raise OSError("cancelled")

            def cancel(self):
                closed.set()

        upstream = BlockingOpen()
        app = self._app(lambda: FakeProvider(), claude_http_factory=lambda: upstream)
        cancel_event = threading.Event()
        sink = CaptureSink()
        body = json.dumps({"model": "claude-opus-5-5"}).encode()
        worker = threading.Thread(target=app.handle_request, args=(
            "POST", "/test-secret/v1/messages", {"Content-Type": "application/json"}, body, sink,
        ), kwargs={"cancel_event": cancel_event})

        # When
        worker.start()
        self.assertTrue(entered.wait(2))
        cancel_event.set()
        worker.join(timeout=2)

        # Then
        self.assertFalse(worker.is_alive())
        self.assertTrue(closed.is_set())

    def test_runtime_stop은_active_request_cancel을_호출하고_listener를_닫는다(self):
        # Given
        serving = threading.Event()
        stopping = threading.Event()
        closed = threading.Event()
        cancelled = threading.Event()

        class FakeServer:
            def serve_forever(self):
                serving.set()
                stopping.wait(2)

            def shutdown(self):
                stopping.set()

            def server_close(self):
                closed.set()

        runtime = gateway.GatewayRuntime(FakeServer(), "http://127.0.0.1/test", cancelled.set)

        # When
        runtime.start()
        self.assertTrue(serving.wait(2))
        runtime.stop()

        # Then
        self.assertTrue(cancelled.is_set())
        self.assertTrue(closed.is_set())
        self.assertIsNone(runtime.thread)

    def test_성공_텍스트를_Anthropic_SSE와_캐시_usage로_변환한다(self):
        # Given
        provider = FakeProvider(stream=_sse(
            {"type": "response.output_text.delta", "delta": "Hello"},
            _completion(text="Hello"),
        ))
        app = self._app(lambda: provider)

        # When
        sink = self._post(app)

        # Then
        events = sink.events()
        self.assertEqual(200, sink.status)
        self.assertEqual("text/event-stream; charset=utf-8", dict(sink.headers)["Content-Type"])
        self.assertEqual(["message_start", "content_block_start", "content_block_delta",
                          "content_block_stop", "message_delta", "message_stop"],
                         [name for name, _data in events])
        delta = next(data for name, data in events if name == "message_delta")
        self.assertEqual("end_turn", delta["delta"]["stop_reason"])
        self.assertEqual({"input_tokens": 6, "cache_read_input_tokens": 2, "output_tokens": 3}, delta["usage"])

    def test_sparse_완료는_EOF_검증후에만_tool_use와_reasoning_state를_공개한다(self):
        # Given
        function_call = {
            "id": "fc-item-1", "type": "function_call", "status": "completed",
            "call_id": "call_1", "namespace": "claude", "name": "Read",
            "arguments": '{"file_path":"a.txt"}',
        }
        provider = FakeProvider(stream=_sse(
            {"type": "response.output_item.added", "output_index": 0,
             "item": {"id": "rs-1", "type": "reasoning"}},
            {"type": "response.output_item.done", "output_index": 0,
             "item": {"id": "rs-1", "type": "reasoning", "encrypted_content": "opaque"}},
            {"type": "response.output_item.added", "output_index": 1,
             "item": {"id": "fc-item-1", "type": "function_call"}},
            {"type": "response.output_item.done", "output_index": 1, "item": function_call},
            _completion(output=[]),
        ))
        app = self._app(lambda: provider)

        # When
        sink = self._post(app, _anthropic_request(tools=[{
            "name": "Read", "description": "Read", "input_schema": _schema(),
        }]))

        # Then
        events = sink.events()
        self.assertEqual(200, sink.status)
        starts = [data["content_block"] for name, data in events if name == "content_block_start"]
        self.assertEqual([{ "type": "tool_use", "id": "call_1", "name": "Read", "input": {}}], starts)
        self.assertEqual(["call_1"], self.store.read_provider_state(self.profile_id)[0]["ids"])
        self.assertEqual("tool_use", next(data for name, data in events if name == "message_delta")["delta"]["stop_reason"])

    def test_sparse_completion_뒤_transport_failure는_도구와_state를_보내지_않는다(self):
        # Given
        call = {"id": "fc-item-term", "type": "function_call", "status": "completed",
                "call_id": "call_term", "namespace": "claude", "name": "Read",
                "arguments": '{"file_path":"a.txt"}'}
        encoded = _sse(
            {"type": "response.output_item.added", "output_index": 0,
             "item": {"id": call["id"], "type": "function_call"}},
            {"type": "response.output_item.done", "output_index": 0, "item": call},
            _completion(output=[]),
        )

        class BrokenStream(io.BytesIO):
            def readline(self, size=-1):
                if self.tell() == len(self.getvalue()):
                    raise OSError("private transport diagnostic")
                return super().readline(size)

        provider = FakeProvider(stream=BrokenStream(encoded))
        log = FakeLog()
        app = self._app(lambda: provider, logger=log)
        request = _anthropic_request(tools=[{"name": "Read", "description": "Read", "input_schema": _schema()}])

        # When
        sink = self._post(app, request)

        # Then
        events = sink.events()
        self.assertEqual(200, sink.status)
        self.assertEqual(["message_start", "error"], [name for name, _data in events])
        self.assertEqual("stream_after_completion", events[-1][1]["error"]["code"])
        self.assertEqual([], self.store.read_provider_state(self.profile_id))
        self.assertNotIn("call_term", bytes(sink.body).decode())
        self.assertNotIn("private transport diagnostic", bytes(sink.body).decode())
        self.assertEqual({"input_tokens": 8, "cached_input_tokens": 2, "output_tokens": 3,
                          "reasoning_tokens": 1}, log.attempts[0]["error"].provider_usage["usage"])

    def test_잘못되거나_중복되거나_알_수_없는_tool_call은_실행용_SSE를_보내지_않는다(self):
        # Given
        cases = [
            ("잘못된 ID", [{"type": "function_call", "id": "fc-invalid", "call_id": "call.invalid", "namespace": "claude",
                          "name": "Read", "arguments": '{"file_path":"a.txt"}'}], "unsupported_call_id"),
            ("중복 ID", [
                {"type": "function_call", "id": "fc-dup-1", "call_id": "call_dup", "namespace": "claude", "name": "Read",
                 "arguments": '{"file_path":"a.txt"}'},
                {"type": "function_call", "id": "fc-dup-2", "call_id": "call_dup", "namespace": "claude", "name": "Read",
                 "arguments": '{"file_path":"b.txt"}'},
            ], "invalid_tool_call"),
            ("미등록 도구", [{"type": "function_call", "id": "fc-unknown", "call_id": "call_unknown", "namespace": "claude",
                           "name": "Bash", "arguments": '{"file_path":"a.txt"}'}], "invalid_tool_call"),
        ]

        # When
        for case_name, output, code in cases:
            with self.subTest(case_name=case_name):
                provider = FakeProvider(stream=_sse(_completion(output=output)))
                app = self._app(lambda provider=provider: provider, max_attempts=1)
                request = _anthropic_request(tools=[{"name": "Read", "description": "Read", "input_schema": _schema()}])
                sink = self._post(app, request)

                # Then
                events = sink.events()
                self.assertEqual(200, sink.status)
                self.assertEqual("error", events[-1][0])
                self.assertEqual(code, events[-1][1]["error"]["code"])
                self.assertEqual([], self.store.read_provider_state(self.profile_id))
                self.assertNotIn('"type":"tool_use"', bytes(sink.body).decode())

    def test_잘린_이벤트는_retry_budget_안에서만_재시도하고_원래_history에_partial_text를_붙인다(self):
        # Given
        class CutAfterDelta(io.BytesIO):
            def readline(self, size=-1):
                if self.tell() == len(self.getvalue()):
                    raise OSError("private network cause")
                return super().readline(size)

        first = FakeProvider(stream=CutAfterDelta(_sse(
            {"type": "response.output_text.delta", "delta": "Partial"},
        )))
        second = FakeProvider(stream=_sse(
            {"type": "response.output_text.delta", "delta": " continuation"},
            _completion(text=" continuation"),
        ))
        sequence = iter([first, second])
        clock = FakeClock()
        app = self._app(lambda: next(sequence), clock=clock, wait=clock.wait, jitter=lambda: 0)

        # When
        sink = self._post(app)

        # Then
        events = sink.events()
        visible = "".join(data["delta"]["text"] for name, data in events
                          if name == "content_block_delta" and data.get("delta", {}).get("type") == "text_delta")
        self.assertEqual("Partial continuation", visible)
        self.assertEqual(2, len(first.open_calls) + len(second.open_calls))
        retry_payload = json.loads(second.open_calls[0].data)
        self.assertIn("Gateway recovery:", retry_payload["instructions"])
        self.assertEqual("Partial", retry_payload["input"][-1]["content"][0]["text"])
        self.assertEqual("message_stop", events[-1][0])

    def test_SSE_최상위_오류는_일시적_제한만_재시도하고_인증과_한도_오류는_중단한다(self):
        for code in ("rate_limit_exceeded", "insufficient_quota", "invalid_api_key", "private_error_code"):
            with self.subTest(code=code):
                # Given
                first = FakeProvider(stream=_sse({
                    "type": "error", "code": code, "message": "private diagnostic",
                }))
                second = FakeProvider(stream=_sse(_completion()))
                providers = iter([first, second])
                clock = FakeClock()
                app = self._app(lambda: next(providers), clock=clock, wait=clock.wait, jitter=lambda: 0)

                # When
                sink = self._post(app)

                # Then
                events = sink.events()
                self.assertEqual(1, len(first.open_calls))
                if code == "rate_limit_exceeded":
                    self.assertEqual(1, len(second.open_calls))
                    self.assertEqual("message_stop", events[-1][0])
                    self.assertAlmostEqual(1.0, sum(clock.waits))
                else:
                    self.assertEqual([], second.open_calls)
                    self.assertEqual([], clock.waits)
                    self.assertEqual("error", events[-1][0])
                    expected = "provider_failed" if code == "private_error_code" else code
                    self.assertEqual(expected, events[-1][1]["error"]["code"])
                    self.assertNotIn("message_stop", [name for name, _data in events])
                self.assertNotIn("private diagnostic", bytes(sink.body).decode())
                self.assertNotIn('"type":"tool_use"', bytes(sink.body).decode())
                self.assertEqual([], self.store.read_provider_state(self.profile_id))

    def test_복구_60초가_지나면_열린_재시도_stream도_닫고_새_요청을_보내지_않는다(self):
        # Given
        clock = FakeClock()
        closed = threading.Event()

        class BlockingStream:
            def readline(self, size=-1):
                clock.value = 61.0
                if not closed.wait(2):
                    raise AssertionError("recovery deadline did not close the stream")
                raise OSError("cancelled")

            def close(self):
                closed.set()

        first = FakeProvider(status=503, body=b'{"error":{"code":"server_error"}}')
        second = FakeProvider(stream=BlockingStream())
        providers = iter([first, second])
        app = self._app(lambda: next(providers), clock=clock, wait=clock.wait, jitter=lambda: 0)

        # When
        sink = self._post(app)

        # Then
        self.assertTrue(closed.is_set())
        self.assertEqual(2, len(first.open_calls) + len(second.open_calls))
        self.assertEqual("gateway_recovery_deadline", sink.events()[-1][1]["error"]["code"])
        self.assertNotIn("message_stop", [name for name, _data in sink.events()])
        self.assertEqual([], self.store.read_provider_state(self.profile_id))

    def test_continuation의_정상_접두문자를_잘라내지_않고_모든_delta를_전달한다(self):
        # Given
        class CutAfterDelta(io.BytesIO):
            def readline(self, size=-1):
                if self.tell() == len(self.getvalue()):
                    raise OSError("private network cause")
                return super().readline(size)

        first = FakeProvider(stream=CutAfterDelta(_sse(
            {"type": "response.output_text.delta", "delta": "A"},
        )))
        second = FakeProvider(stream=_sse(
            {"type": "response.output_text.delta", "delta": "Again"},
            _completion(text="Again"),
        ))
        sequence = iter([first, second])
        clock = FakeClock()
        app = self._app(lambda: next(sequence), clock=clock, wait=clock.wait, jitter=lambda: 0)

        # When
        sink = self._post(app)

        # Then
        visible = "".join(data["delta"]["text"] for name, data in sink.events()
                          if name == "content_block_delta" and data.get("delta", {}).get("type") == "text_delta")
        self.assertEqual("AAgain", visible)

    def test_복구_연결이_열리기를_기다리는_동안에도_기존_stream에_ping을_보낸다(self):
        # Given
        ping_received = threading.Event()
        clock = FakeClock()
        first = FakeProvider(stream=_sse({"type": "response.output_text.delta", "delta": "앞부분"}))

        class WaitingProvider(FakeProvider):
            def open(self, request):
                clock.value = 12.0
                if not ping_received.wait(2):
                    raise AssertionError("no ping before retry stream opening")
                return super().open(request)

        class PingSink(CaptureSink):
            def write(self, data):
                super().write(data)
                if data.startswith(b"event: ping\n"):
                    ping_received.set()

        second = WaitingProvider(stream=_sse(
            {"type": "response.output_text.delta", "delta": "이어쓰기"},
            _completion(text="이어쓰기"),
        ))
        providers = iter([first, second])
        app = self._app(lambda: next(providers), clock=clock, wait=clock.wait, jitter=lambda: 0)

        # When
        sink = self._post(app, sink=PingSink())

        # Then
        self.assertTrue(ping_received.is_set())
        self.assertEqual(1, len(second.open_calls))
        self.assertEqual("message_stop", sink.events()[-1][0])

    def test_HTTP_연결이_응답_전에_끊기면_새_연결로_재시도한다(self):
        # Given
        class DisconnectedProvider(FakeProvider):
            def open(self, request):
                self.open_calls.append(request)
                try:
                    raise gateway.http.client.RemoteDisconnected("private disconnect detail")
                except gateway.http.client.RemoteDisconnected as cause:
                    raise helper.ClaudeGptError("network_error", "safe transport failure") from cause

        first = DisconnectedProvider()
        second = FakeProvider(stream=_sse(
            {"type": "response.output_text.delta", "delta": "연결 복구"},
            _completion(text="연결 복구"),
        ))
        providers = iter([first, second])
        clock = FakeClock()
        app = self._app(lambda: next(providers), clock=clock, wait=clock.wait, jitter=lambda: 0)

        # When
        sink = self._post(app)

        # Then
        self.assertEqual(2, len(first.open_calls) + len(second.open_calls))
        self.assertEqual("message_stop", sink.events()[-1][0])
        self.assertNotIn("private disconnect", bytes(sink.body).decode())

    def test_문자열이_아닌_model은_GPT로_선택하지_않고_Claude에_원문으로_전달한다(self):
        # Given
        claude = FakeProvider(stream=b"unchanged")
        app = self._app(lambda: self.fail("GPT must not be called"), claude_http_factory=lambda: claude)
        request = _anthropic_request(model={"unexpected": "value"})

        # When
        sink = self._post(app, request)

        # Then
        self.assertEqual(request, json.loads(claude.open_calls[0].data))
        self.assertEqual(b"unchanged", bytes(sink.body))

    def test_공유_attempt_budget은_다음_Messages까지_적용되고_local_limit을_명시한다(self):
        # Given
        provider = FakeProvider(stream=_sse(
            {"type": "response.output_text.delta", "delta": "Done"},
            _completion(text="Done"),
        ))
        budget = gateway.GatewayRequestBudget(max_attempts=1)
        app = self._app(lambda: provider, request_budget=budget)

        # When
        first = self._post(app)
        second = self._post(app)

        # Then
        self.assertEqual(200, first.status)
        self.assertEqual(429, second.status)
        self.assertEqual("gateway_request_budget_exhausted", json.loads(bytes(second.body))["error"]["code"])
        self.assertEqual(1, len(provider.open_calls))

    def test_공유_monotonic_deadline이_retry_wait보다_짧으면_budget_error로_끝낸다(self):
        # Given
        provider = FakeProvider(
            status=503, body=b'{"error":{"type":"server_error","code":"server_error"}}',
        )
        clock = FakeClock()
        budget = gateway.GatewayRequestBudget(max_attempts=2, deadline=0.5)
        app = self._app(lambda: provider, clock=clock, wait=clock.wait, jitter=lambda: 0,
                        request_budget=budget)

        # When
        sink = self._post(app)

        # Then
        self.assertEqual(429, sink.status)
        self.assertEqual("gateway_request_budget_exhausted", json.loads(bytes(sink.body))["error"]["code"])
        self.assertEqual(1, len(provider.open_calls))
        self.assertEqual([], clock.waits)

    def test_첫_attempt의_shared_deadline도_blocked_open을_취소하고_local_limit로_끝낸다(self):
        # Given
        entered = threading.Event()
        cancelled = threading.Event()

        class BlockingProvider:
            def open(self, _request):
                entered.set()
                cancelled.wait(2)
                raise OSError("test provider cancelled")

            def cancel(self):
                cancelled.set()

        class DeadlineClock:
            def __init__(self):
                self.calls = 0

            def __call__(self):
                self.calls += 1
                if self.calls == 1:
                    return 0.0
                if not entered.wait(2):
                    raise AssertionError("provider open did not start before deadline check")
                return 2.0

        provider = BlockingProvider()
        logger = FakeLog()
        budget = gateway.GatewayRequestBudget(deadline=1.0)
        app = self._app(lambda: provider, logger=logger, clock=DeadlineClock(), request_budget=budget)

        # When
        sink = self._post(app)

        # Then
        self.assertEqual(429, sink.status)
        self.assertEqual("gateway_request_budget_exhausted", json.loads(bytes(sink.body))["error"]["code"])
        self.assertTrue(cancelled.is_set())
        self.assertEqual("terminal", logger.attempts[0]["outcome"])
        self.assertEqual("gateway_request_budget_exhausted", logger.attempts[0]["error"].code)

    def test_잘린_tool_call은_completed_전에는_tool_use나_reasoning_state를_보내지_않는다(self):
        # Given
        provider = FakeProvider(stream=_sse(
            {"type": "response.output_item.added", "output_index": 0,
             "item": {"id": "fc-partial", "type": "function_call"}},
            {"type": "response.function_call_arguments.delta", "output_index": 0,
             "delta": '{"file_path":"private.txt"'},
        ))
        app = self._app(lambda: provider, max_attempts=1)
        request = _anthropic_request(tools=[{
            "name": "Read", "description": "Read", "input_schema": _schema(),
        }])

        # When
        sink = self._post(app, request)

        # Then
        events = sink.events()
        self.assertEqual(200, sink.status)
        self.assertEqual("error", events[-1][0])
        self.assertNotIn('"type":"tool_use"', bytes(sink.body).decode())
        self.assertEqual([], self.store.read_provider_state(self.profile_id))
        self.assertEqual(1, len(provider.open_calls))

    def test_Retry_After가_recovery_budget보다_길면_기다리거나_재시도하지_않는다(self):
        # Given
        provider = FakeProvider(
            status=503, headers={"Retry-After": "120"},
            body=b'{"error":{"type":"server_error","code":"server_error"}}',
        )
        clock = FakeClock()
        app = self._app(lambda: provider, clock=clock, wait=clock.wait, jitter=lambda: 0)

        # When
        sink = self._post(app)

        # Then
        self.assertEqual(429, sink.status)
        self.assertEqual("gateway_retry_exhausted", json.loads(bytes(sink.body))["error"]["code"])
        self.assertEqual(1, len(provider.open_calls))
        self.assertEqual([], clock.waits)

    def test_retry_wait_중_취소되면_두번째_provider_attempt를_열지_않는다(self):
        # Given
        provider = FakeProvider(
            status=503, body=b'{"error":{"type":"server_error","code":"server_error"}}',
        )
        clock = FakeClock()
        cancelled = threading.Event()

        def cancel_during_wait(event, seconds):
            clock.waits.append(seconds)
            clock.value += seconds
            cancelled.set()
            return True

        app = self._app(lambda: provider, clock=clock, wait=cancel_during_wait, jitter=lambda: 0)
        sink = CaptureSink()
        body = json.dumps(_anthropic_request()).encode()

        # When
        app.handle_request("POST", "/test-secret/v1/messages", {"Content-Type": "application/json"},
                           body, sink, cancel_event=cancelled)

        # Then
        self.assertEqual(1, len(provider.open_calls))
        self.assertEqual(1, len(clock.waits))
        self.assertIsNone(sink.status)
        self.assertEqual(b"", bytes(sink.body))

    def test_launcher는_빈_인증환경변수도_존재하면_plugin_조회전에_거부한다(self):
        # Given
        calls = []

        # When
        with self.assertRaises(helper.ClaudeGptError) as raised:
            gateway.launch(
                self.profile_id, [], store=self.store,
                environ={"PATH": "/usr/bin", "ANTHROPIC_BASE_URL": "",
                         "CLAUDE_CONFIG_DIR": str(self.root / "config")},
                cwd=self.root, run=lambda *args, **kwargs: calls.append(args), source_version="2.2.0",
            )

        # Then
        self.assertEqual("launcher_auth_conflict", raised.exception.code)
        self.assertEqual([], calls)

    def test_구조화된_quota_code가_retryable_HTTP_status보다_우선한다(self):
        # Given
        provider = FakeProvider(
            status=503, body=b'{"error":{"code":"insufficient_quota","message":"secret provider text"}}',
        )
        log = FakeLog()
        app = self._app(lambda: provider, logger=log)

        # When
        sink = self._post(app)

        # Then
        self.assertEqual(429, sink.status)
        body = bytes(sink.body).decode()
        self.assertIn("rate_limit_error", body)
        self.assertNotIn("secret provider text", body)
        self.assertEqual(1, len(provider.open_calls))
        self.assertEqual("insufficient_quota", log.attempts[0]["error"].provider_code)

    def test_알_수_없는_bare_429는_자동_retry하지_않고_terminal_validation으로_매핑한다(self):
        # Given
        provider = FakeProvider(status=429, body=b'{"error":{"message":"secret throttle text"}}')
        app = self._app(lambda: provider)

        # When
        sink = self._post(app)

        # Then
        self.assertEqual(400, sink.status)
        self.assertEqual(1, len(provider.open_calls))
        error = json.loads(bytes(sink.body))["error"]
        self.assertEqual("invalid_request_error", error["type"])
        self.assertNotIn("secret throttle text", bytes(sink.body).decode())

    def test_unknown_structured_503은_terminal이고_bare_503만_retry한다(self):
        # Given
        unknown = FakeProvider(
            status=503,
            body=b'{"error":{"code":"secret_unknown_code","message":"private diagnostic"}}',
        )
        unknown_log = FakeLog()
        unknown_app = self._app(lambda: unknown, logger=unknown_log)
        retryable = FakeProvider(
            status=503, body=b'{"error":{"message":"temporary provider response"}}',
        )
        success = FakeProvider(stream=_sse(
            {"type": "response.output_text.delta", "delta": "Ready"},
            _completion(text="Ready"),
        ))
        sequence = iter([retryable, success])
        clock = FakeClock()
        retry_app = self._app(lambda: next(sequence), clock=clock, wait=clock.wait, jitter=lambda: 0)

        # When
        unknown_sink = self._post(unknown_app)
        retry_sink = self._post(retry_app)

        # Then
        self.assertEqual(1, len(unknown.open_calls))
        self.assertEqual("unknown_provider_error", unknown_log.attempts[0]["error"].code)
        self.assertIsNone(unknown_log.attempts[0]["error"].provider_code)
        self.assertNotIn("secret_unknown_code", bytes(unknown_sink.body).decode())
        self.assertEqual(200, retry_sink.status)
        self.assertEqual(2, len(retryable.open_calls) + len(success.open_calls))

    def test_bare_HTTP_401_와_403은_각각_authentication과_permission_error다(self):
        # Given
        errors = [
            helper.ClaudeGptError("http_error", "safe", http_status=401),
            helper.ClaudeGptError("http_error", "safe", http_status=403),
        ]

        # When
        mapped = [gateway._map_error(error) for error in errors]

        # Then
        self.assertEqual(["authentication_error", "permission_error"], [item[1] for item in mapped])

    def test_certificate_transport_failure는_attempt를_반복하지_않고_api_error를_쓰지_않는다(self):
        # Given
        import ssl

        class CertificateFailure:
            def open(self, _request):
                try:
                    raise ssl.SSLCertVerificationError("private certificate diagnostic")
                except ssl.SSLCertVerificationError as cause:
                    raise helper.ClaudeGptError("network_error", "safe transport error") from cause

        log = FakeLog()
        app = self._app(lambda: CertificateFailure(), logger=log, max_attempts=3)

        # When
        sink = self._post(app)

        # Then
        self.assertEqual(400, sink.status)
        self.assertEqual(1, len(log.attempts))
        error = json.loads(bytes(sink.body))["error"]
        self.assertEqual("invalid_request_error", error["type"])
        self.assertNotIn("api_error", bytes(sink.body).decode())
        self.assertNotIn("private certificate diagnostic", bytes(sink.body).decode())

    def test_cause가_없는_unknown_network_error는_temporary로_추정하지_않는다(self):
        # Given
        class UnknownTransportFailure:
            def __init__(self):
                self.open_calls = 0

            def open(self, _request):
                self.open_calls += 1
                raise helper.ClaudeGptError("network_error", "safe")

        provider = UnknownTransportFailure()
        app = self._app(lambda: provider, max_attempts=3)

        # When
        sink = self._post(app)

        # Then
        self.assertEqual(400, sink.status)
        self.assertEqual(1, provider.open_calls)
        self.assertEqual("invalid_request_error", json.loads(bytes(sink.body))["error"]["type"])

    def test_gateway_final_error_mapping은_local_limit과_completed_validation을_terminal로_유지한다(self):
        # Given
        errors = [
            helper.ClaudeGptError("gateway_recovery_deadline", "safe"),
            helper.ClaudeGptError("gateway_request_budget_exhausted", "safe"),
            helper.ClaudeGptError("stream_after_completion", "safe", terminal_after_completion=True),
            helper.ClaudeGptError("internal_error", "safe"),
        ]

        # When
        mapped = [gateway._map_error(error) for error in errors]

        # Then
        self.assertEqual(["rate_limit_error", "rate_limit_error", "invalid_request_error", "invalid_request_error"],
                         [item[1] for item in mapped])
        self.assertNotIn("api_error", {item[1] for item in mapped})
        self.assertIn("recovery deadline", mapped[0][2])
        self.assertNotIn("approved request limit", mapped[0][2])
        self.assertIn("approved request limit", mapped[1][2])

    def test_취소는_현재_upstream_read를_shutdown하고_추가도구나_state를_막는다(self):
        # Given
        entered = threading.Event()
        closed = threading.Event()

        class BlockingStream:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

            def readline(self, size=-1):
                entered.set()
                if not closed.wait(2):
                    raise TimeoutError("test stream not cancelled")
                raise OSError("cancelled")

            def close(self):
                closed.set()

        call = {"id": "fc-item-cancel", "type": "function_call", "status": "completed",
                "call_id": "call_cancel", "namespace": "claude", "name": "Read",
                "arguments": '{"file_path":"a.txt"}'}
        provider = FakeProvider(stream=BlockingStream())
        log = gateway.PrivateGatewayLog(self.store, self.profile_id)
        app = self._app(lambda: provider, logger=log)
        cancelled = threading.Event()
        request = _anthropic_request(tools=[{"name": "Read", "description": "Read", "input_schema": _schema()}])
        sink = CaptureSink()
        body = json.dumps(request).encode()

        def cancel_when_reading():
            self.assertTrue(entered.wait(2))
            cancelled.set()

        cancel_thread = threading.Thread(target=cancel_when_reading)
        cancel_thread.start()

        # When
        app.handle_request("POST", "/test-secret/v1/messages", {"Content-Type": "application/json"},
                           body, sink, cancel_event=cancelled)
        cancel_thread.join(timeout=2)

        # Then
        self.assertTrue(closed.is_set())
        self.assertEqual([], self.store.read_provider_state(self.profile_id))
        self.assertNotIn("call_cancel", bytes(sink.body).decode())
        records = [json.loads(line) for line in log.path.read_text().splitlines()]
        attempt = next(record for record in records if record.get("kind") == "gpt_attempt")
        self.assertEqual("cancelled", attempt["outcome"])
        self.assertEqual("unknown", attempt["usage"])

    def test_private_log_허용필드만_0600으로_회전하고_unknown_usage를_유지한다(self):
        # Given
        log = gateway.PrivateGatewayLog(self.store, self.profile_id)
        error = helper.ClaudeGptError("stream_interrupted", "safe", request_id="req_123")

        # When
        with patch.object(gateway, "MAX_LOG_BYTES", 150):
            log.access(oauth_capability=True)
            log.attempt(number=1, outcome="failed", error=error)
            log.attempt(number=2, outcome="failed", error=helper.ClaudeGptError("private", "safe"))

        # Then
        current = log.path.read_text()
        self.assertEqual(0o600, log.path.stat().st_mode & 0o777)
        self.assertTrue(log.path.with_name("gateway.log.1").exists())
        self.assertIn('"usage":"unknown"', current)
        self.assertNotIn("access-token", current)
        self.assertEqual(0o700, log.path.parent.stat().st_mode & 0o777)

    def test_launcher는_인증충돌_arguments와_plugin_version을_확인한_뒤_실행한다(self):
        # Given
        class Runtime:
            base_url = "http://127.0.0.1:43210/gateway-secret"
            started = False
            stopped = False

            def start(self):
                self.started = True

            def stop(self):
                self.stopped = True

        runtime = Runtime()
        calls = []

        def run(args, **kwargs):
            calls.append((args, kwargs))
            if args[1:3] == ["plugin", "list"]:
                return SimpleNamespace(returncode=0, stdout=json.dumps([{
                    "id": gateway.PLUGIN_ID, "version": "2.2.0+cachebuster", "enabled": True,
                    "projectEnabled": False,
                }]))
            return SimpleNamespace(returncode=7)

        def make_runtime(_profile_id, *, store):
            self.assertIs(self.store, store)
            return runtime

        # When
        result = gateway.launch(
            self.profile_id, ["--project-config-root", str(self.root / "project-config"),
                              "-p", "unchanged", "--resume", "session"], store=self.store,
            environ={"PATH": "/usr/bin", "CLAUDE_CONFIG_DIR": str(self.root / "config")}, cwd=self.root, run=run,
            gateway_factory=make_runtime, source_version="2.2.0",
        )

        # Then
        self.assertEqual(7, result)
        self.assertTrue(runtime.started)
        self.assertTrue(runtime.stopped)
        child_args, child_kwargs = calls[1]
        self.assertEqual(["claude", "--project-config-root", str(self.root / "project-config"),
                          "-p", "unchanged", "--resume", "session"], child_args)
        self.assertEqual(self.root, calls[0][1]["cwd"])
        self.assertEqual(self.root, child_kwargs["cwd"])
        self.assertEqual({"PATH": "/usr/bin", "CLAUDE_CONFIG_DIR": str(self.root / "config")},
                         calls[0][1]["env"])
        self.assertEqual(runtime.base_url, child_kwargs["env"]["ANTHROPIC_BASE_URL"])
        self.assertEqual(runtime.base_url, child_kwargs["env"]["HEI5ENBUG_GPT_GATEWAY_URL"])
        self.assertEqual("1", child_kwargs["env"]["CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK"])
        self.assertNotIn("capture_output", child_kwargs)

    def test_launcher는_settings에_auth_key가_있으면_값을_출력하지_않고_거부한다(self):
        # Given
        settings_dir = self.root / ".claude"
        settings_dir.mkdir()
        secret = "settings-auth-secret-must-not-leak"
        (settings_dir / "settings.local.json").write_text(json.dumps({"env": {"ANTHROPIC_AUTH_TOKEN": secret}}))
        calls = []

        # When
        with self.assertRaises(helper.ClaudeGptError) as raised:
            gateway.launch(
                self.profile_id, [], store=self.store,
                environ={"PATH": "/usr/bin", "CLAUDE_CONFIG_DIR": str(self.root / "config")}, cwd=self.root,
                run=lambda *args, **kwargs: calls.append(args), source_version="2.2.0",
            )

        # Then
        self.assertEqual("launcher_auth_conflict", raised.exception.code)
        self.assertEqual([], calls)
        self.assertNotIn(secret, str(raised.exception))

    def test_launcher는_인증소스를_바꾸는_claude_argument를_거부한다(self):
        # Given
        calls = []

        # When
        with self.assertRaises(helper.ClaudeGptError) as raised:
            gateway.launch(
                self.profile_id, ["--settings=secret.json"], store=self.store,
                environ={"PATH": "/usr/bin", "CLAUDE_CONFIG_DIR": str(self.root / "config")}, cwd=self.root,
                run=lambda *args, **kwargs: calls.append(args), source_version="2.2.0",
            )

        # Then
        self.assertEqual("launcher_argument_conflict", raised.exception.code)
        self.assertEqual([], calls)

    def test_git_root의_settings_local도_auth_override_key만_확인한다(self):
        # Given
        project = self.root / "project"
        nested = project / "packages" / "app"
        (project / ".git").mkdir(parents=True)
        nested.mkdir(parents=True)
        settings = project / ".claude" / "settings.local.json"
        settings.parent.mkdir()
        secret = "must-not-be-read-or-exposed"
        settings.write_text(json.dumps({"env": {"ANTHROPIC_AUTH_TOKEN": secret}}))

        # When
        conflict = gateway._settings_conflict(
            {"CLAUDE_CONFIG_DIR": str(self.root / "empty-config")}, nested,
        )

        # Then
        self.assertTrue(conflict)

    def test_project_config_root_override의_project와_local_settings도_guard한다(self):
        # Given
        config_root = self.root / "selected-project"
        local_settings = config_root / ".claude" / "settings.local.json"
        local_settings.parent.mkdir(parents=True)
        local_settings.write_text(json.dumps({"env": {"ANTHROPIC_BASE_URL": "do-not-print"}}))
        arguments = ["--project-config-root=" + str(config_root)]

        # When
        conflict = gateway._settings_conflict(
            {"CLAUDE_CONFIG_DIR": str(self.root / "empty-config")}, self.root, arguments,
        )

        # Then
        self.assertTrue(conflict)

    def test_managed_settings_d의_visible_json_settings도_guard한다(self):
        # Given
        managed_root = self.root / "managed"
        managed_settings = managed_root / "managed-settings.d" / "40-policy.json"
        managed_settings.parent.mkdir(parents=True)
        managed_settings.write_text(json.dumps({"env": {"CLAUDE_CODE_USE_VERTEX": "hidden-value"}}))

        # When
        with patch.object(gateway, "_managed_settings_root", return_value=managed_root):
            conflict = gateway._settings_conflict(
                {"CLAUDE_CONFIG_DIR": str(self.root / "empty-config")}, self.root,
            )

        # Then
        self.assertTrue(conflict)


if __name__ == "__main__":
    unittest.main()
