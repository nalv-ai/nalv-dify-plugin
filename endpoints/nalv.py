from __future__ import annotations

import json
from typing import Mapping

from dify_plugin import Endpoint
from werkzeug import Request, Response

try:
    from .nalv_runtime import (
        SurfaceHttpError,
        check_form_html,
        complete_pending_connect,
        disconnect_nalv,
        escape_html,
        redact_secret,
        resolve_runtime_token,
        run_check,
        start_connect,
        storage_get,
        STORAGE_TOKEN_KEY,
    )
except ImportError:
    try:
        from endpoints.nalv_runtime import (
            SurfaceHttpError,
            check_form_html,
            complete_pending_connect,
            disconnect_nalv,
            escape_html,
            redact_secret,
            resolve_runtime_token,
            run_check,
            start_connect,
            storage_get,
            STORAGE_TOKEN_KEY,
        )
    except ImportError:
        from nalv_runtime import (
            SurfaceHttpError,
            check_form_html,
            complete_pending_connect,
            disconnect_nalv,
            escape_html,
            redact_secret,
            resolve_runtime_token,
            run_check,
            start_connect,
            storage_get,
            STORAGE_TOKEN_KEY,
        )


class Nalv(Endpoint):
    def _invoke(self, r: Request, values: Mapping, settings: Mapping) -> Response:
        if r.method == "GET":
            return _get(self.session, settings)
        try:
            payload = r.get_json(silent=True) or {}
        except Exception:
            payload = {}
        if not payload and r.form:
            payload = dict(r.form)
        action = str(payload.get("action") or "").strip()
        if action == "connect":
            return _connect(self.session, settings)
        if action == "disconnect":
            disconnect_nalv(self.session, settings)
            return Response(_page_html(False, None, settings), status=200, content_type="text/html; charset=utf-8")
        result = run_check(self.session, settings, payload)
        status = 200 if result.get("ok") else int(result.get("httpStatus") or 400)
        if (payload.get("format") or r.args.get("format")) == "html" or r.form:
            return Response(
                _result_html(result, resolve_runtime_token(self.session, settings)),
                status=status,
                content_type="text/html; charset=utf-8",
            )
        return Response(
            json.dumps(result),
            status=status,
            content_type="application/json; charset=utf-8",
        )


def _get(session, settings: Mapping) -> Response:
    notice = None
    try:
        pending = complete_pending_connect(session, settings)
        if pending and pending.get("pending"):
            notice = "Waiting for Google authorization. Return here after you continue with Google."
        elif pending and pending.get("connected"):
            notice = None
    except SurfaceHttpError as error:
        notice = error.message
    connected = bool(storage_get(session, STORAGE_TOKEN_KEY) or settings.get("surface_token"))
    return Response(_page_html(connected, notice, settings), status=200, content_type="text/html; charset=utf-8")


def _connect(session, settings: Mapping) -> Response:
    try:
        started = start_connect(session, settings)
        return Response(
            "",
            status=302,
            headers={"Location": started["redirect"]},
        )
    except SurfaceHttpError as error:
        return Response(
            _page_html(False, error.message, settings),
            status=error.status,
            content_type="text/html; charset=utf-8",
        )


def _page_html(connected: bool, notice: str | None, settings: Mapping | None = None) -> str:
    status = (
        "<p>NALV connected</p><p>Ready to run behavior checks.</p>"
        if connected
        else "<p>Connect NALV to authorize this Dify app.</p>"
    )
    connect_form = (
        '<form method="post"><input type="hidden" name="action" value="disconnect">'
        "<button type=\"submit\">Disconnect NALV</button></form>"
        if connected
        else '<form method="post"><input type="hidden" name="action" value="connect">'
        "<button type=\"submit\">Connect NALV</button></form>"
    )
    notice_html = f"<p>{escape_html(notice)}</p>" if notice else ""
    return f"""<!doctype html>
<html><body>
<h1>NALV</h1>
{status}
{notice_html}
{connect_form}
{check_form_html(settings or {}, connected)}
</body></html>"""


def _result_html(result: dict, token: str) -> str:
    compact = result.get("result") or {}
    evidence = compact.get("evidenceUrl") or ""
    counts = compact.get("decisionCounts") or {}
    top = compact.get("topFinding") or {}
    serialized = redact_secret(json.dumps(result, indent=2), token)
    return f"""<!doctype html>
<html><body>
<h1>NALV result</h1>
<p>Decision: {escape_html(str(compact.get("overallDecision", result.get("error") or "")))}</p>
<p>PASS {counts.get("PASS", 0)} · REVIEW {counts.get("REVIEW", 0)} · FAIL {counts.get("FAIL", 0)} · RELEASE_BLOCKER {counts.get("RELEASE_BLOCKER", 0)}</p>
<p>Top finding: {escape_html(str(top.get("statement") or "none"))}</p>
<p><a href="{escape_html(str(evidence))}">Open Evidence</a></p>
<pre>{escape_html(serialized)}</pre>
</body></html>"""


