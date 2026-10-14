from __future__ import annotations

import base64
import importlib.util
import io
import json
import os
import stat
import tempfile
import threading
import time
import unittest
import urllib.parse
from pathlib import Path
from http.client import IncompleteRead
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric import rsa
import jwt


REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("claude_gpt_helper", REPO_ROOT / "scripts/claude_gpt.py")
claude_gpt = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
import sys
sys.modules[SPEC.name] = claude_gpt
SPEC.loader.exec_module(claude_gpt)


def _b64url_int(value: int) -> str:
    size = (value.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(value.to_bytes(size, "big")).decode("ascii").rstrip("=")


def _schema() -> dict:
    return {
        "type": "object",
        "properties": {"file_path": {"type": "string"}},
        "required": ["file_path"],
        "additionalProperties": False,
    }


def _request(profile_id: str, *, history: list[dict] | None = None, tools: list[dict] | None = None,
             session_id: str = "session-test", step_id: str = "step-1") -> dict:
    return {
        "protocol_version": 1,
        "request_id": "request-test",
        "session_id": session_id,
        "turn_id": "turn-test",
        "step_id": step_id,
        "model": "gpt-5.6-luna",
        "effort": "xhigh",
        "profile_id": profile_id,
        "system": "System policy.",
        "developer": ["Developer policy."],
        "history": history or [{"role": "user", "content": [{"type": "text", "text": "Read a file."}]}],
        "tools": tools if tools is not None else [{"name": "Read", "description": "Read a file.", "input_schema": _schema()}],
    }


def _sse(*events: dict) -> bytes:
    chunks = []
    for event in events:
        name = event["type"]
        chunks.append(f"event: {name}\ndata: {json.dumps(event, separators=(',', ':'))}\n\n".encode())
    return b"".join(chunks)


class FakeHttp:
    def __init__(self, *, discovery: dict | None = None, token: dict | None = None,
                 jwks: dict | None = None, stream: Any = None, status: int = 200,
                 error_body: bytes = b"{}", response_headers: dict[str, str] | None = None):
        self.discovery = discovery or {
            "issuer": claude_gpt.OAUTH_ISSUER,
            "authorization_endpoint": "https://auth.openai.com/api/accounts/authorize",
            "token_endpoint": "https://auth.openai.com/api/accounts/oauth/token",
            "jwks_uri": "https://auth.openai.com/.well-known/jwks.json",
            "revocation_endpoint": "https://auth.openai.com/api/accounts/oauth/revoke",
        }
        self.token = token or {}
        self.jwks = jwks or {"keys": []}
        self.stream = stream
        self.status = status
        self.error_body = error_body
        self.response_headers = response_headers or {}
        self.json_calls = []
        self.open_calls = []
        self.lock = threading.Lock()

    def json(self, url, *, method="GET", data=None, headers=None):
        with self.lock:
            self.json_calls.append({"url": url, "method": method, "data": data, "headers": dict(headers or {})})
        if url == claude_gpt.DISCOVERY_URL:
            return self.discovery
        if url == self.discovery["token_endpoint"]:
            return self.token
        if url == self.discovery["jwks_uri"]:
            return self.jwks
        raise AssertionError(f"unexpected fake URL: {url}")

    def open(self, request):
        with self.lock:
            self.open_calls.append(request)
        if self.status < 200 or self.status >= 300:
            return claude_gpt.HttpResponse(self.status, self.response_headers, self.error_body)
        if self.stream is None:
            return claude_gpt.HttpResponse(200, self.response_headers, b"")
        stream = self.stream if hasattr(self.stream, "readline") else io.BytesIO(self.stream)
        return claude_gpt.HttpResponse(
            200, {"Content-Type": "text/event-stream", **self.response_headers}, b"", stream,
        )


class ClaudeGptTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="w3-claude-gpt-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.store = claude_gpt.ProfileStore(self.base / "claude-gpt")

    def _subscription_http(self, *, scope=claude_gpt.OAUTH_SCOPES, nonce="nonce-value"):
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_numbers = private_key.public_key().public_numbers()
        jwk = {
            "kty": "RSA", "kid": "offline-key", "use": "sig", "alg": "RS256",
            "n": _b64url_int(public_numbers.n), "e": _b64url_int(public_numbers.e),
        }
        now = int(time.time())
        token = jwt.encode({
            "iss": claude_gpt.OAUTH_ISSUER,
            "aud": "oaiapp_issued-client",
            "sub": "account-subject-1",
            "nonce": nonce,
            "email": "account@example.test",
            "iat": now,
            "exp": now + 3600,
        }, private_key, algorithm="RS256", headers={"kid": "offline-key"})
        http = FakeHttp(
            token={"access_token": "access-secret", "refresh_token": "refresh-secret", "id_token": token,
                   "token_type": "Bearer", "expires_in": 3600, "scope": scope},
            jwks={"keys": [jwk]},
        )
        return http, now, private_key

    def test_출시_gateway가_없으면_안전한_오류를_내고_시작하지_않는다(self):
        # Given
        def unexpected(*args, **kwargs):
            raise AssertionError("launch inspected state or used the network")

        # When
        missing = ModuleNotFoundError("gateway unavailable", name="claude_gpt_gateway")
        with patch.object(claude_gpt.ProfileStore, "default", unexpected), \
                patch.object(claude_gpt, "HttpClient", unexpected), \
                patch.object(claude_gpt.importlib, "import_module", side_effect=missing):
            with self.assertRaises(claude_gpt.ClaudeGptError) as raised:
                claude_gpt.main(["launch", "--profile", "p_" + "c" * 32])

        # Then
        self.assertEqual("gateway_not_available", raised.exception.code)
        self.assertNotIn("Traceback", raised.exception.message)
        self.assertFalse(self.store.root.exists())

    def test_출시가_프로필과_구분자_뒤의_Claude_인자를_gateway에_그대로_전달한다(self):
        # Given
        profile_id = "p_" + "d" * 32
        received = []

        def launch(profile, arguments):
            received.append((profile, arguments))
            return 17

        gateway = type("Gateway", (), {"launch": staticmethod(launch)})()

        # When
        with patch.object(claude_gpt.ProfileStore, "default", side_effect=AssertionError("store accessed")), \
                patch.object(claude_gpt, "HttpClient", side_effect=AssertionError("network client created")), \
                patch.object(claude_gpt.importlib, "import_module", return_value=gateway):
            result = claude_gpt.main([
                "launch", "--profile", profile_id, "--", "--model", "gpt-6.1-sol", "-p", "prompt text",
            ])

        # Then
        self.assertEqual(17, result)
        self.assertEqual([(profile_id, ["--model", "gpt-6.1-sol", "-p", "prompt text"])], received)

    def test_nullable_effort_tool_choice와_열린_JSON_Schema를_Responses_요청에_그대로_보낸다(self):
        # Given
        profile_id = "p_" + "e" * 32
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {"path": {"type": "string", "minLength": 1}},
            "type": ["object", "null"],
            "properties": {"file_path": {"$ref": "#/$defs/path", "type": ["string", "null"]}},
            "required": ["file_path"],
            "anyOf": [{"properties": {"file_path": {"pattern": "^[a-z]"}}}],
        }
        request = _request(profile_id, tools=[{"name": "Read", "description": "Read.", "input_schema": schema}])
        request["model"] = "gpt-6.1-sol"
        request["effort"] = None
        request["tool_choice"] = {"type": "function", "name": "Read"}

        # When
        payload, _ = claude_gpt.build_responses_payload(request, subscription=False)
        accepted = claude_gpt._validate_tool_input(
            {"file_path": "a.txt", "extra": 7}, schema, "test",
        )

        # Then
        self.assertEqual({"file_path": "a.txt", "extra": 7}, accepted)
        self.assertNotIn("reasoning", payload)
        self.assertEqual(request["tool_choice"], payload["tool_choice"])
        self.assertEqual(schema, payload["tools"][0]["tools"][0]["parameters"])

    def test_Luna는_고정_모델과_xhigh를_Responses_요청에_전달한다(self):
        """허용된 Luna 요청에는 사용자 지정 모델과 xhigh가 그대로 전달된다."""
        # Given
        request = _request("p_" + "e" * 32)

        # When
        payload, _ = claude_gpt.build_responses_payload(request, subscription=False)

        # Then
        self.assertEqual("gpt-5.6-luna", payload["model"])
        self.assertEqual({"effort": "xhigh"}, payload["reasoning"])

    def test_다른_Luna_버전과_추론_강도는_인증과_공급자_접근_전에_거부한다(self):
        """다른 Luna 버전이나 xhigh 이외의 추론 강도는 프로필과 네트워크를 읽기 전에 거부된다."""
        # Given
        requests = []
        for model, effort in [("gpt-6-luna", "xhigh"), *[("gpt-5.6-luna", e) for e in (None, "low", "medium", "high", "max")]]:
            request = _request("p_" + "e" * 32)
            request.update(model=model, effort=effort)
            requests.append(request)
        http = FakeHttp()
        errors = []

        # When
        for request in requests:
            try:
                claude_gpt.execute_request(self.store, http, request)
            except claude_gpt.ClaudeGptError as error:
                errors.append(error.code)

        # Then
        self.assertEqual(["unsupported_model", *["unsupported_effort"] * 5], errors)
        self.assertEqual([], http.json_calls)
        self.assertEqual([], http.open_calls)
        self.assertFalse(self.store.root.exists())

    def test_스키마가_이해하지_않는_키워드는_위임하고_기본값과_boolean_스키마를_적용한다(self):
        # Given
        schema = {"properties": {"count": {"type": ["integer", "null"], "enum": [1, None]}},
                  "examples": [{"count": 1}], "additionalProperties": {"type": "string"}}

        # When
        claude_gpt._validate_json_schema(schema)
        valid = claude_gpt._validate_tool_input({"count": 1, "extra": "kept"}, schema, "test")
        true_value = claude_gpt._validate_tool_input({}, True, "test")

        # Then
        self.assertEqual({"count": 1, "extra": "kept"}, valid)
        self.assertEqual({}, true_value)
        with self.assertRaises(claude_gpt.ClaudeGptError) as false_schema:
            claude_gpt._validate_tool_input({}, False, "test")
        self.assertEqual("invalid_tool_call", false_schema.exception.code)
        with self.assertRaises(claude_gpt.ClaudeGptError) as bool_enum:
            claude_gpt._validate_tool_input({"count": True}, schema, "test")
        self.assertEqual("invalid_tool_call", bool_enum.exception.code)
        with self.assertRaises(claude_gpt.ClaudeGptError) as extra_type:
            claude_gpt._validate_tool_input({"count": 1, "extra": 2}, schema, "test")
        self.assertEqual("invalid_tool_call", extra_type.exception.code)
        with self.assertRaises(claude_gpt.ClaudeGptError) as malformed:
            claude_gpt._validate_json_schema({"type": ["object", "object"]})
        self.assertEqual("unsupported_schema", malformed.exception.code)

    def test_user_첨부와_오류_도구_결과의_이미지와_PDF를_Responses_입력으로_옮긴다(self):
        # Given
        profile_id = "p_" + "f" * 32
        png = base64.b64encode(b"png-data").decode("ascii")
        pdf = base64.b64encode(b"pdf-data").decode("ascii")
        history = [
            {"role": "user", "content": [
                {"type": "text", "text": "Inspect these."},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": png}},
                {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": pdf}},
            ]},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "call-media", "name": "Read",
                                                    "input": {"file_path": "image.png"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call-media", "is_error": True,
                                               "content": [
                                                   {"type": "text", "text": "permission denied"},
                                                   {"type": "image", "source": {"type": "base64", "media_type": "image/webp", "data": png}},
                                                   {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": pdf}},
                                               ]}]},
        ]
        request = _request(profile_id, history=history)

        # When
        payload, _ = claude_gpt.build_responses_payload(request, subscription=False)

        # Then
        user_inputs = [item["content"] for item in payload["input"] if item.get("role") == "user"]
        self.assertEqual("data:image/png;base64," + png, user_inputs[0][1]["image_url"])
        self.assertEqual("data:application/pdf;base64," + pdf, user_inputs[0][2]["file_data"])
        self.assertEqual("attachment.pdf", user_inputs[0][2]["filename"])
        output = next(item["output"] for item in payload["input"] if item.get("type") == "function_call_output")
        self.assertTrue(output.startswith("Tool error: permission denied"))
        self.assertIn("첨부 파일", output)
        self.assertEqual("data:image/webp;base64," + png, user_inputs[1][0]["image_url"])
        self.assertEqual("data:application/pdf;base64," + pdf, user_inputs[1][1]["file_data"])
        self.assertEqual("attachment.pdf", user_inputs[1][1]["filename"])

    def test_잘못된_첨부_base64와_허용하지_않은_이미지_형식을_거부한다(self):
        # Given
        profile_id = "p_" + "1" * 32
        bad_blocks = [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "%%%"}},
            {"type": "image", "source": {"type": "base64", "media_type": "image/svg+xml", "data": "AA=="}},
        ]

        # When
        errors = []
        for block in bad_blocks:
            request = _request(profile_id, history=[{"role": "user", "content": [block]}])
            with self.assertRaises(claude_gpt.ClaudeGptError) as raised:
                claude_gpt.build_responses_payload(request, subscription=False)
            errors.append(raised.exception.code)

        # Then
        self.assertEqual(["invalid_media", "invalid_media"], errors)

    def test_API_과금에_동의하지_않으면_키를_저장하지_않는다(self):
        # Given
        answers = iter(["n"])

        # When
        with self.assertRaises(claude_gpt.ClaudeGptError) as raised:
            claude_gpt.run_api_key_setup(self.store, env_name=None, input_fn=lambda _: next(answers),
                                         password_fn=lambda _: self.fail("키를 먼저 입력받았습니다"))

        # Then
        self.assertEqual("billing_not_confirmed", raised.exception.code)
        self.assertFalse(self.store.root.exists())

    def test_API_환경_키는_사용자가_명시한_이름으로만_가져오고_별도_보호_파일에_저장한다(self):
        # Given
        variable = "CLAUDE_GPT_W3_FAKE_KEY"
        secret = "sk-test-private-value"
        os.environ[variable] = secret
        self.addCleanup(os.environ.pop, variable, None)

        # When
        result = claude_gpt.run_api_key_setup(self.store, env_name=variable, input_fn=lambda _: "y")

        # Then
        profile = self.store.read_profile(result["profile_id"])
        credentials_path = self.store.profile_dir(result["profile_id"]) / "credentials.json"
        self.assertEqual("api_key", profile["mode"])
        self.assertIsNotNone(profile["api_billing_consent_at"])
        self.assertNotIn(secret, json.dumps(profile))
        self.assertEqual(secret, self.store.read_credentials(result["profile_id"])["api_key"])
        self.assertEqual(0o600, stat.S_IMODE(credentials_path.stat().st_mode))
        self.assertEqual(result["profile_id"], self.store.active_profile_id())

    def test_구독_로그인은_PKCE와_서명_JWKS를_검증하고_직접_사용_권한만_저장한다(self):
        # Given
        with self.store.locked():
            host_id = self.store.host_id(create=True)
        redirect = "http://127.0.0.1:1455/auth/callback"
        attempt = claude_gpt.create_authorization_attempt(
            client_id=claude_gpt.OAUTH_DYNAMIC_CLIENT, host_id=host_id, redirect_uri=redirect,
        )
        http, now, _ = self._subscription_http(nonce=attempt["nonce"])
        callback = redirect + "?" + urllib.parse.urlencode({
            "code": "one-time-code", "state": attempt["state"], "client_id": "oaiapp_issued-client",
            "scope": claude_gpt.OAUTH_SCOPES,
        })

        # When
        result = claude_gpt.finish_subscription_login(self.store, http, profile_id=None, attempt=attempt,
                                                       callback_url=callback, now=now)

        # Then
        profile = self.store.read_profile(result["profile_id"])
        credentials = self.store.read_credentials(result["profile_id"])
        token_call = next(call for call in http.json_calls if call["url"] == http.discovery["token_endpoint"])
        form = urllib.parse.parse_qs(token_call["data"].decode("ascii"))
        self.assertEqual("subscription", profile["mode"])
        self.assertEqual("oaiapp_issued-client", profile["client_id"])
        self.assertEqual("account-subject-1", profile["subject"])
        self.assertIn(claude_gpt.REQUIRED_SUBSCRIPTION_SCOPE, profile["scopes"])
        self.assertEqual([attempt["verifier"]], form["code_verifier"])
        self.assertEqual([claude_gpt.OPENAI_RESOURCE], form["resource"])
        self.assertNotIn("client_secret", form)
        self.assertNotIn("access-secret", json.dumps(profile))
        self.assertNotIn("refresh-secret", json.dumps(result))
        self.assertEqual("access-secret", credentials["access_token"])
        params = attempt["url_params"]
        self.assertEqual(host_id, params["ext_agent_host_id"])
        self.assertEqual(claude_gpt.OAUTH_AGENT_NAME, params["agent_name_hint"])
        self.assertNotIn(claude_gpt.OAUTH_DYNAMIC_CLIENT, form["client_id"])

    def test_필수_scope가_없으면_프로필을_저장하지_않고_state가_틀리면_토큰을_교환하지_않는다(self):
        # Given
        host_id = "urn:uuid:12345678-1234-5678-1234-567812345678"
        redirect = "http://127.0.0.1:1455/auth/callback"
        attempt = claude_gpt.create_authorization_attempt(client_id=claude_gpt.OAUTH_DYNAMIC_CLIENT,
                                                          host_id=host_id, redirect_uri=redirect)
        insufficient, now, _ = self._subscription_http(scope="openid profile email offline_access resource.invoke")
        insufficient_callback = redirect + "?" + urllib.parse.urlencode({
            "code": "one-time-code", "state": attempt["state"], "client_id": "oaiapp_issued-client",
        })
        wrong_state = redirect + "?" + urllib.parse.urlencode({
            "code": "one-time-code", "state": "attacker-state", "client_id": "oaiapp_issued-client",
        })
        other_http, _, _ = self._subscription_http()

        # When
        with self.assertRaises(claude_gpt.ClaudeGptError) as scope_error:
            claude_gpt.finish_subscription_login(self.store, insufficient, profile_id=None, attempt=attempt,
                                                  callback_url=insufficient_callback, now=now)
        with self.assertRaises(claude_gpt.ClaudeGptError) as state_error:
            claude_gpt.finish_subscription_login(self.store, other_http, profile_id=None, attempt=attempt,
                                                  callback_url=wrong_state, now=now)

        # Then
        self.assertEqual("missing_direct_scope", scope_error.exception.code)
        self.assertEqual("invalid_state", state_error.exception.code)
        self.assertTrue(any(call["url"].endswith("oauth/token") for call in insufficient.json_calls))
        self.assertFalse(any(call["url"].endswith("jwks.json") for call in insufficient.json_calls))
        self.assertEqual([], other_http.json_calls)
        self.assertFalse((self.store.root / "profiles").exists() and list((self.store.root / "profiles").iterdir()))

    def test_구독_토큰_갱신은_회전된_refresh_token을_한_번만_저장한다(self):
        # Given
        profile_id = "p_" + "a" * 32
        profile = {"profile_id": profile_id, "mode": "subscription", "client_id": "oaiapp_issued-client",
                   "issuer": claude_gpt.OAUTH_ISSUER, "subject": "subject", "scopes": [claude_gpt.REQUIRED_SUBSCRIPTION_SCOPE],
                   "status": "connected"}
        old = {"access_token": "old-access", "refresh_token": "old-refresh", "id_token": "verified-id-token",
               "expires_at": 1000, "scopes": [claude_gpt.REQUIRED_SUBSCRIPTION_SCOPE]}
        with self.store.locked():
            self.store.write_profile(profile)
            self.store.write_credentials(profile_id, old)
        http = FakeHttp(token={"access_token": "new-access", "refresh_token": "new-refresh", "token_type": "Bearer",
                               "expires_in": 3600})
        results = []

        # When
        threads = [threading.Thread(target=lambda: results.append(
            claude_gpt._refresh_if_needed(self.store, http, profile_id, now=1000))) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)

        # Then
        saved = self.store.read_credentials(profile_id)
        refresh_calls = [call for call in http.json_calls if call["url"].endswith("oauth/token")]
        form = urllib.parse.parse_qs(refresh_calls[0]["data"].decode("ascii"))
        self.assertEqual(2, len(results))
        self.assertEqual(1, len(refresh_calls))
        self.assertEqual(["oaiapp_issued-client"], form["client_id"])
        self.assertEqual(["old-refresh"], form["refresh_token"])
        self.assertNotIn("scope", form)
        self.assertEqual("new-refresh", saved["refresh_token"])
        self.assertEqual("verified-id-token", saved["id_token"])

    def test_로그아웃_뒤에는_저장된_등록을_유지하고_ID_힌트_없이_재인증한다(self):
        # Given
        profile_id = "p_" + "b" * 32
        with self.store.locked():
            self.store.write_profile({
                "profile_id": profile_id, "mode": "subscription", "issuer": claude_gpt.OAUTH_ISSUER,
                "client_id": "oaiapp_issued-client", "subject": "account-subject-1",
                "email": "account@example.test", "scopes": [claude_gpt.REQUIRED_SUBSCRIPTION_SCOPE],
                "created_at": "2026-10-06T00:00:00Z", "status": "signed_out",
            })
        redirect = "http://127.0.0.1:1455/auth/callback"
        attempt = claude_gpt.create_authorization_attempt(
            client_id="oaiapp_issued-client", host_id="urn:uuid:12345678-1234-5678-1234-567812345678",
            redirect_uri=redirect, login_hint="account@example.test",
        )
        http, _, _ = self._subscription_http(nonce=attempt["nonce"])
        received = {"url": redirect + "?" + urllib.parse.urlencode({
            "code": "reauth-code", "state": attempt["state"], "client_id": "oaiapp_issued-client",
        })}

        class CallbackServer:
            def handle_request(self):
                return None

            def server_close(self):
                return None

        opened_urls = []

        # When
        with patch.object(claude_gpt, "_callback_server", return_value=(CallbackServer(), redirect, received)), \
                patch.object(claude_gpt, "create_authorization_attempt", return_value=attempt), \
                patch.object(claude_gpt.webbrowser, "open", side_effect=lambda url, **kwargs: opened_urls.append(url) or True):
            result = claude_gpt.run_subscription_login(self.store, http, profile_id=profile_id)

        # Then
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(opened_urls[0]).query)
        self.assertEqual("oaiapp_issued-client", query["client_id"][0])
        self.assertEqual("account@example.test", query["login_hint"][0])
        self.assertNotIn("id_token_hint", query)
        self.assertEqual(profile_id, result["profile_id"])
        self.assertEqual("account-subject-1", self.store.read_profile(profile_id)["subject"])

    def test_Responses_요청은_상태를_저장하지_않고_도구_호출의_비공개_추론_상태만_유지한다(self):
        # Given
        api = claude_gpt.create_api_key_profile(self.store, "sk-local-test", confirmed_usage_billing=True, now=1000)
        first_request = _request(api["profile_id"])
        first_http = FakeHttp(stream=_sse(
            {"type": "response.output_text.delta", "delta": "도구를 호출합니다."},
            {"type": "response.completed", "response": {
                "id": "resp-one", "status": "completed", "model": "gpt-5.6-luna",
                "output": [
                    {"id": "rs-one", "type": "reasoning", "summary": [{"type": "summary_text", "text": "provider-only"}]},
                    {"type": "function_call", "call_id": "call-one", "namespace": "claude", "name": "Read",
                     "arguments": "{\"file_path\":\"a.txt\"}"},
                    {"id": "msg-one", "type": "message", "content": [{"type": "output_text", "text": "도구를 호출합니다."}]},
                ],
                "usage": {"input_tokens": 20, "input_tokens_details": {"cached_tokens": 5},
                          "output_tokens": 9, "output_tokens_details": {"reasoning_tokens": 3}},
            }},
        ))
        first_output = io.StringIO()

        # When
        claude_gpt.execute_request(self.store, first_http, first_request, now=1000, stream_out=first_output)

        # Then
        first_records = [json.loads(line) for line in first_output.getvalue().splitlines()]
        open_request = first_http.open_calls[0]
        payload = json.loads(open_request.data)
        self.assertEqual("Bearer sk-local-test", open_request.get_header("Authorization"))
        self.assertFalse(payload["store"])
        self.assertTrue(payload["stream"])
        self.assertEqual("System policy.", payload["instructions"])
        self.assertEqual("Developer policy.", payload["input"][0]["content"][0]["text"])
        self.assertEqual("namespace", payload["tools"][0]["type"])
        self.assertEqual("claude", payload["tools"][0]["name"])
        self.assertNotIn("tool_search", json.dumps(payload))
        self.assertEqual(["text_delta", "completed"], [record["type"] for record in first_records])
        self.assertEqual({
            "protocol_version", "type", "response_id", "model", "usage", "tool_calls",
            "provider_reported_effort",
        }, set(first_records[-1]))
        self.assertEqual({"id": "call-one", "name": "Read", "arguments": {"file_path": "a.txt"}},
                         first_records[-1]["tool_calls"][0])
        self.assertNotIn("sk-local-test", first_output.getvalue())

        # Given
        followup_history = [
            {"role": "user", "content": [{"type": "text", "text": "Read a file."}]},
            {"role": "assistant", "content": [
                {"type": "text", "text": "도구를 호출합니다."},
                {"type": "tool_use", "id": "call-one", "name": "Read", "input": {"file_path": "a.txt"}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "call-one", "content": "file contents"},
            ]},
        ]
        second_request = _request(api["profile_id"], history=followup_history,
                                  session_id="resumed-session", step_id="step-2")
        second_http = FakeHttp(stream=_sse(
            {"type": "response.output_text.delta", "delta": "완료했습니다."},
            {
            "type": "response.completed", "response": {
                "id": "resp-two", "status": "completed", "model": "gpt-5.6-luna",
                "output": [{"id": "msg-two", "type": "message", "content": [{"type": "output_text", "text": "완료했습니다."}]}],
                "usage": {"input_tokens": 27, "input_tokens_details": {"cached_tokens": 0},
                          "output_tokens": 5, "output_tokens_details": {"reasoning_tokens": 1}},
            },
            },
        ))
        second_output = io.StringIO()

        # When
        claude_gpt.execute_request(self.store, second_http, second_request, now=1001, stream_out=second_output)

        # Then
        second_payload = json.loads(second_http.open_calls[0].data)
        second_input = second_payload["input"]
        self.assertTrue(any(item.get("type") == "reasoning" and item["summary"][0]["text"] == "provider-only" for item in second_input))
        self.assertTrue(any(item.get("type") == "function_call" and item["call_id"] == "call-one" for item in second_input))
        self.assertTrue(any(item.get("type") == "function_call_output" and item["call_id"] == "call-one" and
                            item["output"] == "file contents" for item in second_input))
        state_files = list((self.store.profile_dir(api["profile_id"]) / "state").glob("*.json"))
        state_text = state_files[0].read_text()
        self.assertIn("provider-only", state_text)
        self.assertNotIn("sk-local-test", state_text)
        self.assertEqual("api_key", self.store.read_profile(api["profile_id"])["mode"])

    def test_미완료_스트림이나_알_수_없는_도구는_실행할_도구_호출을_출력하지_않는다(self):
        # Given
        api = claude_gpt.create_api_key_profile(self.store, "sk-test-failure", confirmed_usage_billing=True)
        bad_response = {
            "type": "response.completed", "response": {
                "id": "resp-bad", "status": "completed", "model": "gpt-5.6-luna",
                "output": [{"type": "function_call", "call_id": "call-unknown", "namespace": "claude",
                            "name": "Bash", "arguments": "{\"command\":\"true\"}"}],
                "usage": {"input_tokens": 1, "input_tokens_details": {"cached_tokens": 0},
                          "output_tokens": 1, "output_tokens_details": {"reasoning_tokens": 0}},
            },
        }
        http = FakeHttp(stream=_sse({"type": "response.output_text.delta", "delta": "partial"}, bad_response))
        out = io.StringIO()
        request = _request(api["profile_id"])

        # When
        with self.assertRaises(claude_gpt.ClaudeGptError) as raised:
            claude_gpt.execute_request(self.store, http, request, stream_out=out)

        # Then
        records = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual("invalid_tool_call", raised.exception.code)
        self.assertEqual(["text_delta"], [record["type"] for record in records])
        self.assertNotIn("call-unknown", out.getvalue())

    def test_스트림_불일치_오류는_민감_본문_없이_완료_usage와_진단_숫자를_보존한다(self):
        # Given
        response = {"type": "response.completed", "response": {
            "id": "resp-diagnostic-mismatch", "status": "completed", "model": "gpt-5.6-luna",
            "reasoning": {"effort": "high"},
            "output": [{"id": "msg-diagnostic", "type": "message", "content": [
                {"type": "output_text", "text": "abY"},
            ]}],
            "usage": {"input_tokens": 7, "input_tokens_details": {"cached_tokens": 2},
                      "output_tokens": 4, "output_tokens_details": {"reasoning_tokens": 1}},
        }}
        http = FakeHttp(stream=_sse(
            {"type": "response.content_part.added", "output_index": 2, "content_index": 4,
             "part": {"type": "output_text", "text": "added-private-content"}},
            {"type": "response.output_text.delta", "output_index": 2, "content_index": 4,
             "delta": "abX"},
            {"type": "response.output_text.done", "output_index": 2, "content_index": 4,
             "text": "done-private-content"},
            {"type": "response.content_part.done", "output_index": 2, "content_index": 4,
             "part": {"type": "refusal", "refusal": "part-done-private-content"}},
            {"type": "response.refusal.done", "output_index": 2, "content_index": 5,
             "refusal": "refusal-private-content"},
            {"type": "response.reasoning_text.delta", "output_index": 3, "content_index": 0,
             "delta": "reasoning-private-content"},
            {"type": "response.reasoning_text.done", "output_index": 3, "content_index": 0,
             "text": "reasoning-private-content"},
            response,
        ))
        output = io.StringIO()

        # When
        with self.assertRaises(claude_gpt.ClaudeGptError) as raised:
            claude_gpt.stream_responses(
                http, payload={}, api_key="sk-offline-only", expected_model="gpt-5.6-luna",
                requested_effort="high", tool_schemas={"Read": _schema()}, prior_call_ids=set(),
                stream_out=output,
            )
        record = claude_gpt.protocol_error(raised.exception)

        # Then
        self.assertEqual("stream_mismatch", raised.exception.code)
        self.assertEqual({
            "model": "gpt-5.6-luna",
            "usage": {"input_tokens": 7, "cached_input_tokens": 2,
                      "output_tokens": 4, "reasoning_tokens": 1},
            "provider_reported_effort": "high",
        }, record["provider_usage"])
        diagnostic = record["stream_diagnostics"]
        self.assertEqual(3, diagnostic["streamed_characters"])
        self.assertEqual(3, diagnostic["completed_visible_characters"])
        self.assertEqual(2, diagnostic["first_mismatch_offset"])
        self.assertEqual(1, diagnostic["event_counts"]["response.content_part.added"])
        self.assertEqual(1, diagnostic["event_counts"]["response.content_part.done"])
        self.assertEqual(1, diagnostic["event_counts"]["response.output_text.delta"])
        self.assertEqual(1, diagnostic["event_counts"]["response.reasoning_text.delta"])
        self.assertEqual(1, diagnostic["event_counts"]["response.reasoning_text.done"])
        self.assertEqual(1, diagnostic["event_counts"]["response.completed"])
        self.assertEqual(0, diagnostic["event_counts"]["unknown_events"])
        self.assertEqual(1, diagnostic["output_item_counts"]["message"])
        part_summaries = {
            (item["output_index"], item["content_index"]): item
            for item in diagnostic["part_summaries"]
        }
        self.assertEqual({
            "output_index": 2, "content_index": 4,
            "delta_events": 1, "delta_characters": 3,
            "added_events": 1, "added_characters": len("added-private-content"),
            "text_done_events": 1, "text_done_characters": len("done-private-content"),
            "part_done_events": 1, "part_done_characters": len("part-done-private-content"),
        }, part_summaries[(2, 4)])
        self.assertEqual({
            "output_index": 2, "content_index": 5,
            "delta_events": 0, "delta_characters": 0,
            "added_events": 0, "added_characters": 0,
            "text_done_events": 1, "text_done_characters": len("refusal-private-content"),
            "part_done_events": 0, "part_done_characters": 0,
        }, part_summaries[(2, 5)])
        serialized = json.dumps(record)
        for private_text in (
            "added-private-content", "abX", "done-private-content", "part-done-private-content",
            "refusal-private-content", "reasoning-private-content", "abY",
        ):
            self.assertNotIn(private_text, serialized)

    def test_완료_output이_비어_있어도_완료된_message_snapshot으로_텍스트를_검증한다(self):
        # Given
        final_item = {
            "id": "msg-sparse-text", "type": "message", "role": "assistant",
            "status": "completed", "content": [{"type": "output_text", "text": "안녕하세요"}],
        }
        response = {"type": "response.completed", "response": {
            "id": "resp-sparse-text", "status": "completed", "model": "gpt-5.6-luna",
            "output": [], "usage": {"input_tokens": 1, "output_tokens": 2},
        }}
        http = FakeHttp(stream=_sse(
            {"type": "response.output_item.added", "output_index": 0,
             "item": {"id": "msg-sparse-text", "type": "message", "role": "assistant"}},
            {"type": "response.output_text.delta", "output_index": 0, "content_index": 0,
             "delta": "안녕하세요"},
            {"type": "response.output_item.done", "output_index": 0, "item": final_item},
            response,
        ))
        output = io.StringIO()

        # When
        result = claude_gpt.stream_responses(
            http, payload={}, api_key="sk-offline-only", expected_model="gpt-5.6-luna",
            requested_effort=None, tool_schemas={"Read": _schema()}, prior_call_ids=set(), stream_out=output,
        )

        # Then
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(0, result)
        self.assertEqual(["text_delta", "completed"], [record["type"] for record in records])
        self.assertEqual("안녕하세요", records[0]["text"])
        self.assertEqual([], records[-1]["tool_calls"])

    def test_완료_output이_비어_있으면_도구와_reasoning을_검증한_뒤_EOF에서만_저장한다(self):
        # Given
        reasoning = {"id": "rs-sparse", "type": "reasoning", "encrypted_content": "opaque-reasoning"}
        function_call = {
            "id": "fc-item-sparse", "type": "function_call", "status": "completed",
            "call_id": "call-sparse", "namespace": "claude", "name": "Read",
            "arguments": '{"file_path":"x.txt"}',
        }
        response = {"type": "response.completed", "response": {
            "id": "resp-sparse-tool", "status": "completed", "model": "gpt-5.6-luna",
            "output": [], "usage": {"input_tokens": 1, "output_tokens": 0},
        }}
        encoded = _sse(
            {"type": "response.output_item.added", "output_index": 0,
             "item": {"id": "rs-sparse", "type": "reasoning"}},
            {"type": "response.output_item.done", "output_index": 0, "item": reasoning},
            {"type": "response.output_item.added", "output_index": 1,
             "item": {"id": "fc-item-sparse", "type": "function_call"}},
            {"type": "response.output_item.done", "output_index": 1, "item": function_call},
            response,
        )
        source = io.BytesIO(encoded)
        http = FakeHttp(stream=source)
        saved = []
        output = io.StringIO()

        saved_after_close = []

        def save_at_eof(groups):
            saved_after_close.append(source.closed)
            saved.append(groups)

        # When
        result = claude_gpt.stream_responses(
            http, payload={}, api_key="sk-offline-only", expected_model="gpt-5.6-luna",
            requested_effort=None, tool_schemas={"Read": _schema()}, prior_call_ids=set(),
            store_state=save_at_eof, stream_out=output,
        )

        # Then
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(0, result)
        self.assertEqual(["completed"], [record["type"] for record in records])
        self.assertEqual([{"id": "call-sparse", "name": "Read", "arguments": {"file_path": "x.txt"}}],
                         records[0]["tool_calls"])
        self.assertEqual(1, len(saved))
        self.assertEqual([True], saved_after_close)
        self.assertEqual(["call-sparse"], saved[0][0]["ids"])
        self.assertEqual(["reasoning", "function_call"], [item["type"] for item in saved[0][0]["items"]])

    def test_잘못된_output_item_event와_snapshot은_완료나_상태없이_거부한다(self):
        # Given
        def added(index=0, item_id="item-one", item_type="message"):
            return {"type": "response.output_item.added", "output_index": index,
                    "item": {"id": item_id, "type": item_type}}

        def done(index=0, item_id="item-one", item_type="message", **fields):
            return {"type": "response.output_item.done", "output_index": index,
                    "item": {"id": item_id, "type": item_type, **fields}}

        completion = {"type": "response.completed", "response": {
            "id": "resp-invalid-sparse", "status": "completed", "model": "gpt-5.6-luna",
            "output": [], "usage": {"input_tokens": 1, "output_tokens": 0},
        }}
        cases = [
            ("불리언 인덱스", [{"type": "response.output_item.added", "output_index": True,
                          "item": {"id": "item-one", "type": "message"}}], "invalid_output_item_event"),
            ("중복 추가", [added(), added()], "duplicate_output_item_event"),
            ("중복 완료", [added(), done(content=[]), done(content=[])], "duplicate_output_item_event"),
            ("다른 인덱스의 중복 ID", [added(), added(index=1)], "duplicate_output_item_event"),
            ("추가 없는 완료", [done(content=[])], "output_item_identity_mismatch"),
            ("인덱스 간격", [added(index=1), done(index=1, content=[])], "output_item_index_gap"),
            ("추가와 완료 ID 불일치", [added(), done(item_id="item-two", content=[])],
             "output_item_identity_mismatch"),
            ("완료 스냅샷 누락", [added()], "incomplete_output_items"),
            ("미완료 status", [added(), done(status="in_progress", content=[])],
             "invalid_output_item_snapshot"),
            ("잘못된 assistant role", [added(), done(role="user", content=[])],
             "invalid_output_item_snapshot"),
            ("도구 입력 스키마 위반", [
                added(item_id="fc-item", item_type="function_call"),
                {"type": "response.output_item.done", "output_index": 0,
                 "item": {"id": "fc-item", "type": "function_call", "status": "completed",
                          "call_id": "call-invalid", "namespace": "claude", "name": "Read",
                          "arguments": '{"file_path":4}'}},
            ], "invalid_tool_call"),
        ]

        for case_name, events, expected_code in cases:
            with self.subTest(case_name=case_name):
                # Given
                http = FakeHttp(stream=_sse(*events, completion))
                saved = []
                output = io.StringIO()

                # When
                with self.assertRaises(claude_gpt.ClaudeGptError) as raised:
                    claude_gpt.stream_responses(
                        http, payload={}, api_key="sk-offline-only", expected_model="gpt-5.6-luna",
                        requested_effort=None, tool_schemas={"Read": _schema()}, prior_call_ids=set(),
                        store_state=saved.append, stream_out=output,
                    )

                # Then
                self.assertEqual(expected_code, raised.exception.code)
                self.assertEqual([], saved)
                self.assertFalse(any(record["type"] == "completed" for record in
                                     (json.loads(line) for line in output.getvalue().splitlines())))

    def test_완전한_output과_완료_항목이_일치하면_도구를_중복하지_않는다(self):
        # Given
        function_call = {
            "id": "fc-item-full", "type": "function_call", "status": "completed",
            "call_id": "call-full", "namespace": "claude", "name": "Read",
            "arguments": '{"file_path":"x.txt"}',
        }
        http = FakeHttp(stream=_sse(
            {"type": "response.output_item.added", "output_index": 0,
             "item": {"id": function_call["id"], "type": "function_call"}},
            {"type": "response.output_item.done", "output_index": 0, "item": function_call},
            {"type": "response.completed", "response": {
                "id": "resp-full-item", "status": "completed", "model": "gpt-5.6-luna",
                "output": [function_call], "usage": {"input_tokens": 1, "output_tokens": 0},
            }},
        ))
        output = io.StringIO()
        saved = []

        # When
        result = claude_gpt.stream_responses(
            http, payload={}, api_key="sk-offline-only", expected_model="gpt-5.6-luna",
            requested_effort=None, tool_schemas={"Read": _schema()}, prior_call_ids=set(),
            store_state=saved.append, stream_out=output,
        )

        # Then
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(0, result)
        self.assertEqual(["completed"], [record["type"] for record in records])
        self.assertEqual(["call-full"], [call["id"] for call in records[0]["tool_calls"]])
        self.assertEqual(1, len(saved))

    def test_완전한_output과_완료_항목의_ID나_내용이_충돌하면_거부한다(self):
        function_call = {
            "id": "fc-item-full", "type": "function_call", "status": "completed",
            "call_id": "call-full", "namespace": "claude", "name": "Read",
            "arguments": '{"file_path":"x.txt"}',
        }
        for conflict in ({"id": "fc-item-other"}, {"arguments": '{"file_path":"other.txt"}'}):
            with self.subTest(conflict=next(iter(conflict))):
                # Given
                http = FakeHttp(stream=_sse(
                    {"type": "response.output_item.added", "output_index": 0,
                     "item": {"id": function_call["id"], "type": "function_call"}},
                    {"type": "response.output_item.done", "output_index": 0, "item": function_call},
                    {"type": "response.completed", "response": {
                        "id": "resp-full-item", "status": "completed", "model": "gpt-5.6-luna",
                        "output": [{**function_call, **conflict}],
                        "usage": {"input_tokens": 1, "output_tokens": 0},
                    }},
                ))
                output = io.StringIO()
                saved = []

                # When
                with self.assertRaises(claude_gpt.ClaudeGptError) as raised:
                    claude_gpt.stream_responses(
                        http, payload={}, api_key="sk-offline-only", expected_model="gpt-5.6-luna",
                        requested_effort=None, tool_schemas={"Read": _schema()}, prior_call_ids=set(),
                        store_state=saved.append, stream_out=output,
                    )

                # Then
                self.assertEqual("output_item_completion_mismatch", raised.exception.code)
                self.assertEqual([], saved)
                self.assertEqual("", output.getvalue())

    def test_sparse_completed_뒤_transport_실패는_usage만_남기고_도구나_상태를_내보내지_않는다(self):
        # Given
        function_call = {
            "id": "fc-item-terminal", "type": "function_call", "status": "completed",
            "call_id": "call-terminal", "namespace": "claude", "name": "Read",
            "arguments": '{"file_path":"x.txt"}',
        }
        response = {"type": "response.completed", "response": {
            "id": "resp-sparse-terminal", "status": "completed", "model": "gpt-5.6-luna",
            "output": [], "usage": {"input_tokens": 5, "output_tokens": 1},
        }}
        encoded = _sse(
            {"type": "response.output_item.added", "output_index": 0,
             "item": {"id": function_call["id"], "type": "function_call"}},
            {"type": "response.output_item.done", "output_index": 0, "item": function_call},
            response,
        )

        class BrokenAfterCompletion(io.BytesIO):
            def readline(self, size=-1):
                if self.tell() == len(self.getvalue()):
                    raise OSError("private transport detail")
                return super().readline(size)

        output = io.StringIO()
        saved = []
        http = FakeHttp(stream=BrokenAfterCompletion(encoded))

        # When
        with self.assertRaises(claude_gpt.ClaudeGptError) as raised:
            claude_gpt.stream_responses(
                http, payload={}, api_key="sk-offline-only", expected_model="gpt-5.6-luna",
                requested_effort=None, tool_schemas={"Read": _schema()}, prior_call_ids=set(),
                store_state=saved.append, stream_out=output,
            )

        # Then
        record = claude_gpt.protocol_error(raised.exception)
        self.assertEqual("stream_after_completion", raised.exception.code)
        self.assertTrue(raised.exception.terminal_after_completion)
        self.assertEqual([], saved)
        self.assertEqual("", output.getvalue())
        self.assertEqual({"input_tokens": 5, "cached_input_tokens": 0,
                          "output_tokens": 1, "reasoning_tokens": 0},
                         record["provider_usage"]["usage"])

    def test_오류_메타데이터_생성과_직렬화는_임의_키와_문자열을_걸러낸다(self):
        # Given
        secret = "private-provider-diagnostic-secret"
        error = claude_gpt.ClaudeGptError(
            "invalid_completion", "safe message",
            provider_usage={
                "model": "gpt-5.6-luna",
                "usage": {"model": "gpt-5.6-luna", "input_tokens": 3,
                          "cached_input_tokens": 0, "output_tokens": 1, "reasoning_tokens": 0,
                          "credential": secret},
                "provider_reported_effort": "high", "credential": secret,
            },
            stream_diagnostics={
                "event_counts": {"response.completed": 1, "unknown_events": 2,
                                 "private-event-name": secret},
                "streamed_characters": secret,
                "output_item_counts": {"message": 1, "private-type": 99},
                "part_summaries": [
                    {"output_index": index, "content_index": 1, "delta_events": 1,
                     "delta_characters": 4, **({"text": secret} if index == 0 else {})}
                    for index in range(65)
                ],
                "part_summaries_overflow": 0, "private_key": secret,
            },
        )
        error.stream_diagnostics["private_key"] = secret

        # When
        record = claude_gpt.protocol_error(error)
        serialized = json.dumps(record)

        # Then
        self.assertNotIn(secret, serialized)
        self.assertNotIn("private-event-name", serialized)
        self.assertNotIn("private-type", serialized)
        self.assertNotIn("private_key", serialized)
        self.assertEqual(0, record["stream_diagnostics"]["streamed_characters"])
        self.assertEqual(1, record["stream_diagnostics"]["output_item_counts"]["message"])
        self.assertEqual(64, len(record["stream_diagnostics"]["part_summaries"]))
        self.assertEqual(1, record["stream_diagnostics"]["part_summaries_overflow"])
        self.assertNotIn("text", record["stream_diagnostics"]["part_summaries"][0])

    def test_failed_또는_incomplete_응답은_일치하는_모델과_유효한_usage만_보존한다(self):
        # Given
        valid_usage = {
            "input_tokens": 3, "input_tokens_details": {"cached_tokens": 1},
            "output_tokens": 2, "output_tokens_details": {"reasoning_tokens": 1},
        }
        cases = [
            ({"model": "gpt-5.6-luna", "usage": valid_usage,
              "error": {"code": "server_error", "message": "private failure diagnostic"}}, True),
            ({"model": "gpt-6.1-sol", "usage": valid_usage,
              "error": {"code": "server_error"}}, False),
            ({"model": "gpt-5.6-luna", "usage": {"input_tokens": "private-diagnostic", "output_tokens": 2},
              "error": {"code": "server_error"}}, False),
        ]

        # When
        records = []
        for index, (response_body, expected_usage) in enumerate(cases):
            event_type = "response.failed" if index == 0 else "response.incomplete"
            http = FakeHttp(stream=_sse({"type": event_type, "response": response_body}))
            with self.subTest(index=index):
                with self.assertRaises(claude_gpt.ClaudeGptError) as raised:
                    claude_gpt.stream_responses(
                        http, payload={}, api_key="sk-offline-only", expected_model="gpt-5.6-luna",
                        requested_effort=None, tool_schemas={"Read": _schema()}, prior_call_ids=set(),
                        stream_out=io.StringIO(),
                    )
                records.append((claude_gpt.protocol_error(raised.exception), expected_usage))

        # Then
        for record, expected_usage in records:
            if expected_usage:
                self.assertEqual("gpt-5.6-luna", record["provider_usage"]["model"])
                self.assertEqual({"input_tokens": 3, "cached_input_tokens": 1,
                                  "output_tokens": 2, "reasoning_tokens": 1},
                                 record["provider_usage"]["usage"])
            else:
                self.assertNotIn("provider_usage", record)
            self.assertNotIn("private", json.dumps(record))

    def test_response_completed_뒤의_transport_실패는_완료와_상태를_내보내지_않는다(self):
        # Given
        response = {"type": "response.completed", "response": {
            "id": "resp-broken-eof", "status": "completed", "model": "gpt-5.6-luna",
            "output": [{"type": "function_call", "call_id": "call-broken-eof", "namespace": "claude",
                        "name": "Read", "arguments": '{"file_path":"a.txt"}'}],
            "usage": {"input_tokens": 1, "output_tokens": 0},
        }}

        class BrokenAfterCompletion(io.BytesIO):
            def readline(self, size=-1):
                if self.tell() == len(self.getvalue()):
                    raise OSError("private transport detail")
                return super().readline(size)

        http = FakeHttp(stream=BrokenAfterCompletion(_sse(response)))
        output = io.StringIO()
        saved = []

        # When
        with self.assertRaises(claude_gpt.ClaudeGptError) as raised:
            claude_gpt.stream_responses(
                http, payload={}, api_key="sk-offline-only", expected_model="gpt-5.6-luna", requested_effort="high",
                tool_schemas={"Read": _schema()}, prior_call_ids=set(), store_state=saved.append,
                stream_out=output,
            )

        # Then
        self.assertEqual("stream_after_completion", raised.exception.code)
        self.assertTrue(raised.exception.terminal_after_completion)
        self.assertEqual([], saved)
        self.assertEqual("", output.getvalue())
        self.assertNotIn("private transport detail", str(raised.exception))
        record = claude_gpt.protocol_error(raised.exception)
        self.assertEqual("gpt-5.6-luna", record["provider_usage"]["model"])
        self.assertEqual({"input_tokens": 1, "cached_input_tokens": 0,
                          "output_tokens": 0, "reasoning_tokens": 0},
                         record["provider_usage"]["usage"])
        self.assertEqual(1, record["stream_diagnostics"]["event_counts"]["response.completed"])
        self.assertEqual(0, record["stream_diagnostics"]["completed_visible_characters"])

    def test_잘린_HTTP_chunk는_완료_이벤트_여부에_맞는_오류로_남고_도구를_내보내지_않는다(self):
        for completed in (False, True):
            with self.subTest(completed=completed):
                # Given
                completion = {"type": "response.completed", "response": {
                    "id": "resp-chunk-cut", "status": "completed", "model": "gpt-5.6-luna",
                    "output": [{"type": "function_call", "call_id": "call-chunk-cut", "namespace": "claude",
                                "name": "Read", "arguments": '{"file_path":"a.txt"}'}],
                    "usage": {"input_tokens": 1, "output_tokens": 0},
                }}

                class BrokenChunk(io.BytesIO):
                    def readline(self, size=-1):
                        if self.tell() == len(self.getvalue()):
                            raise IncompleteRead(b"private-partial-response", 32)
                        return super().readline(size)

                provider = FakeHttp(stream=BrokenChunk(_sse(completion) if completed else b""))
                output = io.StringIO()
                saved = []

                # When
                with self.assertRaises(claude_gpt.ClaudeGptError) as raised:
                    claude_gpt.stream_responses(
                        provider, payload={}, api_key="sk-offline-only", expected_model="gpt-5.6-luna",
                        requested_effort=None, tool_schemas={"Read": _schema()}, prior_call_ids=set(),
                        store_state=saved.append, stream_out=output,
                    )

                # Then
                self.assertEqual("stream_after_completion" if completed else "stream_interrupted", raised.exception.code)
                self.assertEqual(completed, raised.exception.terminal_after_completion)
                self.assertEqual([], saved)
                self.assertEqual("", output.getvalue())
                self.assertNotIn("private-partial-response", str(raised.exception))

    def test_캐시의_도구_입력은_boolean과_숫자가_다르면_불일치로_처리한다(self):
        # Given
        group = {
            "ids": ["call-cache"],
            "calls": {"call-cache": {"name": "Read", "arguments": {"value": True}}},
            "items": [{"type": "function_call", "call_id": "call-cache", "namespace": "claude",
                       "name": "Read", "arguments": '{"value":1}'}],
        }

        # When
        with self.assertRaises(claude_gpt.ClaudeGptError) as raised:
            claude_gpt._validated_provider_groups([group], {"Read": {"type": "object"}})

        # Then
        self.assertEqual("invalid_state", raised.exception.code)

    def test_response_completed_뒤의_추가_event는_완료와_상태를_내보내지_않는다(self):
        # Given
        response = {"type": "response.completed", "response": {
            "id": "resp-extra-event", "status": "completed", "model": "gpt-5.6-luna",
            "output": [], "usage": {"input_tokens": 1, "output_tokens": 0},
        }}
        http = FakeHttp(stream=_sse(response, {"type": "response.output_text.delta", "delta": "late"}))
        output = io.StringIO()
        saved = []

        # When
        with self.assertRaises(claude_gpt.ClaudeGptError) as raised:
            claude_gpt.stream_responses(
                http, payload={}, api_key="sk-offline-only", expected_model="gpt-5.6-luna", requested_effort=None,
                tool_schemas={"Read": _schema()}, prior_call_ids=set(), store_state=saved.append,
                stream_out=output,
            )

        # Then
        self.assertEqual("event_after_completion", raised.exception.code)
        self.assertTrue(raised.exception.terminal_after_completion)
        self.assertEqual([], saved)
        self.assertEqual("", output.getvalue())

    def test_응답_model_mismatch는_완료_레코드나_상태를_저장하지_않는다(self):
        # Given
        response = {"type": "response.completed", "response": {
            "id": "resp-wrong-model", "status": "completed", "model": "gpt-6.1-sol",
            "output": [], "usage": {"input_tokens": 1, "output_tokens": 0},
        }}
        http = FakeHttp(stream=_sse(response))
        output = io.StringIO()
        saved = []

        # When
        with self.assertRaises(claude_gpt.ClaudeGptError) as raised:
            claude_gpt.stream_responses(
                http, payload={}, api_key="sk-offline-only", expected_model="gpt-5.6-luna", requested_effort=None,
                tool_schemas={"Read": _schema()}, prior_call_ids=set(), store_state=saved.append,
                stream_out=output,
            )

        # Then
        self.assertEqual("invalid_completion", raised.exception.code)
        self.assertTrue(raised.exception.terminal_after_completion)
        self.assertEqual([], saved)
        self.assertEqual("", output.getvalue())

    def test_profile별_상태_병합은_다른_호출을_유지하고_크기_한도에서_오래된_그룹부터_지운다(self):
        # Given
        api = claude_gpt.create_api_key_profile(self.store, "sk-state-eviction", confirmed_usage_billing=True)

        def group(call_id: str, reasoning_id: str) -> dict:
            arguments = {"file_path": "x"}
            return {
                "ids": [call_id],
                "calls": {call_id: {"name": "Read", "arguments": arguments}},
                "items": [
                    {"type": "reasoning", "id": reasoning_id, "encrypted_content": "r" * 200},
                    {"type": "function_call", "call_id": call_id, "namespace": "claude", "name": "Read",
                     "arguments": '{"file_path":"x"}'},
                ],
            }

        first = group("call-000001", "reason-000001")
        second = group("call-000002", "reason-000002")
        third = group("call-000003", "reason-000003")
        two_group_size = len(claude_gpt._json_bytes({
            "version": 1, "profile_id": api["profile_id"], "groups": [first, second],
        }))

        # When
        with patch.object(claude_gpt, "MAX_STATE_BYTES", two_group_size + 32):
            for provider_group in (first, second, third):
                with self.store.locked():
                    self.store.merge_provider_state(api["profile_id"], [provider_group])
            state_path = self.store.provider_state_path(api["profile_id"])
            saved_text = state_path.read_text()

        # Then
        groups = json.loads(saved_text)["groups"]
        self.assertEqual([["call-000002"], ["call-000003"]], [item["ids"] for item in groups])
        self.assertLessEqual(len(saved_text.encode()), two_group_size + 32)
        self.assertNotIn("session_id", saved_text)

    def test_HTTP_오류는_인증_정보를_출력하지_않고_대체_프로필을_시도하지_않는다(self):
        # Given
        api = claude_gpt.create_api_key_profile(self.store, "sk-never-print", confirmed_usage_billing=True)
        http = FakeHttp(status=401, error_body=b'{"error":{"message":"sk-never-print","code":"sk-never-print"}}')

        # When
        with self.assertRaises(claude_gpt.ClaudeGptError) as raised:
            claude_gpt.execute_request(self.store, http, _request(api["profile_id"]))

        # Then
        self.assertNotIn("sk-never-print", str(raised.exception))
        self.assertEqual(1, len(http.open_calls))
        self.assertEqual("api_key", self.store.read_profile(api["profile_id"])["mode"])

    def test_HTTP_오류는_안전한_상태와_allowlist_code_request_id_retry_after만_보존한다(self):
        # Given
        body = b'{"error":{"code":"subscription_sharing_user_not_eligible","message":"private diagnostic"}}'
        headers = {"X-Request-ID": "req_abc-123", "Retry-After": "8"}

        # When
        error = claude_gpt._http_error(403, body, headers)
        record = claude_gpt.protocol_error(error)

        # Then
        self.assertEqual(403, error.http_status)
        self.assertEqual("subscription_sharing_user_not_eligible", error.provider_code)
        self.assertEqual("req_abc-123", error.request_id)
        self.assertEqual(8.0, error.retry_after)
        self.assertEqual(8.0, record["retry_after"])
        self.assertNotIn("private diagnostic", str(error))
        self.assertNotIn("private diagnostic", json.dumps(record))
        self.assertTrue({
            "subscription_sharing_user_not_eligible", "subscription_sharing_usage_limit_exceeded",
            "subscription_sharing_usage_unavailable", "subscription_sharing_unsupported_capability",
            "subscription_sharing_route_not_supported", "subscription_sharing_invalid_user",
            "subscription_sharing_user_unavailable", "chatpass_v2_scope_not_authorized",
            "chatpass_v2_invalid_authorization_context",
        }.issubset(claude_gpt.SAFE_PROVIDER_ERROR_CODES))

    def test_HTTP_오류는_임의의_공급자_code와_비밀이_든_header를_버린다(self):
        # Given
        secret = "private-provider-diagnostic"
        error = claude_gpt._http_error(
            429, json.dumps({"error": {"code": secret, "message": secret}}).encode(),
            {"X-Request-ID": secret, "Retry-After": "5"},
        )

        # When
        record = claude_gpt.protocol_error(error)

        # Then
        self.assertEqual("unknown_provider_error", record["code"])
        self.assertNotIn("provider_code", record)
        self.assertNotIn("request_id", record)
        self.assertEqual(5.0, record["retry_after"])
        self.assertNotIn(secret, str(error))
        self.assertNotIn(secret, json.dumps(record))

    def test_503의_알_수_없는_공급자_code는_code_없는_HTTP_오류와_구분한다(self):
        # Given
        bodies = [
            b'{"error":{"code":"private-unknown-code"}}',
            b'{"error":{"code":{"private":"diagnostic"}}}',
            b'{"error":{"code":null}}',
            b'{}',
        ]

        # When
        records = [claude_gpt.protocol_error(claude_gpt._http_error(503, body)) for body in bodies]

        # Then
        self.assertEqual(
            ["unknown_provider_error", "unknown_provider_error", "http_error", "http_error"],
            [record["code"] for record in records],
        )
        self.assertTrue(all(record["http_status"] == 503 for record in records))
        self.assertTrue(all("provider_code" not in record for record in records))
        self.assertNotIn("private", json.dumps(records))

    def test_request_id는_허용된_요청_ID_형식만_보존한다(self):
        # Given
        uuid_request_id = "123e4567-e89b-12d3-a456-426614174000"
        unsafe_values = ["Bearer sk-secret", "Authorization: Bearer sk-secret", "req_bad_value"]

        # When
        accepted = claude_gpt._response_request_id({"x-request-id": uuid_request_id})
        rejected = [claude_gpt._response_request_id({"x-request-id": value}) for value in unsafe_values]

        # Then
        self.assertEqual(uuid_request_id, accepted)
        self.assertEqual([None, None, None], rejected)

    def test_Retry_After_HTTP_날짜를_음수가_아닌_초로_해석한다(self):
        # Given
        now = claude_gpt.dt.datetime(2026, 10, 11, 0, 0, 0, tzinfo=claude_gpt.dt.timezone.utc)
        future = {"Retry-After": "Sun, 11 Oct 2026 00:00:12 GMT"}
        past = {"Retry-After": "Sat, 10 Oct 2026 23:59:00 GMT"}

        # When
        future_delay = claude_gpt._retry_after(future, now=now)
        past_delay = claude_gpt._retry_after(past, now=now)

        # Then
        self.assertEqual(12.0, future_delay)
        self.assertEqual(0.0, past_delay)

    def test_SSE_provider_error를_구조화해_보존하고_원문_진단을_숨긴다(self):
        # Given
        api = claude_gpt.create_api_key_profile(self.store, "sk-sse-error", confirmed_usage_billing=True)
        http = FakeHttp(
            stream=_sse({"type": "response.failed", "response": {
                "error": {"code": "chatpass_v2_scope_not_authorized", "message": "private diagnostic"},
            }}),
            response_headers={"x-request-id": "req_sse-1"},
        )

        # When
        with self.assertRaises(claude_gpt.ClaudeGptError) as raised:
            claude_gpt.execute_request(self.store, http, _request(api["profile_id"]))

        # Then
        self.assertEqual("chatpass_v2_scope_not_authorized", raised.exception.code)
        self.assertEqual("chatpass_v2_scope_not_authorized", raised.exception.provider_code)
        self.assertEqual(200, raised.exception.http_status)
        self.assertEqual("req_sse-1", raised.exception.request_id)
        self.assertNotIn("private diagnostic", str(raised.exception))

    def test_SSE_최상위_rate_limit_exceeded를_보존하고_완료나_상태를_기록하지_않는다(self):
        # Given
        api = claude_gpt.create_api_key_profile(self.store, "sk-top-level-rate-limit", confirmed_usage_billing=True)
        secret = "private rate limit diagnostic"
        http = FakeHttp(stream=_sse(
            {"type": "response.output_text.delta", "delta": "partial"},
            {"type": "error", "code": "rate_limit_exceeded", "message": secret},
        ))
        output = io.StringIO()

        # When
        with patch.object(self.store, "merge_provider_state") as save_state:
            with self.assertRaises(claude_gpt.ClaudeGptError) as raised:
                claude_gpt.execute_request(self.store, http, _request(api["profile_id"]), stream_out=output)

        # Then
        self.assertEqual("rate_limit_exceeded", raised.exception.code)
        self.assertEqual("rate_limit_exceeded", raised.exception.provider_code)
        self.assertIn('"type":"text_delta"', output.getvalue())
        self.assertNotIn('"type":"completed"', output.getvalue())
        self.assertNotIn('"tool_calls"', output.getvalue())
        self.assertNotIn(secret, str(raised.exception) + output.getvalue())
        save_state.assert_not_called()

    def test_SSE_최상위_insufficient_quota를_보존하고_완료나_상태를_기록하지_않는다(self):
        # Given
        api = claude_gpt.create_api_key_profile(self.store, "sk-top-level-quota", confirmed_usage_billing=True)
        secret = "private quota diagnostic"
        http = FakeHttp(stream=_sse(
            {"type": "error", "code": "insufficient_quota", "message": secret},
        ))
        output = io.StringIO()

        # When
        with patch.object(self.store, "merge_provider_state") as save_state:
            with self.assertRaises(claude_gpt.ClaudeGptError) as raised:
                claude_gpt.execute_request(self.store, http, _request(api["profile_id"]), stream_out=output)

        # Then
        self.assertEqual("insufficient_quota", raised.exception.code)
        self.assertEqual("insufficient_quota", raised.exception.provider_code)
        self.assertNotIn('"type":"completed"', output.getvalue())
        self.assertNotIn('"tool_calls"', output.getvalue())
        self.assertNotIn(secret, str(raised.exception) + output.getvalue())
        save_state.assert_not_called()

    def test_SSE_최상위_invalid_api_key를_보존하고_완료나_상태를_기록하지_않는다(self):
        # Given
        api = claude_gpt.create_api_key_profile(self.store, "sk-top-level-invalid-key", confirmed_usage_billing=True)
        secret = "private API key diagnostic"
        http = FakeHttp(stream=_sse(
            {"type": "error", "code": "invalid_api_key", "message": secret},
        ))
        output = io.StringIO()

        # When
        with patch.object(self.store, "merge_provider_state") as save_state:
            with self.assertRaises(claude_gpt.ClaudeGptError) as raised:
                claude_gpt.execute_request(self.store, http, _request(api["profile_id"]), stream_out=output)

        # Then
        self.assertEqual("invalid_api_key", raised.exception.code)
        self.assertEqual("invalid_api_key", raised.exception.provider_code)
        self.assertNotIn('"type":"completed"', output.getvalue())
        self.assertNotIn('"tool_calls"', output.getvalue())
        self.assertNotIn(secret, str(raised.exception) + output.getvalue())
        save_state.assert_not_called()

    def test_SSE_최상위_알_수_없는_코드가_중첩_코드보다_우선하고_민감_내용을_숨긴다(self):
        # Given
        api = claude_gpt.create_api_key_profile(self.store, "sk-top-level-private-code", confirmed_usage_billing=True)
        secret = "private top-level diagnostic"
        http = FakeHttp(stream=_sse(
            {"type": "error", "code": "chatpass_v2_private_internal_code", "message": secret,
             "error": {"code": "rate_limit_exceeded", "message": "nested retryable diagnostic"}},
        ))
        output = io.StringIO()

        # When
        with patch.object(self.store, "merge_provider_state") as save_state:
            with self.assertRaises(claude_gpt.ClaudeGptError) as raised:
                claude_gpt.execute_request(self.store, http, _request(api["profile_id"]), stream_out=output)

        # Then
        self.assertEqual("provider_failed", raised.exception.code)
        self.assertIsNone(raised.exception.provider_code)
        self.assertNotIn('"type":"completed"', output.getvalue())
        self.assertNotIn('"tool_calls"', output.getvalue())
        self.assertNotIn(secret, str(raised.exception) + output.getvalue())
        self.assertNotIn("nested retryable diagnostic", str(raised.exception) + output.getvalue())
        save_state.assert_not_called()

    def test_이전_Claude_도구_ID와_겹치는_새_Responses_호출을_거부한다(self):
        # Given
        api = claude_gpt.create_api_key_profile(self.store, "sk-collision-test", confirmed_usage_billing=True)
        history = [
            {"role": "user", "content": [{"type": "text", "text": "Read."}]},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "call-previous", "name": "Read",
                                                   "input": {"file_path": "a.txt"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call-previous",
                                              "content": "contents"}]},
        ]
        response = {"type": "response.completed", "response": {
            "id": "resp-collision", "status": "completed", "model": "gpt-5.6-luna",
            "output": [{"type": "function_call", "call_id": "call-previous", "namespace": "claude",
                        "name": "Read", "arguments": "{\"file_path\":\"b.txt\"}"}],
            "usage": {"input_tokens": 4, "output_tokens": 2},
        }}
        http = FakeHttp(stream=_sse(response))
        output = io.StringIO()

        # When
        with self.assertRaises(claude_gpt.ClaudeGptError) as raised:
            claude_gpt.execute_request(self.store, http, _request(api["profile_id"], history=history),
                                       stream_out=output)

        # Then
        self.assertEqual("invalid_tool_call", raised.exception.code)
        self.assertEqual("", output.getvalue())
        self.assertEqual(1, len(http.open_calls))

    def test_Responses_도구_ID의_형식이_잘못되면_완료_레코드를_출력하지_않는다(self):
        # Given
        api = claude_gpt.create_api_key_profile(self.store, "sk-malformed-id", confirmed_usage_billing=True)
        response = {"type": "response.completed", "response": {
            "id": "resp-malformed", "status": "completed", "model": "gpt-5.6-luna",
            "output": [{"type": "function_call", "call_id": "../outside", "namespace": "claude",
                        "name": "Read", "arguments": "{\"file_path\":\"a.txt\"}"}],
            "usage": {"input_tokens": 4, "output_tokens": 2},
        }}
        http = FakeHttp(stream=_sse(response))
        output = io.StringIO()

        # When
        with self.assertRaises(claude_gpt.ClaudeGptError) as raised:
            claude_gpt.execute_request(self.store, http, _request(api["profile_id"]), stream_out=output)

        # Then
        self.assertEqual("invalid_tool_call", raised.exception.code)
        self.assertEqual("", output.getvalue())

    def test_요청과_다른_보고된_reasoning_effort는_완료로_전달하지_않는다(self):
        # Given
        api = claude_gpt.create_api_key_profile(self.store, "sk-effort-mismatch", confirmed_usage_billing=True)
        response = {"type": "response.completed", "response": {
            "id": "resp-effort", "status": "completed", "model": "gpt-5.6-luna",
            "reasoning": {"effort": "low"},
            "output": [{"type": "function_call", "call_id": "call-effort", "namespace": "claude",
                        "name": "Read", "arguments": "{\"file_path\":\"a.txt\"}"}],
            "usage": {"input_tokens": 4, "output_tokens": 2},
        }}
        http = FakeHttp(stream=_sse(response))
        output = io.StringIO()

        # When
        with self.assertRaises(claude_gpt.ClaudeGptError) as raised:
            claude_gpt.execute_request(self.store, http, _request(api["profile_id"]), stream_out=output)

        # Then
        self.assertEqual("effort_mismatch", raised.exception.code)
        self.assertEqual("", output.getvalue())

    def test_도구_결과와_스키마가_맞지_않으면_요청을_만들지_않는다(self):
        # Given
        api = claude_gpt.create_api_key_profile(self.store, "sk-test", confirmed_usage_billing=True)
        mismatch = [
            {"role": "user", "content": [{"type": "text", "text": "Read."}]},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "call-1", "name": "Read", "input": {"file_path": 4}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call-1", "content": "result"}]},
        ]
        http = FakeHttp(stream=b"")

        # When
        with self.assertRaises(claude_gpt.ClaudeGptError) as raised:
            claude_gpt.execute_request(self.store, http, _request(api["profile_id"], history=mismatch))

        # Then
        self.assertEqual("invalid_tool_call", raised.exception.code)
        self.assertEqual([], http.open_calls)

    def test_다른_세션의_대화와_맞지_않는_GPT_상태는_보내지_않는다(self):
        # Given
        api = claude_gpt.create_api_key_profile(self.store, "sk-state-test", confirmed_usage_billing=True)
        group = {
            "ids": ["call-1"],
            "calls": {"call-1": {"name": "Read", "arguments": {"file_path": "a.txt"}}},
            "items": [{
                "type": "reasoning", "id": "reasoning-old", "encrypted_content": "provider-only",
            }, {
                "type": "function_call", "call_id": "call-1", "namespace": "claude",
                "name": "Read", "arguments": "{\"file_path\":\"a.txt\"}",
            }],
        }
        with self.store.locked():
            self.store.merge_provider_state(api["profile_id"], [group])
        history = [
            {"role": "user", "content": [{"type": "text", "text": "Read."}]},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "call-1", "name": "Read",
                                                    "input": {"file_path": "b.txt"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call-1",
                                              "content": "contents"}]},
        ]
        response = {"type": "response.completed", "response": {
            "id": "resp-stale-state", "status": "completed", "model": "gpt-5.6-luna",
            "output": [], "usage": {"input_tokens": 1, "output_tokens": 0},
        }}
        http = FakeHttp(stream=_sse(response))

        # When
        claude_gpt.execute_request(
            self.store, http, _request(api["profile_id"], history=history, session_id="resumed-session"),
        )

        # Then
        payload = json.loads(http.open_calls[0].data)
        self.assertFalse(any(item.get("type") == "reasoning" for item in payload["input"]))
        saved_call = next(item for item in payload["input"] if item.get("type") == "function_call")
        self.assertEqual("call-1", saved_call["call_id"])
        self.assertEqual({"file_path": "b.txt"}, json.loads(saved_call["arguments"]))

    def test_현재_기록에_없는_다른_도구의_프로필_캐시는_현재_요청을_막지_않는다(self):
        # Given
        api = claude_gpt.create_api_key_profile(self.store, "sk-unrelated-cache", confirmed_usage_billing=True)
        unrelated = {
            "ids": ["call-other-session"],
            "calls": {"call-other-session": {"name": "Write", "arguments": {"path": "old.txt"}}},
            "items": [{
                "type": "reasoning", "id": "reasoning-other-session", "encrypted_content": "private-context",
            }, {
                "type": "function_call", "call_id": "call-other-session", "namespace": "claude",
                "name": "Write", "arguments": '{"path":"old.txt"}',
            }],
        }
        with self.store.locked():
            self.store.merge_provider_state(api["profile_id"], [unrelated])
        response = {"type": "response.completed", "response": {
            "id": "resp-unrelated-cache", "status": "completed", "model": "gpt-5.6-luna",
            "output": [], "usage": {"input_tokens": 1, "output_tokens": 0},
        }}
        http = FakeHttp(stream=_sse(response))

        # When
        claude_gpt.execute_request(
            self.store, http, _request(api["profile_id"], session_id="current-session"),
        )

        # Then
        payload = json.loads(http.open_calls[0].data)
        self.assertFalse(any(item.get("type") == "reasoning" for item in payload["input"]))
        self.assertEqual(["call-other-session"], self.store.read_provider_state(api["profile_id"])[0]["ids"])

    def test_심볼릭_링크인_설정_경로와_인증_파일을_거부한다(self):
        # Given
        target = self.base / "safe-target"
        target.mkdir(mode=0o700)
        link = self.base / "root-link"
        link.symlink_to(target, target_is_directory=True)
        unsafe_store = claude_gpt.ProfileStore(link)

        # When
        with self.assertRaises(claude_gpt.ClaudeGptError) as root_error:
            unsafe_store.ensure()
        api = claude_gpt.create_api_key_profile(self.store, "sk-test", confirmed_usage_billing=True)
        credential = self.store.profile_dir(api["profile_id"]) / "credentials.json"
        credential.unlink()
        credential.symlink_to(target / "outside.json")
        (target / "outside.json").write_text('{"api_key":"outside"}')
        with self.assertRaises(claude_gpt.ClaudeGptError) as file_error:
            self.store.read_credentials(api["profile_id"])

        # Then
        self.assertEqual("unsafe_path", root_error.exception.code)
        self.assertEqual("unsafe_path", file_error.exception.code)

    def test_부분_출력_뒤_할당량_실패와_취소는_도구를_완료하지_않는다(self):
        # Given
        api = claude_gpt.create_api_key_profile(self.store, "sk-quota-test", confirmed_usage_billing=True)
        quota = FakeHttp(stream=_sse(
            {"type": "response.output_text.delta", "delta": "partial"},
            {"type": "response.failed", "response": {"error": {"code": "insufficient_quota"}}},
        ))
        truncated = FakeHttp(stream=_sse({"type": "response.output_text.delta", "delta": "partial"}))

        class CancelledStream(io.BytesIO):
            def readline(self, *args):
                raise OSError("cancelled")

        class CancelledHttp(FakeHttp):
            def open(self, request):
                self.open_calls.append(request)
                return claude_gpt.HttpResponse(200, {}, b"", CancelledStream())

        scenarios = [(quota, "insufficient_quota"), (truncated, "truncated_stream"),
                     (CancelledHttp(), "stream_interrupted")]

        # When
        outcomes = []
        for http, expected in scenarios:
            output = io.StringIO()
            with self.assertRaises(claude_gpt.ClaudeGptError) as raised:
                claude_gpt.execute_request(self.store, http, _request(api["profile_id"]), stream_out=output)
            outcomes.append((http, expected, raised.exception.code, output.getvalue()))

        # Then
        for http, expected, actual, output in outcomes:
            self.assertEqual(expected, actual)
            self.assertEqual(1, len(http.open_calls))
            self.assertNotIn('"type":"completed"', output)
            self.assertNotIn('"tool_calls"', output)
            self.assertNotIn("sk-quota-test", output)

    def test_로그아웃은_선택한_프로필만_지우고_진행_중_요청의_상태_쓰기를_거부한다(self):
        # Given
        first = claude_gpt.create_api_key_profile(self.store, "sk-first", confirmed_usage_billing=True)
        second = claude_gpt.create_api_key_profile(self.store, "sk-second", confirmed_usage_billing=True)
        request = _request(first["profile_id"])
        _, save = claude_gpt._session_state_groups(self.store, request)
        http = FakeHttp()

        # When
        result = claude_gpt.logout_profile(self.store, http, first["profile_id"])
        with self.assertRaises(claude_gpt.ClaudeGptError) as raised:
            save([])

        # Then
        self.assertEqual("signed_out", result["status"])
        self.assertEqual("profile_signed_out", raised.exception.code)
        self.assertFalse((self.store.profile_dir(first["profile_id"]) / "credentials.json").exists())
        self.assertFalse((self.store.profile_dir(first["profile_id"]) / "state").exists())
        self.assertEqual("sk-second", self.store.read_credentials(second["profile_id"])["api_key"])
        self.assertEqual(second["profile_id"], self.store.active_profile_id())
        self.assertEqual([], http.open_calls)

    def test_JWT_서명_nonce_계정_검증에_실패하면_프로필을_선택하지_않는다(self):
        # Given
        redirect = "http://127.0.0.1:1455/auth/callback"
        attempt = claude_gpt.create_authorization_attempt(
            client_id=claude_gpt.OAUTH_DYNAMIC_CLIENT,
            host_id="urn:uuid:12345678-1234-5678-1234-567812345678", redirect_uri=redirect,
        )
        nonce_http, now, _ = self._subscription_http(nonce="different-nonce")
        signature_http, _, _ = self._subscription_http(nonce=attempt["nonce"])
        wrong_key_http, _, _ = self._subscription_http(nonce=attempt["nonce"])
        signature_http.jwks = wrong_key_http.jwks
        callback = redirect + "?" + urllib.parse.urlencode({
            "code": "test-code", "state": attempt["state"], "client_id": "oaiapp_issued-client",
        })

        # When
        errors = []
        for http in (nonce_http, signature_http):
            with self.assertRaises(claude_gpt.ClaudeGptError) as raised:
                claude_gpt.finish_subscription_login(self.store, http, profile_id=None, attempt=attempt,
                                                      callback_url=callback, now=now)
            errors.append(raised.exception.code)

        # Then
        self.assertEqual(["invalid_id_token", "invalid_id_token"], errors)
        self.assertFalse((self.store.root / "active.json").exists())

    def test_가릴_수_없는_키_입력은_저장하지_않는다(self):
        # Given
        def unmasked(_prompt):
            import warnings
            warnings.warn("unmasked input", claude_gpt.getpass.GetPassWarning)
            return "sk-unmasked"

        # When
        with self.assertRaises(claude_gpt.ClaudeGptError) as raised:
            claude_gpt.run_api_key_setup(self.store, env_name=None, input_fn=lambda _: "y", password_fn=unmasked)

        # Then
        self.assertEqual("terminal_required", raised.exception.code)
        self.assertFalse(self.store.root.exists())


if __name__ == "__main__":
    unittest.main()
