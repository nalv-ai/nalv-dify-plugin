from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from endpoints.nalv_runtime import (
    SurfaceHttpError,
    blocking_payload,
    chat_invoke_kwargs,
    display_app_mode,
    redact_secret,
    reverse_invoke_turns,
    selected_dify_app,
)


class FakeChat:
    def __init__(self, responses, fail_on_none_conversation=False):
        self.calls = []
        self.responses = list(responses)
        self.fail_on_none_conversation = fail_on_none_conversation

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_on_none_conversation and "conversation_id" in kwargs and kwargs["conversation_id"] is None:
            raise TypeError("conversation_id must be str")
        if not self.responses:
            raise AssertionError("unexpected invoke")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeSession:
    def __init__(self, chat):
        self.app = type("App", (), {"chat": chat})()


class NalvRuntimeTest(unittest.TestCase):
    def test_settings_app_selector_shape_is_used_without_payload_app_id(self):
        self.assertEqual(
            selected_dify_app({"app": {"app_id": "app-from-selector", "mode": "advanced-chat"}}, {}),
            ("app-from-selector", "advanced-chat"),
        )
        self.assertEqual(
            selected_dify_app({"app": {"app_id": "app-from-selector"}}, {}),
            ("app-from-selector", "chatflow"),
        )
        self.assertEqual(
            selected_dify_app({"app": {"app_id": "app-from-selector"}}, {"app_id": "payload-app"}),
            ("app-from-selector", "chatflow"),
        )
        self.assertEqual(
            selected_dify_app({}, {"app_id": "payload-app", "app_mode": "chatbot"}),
            ("payload-app", "chatbot"),
        )
        self.assertEqual(display_app_mode("advanced-chat"), "Chatflow")
        self.assertEqual(display_app_mode("chat"), "Chatbot")

    def test_omits_conversation_id_until_issued(self):
        self.assertEqual(
            set(chat_invoke_kwargs("app-1", "hello", None)),
            {"app_id", "query", "inputs", "response_mode"},
        )
        self.assertEqual(
            chat_invoke_kwargs("app-1", "hello", "conv-9")["conversation_id"],
            "conv-9",
        )

    def test_preserves_one_conversation_id_across_three_turns(self):
        chat = FakeChat(
            [
                {"answer": "a1", "conversation_id": "conv-stable"},
                {"answer": "a2", "conversation_id": "conv-stable"},
                {"answer": "a3", "conversation_id": "conv-stable"},
            ]
        )
        observed = reverse_invoke_turns(
            FakeSession(chat),
            "app-1",
            ["u1", "u2", "u3"],
        )
        self.assertEqual(observed["conversationId"], "conv-stable")
        self.assertEqual(observed["replies"], ["a1", "a2", "a3"])
        self.assertNotIn("conversation_id", chat.calls[0])
        self.assertEqual(chat.calls[1]["conversation_id"], "conv-stable")
        self.assertEqual(chat.calls[2]["conversation_id"], "conv-stable")

    def test_conversation_break_is_reported_not_retried_without_id(self):
        chat = FakeChat(
            [
                {"answer": "a1", "conversation_id": "conv-a"},
                {"answer": "a2", "conversation_id": "conv-b"},
            ]
        )
        observed = reverse_invoke_turns(FakeSession(chat), "app-1", ["u1", "u2", "u3"])
        self.assertEqual(observed["conversationBroken"], True)
        self.assertEqual(observed["infrastructureError"]["code"], "CONVERSATION_IDENTITY_CHANGED")
        self.assertEqual(len(chat.calls), 2)

    def test_typeerror_after_turn_1_does_not_drop_conversation_id(self):
        chat = FakeChat(
            [
                {"answer": "a1", "conversation_id": "conv-a"},
                TypeError("unexpected kw"),
            ]
        )
        observed = reverse_invoke_turns(FakeSession(chat), "app-1", ["u1", "u2"])
        self.assertEqual(observed["infrastructureError"]["code"], "DIFY_REVERSE_INVOKE_FAILED")
        self.assertEqual(len(chat.calls), 2)
        self.assertEqual(chat.calls[1]["conversation_id"], "conv-a")

    def test_blocking_payload_skips_ping_events(self):
        def stream():
            yield {"event": "ping"}
            yield {"event": "message", "answer": "hi", "conversation_id": "c1"}

        self.assertEqual(
            blocking_payload(stream()),
            {"event": "message", "answer": "hi", "conversation_id": "c1"},
        )

    def test_records_session_app_chat_invoke_and_omitted_then_reused_id(self):
        chat = FakeChat(
            [
                {"answer": "a1", "conversation_id": "conv-stable"},
                {"answer": "a2", "conversation_id": "conv-stable"},
                {"answer": "a3", "conversation_id": "conv-stable"},
            ]
        )
        observed = reverse_invoke_turns(FakeSession(chat), "app-1", ["u1", "u2", "u3"])
        runtime = observed["pluginRuntime"]
        self.assertEqual(runtime["method"], "session.app.chat.invoke")
        self.assertEqual(runtime["sameConversationId"], True)
        self.assertEqual(runtime["turns"][0]["omittedConversationId"], True)
        self.assertEqual(runtime["turns"][1]["omittedConversationId"], False)
        self.assertEqual(runtime["turns"][2]["omittedConversationId"], False)

    def test_missing_plugin_session_is_rejected(self):
        with self.assertRaises(SurfaceHttpError) as raised:
            reverse_invoke_turns(object(), "app-1", ["u1"])
        self.assertEqual(raised.exception.code, "PLUGIN_SESSION_REQUIRED")

    def test_bogus_conversation_id_uses_invoke_and_reports_infra(self):
        chat = FakeChat(
            [
                {"answer": "a1", "conversation_id": "conv-a"},
                RuntimeError("conversation not exists"),
            ]
        )
        observed = reverse_invoke_turns(
            FakeSession(chat),
            "app-1",
            ["u1", "u2"],
            bogus_conversation_id="not-a-real-dify-conversation",
        )
        self.assertEqual(chat.calls[1]["conversation_id"], "not-a-real-dify-conversation")
        self.assertEqual(observed["infrastructureError"]["code"], "DIFY_REVERSE_INVOKE_FAILED")
        self.assertNotEqual(observed.get("pluginRuntime", {}).get("method"), None)

    def test_connection_key_is_redacted_from_errors(self):
        self.assertEqual(
            redact_secret("Bearer nalv_surf_example failed", "nalv_surf_example"),
            "Bearer [redacted] failed",
        )


if __name__ == "__main__":
    unittest.main()
