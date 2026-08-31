from __future__ import annotations

import json
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

SUPPORTED_MODES = {"chat", "chatbot", "advanced-chat", "chatflow"}
UNSUPPORTED_MODES = {"agent", "agent-chat", "workflow", "completion"}
NALV_REQUEST_TIMEOUT_SECONDS = 120
# Some edges reject Python-urllib's default User-Agent. Send a plugin-specific one.
NALV_HTTP_USER_AGENT = "NALV-Dify-Plugin/0.1"
# Fixed production destination. The plugin never reads an origin from settings or
# request payloads, so no caller can redirect its network traffic.
NALV_ORIGIN = "https://app.nalv.ai"
NALV_SURFACE_PATHS = (
    "/api/preflight/surface/dify/bind",
    "/api/preflight/surface/jobs",
)
CONNECT_SESSIONS_PATH = "/api/preflight/surface/connect/sessions"
CONNECT_DISCONNECT_PATH = "/api/preflight/surface/connect/disconnect"
STORAGE_TOKEN_KEY = "nalv.connected.token"
STORAGE_PENDING_KEY = "nalv.connect.pending"


class SurfaceHttpError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


PLUGIN_INVOKE_METHOD = "session.app.chat.invoke"


def redact_secret(text: str, secret: str) -> str:
    cleaned = text
    if secret:
        cleaned = cleaned.replace(secret, "[redacted]")
    return cleaned


def redact_credentials(text: str, *secrets: str) -> str:
    cleaned = text
    for secret in secrets:
        cleaned = redact_secret(cleaned, secret)
    return cleaned


def storage_get(session: Any, key: str) -> str | None:
    storage = getattr(session, "storage", None)
    if storage is None:
        return None
    try:
        raw = storage.get(key)
    except Exception:
        return None
    if raw is None:
        return None
    if isinstance(raw, bytes):
        return raw.decode("utf-8")
    return str(raw)


def storage_set(session: Any, key: str, value: str) -> None:
    storage = getattr(session, "storage", None)
    if storage is None:
        raise SurfaceHttpError(503, "PLUGIN_STORAGE_UNAVAILABLE", "Plugin storage is not available.")
    storage.set(key, value.encode("utf-8"))


def storage_delete(session: Any, key: str) -> None:
    storage = getattr(session, "storage", None)
    if storage is None:
        return
    try:
        storage.delete(key)
    except Exception:
        return


def resolve_runtime_token(session: Any, settings: Mapping) -> str:
    stored = (storage_get(session, STORAGE_TOKEN_KEY) or "").strip()
    if stored:
        return stored
    return str(settings.get("surface_token") or "").strip()


def start_connect(session: Any, settings: Mapping) -> dict:
    created = nalv_json(NALV_ORIGIN, "", "POST", CONNECT_SESSIONS_PATH, {})
    session_id = str(created.get("connectSessionId") or "")
    secret = str(created.get("exchangeSecret") or "")
    authorization_url = str(created.get("authorizationUrl") or "")
    if not session_id or not secret or not authorization_url:
        raise SurfaceHttpError(502, "CONNECT_PROTOCOL_ERROR", "NALV connect session was incomplete.")
    storage_set(
        session,
        STORAGE_PENDING_KEY,
        json.dumps({"connectSessionId": session_id, "exchangeSecret": secret}),
    )
    return {
        "ok": True,
        "redirect": authorization_url,
        "connectSessionId": session_id,
    }


def complete_pending_connect(session: Any, settings: Mapping) -> dict | None:
    pending_raw = storage_get(session, STORAGE_PENDING_KEY)
    if not pending_raw:
        return None
    try:
        pending = json.loads(pending_raw)
    except json.JSONDecodeError:
        storage_delete(session, STORAGE_PENDING_KEY)
        return None
    session_id = str(pending.get("connectSessionId") or "")
    secret = str(pending.get("exchangeSecret") or "")
    if not session_id or not secret:
        storage_delete(session, STORAGE_PENDING_KEY)
        return None
    try:
        exchanged = nalv_json(
            NALV_ORIGIN,
            "",
            "POST",
            CONNECT_SESSIONS_PATH + "/" + session_id + "/exchange",
            {"exchangeSecret": secret},
        )
    except SurfaceHttpError as error:
        if error.code == "CONNECT_PENDING":
            return {"ok": True, "pending": True}
        if error.code in {"CONNECT_CONSUMED", "CONNECT_SESSION_EXPIRED", "CONNECT_SESSION_NOT_FOUND"}:
            storage_delete(session, STORAGE_PENDING_KEY)
        raise
    token = str(exchanged.get("token") or "").strip()
    if not token:
        raise SurfaceHttpError(502, "CONNECT_PROTOCOL_ERROR", "NALV connect exchange returned no credential.")
    storage_set(session, STORAGE_TOKEN_KEY, token)
    storage_delete(session, STORAGE_PENDING_KEY)
    return {"ok": True, "connected": True}


def disconnect_nalv(session: Any, settings: Mapping) -> dict:
    token = resolve_runtime_token(session, settings)
    if token:
        try:
            nalv_json(NALV_ORIGIN, token, "POST", CONNECT_DISCONNECT_PATH, {})
        except SurfaceHttpError:
            pass
    storage_delete(session, STORAGE_TOKEN_KEY)
    storage_delete(session, STORAGE_PENDING_KEY)
    return {"ok": True, "disconnected": True}


def require_plugin_chat_invoke(session: Any):
    try:
        invoke = session.app.chat.invoke
    except AttributeError as error:
        raise SurfaceHttpError(
            400,
            "PLUGIN_SESSION_REQUIRED",
            "This path requires a Dify plugin session with session.app.chat.invoke.",
        ) from error
    if not callable(invoke):
        raise SurfaceHttpError(
            400,
            "PLUGIN_SESSION_REQUIRED",
            "session.app.chat.invoke is not callable.",
        )
    return invoke


def _app_from_setting(selected: Any) -> tuple[str, str]:
    if isinstance(selected, str) and selected.strip():
        return selected.strip(), ""
    if isinstance(selected, Mapping):
        return (
            str(selected.get("app_id") or selected.get("id") or "").strip(),
            str(selected.get("mode") or selected.get("app_mode") or selected.get("appMode") or "").strip(),
        )
    return "", ""


def selected_dify_app(settings: Mapping, payload: Mapping) -> tuple[str, str]:
    setting_id, setting_mode = _app_from_setting(settings.get("app"))
    payload_id = str(payload.get("app_id") or payload.get("appId") or "").strip()
    payload_mode = str(payload.get("app_mode") or payload.get("appMode") or "").strip()
    return setting_id or payload_id, setting_mode or payload_mode or "chatflow"


def display_app_mode(mode: str) -> str:
    normalized = mode.lower().replace("_", "-")
    if normalized in {"chat", "chatbot"}:
        return "Chatbot"
    if normalized in {"advanced-chat", "chatflow"}:
        return "Chatflow"
    return ""


def escape_html(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def check_form_html(settings: Mapping, connected: bool = False) -> str:
    bound_id, bound_mode = selected_dify_app(settings, {})
    if not bound_id:
        return "<p>Select a Chatbot or Chatflow in the Endpoint settings.</p>"
    mode_label = display_app_mode(bound_mode)
    mode_html = f"<p>Mode: {escape_html(mode_label)}</p>" if mode_label else ""
    if not connected:
        return mode_html
    return (
        f"{mode_html}"
        '<form method="post">'
        '<input type="hidden" name="format" value="html">'
        "<button type=\"submit\">Run behavior check</button>"
        "</form>"
    )


def chat_invoke_kwargs(app_id: str, query: str, conversation_id: str | None) -> dict[str, Any]:
    """Omit conversation_id until Dify has issued one. Do not send null/empty."""
    kwargs: dict[str, Any] = {
        "app_id": app_id,
        "query": query,
        "inputs": {},
        "response_mode": "blocking",
    }
    if conversation_id:
        kwargs["conversation_id"] = conversation_id
    return kwargs


def blocking_payload(invoked: Any) -> dict:
    """Blocking reverse-invoke should return a dict. Some Dify hosts yield events."""
    if isinstance(invoked, dict):
        return invoked
    payload: dict = {}
    try:
        iterator = iter(invoked)
    except TypeError:
        return payload
    for item in iterator:
        if not isinstance(item, dict):
            continue
        if item.get("event") == "ping":
            continue
        payload = item
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        answer = str(item.get("answer") or data.get("answer") or "").strip()
        conversation_id = str(
            item.get("conversation_id") or data.get("conversation_id") or ""
        ).strip()
        if answer and conversation_id:
            return {
                **item,
                "answer": answer,
                "conversation_id": conversation_id,
            }
    return payload


def reverse_invoke_turns(
    session: Any,
    app_id: str,
    user_turns: list[str],
    *,
    bogus_conversation_id: str | None = None,
) -> dict[str, Any]:
    invoke = require_plugin_chat_invoke(session)
    conversation_id = None
    replies: list[str] = []
    broken = False
    infra = None
    turns: list[dict[str, Any]] = []
    session_type = type(session)
    for index, query in enumerate(user_turns):
        prior = conversation_id
        if index > 0 and bogus_conversation_id:
            prior = bogus_conversation_id
        kwargs = chat_invoke_kwargs(app_id, query, prior)
        turns.append(
            {
                "turn": index + 1,
                "method": PLUGIN_INVOKE_METHOD,
                "omittedConversationId": "conversation_id" not in kwargs,
                "responseMode": "blocking",
                "kwargKeys": sorted(kwargs.keys()),
            }
        )
        try:
            invoked = invoke(**kwargs)
        except TypeError as error:
            if conversation_id:
                infra = {
                    "code": "DIFY_REVERSE_INVOKE_FAILED",
                    "message": str(error) or "Dify reverse invocation rejected conversation_id.",
                }
                break
            try:
                invoked = invoke(
                    app_id=app_id,
                    query=query,
                    inputs={},
                    response_mode="blocking",
                )
            except Exception as nested:
                infra = {
                    "code": "DIFY_REVERSE_INVOKE_FAILED",
                    "message": str(nested) or "Dify reverse invocation failed.",
                }
                break
        except Exception as error:
            infra = {
                "code": "DIFY_REVERSE_INVOKE_FAILED",
                "message": str(error) or "Dify reverse invocation failed.",
            }
            break
        chunk = blocking_payload(invoked)
        answer = str(chunk.get("answer") or "").strip()
        next_id = str(chunk.get("conversation_id") or "").strip()
        if not answer or not next_id:
            infra = {
                "code": "ADAPTER_PROTOCOL_ERROR",
                "message": "Dify reverse invocation did not return answer and conversation_id.",
            }
            break
        if conversation_id and next_id != conversation_id:
            broken = True
            infra = {
                "code": "CONVERSATION_IDENTITY_CHANGED",
                "message": "Dify conversation identity changed across turns.",
            }
            replies.append(answer)
            break
        conversation_id = next_id
        replies.append(answer)
    evidence: dict[str, Any] = {"replies": replies}
    if conversation_id:
        evidence["conversationId"] = conversation_id
    if broken:
        evidence["conversationBroken"] = True
    if infra:
        evidence["infrastructureError"] = infra
    evidence["pluginRuntime"] = {
        "method": PLUGIN_INVOKE_METHOD,
        "sessionModule": getattr(session_type, "__module__", ""),
        "sessionClass": getattr(session_type, "__name__", ""),
        "replyCount": len(replies),
        "sameConversationId": bool(conversation_id)
        and len(replies) == len(user_turns)
        and not broken
        and not infra,
        "turns": turns,
    }
    return evidence


def run_check(session: Any, settings: Mapping, payload: Mapping) -> dict:
    try:
        complete_pending_connect(session, settings)
    except SurfaceHttpError as error:
        if error.code != "CONNECT_PENDING":
            return {
                "ok": False,
                "httpStatus": error.status,
                "error": error.code,
                "message": redact_credentials(
                    error.message,
                    resolve_runtime_token(session, settings),
                    str(payload.get("surface_token") or ""),
                ),
            }
    token = resolve_runtime_token(session, settings) or str(payload.get("surface_token") or "").strip()
    app_id, app_mode = selected_dify_app(settings, payload)
    if not token:
        return {
            "ok": False,
            "httpStatus": 400,
            "error": "MISSING_SETTINGS",
            "message": "Connect NALV, or provide a NALV connection key.",
        }
    if not app_id:
        return {
            "ok": False,
            "httpStatus": 400,
            "error": "INVALID_REQUEST",
            "message": "Select a Chatbot or Chatflow in the Endpoint settings.",
        }
    mode = app_mode.lower().replace("_", "-")
    if mode in UNSUPPORTED_MODES or mode not in SUPPORTED_MODES:
        return {
            "ok": False,
            "httpStatus": 400,
            "error": "UNSUPPORTED_DIFY_APP",
            "message": "Agent, Workflow, and other modes are an unsupported target, not a behavioral FAIL.",
        }
    try:
        bind = nalv_json(
            NALV_ORIGIN,
            token,
            "POST",
            NALV_SURFACE_PATHS[0],
            {"appId": app_id, "appMode": mode},
        )
        job = nalv_json(NALV_ORIGIN, token, "POST", NALV_SURFACE_PATHS[1], {})
        observed = reverse_invoke_turns(
            session,
            app_id,
            list(job["userTurns"]),
            bogus_conversation_id="not-a-real-dify-conversation"
            if payload.get("acceptFailure") == "bogus-conversation"
            else None,
        )
        runtime = observed.pop("pluginRuntime")
        evidence = {"executionId": job["executionId"], **observed}
        completed = nalv_json(
            NALV_ORIGIN,
            token,
            "POST",
            NALV_SURFACE_PATHS[1] + "/" + str(job["jobId"]) + "/evidence",
            evidence,
        )
        return {
            "ok": True,
            "bind": bind,
            "job": job,
            "result": completed,
            "pluginRuntime": runtime,
        }
    except SurfaceHttpError as error:
        return {
            "ok": False,
            "httpStatus": error.status,
            "error": error.code,
            "message": redact_credentials(
                error.message,
                token,
                str(settings.get("surface_token") or ""),
                str(payload.get("surface_token") or ""),
            ),
        }


def nalv_json(origin: str, token: str, method: str, path: str, body: dict) -> dict:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": NALV_HTTP_USER_AGENT,
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    request = UrlRequest(
        origin + path,
        data=json.dumps(body).encode("utf-8"),
        method=method,
        headers=headers,
    )
    try:
        with urlopen(request, timeout=NALV_REQUEST_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as error:
        raw = error.read().decode("utf-8") if error.fp else ""
        payload = {}
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {}
        raise SurfaceHttpError(
            error.code,
            str(payload.get("error") or "NALV_HTTP_ERROR"),
            redact_secret(str(payload.get("message") or raw or error.reason), token),
        ) from error
    except URLError as error:
        raise SurfaceHttpError(
            502,
            "NALV_UNREACHABLE",
            redact_secret(str(error.reason), token),
        ) from error
