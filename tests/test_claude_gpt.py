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
        "model": "gpt-6-luna",
        "effort": "high",
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
                 jwks: dict | None = None, stream: bytes | None = None, status: int = 200,
                 error_body: bytes = b"{}"):
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
            return claude_gpt.HttpResponse(self.status, {}, self.error_body)
        if self.stream is None:
            return claude_gpt.HttpResponse(200, {}, b"")
        return claude_gpt.HttpResponse(200, {"Content-Type": "text/event-stream"}, b"", io.BytesIO(self.stream))


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

    def test_출시_호스트가_지원되지_않으면_프로필이나_네트워크를_살피기_전에_거부한다(self):
        # Given
        def unexpected(*args, **kwargs):
            raise AssertionError("launch inspected state or used the network")

        # When
        with patch.object(claude_gpt.ProfileStore, "default", unexpected), patch.object(claude_gpt, "HttpClient", unexpected):
            with self.assertRaises(claude_gpt.ClaudeGptError) as raised:
                claude_gpt.main(["launch"])

        # Then
        self.assertEqual("unsupported_host", raised.exception.code)
        self.assertIn("도구 입력 스키마", raised.exception.message)
        self.assertFalse(self.store.root.exists())

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

    def test_구독_권한이_없거나_state가_틀리면_인증_코드를_교환하지_않는다(self):
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
                "id": "resp-one", "status": "completed", "model": "gpt-6-luna",
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
        second_request = _request(api["profile_id"], history=followup_history, step_id="step-2")
        second_http = FakeHttp(stream=_sse(
            {"type": "response.output_text.delta", "delta": "완료했습니다."},
            {
            "type": "response.completed", "response": {
                "id": "resp-two", "status": "completed", "model": "gpt-6-luna",
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
                "id": "resp-bad", "status": "completed", "model": "gpt-6-luna",
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
            "id": "resp-collision", "status": "completed", "model": "gpt-6-luna",
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
            "id": "resp-malformed", "status": "completed", "model": "gpt-6-luna",
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
            "id": "resp-effort", "status": "completed", "model": "gpt-6-luna",
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

    def test_저장된_GPT_도구_상태가_대화와_맞지_않으면_요청을_만들지_않는다(self):
        # Given
        api = claude_gpt.create_api_key_profile(self.store, "sk-state-test", confirmed_usage_billing=True)
        self.store.write_session_state(api["profile_id"], "session-test", [{
            "ids": ["call-1"],
            "calls": {"call-1": {"name": "Read", "arguments": {"file_path": "a.txt"}}},
            "items": [{
                "type": "function_call", "call_id": "call-other", "namespace": "claude",
                "name": "Read", "arguments": "{\"file_path\":\"a.txt\"}",
            }],
        }])
        http = FakeHttp(stream=b"")

        # When
        with self.assertRaises(claude_gpt.ClaudeGptError) as raised:
            claude_gpt.execute_request(self.store, http, _request(api["profile_id"]))

        # Then
        self.assertEqual("invalid_state", raised.exception.code)
        self.assertEqual([], http.open_calls)

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
