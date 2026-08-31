from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from endpoints.nalv_runtime import (
    NALV_HTTP_USER_AGENT,
    NALV_ORIGIN,
    STORAGE_PENDING_KEY,
    STORAGE_TOKEN_KEY,
    SurfaceHttpError,
    check_form_html,
    complete_pending_connect,
    disconnect_nalv,
    nalv_json,
    redact_secret,
    resolve_runtime_token,
    run_check,
    start_connect,
    storage_get,
    storage_set,
)


STORED = "nalv_surf_stored_credential"
MANUAL = "nalv_surf_manual_fallback"
ORIGIN = "https://app.nalv.ai"


class FakeStorage:
    def __init__(self, store=None):
        self.store = store if store is not None else {}

    def get(self, key):
        if key not in self.store:
            return None
        return self.store[key]

    def set(self, key, value):
        self.store[key] = value if isinstance(value, bytes) else str(value).encode("utf-8")

    def delete(self, key):
        self.store.pop(key, None)


class FakeChat:
    def invoke(self, **kwargs):
        return {"answer": "ok", "conversation_id": "conv-1"}


class FakeSession:
    def __init__(self, store=None):
        self.storage = FakeStorage(store)
        self.app = type("App", (), {"chat": FakeChat()})()


class NalvConnectStorageTest(unittest.TestCase):
    def test_storage_write_read_persists_across_endpoint_invocations(self):
        backing = {}
        first = FakeSession(backing)
        storage_set(first, STORAGE_TOKEN_KEY, STORED)
        second = FakeSession(backing)
        self.assertEqual(storage_get(second, STORAGE_TOKEN_KEY), STORED)
        self.assertEqual(resolve_runtime_token(second, {"surface_token": MANUAL}), STORED)

    def test_stored_credential_is_preferred_over_manual_setting(self):
        session = FakeSession()
        storage_set(session, STORAGE_TOKEN_KEY, STORED)
        self.assertEqual(resolve_runtime_token(session, {"surface_token": MANUAL}), STORED)

    def test_manual_surface_token_fallback_still_works(self):
        session = FakeSession()
        self.assertEqual(resolve_runtime_token(session, {"surface_token": MANUAL}), MANUAL)

    def test_connect_then_exchange_persists_token_for_later_invocation(self):
        backing = {}
        start_session = FakeSession(backing)
        with patch("endpoints.nalv_runtime.nalv_json") as mocked:
            mocked.return_value = {
                "connectSessionId": "csess-aaaaaaaaaaaaaaaa",
                "exchangeSecret": "exchange-secret",
                "authorizationUrl": ORIGIN + "/connect/dify?sid=csess-aaaaaaaaaaaaaaaa&state=state-1",
            }
            started = start_connect(start_session, {"nalv_origin": ORIGIN})
        self.assertEqual(started["redirect"].startswith(ORIGIN + "/connect/dify"), True)
        self.assertNotIn("exchangeSecret", started)
        pending = json.loads(storage_get(start_session, STORAGE_PENDING_KEY))
        self.assertEqual(pending["exchangeSecret"], "exchange-secret")

        later = FakeSession(backing)
        with patch("endpoints.nalv_runtime.nalv_json") as mocked:
            mocked.return_value = {"token": STORED, "tokenId": "stok-1"}
            completed = complete_pending_connect(later, {"nalv_origin": ORIGIN})
        self.assertEqual(completed, {"ok": True, "connected": True})

        third = FakeSession(backing)
        self.assertEqual(resolve_runtime_token(third, {"surface_token": MANUAL}), STORED)
        self.assertIsNone(storage_get(third, STORAGE_PENDING_KEY))

    def test_pending_exchange_stays_pending_without_token(self):
        session = FakeSession()
        storage_set(
            session,
            STORAGE_PENDING_KEY,
            json.dumps({"connectSessionId": "csess-aaaaaaaaaaaaaaaa", "exchangeSecret": "secret"}),
        )
        with patch("endpoints.nalv_runtime.nalv_json") as mocked:
            mocked.side_effect = SurfaceHttpError(409, "CONNECT_PENDING", "wait")
            result = complete_pending_connect(session, {"nalv_origin": ORIGIN})
        self.assertEqual(result, {"ok": True, "pending": True})
        self.assertIsNone(storage_get(session, STORAGE_TOKEN_KEY))

    def test_run_check_uses_settings_app_when_form_has_no_app_id(self):
        session = FakeSession()
        storage_set(session, STORAGE_TOKEN_KEY, STORED)
        settings = {
            "nalv_origin": ORIGIN,
            "app": {"app_id": "app-from-selector", "mode": "advanced-chat"},
        }
        with patch("endpoints.nalv_runtime.nalv_json") as mocked:
            mocked.side_effect = [
                {"ok": True},
                {"jobId": "job-1", "executionId": "exec-1", "userTurns": ["hello"]},
                {"overallDecision": "PASS", "evidenceUrl": "https://nalv.example/e"},
            ]
            result = run_check(session, settings, {"format": "html"})
        self.assertTrue(result["ok"])
        self.assertEqual(
            mocked.call_args_list[0].args[4],
            {"appId": "app-from-selector", "appMode": "advanced-chat"},
        )

    def test_connected_page_uses_settings_app_and_omits_required_app_id(self):
        html = check_form_html({"app": {"app_id": "app-from-selector", "mode": "chatflow"}}, True)
        self.assertIn("Run behavior check", html)
        self.assertIn("Mode: Chatflow", html)
        self.assertNotIn('name="app_id"', html)
        self.assertNotIn("required", html)
        missing = check_form_html({"nalv_origin": ORIGIN}, True)
        self.assertNotIn("Run behavior check", missing)
        self.assertNotIn('name="app_id"', missing)
        self.assertIn("Endpoint settings", missing)

    def test_disconnected_page_keeps_mode_and_hides_run(self):
        html = check_form_html({"app": {"app_id": "app-from-selector", "mode": "chatflow"}}, False)
        self.assertIn("Mode: Chatflow", html)
        self.assertNotIn("Run behavior check", html)
        self.assertNotIn('name="app_id"', html)

    def test_run_check_prefers_stored_token_and_keeps_manual_fallback(self):
        stored_session = FakeSession()
        storage_set(stored_session, STORAGE_TOKEN_KEY, STORED)
        settings = {"nalv_origin": ORIGIN, "surface_token": MANUAL, "app": "app-1"}
        with patch("endpoints.nalv_runtime.nalv_json") as mocked:
            mocked.side_effect = [
                {"ok": True},
                {"jobId": "job-1", "executionId": "exec-1", "userTurns": ["hello"]},
                {"overallDecision": "PASS", "evidenceUrl": "https://nalv.example/e"},
            ]
            result = run_check(stored_session, settings, {"app_id": "app-1", "app_mode": "chatflow"})
        self.assertTrue(result["ok"])
        self.assertEqual(mocked.call_args_list[0].args[1], STORED)
        fallback = FakeSession()
        with patch("endpoints.nalv_runtime.nalv_json") as mocked:
            mocked.side_effect = [
                {"ok": True},
                {"jobId": "job-1", "executionId": "exec-1", "userTurns": ["hello"]},
                {"overallDecision": "PASS", "evidenceUrl": "https://nalv.example/e"},
            ]
            fallback_result = run_check(
                fallback,
                {"nalv_origin": ORIGIN, "surface_token": MANUAL},
                {"app_id": "app-1", "app_mode": "chatflow"},
            )
        self.assertTrue(fallback_result["ok"])
        self.assertEqual(mocked.call_args_list[0].args[1], MANUAL)

    def test_no_token_appears_in_error_output(self):
        session = FakeSession()
        storage_set(session, STORAGE_TOKEN_KEY, STORED)
        with patch("endpoints.nalv_runtime.nalv_json") as mocked:
            mocked.side_effect = SurfaceHttpError(502, "NALV_HTTP_ERROR", "failed " + STORED + " " + MANUAL)
            result = run_check(
                session,
                {"nalv_origin": ORIGIN, "surface_token": MANUAL},
                {"app_id": "app-1", "app_mode": "chatflow"},
            )
        serialized = json.dumps(result)
        self.assertNotIn(STORED, serialized)
        self.assertNotIn(MANUAL, result["message"])
        self.assertEqual(redact_secret("use " + STORED, STORED), "use [redacted]")

    def test_nalv_http_sets_plugin_user_agent_not_python_urllib(self):
        captured = {}

        class FakeResponse:
            def read(self):
                return b'{"ok":true}'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(request, timeout=None):
            captured["headers"] = dict(request.header_items())
            captured["timeout"] = timeout
            return FakeResponse()

        with patch("endpoints.nalv_runtime.urlopen", fake_urlopen):
            payload = nalv_json(ORIGIN, "", "POST", "/api/preflight/surface/connect/sessions", {})
        headers = {key.lower(): value for key, value in captured["headers"].items()}
        self.assertEqual(payload, {"ok": True})
        self.assertEqual(headers["user-agent"], NALV_HTTP_USER_AGENT)
        self.assertFalse(headers["user-agent"].lower().startswith("python-urllib"))
        self.assertEqual(headers["accept"], "application/json")

    def test_disconnect_removes_plugin_stored_credential(self):
        session = FakeSession()
        storage_set(session, STORAGE_TOKEN_KEY, STORED)
        with patch("endpoints.nalv_runtime.nalv_json") as mocked:
            mocked.return_value = {"ok": True, "revoked": True}
            result = disconnect_nalv(session, {"nalv_origin": ORIGIN})
        self.assertEqual(result["disconnected"], True)
        self.assertIsNone(storage_get(session, STORAGE_TOKEN_KEY))
        self.assertEqual(mocked.call_args_list[0].args[1], STORED)


class NalvFixedOriginTest(unittest.TestCase):
    """The Marketplace build must only ever talk to the fixed NALV origin."""

    def test_origin_constant_is_production_nalv(self):
        self.assertEqual(NALV_ORIGIN, "https://app.nalv.ai")

    def test_start_connect_ignores_settings_origin_override(self):
        session = FakeSession()
        with patch("endpoints.nalv_runtime.nalv_json") as mocked:
            mocked.return_value = {
                "connectSessionId": "csess-aaaaaaaaaaaaaaaa",
                "exchangeSecret": "exchange-secret",
                "authorizationUrl": ORIGIN + "/connect/dify?sid=csess-aaaaaaaaaaaaaaaa&state=state-1",
            }
            start_connect(session, {"nalv_origin": "https://attacker.example"})
        self.assertEqual(mocked.call_args_list[0].args[0], "https://app.nalv.ai")

    def test_run_check_ignores_payload_origin_override(self):
        session = FakeSession()
        storage_set(session, STORAGE_TOKEN_KEY, STORED)
        settings = {"nalv_origin": "https://attacker.example", "app": {"app_id": "app-1", "mode": "chatflow"}}
        payload = {"nalv_origin": "https://evil.example", "app_id": "app-1"}
        with patch("endpoints.nalv_runtime.nalv_json") as mocked:
            mocked.side_effect = [
                {"ok": True},
                {"jobId": "job-1", "executionId": "exec-1", "userTurns": ["hello"]},
                {"overallDecision": "PASS", "evidenceUrl": "https://app.nalv.ai/e"},
            ]
            result = run_check(session, settings, payload)
        self.assertTrue(result["ok"])
        for call in mocked.call_args_list:
            self.assertEqual(call.args[0], "https://app.nalv.ai")

    def test_disconnect_ignores_settings_origin_override(self):
        session = FakeSession()
        storage_set(session, STORAGE_TOKEN_KEY, STORED)
        with patch("endpoints.nalv_runtime.nalv_json") as mocked:
            mocked.return_value = {"ok": True, "revoked": True}
            disconnect_nalv(session, {"nalv_origin": "https://attacker.example"})
        self.assertEqual(mocked.call_args_list[0].args[0], "https://app.nalv.ai")

    def test_harmless_unknown_settings_do_not_change_destination(self):
        session = FakeSession()
        storage_set(session, STORAGE_TOKEN_KEY, STORED)
        with patch("endpoints.nalv_runtime.nalv_json") as mocked:
            mocked.side_effect = [
                {"ok": True},
                {"jobId": "job-1", "executionId": "exec-1", "userTurns": ["hello"]},
                {"overallDecision": "PASS", "evidenceUrl": "https://app.nalv.ai/e"},
            ]
            run_check(
                session,
                {"nalv_origin": "http://127.0.0.1:9999", "app": {"app_id": "app-1", "mode": "chat"}},
                {},
            )
        for call in mocked.call_args_list:
            self.assertEqual(call.args[0], "https://app.nalv.ai")


if __name__ == "__main__":
    unittest.main()
